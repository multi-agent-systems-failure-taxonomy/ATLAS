"""Codex hook runtime skin for ATLAS."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_integration.codex.transcript import (
    external_workdirs,
    first_user_message,
    has_assistant_activity,
    latest_user_message,
    read_raw_transcript,
    read_transcript,
    trace_has_assistant_activity,
    transcript_size,
)
from atlas_runtime import (
    GenerationTrace,
    ProgramWorkspace,
    Session,
    SessionDelivery,
    end_session,
    evaluate_pre_submission,
    redact_trace,
    start_session,
)
from atlas_runtime.evidence import record_reflection
from atlas_runtime.reflection import (
    CodeAssignment,
    ReflectionResult,
    parse_reflection,
)
from finding import mast, resolver

from atlas_integration.shared import build_session_state
from atlas_integration.codex.learning_jobs import (
    LearningJobError,
    capture_learning_receipt,
    enqueue_learning_job,
)
from atlas_integration.codex.browser_picker import (
    open_browser_picker,
    read_browser_choice,
    start_browser_picker,
)
from atlas_integration.interactive.selector import (
    SELECTOR_VERSION,
    build_selection,
    parse_selection_choice,
    render_active_selection_context,
    selection_interstitial,
    stored_option,
)

from .config import CodexConfig
from .prompts import STANDING_PROMPT, failure_nudge, reflection_prompt
from .state import load_state, save_state

FAILURE_PATTERNS = (
    re.compile(r"\bTraceback \(most recent call last\)", re.I),
    re.compile(r"\bAssertionError\b", re.I),
    re.compile(r"(?im)^\s*(?:FAILED\b|FAILURES?\s*$)"),
    re.compile(r"\b(?:error|exception)\s*:", re.I),
    re.compile(r"\b(?:exit|return)\s+code\s*[:=]?\s*[1-9]\d*", re.I),
    re.compile(r"\bModuleNotFoundError\b|\bImportError\b|\bSyntaxError\b", re.I),
)


def session_start(event: dict[str, Any], config: CodexConfig) -> dict:
    session_id = _session_id(event)
    existing = load_state(config.trace_output, session_id)
    recovered = False
    if existing and not existing.get("finished") and existing.get("lifecycle"):
        _finish_runtime_session(
            existing,
            config,
            transcript_path=event.get("transcript_path"),
            reason="session_resume_recovery",
        )
        existing["pending"] = {}
        save_state(config.trace_output, session_id, existing)
        recovered = True
    if config.session_selector == "prompt" and config.inherit is None:
        selection = existing.get("selection") if existing else None
        if selection:
            status = selection.get("status")
            if status == "pending":
                selection = _refresh_pending_selection(
                    existing,
                    event,
                    config,
                )
                save_state(config.trace_output, session_id, existing)
                if config.selector_surface == "inline":
                    return _selection_output("SessionStart", selection)
                return _launch_selection_browser(
                    existing,
                    event,
                    config,
                    event_name="SessionStart",
                )
            if status == "browser_pending":
                return _browser_waiting_output(selection, "SessionStart")
            if status == "disabled":
                return {
                    "systemMessage": "ATLAS is disabled for this conversation."
                }
            return _add_context(
                _selected_context(selection, state=existing, config=config),
                event_name="SessionStart",
                system_message=(
                    "ATLAS recovered and closed the previous unfinished episode."
                    if recovered
                    else None
                ),
            )
        if not existing:
            selection = build_selection(
                trace_output=config.trace_output,
                store_dir=config.store_dir,
                cwd=event.get("cwd"),
                catalog_mode=config.selector_surface,
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
            if config.selector_surface == "inline":
                return _selection_output("SessionStart", selection)
            return _launch_selection_browser(
                state,
                event,
                config,
                event_name="SessionStart",
            )

    if recovered:
        return _add_context(
            STANDING_PROMPT,
            event_name="SessionStart",
            system_message=(
                "ATLAS recovered and closed the previous unfinished episode."
            ),
        )

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
    return _add_context(context)


def _start_episode(
    event: dict[str, Any],
    config: CodexConfig,
    *,
    sequence: int,
    cursor: int,
    previous: dict[str, Any] | None = None,
    taxonomy_id: str | None = None,
    episode_task: str | None = None,
) -> tuple[dict[str, Any], Session]:
    """Start one runtime task inside a longer Codex conversation."""
    session_id = _session_id(event)

    # A selector choice establishes the project/group root. Once generation or
    # refinement activates a successor, later episodes follow that shared
    # binding instead of trying to pin the conversation to its original id.
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
        session_id=f"codex:{session_id}:episode:{sequence}",
        atlas_model=config.atlas_model,
        repo_path=event.get("cwd") or Path.cwd(),
        max_retries=config.max_retries,
        dashboard=config.dashboard,
        generation_threshold=config.generation_threshold,
        # Hook processes are killed at the harness's hook timeout, so
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
        max_retries=config.max_retries,
        main_cursor=cursor,
        episode_sequence=sequence,
        episode_cursor=cursor,
        failure={
            "call_index": 0,
            "last_hash": "",
            "last_fired_at": 0.0,
        },
    )
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


def user_prompt_submit(event: dict[str, Any], config: CodexConfig) -> dict | None:
    """Resolve the Codex selector and start the chosen episode."""
    session_id = _session_id(event)
    state = load_state(config.trace_output, session_id)
    if not state:
        session_start({**event, "hook_event_name": "SessionStart"}, config)
        state = load_state(config.trace_output, session_id)
    prompt = _user_prompt(event)

    recovered = False
    if (
        prompt
        and state.get("lifecycle")
        and not state.get("finished")
        and has_assistant_activity(
            event.get("transcript_path"),
            after=int(state.get("episode_cursor", 0)),
        )
    ):
        _finish_runtime_session(
            state,
            config,
            transcript_path=event.get("transcript_path"),
            reason="next_user_prompt_recovery",
            exclude_trailing_user=prompt,
        )
        state["pending"] = {}
        save_state(config.trace_output, session_id, state)
        recovered = True

    if config.session_selector != "prompt" or config.inherit is not None:
        if not prompt:
            return None
        if state.get("finished"):
            fresh, _session = _start_episode(
                event,
                config,
                sequence=max(1, int(state.get("episode_sequence", 0)) + 1),
                cursor=transcript_size(event.get("transcript_path")),
                previous=state,
                episode_task=prompt,
            )
            save_state(config.trace_output, session_id, fresh)
        elif not state.get("episode_task"):
            state["episode_task"] = prompt
            save_state(config.trace_output, session_id, state)
        if recovered:
            return _add_context(
                STANDING_PROMPT,
                event_name="UserPromptSubmit",
                system_message=(
                    "ATLAS recovered the previous episode and started a new one."
                ),
            )
        return None

    selection = state.get("selection")
    if not selection:
        return None

    if (
        selection.get("status") == "pending"
        and int(selection.get("version") or 0) < SELECTOR_VERSION
    ):
        selection = _refresh_pending_selection(state, event, config)
        save_state(config.trace_output, session_id, state)
        return _selection_output("UserPromptSubmit", selection)

    status = selection.get("status")
    if status == "disabled":
        return None
    if status in {"pending", "browser_pending"}:
        choice = None
        if status == "browser_pending":
            taxonomy_id = read_browser_choice(
                selection.get("browser_picker"),
                store_dir=config.store_dir,
            )
            if taxonomy_id:
                if taxonomy_id == mast.MAST_ID:
                    choice = next(
                        (
                            option
                            for option in selection.get("options", [])
                            if option.get("kind") == "mast"
                        ),
                        None,
                    )
                elif taxonomy_id == "none":
                    choice = next(
                        (
                            option
                            for option in selection.get("options", [])
                            if option.get("kind") == "disabled"
                        ),
                        None,
                    )
                else:
                    choice = stored_option(taxonomy_id, config.store_dir)
                selection["status"] = "pending"
                if (
                    prompt
                    and not selection.get("pending_task")
                    and not _browser_continuation_prompt(prompt)
                ):
                    selection["pending_task"] = prompt
            else:
                if (
                    prompt
                    and not selection.get("pending_task")
                    and not _browser_continuation_prompt(prompt)
                ):
                    selection["pending_task"] = prompt
                save_state(config.trace_output, session_id, state)
                return _browser_waiting_output(selection, "UserPromptSubmit")

        if choice is None:
            choice = parse_selection_choice(prompt, selection)
        if choice is None:
            if prompt and not selection.get("pending_task"):
                selection["pending_task"] = prompt
                selection["held_cursor"] = transcript_size(
                    event.get("transcript_path")
                )
                save_state(config.trace_output, session_id, state)
            return _selection_output("UserPromptSubmit", selection)

        if choice["kind"] == "browser":
            return _launch_selection_browser(
                state,
                event,
                config,
                event_name="UserPromptSubmit",
            )

        selection["selected_kind"] = choice["kind"]
        selection["selected_taxonomy_id"] = choice.get("taxonomy_id")
        selection["selected_label"] = choice["label"]
        pending_task = str(selection.get("pending_task") or "").strip()
        if choice["kind"] == "disabled":
            selection["status"] = "disabled"
            state["finished"] = True
            save_state(config.trace_output, session_id, state)
            return _add_context(
                _disabled_context(pending_task),
                event_name="UserPromptSubmit",
                system_message="ATLAS disabled for this conversation.",
            )

        target_config = config
        if choice.get("starts_fresh"):
            target_config = config.start_fresh_conversation(event)
            selection["fresh_task_group"] = target_config.task_group
            selection["shared_taxonomy_preserved"] = selection.get(
                "project_taxonomy_id"
            )
            if target_config.trace_output != config.trace_output:
                routed_state = dict(state)
                routed_state["selection"] = dict(selection)
                source_state = dict(state)
                source_state["selection"] = {
                    **selection,
                    "status": "routed",
                }
                save_state(config.trace_output, session_id, source_state)
                state = routed_state

        selection["status"] = "selected"
        state["selection"] = selection
        if pending_task:
            fresh, _session = _start_episode(
                event,
                target_config,
                sequence=max(1, int(state.get("episode_sequence", 0)) + 1),
                cursor=transcript_size(event.get("transcript_path")),
                previous=state,
                taxonomy_id=str(choice["taxonomy_id"]),
                episode_task=pending_task,
            )
            save_state(target_config.trace_output, session_id, fresh)
        else:
            save_state(target_config.trace_output, session_id, state)
        return _add_context(
            _selection_accepted_context(selection, pending_task),
            event_name="UserPromptSubmit",
            system_message=f"ATLAS selected {choice['label']}.",
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
        return _add_context(
            _selected_context(selection, state=fresh, config=config)
            + "\n\n"
            + STANDING_PROMPT,
            event_name="UserPromptSubmit",
        )
    return None


def _ensure_active_episode(
    event: dict[str, Any],
    config: CodexConfig,
    state: dict[str, Any],
) -> dict[str, Any]:
    selection = state.get("selection") or {}
    if selection.get("status") in {"pending", "browser_pending", "disabled"}:
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


def stop(event: dict[str, Any], config: CodexConfig) -> dict | None:
    """Commit a Codex episode from the final answer in one host callback.

    Codex documents Stop continuation, but some desktop builds complete the
    task after rendering the continuation response without invoking Stop a
    second time. The Codex adapter therefore validates the compact checkpoint
    already present in the original final answer and never leaves the episode
    dependent on a second callback.
    """
    state = _state(event, config)
    selection = state.get("selection") or {}
    if selection.get("status") in {"pending", "browser_pending"}:
        return {
            "continue": True,
            "systemMessage": "ATLAS is waiting for taxonomy selection.",
        }
    if selection.get("status") == "disabled":
        return None
    state = _ensure_active_episode(event, config, state)
    if state.get("finished"):
        return {
            "continue": True,
            "systemMessage": "ATLAS episode already committed.",
        }

    recent = _recent_agent_text(
        event,
        after=int(state.get("main_cursor", state.get("episode_cursor", 0))),
    )
    reflection, gate_status, gate_error = _harvest_codex_checkpoint(
        recent,
        state,
    )
    if reflection is not None:
        record_reflection(
            config.trace_output,
            state,
            reflection,
            gate="stop",
            task_id=_task_id(event, "stop"),
            agent_id=event.get("agent_id"),
            agent_type="codex",
        )

    state["gate_result"] = {
        "status": gate_status,
        "error": gate_error,
        "stop_hook_active": bool(event.get("stop_hook_active")),
        "turn_id": event.get("turn_id"),
    }
    state.setdefault("pending", {}).pop("stop:main", None)
    _finish_runtime_session(
        state,
        config,
        transcript_path=event.get("transcript_path"),
        reason=(
            "stop_gate"
            if gate_status == "READY_TO_SUBMIT"
            else "stop_gate_unresolved"
            if gate_status == "REPAIR_REQUIRED"
            else "stop_gate_missing_checkpoint"
        ),
    )
    state["main_cursor"] = transcript_size(event.get("transcript_path"))
    save_state(config.trace_output, state["session_id"], state)

    if gate_status == "READY_TO_SUBMIT":
        message = "ATLAS checkpoint accepted; episode trace committed."
    elif gate_status == "REPAIR_REQUIRED":
        message = (
            "ATLAS episode trace committed with an unresolved repair checkpoint."
        )
    else:
        message = (
            "ATLAS episode trace committed, but the final compact checkpoint "
            f"was missing or invalid: {gate_error or 'unknown format error'}."
        )
    warning = state.get("project_scope_warning")
    if warning:
        message += "\n\n" + str(warning)
    return {"continue": True, "systemMessage": message}


def subagent_stop(event: dict[str, Any], config: CodexConfig) -> dict | None:
    workspace = ProgramWorkspace(config.trace_output, repo_path=event.get("cwd"))
    try:
        learning_job_id = capture_learning_receipt(workspace, event)
    except (LearningJobError, OSError, ValueError) as exc:
        return {
            "continue": True,
            "systemMessage": f"ATLAS ignored an invalid taxonomy receipt: {exc}",
        }
    if learning_job_id:
        return {
            "continue": True,
            "systemMessage": (
                f"ATLAS taxonomy proposal received for {learning_job_id}; "
                "validation is pending."
            ),
        }
    state = _state(event, config)
    if _selection_inactive(state) or state.get("finished"):
        return None
    agent_event = {
        **event,
        "transcript_path": (
            event.get("agent_transcript_path") or event.get("transcript_path")
        ),
    }
    recent = _recent_agent_text(agent_event)
    reflection, _status, _error = _harvest_codex_checkpoint(recent, state)
    if reflection is None:
        return None
    record_reflection(
        config.trace_output,
        state,
        reflection,
        gate="subagent_stop",
        task_id=_task_id(event, "subagent_stop"),
        agent_id=event.get("agent_id"),
        agent_type=event.get("agent_type") or "codex_subagent",
    )
    return {
        "continue": True,
        "systemMessage": "ATLAS subagent checkpoint captured.",
    }


def post_tool_use(event: dict[str, Any], config: CodexConfig) -> dict | None:
    state = _state(event, config)
    if _selection_inactive(state):
        return None
    state = _ensure_active_episode(event, config, state)
    if state.get("finished"):
        return None
    failure = state.setdefault("failure", {})
    failure["call_index"] = int(failure.get("call_index", 0)) + 1
    text = _tool_text(event)
    if not any(pattern.search(text) for pattern in FAILURE_PATTERNS):
        save_state(config.trace_output, state["session_id"], state)
        return None
    digest = hashlib.sha256(text[:8000].encode("utf-8", "replace")).hexdigest()[:16]
    now = time.time()
    if failure.get("last_hash") == digest or now - float(
        failure.get("last_fired_at", 0)
    ) < 30:
        save_state(config.trace_output, state["session_id"], state)
        return None
    failure.update({"last_hash": digest, "last_fired_at": now})
    checkpoint_id = _checkpoint_id("failure")
    state.setdefault("pending", {})[f"nudge:{checkpoint_id}"] = {
        "checkpoint_id": checkpoint_id,
        "offset": transcript_size(event.get("transcript_path")),
        "full": False,
        "recorded": False,
        "advisory": True,
    }
    save_state(config.trace_output, state["session_id"], state)
    return _add_context(
        failure_nudge(
            state,
            checkpoint_id=checkpoint_id,
            failure_summary=text[-4000:],
        )
    )


def blocking_checkpoint(
    event: dict[str, Any],
    config: CodexConfig,
    *,
    gate: str,
    full: bool,
) -> dict | None:
    state = _state(event, config)
    selection = state.get("selection") or {}
    if selection.get("status") in {"pending", "browser_pending"}:
        return {
            "continue": True,
            "systemMessage": "ATLAS is waiting for taxonomy selection.",
        }
    if selection.get("status") == "disabled":
        return None
    state = _ensure_active_episode(event, config, state)
    if state.get("finished"):
        return {
            "continue": True,
            "systemMessage": "ATLAS episode already committed.",
        }
    key = f"{gate}:main"
    pending = state.setdefault("pending", {}).get(key)
    transcript_path = event.get("transcript_path")
    if pending:
        recent = _recent_agent_text(event, after=int(pending.get("offset", 0)))
        try:
            reflection = parse_reflection(
                recent,
                checkpoint_id=pending["checkpoint_id"],
                known_code_ids=_code_ids(state),
            )
        except ValueError as exc:
            return _block(
                f"ATLAS reflection is incomplete: {exc}\n\n"
                + str(pending.get("prompt", ""))
            )

        if not pending.get("recorded"):
            record_reflection(
                config.trace_output,
                state,
                reflection,
                gate=gate,
                task_id=_task_id(event, gate),
                agent_id=event.get("agent_id"),
                agent_type="codex",
            )
            pending["recorded"] = True

        if full:
            decision = evaluate_pre_submission(
                recent,
                max_retries=int(state["max_retries"]),
            )
            if not decision.allow:
                save_state(config.trace_output, state["session_id"], state)
                return _block(
                    f"ATLAS final gate still blocks completion: "
                    f"{decision.reason}\n\n{pending.get('prompt', '')}"
                )
            if decision.status == "REPAIR_REQUIRED" and decision.allow:
                # Retry budget has been exhausted; capture the honest unresolved
                # report rather than looping forever.
                pass
            _finish_runtime_session(
                state,
                config,
                transcript_path=transcript_path,
                reason="stop_gate",
            )

        state["pending"].pop(key, None)
        state["main_cursor"] = transcript_size(transcript_path)
        save_state(config.trace_output, state["session_id"], state)
        return {"continue": True, "systemMessage": "ATLAS reflection accepted."}

    checkpoint_id = _checkpoint_id(gate)
    recent = _recent_agent_text(event, after=int(state.get("main_cursor", 0)))
    prompt = reflection_prompt(
        state,
        checkpoint_id=checkpoint_id,
        gate_label="submission gate" if full else "subagent checkpoint",
        recent_activity=recent,
        full=full,
    )
    state["pending"][key] = {
        "checkpoint_id": checkpoint_id,
        "offset": transcript_size(transcript_path),
        "prompt": prompt,
        "full": full,
        "recorded": False,
    }
    save_state(config.trace_output, state["session_id"], state)
    return _block(prompt)


def _harvest_codex_checkpoint(
    text: str,
    state: dict[str, Any],
) -> tuple[ReflectionResult | None, str, str | None]:
    """Harvest either a legacy full reflection or the compact final block."""
    pending = (state.get("pending") or {}).get("stop:main")
    if pending:
        try:
            reflection = parse_reflection(
                text,
                checkpoint_id=str(pending["checkpoint_id"]),
                known_code_ids=_code_ids(state),
            )
        except ValueError:
            pass
        else:
            decision = evaluate_pre_submission(
                text,
                max_retries=int(state["max_retries"]),
            )
            status = (
                decision.status
                if decision.status in {"READY_TO_SUBMIT", "REPAIR_REQUIRED"}
                else "READY_TO_SUBMIT"
            )
            return reflection, status, None

    fields, error = _compact_checkpoint_fields(text)
    if fields is None:
        return None, "MISSING_CHECKPOINT", error

    known = {code_id.lower(): code_id for code_id in _code_ids(state)}
    codes_text = fields["relevant codes"]
    none_apply = bool(
        re.search(r"\b(?:none|none\s+apply|n/?a)\b", codes_text, re.I)
    )
    mentioned: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_.-]*-\d+", codes_text):
        canonical = known.get(token.lower())
        if canonical and canonical not in mentioned:
            mentioned.append(canonical)
    if not none_apply and not mentioned:
        return (
            None,
            "MISSING_CHECKPOINT",
            "Relevant codes must name an active taxonomy code or `none apply`",
        )

    evidence = fields["evidence"]
    checkpoint = fields["checkpoint"]
    next_action = fields["next action"]
    assignments = tuple(
        CodeAssignment(code_id=code_id, evidence=evidence)
        for code_id in mentioned
    )
    status = (
        "REPAIR_REQUIRED"
        if re.search(
            r"(?i)\b(?:repair|required|report\s+unresolved|blocked)\b",
            next_action,
        )
        else "READY_TO_SUBMIT"
    )
    return (
        ReflectionResult(
            checkpoint_id=_checkpoint_id("stop"),
            observe=checkpoint,
            assignments=assignments,
            considered_codes=tuple(mentioned),
            none_apply=not assignments,
            correlate=evidence,
            decide=next_action,
        ),
        status,
        None,
    )


def _compact_checkpoint_fields(
    text: str,
) -> tuple[dict[str, str] | None, str | None]:
    """Parse the user-visible four-line ATLAS checkpoint from a final answer."""
    lines = [_checkpoint_line(line) for line in str(text or "").splitlines()]
    starts = [
        index
        for index, line in enumerate(lines)
        if re.match(r"(?i)^checkpoint\s*:", line)
        and not re.match(r"(?i)^checkpoint\s+id\s*:", line)
    ]
    if not starts:
        return None, "missing `Checkpoint:` line"
    fields: dict[str, str] = {}
    for line in lines[starts[-1] :]:
        match = re.match(
            r"(?i)^(checkpoint|relevant\s+codes|evidence|next\s+action)\s*:\s*(.*)$",
            line,
        )
        if match:
            fields[" ".join(match.group(1).lower().split())] = match.group(2).strip()
    for name in ("checkpoint", "relevant codes", "evidence", "next action"):
        if not fields.get(name):
            return None, f"missing or empty `{name.title()}:` line"
    return fields, None


def _checkpoint_line(line: str) -> str:
    cleaned = re.sub(r"^[\s#>*-]+", "", str(line or "")).strip()
    return cleaned.replace("**", "").replace("__", "").strip()


def _without_trailing_user(raw_trajectory: str, prompt: str) -> str:
    lines = str(raw_trajectory or "").splitlines()
    for index in range(len(lines) - 1, -1, -1):
        try:
            item = json.loads(lines[index])
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") == "user" and str(item.get("text") or "").strip() == prompt.strip():
            del lines[index]
        break
    return "\n".join(lines).strip()


def _finish_runtime_session(
    state: dict[str, Any],
    config: CodexConfig,
    *,
    transcript_path: str | None,
    reason: str,
    exclude_trailing_user: str | None = None,
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
        # Hook processes are killed at the harness's hook timeout: learning
        # must never run inline here. Background workers only, regardless of
        # the configured *_stops flags.
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
    if not persisted_trace_names:
        raw_trajectory = read_raw_transcript(
            transcript_path,
            after=cursor,
        ).strip()
        if exclude_trailing_user:
            raw_trajectory = _without_trailing_user(
                raw_trajectory,
                exclude_trailing_user,
            )
        capture_trajectory = (
            raw_trajectory
            if trace_has_assistant_activity(raw_trajectory)
            else ""
        )
        external = external_workdirs(
            capture_trajectory,
            bound_root=state.get("cwd"),
        )
        if external:
            state["project_scope_warning"] = (
                "ATLAS project scope mismatch: this conversation is bound to "
                f"{state.get('cwd') or 'an unknown root'}, but tool work explicitly "
                f"ran in {', '.join(external)}. Start the next task from the actual "
                "repository or configure a stable codex.project_id before collecting "
                "more shared taxonomy traces."
            )
        else:
            state.pop("project_scope_warning", None)

    if not persisted_trace_names and capture_trajectory:
        task = str(state.get("episode_task") or "").strip() or first_user_message(
            transcript_path, after=cursor
        ).strip() or (
            f"Codex episode {sequence} in "
            f"{state.get('cwd') or 'unknown working directory'}"
        )
        trace = GenerationTrace(
            problem_id=f"codex:{state['session_id']}:episode:{sequence}",
            task=task,
            raw_trajectory=capture_trajectory,
            metadata={
                "harness": "codex",
                "codex_session_id": state["session_id"],
                "conversation_id": state["session_id"],
                "episode_sequence": sequence,
                "trace_granularity": "episode",
                "runtime_session_id": state["runtime_session_id"],
                "taxonomy_id": state["taxonomy_id"],
                "end_reason": reason,
                "transcript_format": "codex_normalized_jsonl_v1",
                "external_workdirs": external,
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
    if config.learning_backend == "codex_subagent":
        common = {
            "store_dir": config.store_dir,
            "trace_root": config.trace_root,
            "task_group": config.task_group,
            "conversation_id": str(state["session_id"]),
            "worker_model": config.worker_model,
            "worker_timeout_seconds": config.worker_timeout_seconds,
        }
        generation_launcher = lambda: enqueue_learning_job(
            workspace,
            kind="generation",
            **common,
        )
        refinement_launcher = lambda: enqueue_learning_job(
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


def _state(event: dict[str, Any], config: CodexConfig) -> dict[str, Any]:
    session_id = _session_id(event)
    state = load_state(config.trace_output, session_id)
    if not state:
        session_start(event, config)
        state = load_state(config.trace_output, session_id)
    return state


def _session_id(event: dict[str, Any]) -> str:
    for key in ("session_id", "thread_id", "conversation_id"):
        value = event.get(key)
        if value:
            return str(value)
    cwd = str(event.get("cwd") or Path.cwd())
    return hashlib.sha256(cwd.encode("utf-8", "replace")).hexdigest()[:16]


def _checkpoint_id(gate: str) -> str:
    return f"atlas-{gate}-{uuid.uuid4().hex[:12]}"


def _code_ids(state: dict[str, Any]) -> set[str]:
    return {
        str(code.get("id"))
        for code in state.get("taxonomy", {}).get("codes", [])
        if isinstance(code, dict) and code.get("id")
    }


def _recent_agent_text(event: dict[str, Any], *, after: int = 0) -> str:
    chunks = []
    for key in ("last_assistant_message", "assistant_message", "message", "text"):
        value = event.get(key)
        if value:
            chunks.append(_stringify(value))
    transcript = read_transcript(event.get("transcript_path"), after=after)
    if transcript:
        chunks.append(transcript)
    if not chunks:
        chunks.append(_stringify(event))
    return "\n".join(chunk for chunk in chunks if chunk.strip())


def _tool_text(event: dict[str, Any]) -> str:
    for key in ("tool_response", "output", "result", "stderr", "stdout", "error"):
        value = event.get(key)
        if value:
            return _stringify(value)
    return _stringify(event)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _task_id(event: dict[str, Any], gate: str) -> str:
    return str(
        event.get("task_id")
        or event.get("thread_id")
        or event.get("session_id")
        or gate
    )


def _block(reason: str) -> dict:
    return {"decision": "block", "reason": reason}


def _add_context(
    context: str,
    *,
    event_name: str | None = None,
    system_message: str | None = None,
) -> dict:
    specific = {"additionalContext": context}
    if event_name:
        specific["hookEventName"] = event_name
    output = {"hookSpecificOutput": specific}
    if system_message:
        output["systemMessage"] = system_message
    return output


def _selection_output(event_name: str, selection: dict[str, Any]) -> dict:
    return _add_context(
        selection_interstitial(selection),
        event_name=event_name,
        system_message="ATLAS taxonomy selection required.",
    )


def _refresh_pending_selection(
    state: dict[str, Any],
    event: dict[str, Any],
    config: CodexConfig,
) -> dict[str, Any]:
    current = state.get("selection") or {}
    if int(current.get("version") or 0) >= SELECTOR_VERSION:
        return current
    refreshed = build_selection(
        trace_output=config.trace_output,
        store_dir=config.store_dir,
        cwd=event.get("cwd"),
        catalog_mode=config.selector_surface,
    )
    for key in ("pending_task", "held_cursor"):
        if current.get(key) is not None:
            refreshed[key] = current[key]
    state["selection"] = refreshed
    return refreshed


def _launch_selection_browser(
    state: dict[str, Any],
    event: dict[str, Any],
    config: CodexConfig,
    *,
    event_name: str,
) -> dict:
    selection = state.get("selection") or {}
    try:
        picker = start_browser_picker(
            config.trace_output,
            _session_id(event),
            store_dir=config.store_dir,
            selection=selection,
            event=event,
            routing_root=config.routing_root or config.trace_output,
            default_trace_output=(
                config.default_trace_output or config.trace_output
            ),
            task_group=config.task_group,
            project_scope=config.project_scope,
            project_id=config.project_id,
            timeout_seconds=config.worker_timeout_seconds,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _add_context(
            "ATLAS could not open its local taxonomy library. Do not perform "
            "the held task yet; report the selector error to the user.",
            event_name=event_name,
            system_message=f"ATLAS could not open the taxonomy library: {exc}",
        )
    selection["status"] = "browser_pending"
    selection["browser_picker"] = picker
    state["selection"] = selection
    save_state(config.trace_output, _session_id(event), state)
    open_browser_picker(picker)
    return _browser_opened_output(selection, event_name)


def _browser_opened_output(selection: dict[str, Any], event_name: str) -> dict:
    picker = selection.get("browser_picker") or {}
    url = str(picker.get("url") or "the local ATLAS catalog")
    return _add_context(
        "ATLAS taxonomy selection is waiting in the local browser. The catalog "
        f"opened at {url}. Do not perform the held task yet. Ask the user to "
        "choose a taxonomy there. The browser applies it directly to this "
        "conversation; return to Codex when the page confirms activation.",
        event_name=event_name,
        system_message="ATLAS taxonomy library opened in the browser.",
    )


def _browser_waiting_output(
    selection: dict[str, Any],
    event_name: str,
) -> dict:
    picker = selection.get("browser_picker") or {}
    url = str(picker.get("url") or "the local ATLAS catalog")
    return _add_context(
        "ATLAS is still waiting for a taxonomy choice in the local browser at "
        f"{url}. Do not perform the held task yet. Ask the user to finish the "
        "browser selection and send another message.",
        event_name=event_name,
        system_message="ATLAS is waiting for the browser taxonomy selection.",
    )


def _selection_inactive(state: dict[str, Any]) -> bool:
    return (state.get("selection") or {}).get("status") in {
        "pending",
        "browser_pending",
        "disabled",
    }


def _browser_continuation_prompt(prompt: str) -> bool:
    return str(prompt or "").strip().casefold() in {
        "continue",
        "done",
        "selected",
        "i selected it",
        "selection complete",
    }


def _selected_context(
    selection: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    config: CodexConfig | None = None,
) -> str:
    active_id = str((state or {}).get("taxonomy_id") or "").strip() or None
    store_dir = config.store_dir if config else Path()
    if config:
        manifest_id = ProgramWorkspace(config.trace_output).load().get("taxonomy_id")
        active_id = str(manifest_id or active_id or "").strip() or None
    return render_active_selection_context(
        selection,
        active_taxonomy_id=active_id,
        store_dir=store_dir,
    )


def _selection_accepted_context(
    selection: dict[str, Any],
    pending_task: str,
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
    transcript_prompt = latest_user_message(event.get("transcript_path"))
    if transcript_prompt:
        return transcript_prompt
    for key in ("prompt", "user_prompt", "message", "text"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            prompt = value.strip()
            if not _internal_prompt(prompt):
                return prompt
    return ""


def _internal_prompt(prompt: str) -> bool:
    lowered = str(prompt or "").lstrip().lower()
    return lowered.startswith(
        (
            "<hook_prompt",
            "<environment_context",
            "<skills_instructions",
            "<permissions instructions",
            "<app-context",
        )
    )


def decisions_log(config: CodexConfig, event: dict[str, Any], output: dict | None) -> None:
    path = Path(config.trace_output) / "codex-decisions.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8") if not path.exists() else None
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": event.get("hook_event_name"),
                    "session_id": _session_id(event),
                    "output": output,
                },
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )
