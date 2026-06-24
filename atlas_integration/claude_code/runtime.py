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
    record_trace,
    start_session,
)
from finding import resolver

from .config import ClaudeCodeConfig
from .prompts import STANDING_PROMPT, failure_nudge, reflection_prompt
from .reflection import ReflectionResult, parse_reflection
from .state import load_state, record_reflection, save_state
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
    if existing and not existing.get("finished"):
        return _context("SessionStart", STANDING_PROMPT)

    inherit = config.inherit if config.inherit is not None else resolver.ABSENT
    session = start_session(
        inherit,
        trace_output=config.trace_output,
        store_dir=config.store_dir,
        trace_root=config.trace_root,
        session_id=f"claude-code:{session_id}",
        atlas_model=config.atlas_model,
        repo_path=event.get("cwd") or Path.cwd(),
        max_retries=config.max_retries,
        dashboard=config.dashboard,
        generation_threshold=config.generation_threshold,
        generation_stops=config.generation_stops,
        skip_judge=config.skip_judge,
        k_init=config.k_init,
        k=config.k,
        refinement_stops=config.refinement_stops,
        advanced_refinement=config.advanced_refinement,
    )
    state = {
        "version": 1,
        "session_id": session_id,
        "runtime_session_id": session.session_id,
        "program_id": session.program_id,
        "cwd": str(event.get("cwd") or ""),
        "taxonomy_id": session.delivery.taxonomy_id,
        "taxonomy": session.delivery.taxonomy,
        "dashboard_url": session.delivery.dashboard_url,
        "max_retries": config.max_retries,
        "lifecycle": {
            "store_dir": str(session.store_dir),
            "trace_root": str(session.trace_root),
            "generation_threshold": session.generation_threshold,
            "generation_stops": session.generation_stops,
            "skip_judge": session.skip_judge,
            "k_init": session.k_init,
            "k": session.k,
            "refinement_stops": session.refinement_stops,
            "advanced_refinement": session.advanced_refinement,
            "runtime_protocol": session.delivery.runtime_protocol,
        },
        "main_cursor": transcript_size(event.get("transcript_path")),
        "pending": {},
        "failure": {
            "call_index": 0,
            "last_fired_call": -10**9,
            "last_hash": "",
            "last_fired_at": 0.0,
        },
        "finished": False,
        "trace_captured": False,
    }
    save_state(config.trace_output, session_id, state)
    context = STANDING_PROMPT
    if session.delivery.dashboard_url:
        context += f"\nLive ATLAS dashboard: {session.delivery.dashboard_url}\n"
    return _context("SessionStart", context)


def blocking_checkpoint(
    event: dict[str, Any],
    config: ClaudeCodeConfig,
    *,
    gate: str,
) -> tuple[int, str]:
    state = _state(event, config)
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
        try:
            reflection = parse_reflection(
                recent,
                checkpoint_id=pending["checkpoint_id"],
                known_code_ids=_code_ids(state),
            )
        except ValueError as exc:
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
                    detail=f"Last shape error: {exc}",
                )
            save_state(config.trace_output, state["session_id"], state)
            return 2, f"ATLAS reflection is incomplete: {exc}\n\n" + pending["prompt"]

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
            decision = evaluate_pre_submission(
                recent, max_retries=int(state["max_retries"])
            )
            repairs_completed = int(pending.get("repairs_completed", 0))
            if decision.repair_attempts_used != repairs_completed:
                pending["guard_failures"] = int(
                    pending.get("guard_failures", 0)
                ) + 1
                reason = (
                    "`Repair attempts used:` must match the hook-owned "
                    f"counter ({repairs_completed}), not "
                    f"{decision.repair_attempts_used}"
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
            reflection_requires_change = bool(
                re.search(r"\bchange\s*:", reflection.decide, re.I)
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
                return 2, _repair_action_feedback(
                    decision.reason,
                    next_attempt=next_attempt,
                    limit=int(state["max_retries"]),
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
    state = _state(event, config)
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
    if state.get("trace_captured"):
        state["finished"] = True
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
        generation_stops=bool(lifecycle["generation_stops"]),
        atlas_model=config.atlas_model,
        skip_judge=bool(lifecycle.get("skip_judge", False)),
        k_init=int(lifecycle["k_init"]),
        k=int(lifecycle["k"]),
        refinement_stops=bool(lifecycle["refinement_stops"]),
        advanced_refinement=bool(lifecycle["advanced_refinement"]),
    )
    raw_trajectory = read_raw_transcript(transcript_path).strip()
    if not raw_trajectory:
        raw_trajectory = (
            "Claude Code session ended before transcript content was available."
        )
    task = first_user_message(transcript_path).strip() or (
        f"Claude Code task in {state.get('cwd') or 'unknown working directory'}"
    )
    record_trace(
        session,
        GenerationTrace(
            problem_id=f"claude-code:{state['session_id']}",
            task=task,
            raw_trajectory=raw_trajectory,
            metadata={
                "harness": "claude_code",
                "claude_session_id": state["session_id"],
                "runtime_session_id": state["runtime_session_id"],
                "taxonomy_id": state["taxonomy_id"],
                "end_reason": reason,
            },
        ),
    )
    result = end_session(session)
    state["trace_captured"] = True
    state["trace_capture"] = {
        "persisted_traces": result.persisted_traces,
        "integrated_traces": result.integrated_traces,
        "generation_action": result.generation.action,
        "refinement_action": result.refinement.action,
        "reason": reason,
    }
    state["finished"] = True


def session_end(
    event: dict[str, Any], config: ClaudeCodeConfig
) -> tuple[int, str | None]:
    """Capture and close sessions that terminate without a successful Stop gate."""
    state = _state(event, config)
    if state.get("trace_captured"):
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


def _retry_limit_reached(
    pending: dict[str, Any], state: dict[str, Any]
) -> bool:
    limit = max(1, int(state.get("max_retries", 3)))
    return int(pending.get("guard_failures", 0)) >= limit


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
    limit = max(0, int(state.get("max_retries", 3)))
    return int(pending.get("repairs_completed", 0)) >= limit


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
    guard_failures = int(pending.get("guard_failures", 0))
    repairs_completed = int(pending.get("repairs_completed", 0))
    limit = int(state.get("max_retries", 3))

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
        f"(guard_failures={guard_failures}, repairs_completed={repairs_completed}, "
        f"limit={limit}). detail={detail!r}"
    )
    print(summary, file=sys.stderr)
    try:
        decisions_log = Path(config.trace_output) / "decisions.log"
        decisions_log.parent.mkdir(parents=True, exist_ok=True)
        with decisions_log.open("a", encoding="utf-8") as fh:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fh.write(json.dumps({
                "ts": ts,
                "event": "retry_guard_release",
                "gate": gate,
                "session_id": state.get("session_id"),
                "guard_failures": guard_failures,
                "repairs_completed": repairs_completed,
                "limit": limit,
                "detail": detail,
            }) + "\n")
    except OSError:
        pass

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


def _required(event: dict[str, Any], name: str) -> str:
    value = str(event.get(name, "")).strip()
    if not value:
        raise ValueError(f"hook input is missing {name}")
    return value
