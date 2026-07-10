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

from atlas_integration.claude_code.transcript import (
    first_user_message,
    read_raw_transcript,
    read_transcript,
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
from atlas_runtime.reflection import parse_reflection
from finding import resolver

from atlas_integration.shared import build_session_state

from .config import CodexConfig
from .prompts import STANDING_PROMPT, failure_nudge, reflection_prompt
from .state import load_state, save_state

FAILURE_PATTERNS = (
    re.compile(r"\bTraceback \(most recent call last\)", re.I),
    re.compile(r"\bAssertionError\b", re.I),
    re.compile(r"\b(?:FAILED|FAILURES?)\b", re.I),
    re.compile(r"\b(?:error|exception)\s*:", re.I),
    re.compile(r"\b(?:exit|return)\s+code\s*[:=]?\s*[1-9]\d*", re.I),
    re.compile(r"\bModuleNotFoundError\b|\bImportError\b|\bSyntaxError\b", re.I),
)


def session_start(event: dict[str, Any], config: CodexConfig) -> dict:
    session_id = _session_id(event)
    existing = load_state(config.trace_output, session_id)
    if existing and not existing.get("finished"):
        return _add_context(STANDING_PROMPT)

    inherit = config.inherit if config.inherit is not None else resolver.ABSENT
    session = start_session(
        inherit,
        trace_output=config.trace_output,
        store_dir=config.store_dir,
        trace_root=config.trace_root,
        session_id=f"codex:{session_id}",
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
        main_cursor=transcript_size(event.get("transcript_path")),
        failure={
            "call_index": 0,
            "last_hash": "",
            "last_fired_at": 0.0,
        },
    )
    save_state(config.trace_output, session_id, state)
    context = STANDING_PROMPT
    if session.delivery.dashboard_url:
        context += f"\nLive ATLAS dashboard: {session.delivery.dashboard_url}\n"
    return _add_context(context)


def stop(event: dict[str, Any], config: CodexConfig) -> dict:
    return blocking_checkpoint(event, config, gate="stop", full=True)


def subagent_stop(event: dict[str, Any], config: CodexConfig) -> dict:
    return blocking_checkpoint(event, config, gate="subagent_stop", full=False)


def post_tool_use(event: dict[str, Any], config: CodexConfig) -> dict | None:
    state = _state(event, config)
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
) -> dict:
    state = _state(event, config)
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


def _finish_runtime_session(
    state: dict[str, Any],
    config: CodexConfig,
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
    if not state.get("trace_captured"):
        raw_trajectory = read_raw_transcript(transcript_path).strip()
        if not raw_trajectory:
            raw_trajectory = (
                "Codex session ended before transcript content was available."
            )
        task = first_user_message(transcript_path).strip() or (
            f"Codex task in {state.get('cwd') or 'unknown working directory'}"
        )
        trace = GenerationTrace(
            problem_id=f"codex:{state['session_id']}",
            task=task,
            raw_trajectory=raw_trajectory,
            metadata={
                "harness": "codex",
                "codex_session_id": state["session_id"],
                "runtime_session_id": state["runtime_session_id"],
                "taxonomy_id": state["taxonomy_id"],
                "end_reason": reason,
            },
        )
        if config.redact_traces:
            trace = redact_trace(trace)
        workspace.pending.append_many_with_names([trace])
        # Persist the capture marker before any lifecycle work: a crash or
        # hook-timeout kill in end_session below must not let a retry record
        # a second copy of this trace.
        state["trace_captured"] = True
        save_state(config.trace_output, state["session_id"], state)
    result = end_session(session)
    state["trace_capture"] = {
        "persisted_traces": 1,
        "integrated_traces": result.integrated_traces,
        "generation_action": result.generation.action,
        "refinement_action": result.refinement.action,
        "reason": reason,
    }
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


def _add_context(context: str) -> dict:
    return {"hookSpecificOutput": {"additionalContext": context}}


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
