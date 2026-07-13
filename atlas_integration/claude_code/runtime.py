"""Shared Claude Code hook behavior."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_runtime import (
    GenerationTrace,
    ProgramWorkspace,
    Session,
    SessionDelivery,
    end_session,
    evaluate_pre_submission,
    pin_gate_decision,
    redact_trace,
    render_format_repair,
    start_session,
)
from atlas_runtime.evidence import record_reflection
from atlas_runtime.reflection import (
    ReflectionResult,
    harvest_reflection,
    parse_reflection,
)
from finding import mast, resolver

from atlas_integration.shared import build_session_state
from atlas_integration.interactive.selector import (
    build_selection,
    parse_selection_choice,
    render_selection,
    selection_interstitial,
)

from .config import ClaudeCodeConfig
from .learning_jobs import enqueue_claude_learning_job
from .prompts import STANDING_PROMPT, failure_nudge, reflection_prompt
from .state import load_state, save_state
from .transcript import (
    first_user_message,
    read_raw_transcript,
    read_transcript,
    transcript_size,
)

CHECKPOINT_REQUEST = re.compile(
    r"ATLAS\s+checkpoint\s+request\s*:\s*(.+)",
    re.IGNORECASE,
)
FAILURE_PATTERNS = (
    re.compile(r"\bTraceback \(most recent call last\)", re.I),
    re.compile(r"\bAssertionError\b", re.I),
    re.compile(r"\b(?:FAILED|FAILURES?)\b", re.I),
    re.compile(r"\b(?:error|exception)\s*:", re.I),
    re.compile(r"\b(?:exit|return)\s+code\s*[:=]?\s*[1-9]\d*", re.I),
    re.compile(r"\bModuleNotFoundError\b|\bImportError\b|\bSyntaxError\b", re.I),
)


def session_start(event: dict[str, Any], config: ClaudeCodeConfig) -> dict:
    session_id = _required(event, "session_id")
    existing = load_state(config.trace_output, session_id)
    if config.session_selector == "prompt" and config.inherit is None:
        selection = existing.get("selection") if existing else None
        if selection:
            status = selection.get("status")
            if status == "pending":
                return _selection_output("SessionStart", selection)
            if status == "disabled":
                return {"systemMessage": "ATLAS is disabled for this conversation."}
            return _context(
                "SessionStart",
                _selected_context(selection) + "\n\n" + STANDING_PROMPT,
            )
        if not existing:
            selection = build_selection(
                trace_output=config.trace_output,
                store_dir=config.store_dir,
                cwd=event.get("cwd"),
            )
            state = {
                "version": 1,
                "session_id": session_id,
                "conversation_id": session_id,
                "cwd": str(event.get("cwd") or ""),
                "episode_sequence": 0,
                "main_cursor": transcript_size(event.get("transcript_path")),
                "episode_cursor": transcript_size(event.get("transcript_path")),
                "selection": selection,
                "finished": True,
                "trace_captured": False,
            }
            save_state(config.trace_output, session_id, state)
            return _selection_output("SessionStart", selection)
    if existing and not existing.get("finished"):
        return _context("SessionStart", STANDING_PROMPT)

    sequence = int(existing.get("episode_sequence", 0)) + 1 if existing else 1
    state, session = _start_episode(
        event,
        config,
        sequence=sequence,
        cursor=transcript_size(event.get("transcript_path")),
        previous=existing,
    )
    save_state(config.trace_output, session_id, state)
    context = STANDING_PROMPT
    if session.delivery.dashboard_url:
        context += f"\nLive ATLAS dashboard: {session.delivery.dashboard_url}\n"
    return _context("SessionStart", context)


def _start_episode(
    event: dict[str, Any],
    config: ClaudeCodeConfig,
    *,
    sequence: int,
    cursor: int,
    previous: dict[str, Any] | None = None,
    taxonomy_id: str | None = None,
    episode_task: str | None = None,
) -> tuple[dict[str, Any], Session]:
    """Start one runtime task inside a longer Claude conversation."""
    session_id = _required(event, "session_id")

    manifest_path = Path(config.trace_output) / ".atlas-program.json"
    bound_taxonomy_id = None
    if manifest_path.exists():
        try:
            bound_taxonomy_id = json.loads(
                manifest_path.read_text(encoding="utf-8")
            ).get("taxonomy_id")
        except (OSError, json.JSONDecodeError):
            bound_taxonomy_id = None
    if bound_taxonomy_id:
        taxonomy_id = str(bound_taxonomy_id)

    if taxonomy_id == mast.MAST_ID:
        inherit = resolver.ABSENT
    elif taxonomy_id:
        inherit = taxonomy_id
    else:
        inherit = config.inherit if config.inherit is not None else resolver.ABSENT
    session = start_session(
        inherit,
        trace_output=config.trace_output,
        store_dir=config.store_dir,
        trace_root=config.trace_root,
        session_id=f"claude-code:{session_id}:episode:{sequence}",
        atlas_model=config.atlas_model,
        repo_path=event.get("cwd") or Path.cwd(),
        max_retries=config.repair_rounds,
        dashboard=config.dashboard,
        generation_threshold=config.generation_threshold,
        # Hook processes are killed at Claude Code's per-hook timeout, so
        # learning always runs in background workers here; the *_stops flags
        # only make sense for CLI/benchmark wrappers that own their process.
        generation_stops=False,
        skip_judge=config.skip_judge,
        k_init=config.k_init,
        k=config.k,
        refinement_stops=False,
        advanced_refinement=config.advanced_refinement,
        freeze=config.freeze,
        evidence_export=config.evidence_export,
    )
    state = build_session_state(
        session_id=session_id,
        session=session,
        cwd=str(event.get("cwd") or ""),
        max_retries=config.repair_rounds,
        main_cursor=cursor,
        episode_sequence=sequence,
        episode_cursor=cursor,
        failure={
            "call_index": 0,
            "last_fired_call": -10**9,
            "last_hash": "",
            "last_fired_at": 0.0,
        },
    )
    state["format_retries"] = config.format_retries
    state["repair_rounds"] = config.repair_rounds
    state["conversation_id"] = session_id
    state["conversation_taxonomy_root"] = (
        (previous or {}).get("conversation_taxonomy_root")
        or session.delivery.taxonomy_id
    )
    if previous:
        state["previous_taxonomy_id"] = previous.get("taxonomy_id")
        if previous.get("selection"):
            state["selection"] = previous["selection"]
    if episode_task:
        state["episode_task"] = episode_task
    return state, session


def user_prompt_submit(
    event: dict[str, Any], config: ClaudeCodeConfig
) -> dict | None:
    """Resolve the session selector and preserve the held substantive prompt."""
    if config.session_selector != "prompt" or config.inherit is not None:
        return None
    session_id = _required(event, "session_id")
    state = load_state(config.trace_output, session_id)
    if not state:
        session_start({**event, "hook_event_name": "SessionStart"}, config)
        state = load_state(config.trace_output, session_id)
    selection = state.get("selection")
    if not selection:
        return None

    status = selection.get("status")
    prompt = _user_prompt(event)
    if status == "disabled":
        return None
    if status == "pending":
        choice = parse_selection_choice(prompt, selection)
        if choice is None:
            if prompt and not selection.get("pending_task"):
                selection["pending_task"] = prompt
                selection["held_cursor"] = transcript_size(
                    event.get("transcript_path")
                )
                save_state(config.trace_output, session_id, state)
            return _selection_block(selection)

        selection["selected_kind"] = choice["kind"]
        selection["selected_taxonomy_id"] = choice.get("taxonomy_id")
        selection["selected_label"] = choice["label"]
        pending_task = str(selection.get("pending_task") or "").strip()
        if choice["kind"] == "disabled":
            selection["status"] = "disabled"
            state["finished"] = True
            save_state(config.trace_output, session_id, state)
            return _context_with_message(
                "UserPromptSubmit",
                _disabled_context(pending_task),
                "ATLAS disabled for this conversation.",
            )

        selection["status"] = "selected"
        if pending_task:
            fresh, _session = _start_episode(
                event,
                config,
                sequence=max(1, int(state.get("episode_sequence", 0)) + 1),
                cursor=transcript_size(event.get("transcript_path")),
                previous=state,
                taxonomy_id=str(choice["taxonomy_id"]),
                episode_task=pending_task,
            )
            save_state(config.trace_output, session_id, fresh)
        else:
            save_state(config.trace_output, session_id, state)
        return _context_with_message(
            "UserPromptSubmit",
            _selection_accepted_context(selection, pending_task),
            f"ATLAS selected {choice['label']}.",
        )

    if status == "selected" and (not state.get("lifecycle") or state.get("finished")):
        if not prompt:
            return None
        fresh, _session = _start_episode(
            event,
            config,
            sequence=max(1, int(state.get("episode_sequence", 0)) + 1),
            cursor=transcript_size(event.get("transcript_path")),
            previous=state,
            taxonomy_id=str(selection["selected_taxonomy_id"]),
            episode_task=prompt,
        )
        save_state(config.trace_output, session_id, fresh)
        return _context(
            "UserPromptSubmit",
            _selected_context(selection) + "\n\n" + STANDING_PROMPT,
        )
    return None


def _ensure_active_episode(
    event: dict[str, Any],
    config: ClaudeCodeConfig,
    state: dict[str, Any],
) -> dict[str, Any]:
    selection = state.get("selection") or {}
    if selection.get("status") in {"pending", "disabled"}:
        return state
    if not state.get("finished"):
        return state
    sequence = int(state.get("episode_sequence", 0)) + 1
    cursor = int(
        state.get("episode_cursor", state.get("main_cursor", 0))
    )
    if not read_raw_transcript(
        event.get("transcript_path"),
        after=cursor,
    ).strip():
        return state
    fresh, _session = _start_episode(
        event,
        config,
        sequence=sequence,
        cursor=cursor,
        previous=state,
        taxonomy_id=selection.get("selected_taxonomy_id"),
    )
    save_state(config.trace_output, fresh["session_id"], fresh)
    return fresh


def blocking_checkpoint(
    event: dict[str, Any],
    config: ClaudeCodeConfig,
    *,
    gate: str,
) -> tuple[int, str]:
    state = _ensure_active_episode(event, config, _state(event, config))
    if _selection_inactive(state):
        return 0, "ATLAS taxonomy selection is pending or disabled."
    if state.get("finished"):
        return 0, "ATLAS episode already committed."
    transcript_path = _transcript_path(event, gate)
    _harvest_advisory_reflections(
        state,
        config,
        transcript_path=event.get("transcript_path"),
    )
    key = _checkpoint_key(event, gate)
    pending = state.setdefault("pending", {}).get(key)
    if pending:
        if gate == "stop" and pending.get("awaiting_repair"):
            completed = int(pending.get("repairs_completed", 0)) + 1
            pending.update(
                {
                    "awaiting_repair": False,
                    "repairs_completed": completed,
                    "checkpoint_id": _checkpoint_id(gate),
                    "guard_failures": 0,
                    "pinned_status": None,
                    "pinned_decide": None,
                    "recorded": False,
                }
            )
            recent = read_transcript(
                transcript_path,
                after=int(pending.get("repair_offset", pending["offset"])),
            )
            prompt = reflection_prompt(
                state,
                checkpoint_id=pending["checkpoint_id"],
                gate_label="post-repair submission re-evaluation",
                recent_activity=recent,
                full=True,
                repair_attempts_used=completed,
            )
            pending["offset"] = transcript_size(transcript_path)
            pending["prompt"] = prompt
            save_state(config.trace_output, state["session_id"], state)
            return 2, prompt

        recent = read_transcript(transcript_path, after=int(pending["offset"]))
        if event.get("last_assistant_message"):
            recent += "\n" + str(event["last_assistant_message"])
        harvest = harvest_reflection(
            recent,
            checkpoint_id=pending["checkpoint_id"],
            known_code_ids=_code_ids(state),
        )
        if harvest.result is None:
            partial = harvest.partial
            pending["guard_failures"] = int(
                pending.get("guard_failures", 0)
            ) + 1
            if partial is not None and partial.has_block:
                # Preserve the pre-re-prompt verdict: a format re-emission
                # must not be allowed to flip it (sampling noise, not new
                # information).
                if partial.status and not pending.get("pinned_status"):
                    pending["pinned_status"] = partial.status
                if (
                    pending.get("pinned_decide") is None
                    and partial.decide_change is not None
                ):
                    pending["pinned_decide"] = partial.decide_change
            if _retry_limit_reached(pending, state):
                return _release_retry_guard(
                    config,
                    state,
                    key=key,
                    gate=gate,
                    transcript_path=transcript_path,
                    detail=f"Last shape error: {harvest.error}",
                )
            save_state(config.trace_output, state["session_id"], state)
            if partial is not None and partial.has_block:
                return 2, render_format_repair(
                    checkpoint_id=pending["checkpoint_id"],
                    issues=partial.issues,
                    full=gate == "stop" and bool(pending.get("full", True)),
                )
            return 2, (
                f"ATLAS reflection is incomplete: {harvest.error}\n\n"
                + pending["prompt"]
            )
        reflection = harvest.result
        if harvest.id_corrected:
            _log_decision(
                config,
                {
                    "event": "checkpoint_id_corrected",
                    "gate": gate,
                    "session_id": state.get("session_id"),
                    "expected_checkpoint_id": pending["checkpoint_id"],
                    "found_checkpoint_id": harvest.found_checkpoint_id,
                },
            )

        if not pending.get("recorded"):
            task_id = _task_id(event, gate)
            record_reflection(
                config.trace_output,
                state,
                reflection,
                gate=gate,
                task_id=task_id,
                agent_id=event.get("agent_id"),
                agent_type=event.get("agent_type"),
            )
            pending["recorded"] = True
        if gate == "stop" and pending.get("full", True):
            repair_rounds = _repair_rounds(state)
            emitted = evaluate_pre_submission(
                recent, max_retries=repair_rounds
            )
            decision, flipped = pin_gate_decision(
                emitted,
                pending.get("pinned_status"),
                max_retries=repair_rounds,
            )
            if flipped:
                _log_decision(
                    config,
                    {
                        "event": "verdict_flip_suppressed",
                        "gate": gate,
                        "session_id": state.get("session_id"),
                        "pinned_status": pending.get("pinned_status"),
                        "emitted_status": emitted.status,
                    },
                )
            repairs_completed = int(pending.get("repairs_completed", 0))
            pinned_decide = pending.get("pinned_decide")
            reflection_requires_change = (
                bool(pinned_decide)
                if pinned_decide is not None
                else bool(re.search(r"\bchange\s*:", reflection.decide, re.I))
            )
            if (
                reflection_requires_change
                and decision.status != "REPAIR_REQUIRED"
            ):
                pending["guard_failures"] = int(
                    pending.get("guard_failures", 0)
                ) + 1
                reason = (
                    "Decide says `change:` so `Final ATLAS status:` must be "
                    "REPAIR_REQUIRED; the provisional answer cannot be released"
                )
                if _retry_limit_reached(pending, state):
                    return _release_retry_guard(
                        config,
                        state,
                        key=key,
                        gate=gate,
                        transcript_path=transcript_path,
                        detail=reason,
                    )
                save_state(config.trace_output, state["session_id"], state)
                return 2, _repair_feedback(reason, pending["prompt"])
            if decision.status == "REPAIR_REQUIRED":
                if _repair_limit_reached(pending, state):
                    return _release_retry_guard(
                        config,
                        state,
                        key=key,
                        gate=gate,
                        transcript_path=transcript_path,
                        detail=(
                            "The final classifier still reported "
                            "REPAIR_REQUIRED."
                        ),
                    )
                next_attempt = repairs_completed + 1
                pending["awaiting_repair"] = True
                pending["repair_offset"] = transcript_size(transcript_path)
                save_state(config.trace_output, state["session_id"], state)
                # Verbatim, parse-free audit record: lets the next A/B
                # classify repairs (did the agent run a check before
                # replacing the answer?) without transcript digging.
                _log_decision(
                    config,
                    {
                        "event": "repair_round_started",
                        "gate": gate,
                        "session_id": state.get("session_id"),
                        "repair_round": next_attempt,
                        "repair_rounds": repair_rounds,
                        "decide": reflection.decide[:2000],
                    },
                )
                return 2, _repair_action_feedback(
                    decision.reason,
                    next_attempt=next_attempt,
                    limit=repair_rounds,
                )
            if not decision.allow:
                pending["guard_failures"] = int(
                    pending.get("guard_failures", 0)
                ) + 1
                if _retry_limit_reached(pending, state):
                    return _release_retry_guard(
                        config,
                        state,
                        key=key,
                        gate=gate,
                        transcript_path=transcript_path,
                        detail=decision.reason,
                    )
                save_state(config.trace_output, state["session_id"], state)
                return 2, _repair_feedback(decision.reason, pending["prompt"])
            _finish_runtime_session(
                state,
                config,
                transcript_path=transcript_path,
                reason="stop_gate",
            )
        state["pending"].pop(key, None)
        if gate != "subagent_stop":
            state["main_cursor"] = transcript_size(transcript_path)
        save_state(config.trace_output, state["session_id"], state)
        if gate == "stop" and not pending.get("full", True):
            return (
                2,
                "ATLAS major-segment reflection accepted. Continue the task; "
                "the final submission gate will run when you next finish.",
            )
        return 0, "ATLAS reflection accepted."

    checkpoint_id = _checkpoint_id(gate)
    offset = (
        int(state.get("main_cursor", 0))
        if gate != "subagent_stop"
        else 0
    )
    recent = read_transcript(transcript_path, after=offset)
    full = gate == "stop" and not CHECKPOINT_REQUEST.search(
        str(event.get("last_assistant_message") or "")
    )
    label = {
        "stop": "submission gate" if full else "voluntary major-segment checkpoint",
        "task_completed": "sub-task checkpoint",
        "subagent_stop": "subagent checkpoint",
    }[gate]
    prompt = reflection_prompt(
        state,
        checkpoint_id=checkpoint_id,
        gate_label=label,
        recent_activity=recent,
        full=full,
    )
    state["pending"][key] = {
        "checkpoint_id": checkpoint_id,
        "offset": transcript_size(transcript_path),
        "prompt": prompt,
        "full": full,
        "guard_failures": 0,
        "repairs_completed": 0,
        "awaiting_repair": False,
        "pinned_status": None,
        "pinned_decide": None,
        "recorded": False,
    }
    save_state(config.trace_output, state["session_id"], state)
    return 2, prompt


def post_tool(
    event: dict[str, Any],
    config: ClaudeCodeConfig,
    *,
    execution_failed: bool,
) -> dict | None:
    state = _ensure_active_episode(event, config, _state(event, config))
    if _selection_inactive(state):
        return None
    if state.get("finished"):
        return None
    failure = state.setdefault("failure", {})
    failure["call_index"] = int(failure.get("call_index", 0)) + 1
    text = (
        str(event.get("error", ""))
        if execution_failed
        else json.dumps(event.get("tool_response", ""), ensure_ascii=False)
    )
    if not execution_failed and not any(p.search(text) for p in FAILURE_PATTERNS):
        save_state(config.trace_output, state["session_id"], state)
        return None

    digest = hashlib.sha256(text[:8000].encode("utf-8", "replace")).hexdigest()[:16]
    now = time.time()
    throttled = (
        failure.get("last_hash") == digest
        or int(failure["call_index"]) - int(
            failure.get("last_fired_call", -10**9)
        ) < config.failure_throttle_calls
        or now - float(failure.get("last_fired_at", 0))
        < config.failure_recency_seconds
    )
    if throttled:
        save_state(config.trace_output, state["session_id"], state)
        return None

    failure.update(
        {
            "last_hash": digest,
            "last_fired_call": failure["call_index"],
            "last_fired_at": now,
        }
    )
    checkpoint_id = _checkpoint_id("failure")
    transcript_path = event.get("transcript_path")
    state.setdefault("pending", {})[f"nudge:{checkpoint_id}"] = {
        "checkpoint_id": checkpoint_id,
        "offset": transcript_size(transcript_path),
        "prompt": "",
        "full": False,
        "guard_failures": 0,
        "advisory": True,
        "recorded": False,
    }
    save_state(config.trace_output, state["session_id"], state)
    return _context(
        "PostToolUseFailure" if execution_failed else "PostToolUse",
        failure_nudge(
            state,
            checkpoint_id=checkpoint_id,
            failure_summary=text[-4000:],
        ),
    )


def _harvest_advisory_reflections(
    state: dict[str, Any],
    config: ClaudeCodeConfig,
    *,
    transcript_path: str | None,
) -> None:
    """Persist completed nonblocking nudge reflections when a later hook fires."""
    changed = False
    for key, pending in list(state.setdefault("pending", {}).items()):
        if not pending.get("advisory"):
            continue
        recent = read_transcript(
            transcript_path, after=int(pending.get("offset", 0))
        )
        try:
            reflection = parse_reflection(
                recent,
                checkpoint_id=pending["checkpoint_id"],
                known_code_ids=_code_ids(state),
            )
        except ValueError:
            continue
        record_reflection(
            config.trace_output,
            state,
            reflection,
            gate="post_tool_failure",
            task_id=str(state["session_id"]),
        )
        state["pending"].pop(key, None)
        state["main_cursor"] = transcript_size(transcript_path)
        changed = True
    if changed:
        save_state(config.trace_output, state["session_id"], state)


def _state(
    event: dict[str, Any], config: ClaudeCodeConfig
) -> dict[str, Any]:
    session_id = _required(event, "session_id")
    state = load_state(config.trace_output, session_id)
    if not state:
        session_start(event, config)
        state = load_state(config.trace_output, session_id)
    return state


def _finish_runtime_session(
    state: dict[str, Any],
    config: ClaudeCodeConfig,
    *,
    transcript_path: str | None,
    reason: str,
) -> None:
    if state.get("finished") and state.get("trace_captured"):
        return
    lifecycle = state["lifecycle"]
    workspace = ProgramWorkspace(config.trace_output)
    delivery = SessionDelivery(
        taxonomy_id=str(state["taxonomy_id"]),
        taxonomy=state["taxonomy"],
        runtime_protocol=str(lifecycle["runtime_protocol"]),
        dashboard_url=state.get("dashboard_url"),
    )
    session = Session(
        session_id=str(state["runtime_session_id"]),
        program_id=str(state["program_id"]),
        workspace=workspace,
        delivery=delivery,
        store_dir=Path(lifecycle["store_dir"]),
        trace_root=Path(lifecycle["trace_root"]),
        max_retries=int(state["max_retries"]),
        generation_threshold=int(lifecycle["generation_threshold"]),
        # Hooks run under Claude Code's per-hook timeout: learning must never
        # run inline here or the kill lands mid-finalize. Background workers
        # only, regardless of the configured *_stops flags.
        generation_stops=False,
        atlas_model=config.atlas_model,
        skip_judge=bool(lifecycle.get("skip_judge", False)),
        k_init=int(lifecycle["k_init"]),
        k=int(lifecycle["k"]),
        refinement_stops=False,
        advanced_refinement=bool(lifecycle["advanced_refinement"]),
        freeze=bool(lifecycle.get("freeze", False)),
        evidence_export=(
            Path(lifecycle["evidence_export"])
            if lifecycle.get("evidence_export")
            else None
        ),
    )
    cursor = int(state.get("episode_cursor", 0))
    sequence = int(state.get("episode_sequence", 1))
    persisted_trace_names = [
        str(name) for name in state.get("persisted_trace_names", [])
    ]
    raw_trajectory = ""
    if not persisted_trace_names:
        raw_trajectory = read_raw_transcript(
            transcript_path,
            after=cursor,
        ).strip()
    if not persisted_trace_names and raw_trajectory:
        task = str(state.get("episode_task") or "").strip() or first_user_message(
            transcript_path,
            after=cursor,
        ).strip() or (
            f"Claude Code episode {sequence} in "
            f"{state.get('cwd') or 'unknown working directory'}"
        )
        trace = GenerationTrace(
            problem_id=(
                f"claude-code:{state['session_id']}:episode:{sequence}"
            ),
            task=task,
            raw_trajectory=raw_trajectory,
            metadata={
                "harness": "claude_code",
                "claude_session_id": state["session_id"],
                "conversation_id": state["session_id"],
                "episode_sequence": sequence,
                "trace_granularity": "episode",
                "runtime_session_id": state["runtime_session_id"],
                "taxonomy_id": state["taxonomy_id"],
                "end_reason": reason,
            },
        )
        if config.redact_traces:
            trace = redact_trace(trace)
        persisted_trace_names = workspace.pending.append_many_with_names([trace])
        state["trace_captured"] = True
        state["persisted_trace_names"] = persisted_trace_names
        save_state(config.trace_output, state["session_id"], state)
    generation_launcher = None
    refinement_launcher = None
    if config.learning_backend == "claude_subagent":
        common = {
            "store_dir": config.store_dir,
            "trace_root": config.trace_root,
            "task_group": config.task_group,
            "conversation_id": str(state["session_id"]),
            "worker_model": config.worker_model,
            "claude_cli_path": config.claude_cli_path,
            "worker_timeout_seconds": config.worker_timeout_seconds,
        }
        generation_launcher = lambda: enqueue_claude_learning_job(
            workspace,
            kind="generation",
            **common,
        )
        refinement_launcher = lambda: enqueue_claude_learning_job(
            workspace,
            kind="refinement",
            **common,
        )
    result = end_session(
        session,
        background_launcher=generation_launcher,
        refinement_background_launcher=refinement_launcher,
        pre_persisted_trace_names=persisted_trace_names,
    )
    state["trace_captured"] = bool(persisted_trace_names)
    state["trace_capture"] = {
        "persisted_traces": result.persisted_traces,
        "integrated_traces": result.integrated_traces,
        "generation_action": result.generation.action,
        "refinement_action": result.refinement.action,
        "reason": reason,
    }
    state.pop("persisted_trace_names", None)
    state["episode_cursor"] = transcript_size(transcript_path)
    state["finished"] = True


def session_end(
    event: dict[str, Any], config: ClaudeCodeConfig
) -> tuple[int, str | None]:
    """Capture and close sessions that terminate without a successful Stop gate."""
    state = _state(event, config)
    if _selection_inactive(state):
        return 0, None
    if state.get("finished"):
        return 0, None
    _harvest_advisory_reflections(
        state,
        config,
        transcript_path=event.get("transcript_path"),
    )
    _finish_runtime_session(
        state,
        config,
        transcript_path=event.get("transcript_path"),
        reason=f"session_end:{event.get('reason') or 'unknown'}",
    )
    save_state(config.trace_output, state["session_id"], state)
    return 0, "ATLAS captured the Claude Code session trace."


def _format_retries(state: dict[str, Any]) -> int:
    return max(1, int(state.get("format_retries", 2)))


def _repair_rounds(state: dict[str, Any]) -> int:
    # Sessions persisted before the budget split carry only max_retries.
    return max(0, int(state.get("repair_rounds", state.get("max_retries", 3))))


def _retry_limit_reached(
    pending: dict[str, Any], state: dict[str, Any]
) -> bool:
    return int(pending.get("guard_failures", 0)) >= _format_retries(state)


def _repair_feedback(reason: str, prompt: str) -> str:
    return (
        f"{reason}\n\n"
        "The task answer is still provisional and has not been released. "
        "If your reflection found a real issue, repair and verify it now; "
        "do not describe the checkpoint as post-hoc. Your next final-gate "
        "block must use exactly READY_TO_SUBMIT or REPAIR_REQUIRED.\n\n"
        + prompt
    )


def _repair_limit_reached(
    pending: dict[str, Any], state: dict[str, Any]
) -> bool:
    return int(pending.get("repairs_completed", 0)) >= _repair_rounds(state)


def _repair_action_feedback(
    reason: str,
    *,
    next_attempt: int,
    limit: int,
) -> str:
    return (
        f"{reason}\n\n"
        f"Perform repair attempt {next_attempt} of {limit} now. Address the "
        "highest-impact unresolved issue and verify the changed result. The "
        "answer remains provisional. When you next try to finish, ATLAS will "
        "issue a fresh checkpoint over the repair trajectory; do not reuse "
        "the previous reflection."
    )


def _log_decision(config: ClaudeCodeConfig, payload: dict[str, Any]) -> None:
    """Append one audit record to ``<trace_output>/decisions.log``."""
    try:
        decisions_log = Path(config.trace_output) / "decisions.log"
        decisions_log.parent.mkdir(parents=True, exist_ok=True)
        with decisions_log.open("a", encoding="utf-8") as fh:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fh.write(json.dumps({"ts": ts, **payload}) + "\n")
    except OSError:
        pass


def _release_retry_guard(
    config: ClaudeCodeConfig,
    state: dict[str, Any],
    *,
    key: str,
    gate: str,
    transcript_path: str | None,
    detail: str,
) -> tuple[int, str]:
    pending = state.get("pending", {}).get(key, {}) or {}
    format_failures = int(pending.get("guard_failures", 0))
    repairs_completed = int(pending.get("repairs_completed", 0))
    format_retries = _format_retries(state)
    repair_rounds = _repair_rounds(state)

    state["pending"].pop(key, None)
    if gate == "stop":
        _finish_runtime_session(
            state,
            config,
            transcript_path=transcript_path,
            reason="stop_retry_guard",
        )
    save_state(config.trace_output, state["session_id"], state)

    # Make the release visible to the operator — both in stderr (so it shows
    # up in Claude Code's hook output) and as an appended line in
    # ``<trace_output>/decisions.log`` so post-hoc audits don't depend on
    # remembering that a hook fired in some scrollback.
    summary = (
        f"[atlas] {gate} gate released after retry guard hit "
        f"(format_failures={format_failures}/{format_retries}, "
        f"repairs_completed={repairs_completed}/{repair_rounds}). "
        f"detail={detail!r}"
    )
    print(summary, file=sys.stderr)
    _log_decision(
        config,
        {
            "event": "retry_guard_release",
            "gate": gate,
            "session_id": state.get("session_id"),
            "guard_failures": format_failures,
            "format_failures": format_failures,
            "format_retries": format_retries,
            "repairs_completed": repairs_completed,
            "repair_rounds": repair_rounds,
            "limit": repair_rounds,
            "detail": detail,
        },
    )

    return (
        0,
        "ATLAS released this boundary after its hook-owned retry limit to "
        f"prevent an infinite loop. {detail}",
    )


def _checkpoint_key(event: dict[str, Any], gate: str) -> str:
    if gate == "task_completed":
        return f"task:{event.get('task_id', 'unknown')}"
    if gate == "subagent_stop":
        return f"agent:{event.get('agent_id', 'unknown')}"
    return "stop"


def _checkpoint_id(gate: str) -> str:
    return f"{gate}-{uuid.uuid4().hex[:12]}"


def _task_id(event: dict[str, Any], gate: str) -> str:
    if gate == "task_completed":
        return str(event.get("task_id") or event["session_id"])
    if gate == "subagent_stop":
        return str(event.get("agent_id") or event["session_id"])
    return str(event["session_id"])


def _transcript_path(event: dict[str, Any], gate: str) -> str | None:
    if gate == "subagent_stop":
        return event.get("agent_transcript_path") or event.get("transcript_path")
    return event.get("transcript_path")


def _code_ids(state: dict[str, Any]) -> list[str]:
    return [str(code["id"]) for code in state["taxonomy"]["codes"]]


def _context(event_name: str, text: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }


def _context_with_message(event_name: str, text: str, message: str) -> dict:
    output = _context(event_name, text)
    output["systemMessage"] = message
    return output


def _selection_output(event_name: str, selection: dict[str, Any]) -> dict:
    return _context_with_message(
        event_name,
        selection_interstitial(selection),
        render_selection(selection),
    )


def _selection_block(selection: dict[str, Any]) -> dict:
    output = _selection_output("UserPromptSubmit", selection)
    output["decision"] = "block"
    output["reason"] = render_selection(selection)
    return output


def _selection_inactive(state: dict[str, Any]) -> bool:
    return (state.get("selection") or {}).get("status") in {"pending", "disabled"}


def _selected_context(selection: dict[str, Any]) -> str:
    label = selection.get("selected_label") or selection.get("selected_taxonomy_id")
    return (
        f"ATLAS taxonomy is pinned to {label} for this conversation. "
        "Do not ask for taxonomy selection again."
    )


def _selection_accepted_context(
    selection: dict[str, Any], pending_task: str
) -> str:
    context = _selected_context(selection)
    if pending_task:
        context += (
            " The user's held task follows. Continue it now without asking the "
            f"user to repeat it:\n\n{pending_task}"
        )
    else:
        context += " No task is held; acknowledge the choice and wait for a task."
    return context + "\n\n" + STANDING_PROMPT


def _disabled_context(pending_task: str) -> str:
    context = (
        "ATLAS is disabled for this conversation. Do not emit ATLAS checkpoints, "
        "run ATLAS gates, or record ATLAS traces."
    )
    if pending_task:
        context += (
            " Continue the user's held task now without asking them to repeat it:\n\n"
            + pending_task
        )
    else:
        context += " Acknowledge the choice and wait for a task."
    return context


def _user_prompt(event: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message", "text"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _required(event: dict[str, Any], name: str) -> str:
    value = str(event.get(name, "")).strip()
    if not value:
        raise ValueError(f"hook input is missing {name}")
    return value
