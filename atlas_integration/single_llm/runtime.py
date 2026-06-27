"""Drive one LLM agent conversation through the ATLAS lifecycle."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable

from atlas_runtime import (
    GenerationTrace,
    ReflectionResult,
    SessionEndResult,
    end_session,
    pre_submission,
    record_trace,
    start_session,
)
from atlas_runtime.checkpoint_prompt import render_reflection_prompt
from atlas_runtime.evidence import record_reflection
from atlas_runtime.reflection import parse_reflection
from atlas_runtime.traces import DEFAULT_TRACE_ROOT
from finding import resolver, store

MessageCall = Callable[[list[dict[str, str]]], str]

CHECKPOINT_REQUEST = re.compile(
    r"ATLAS\s+checkpoint\s+request\s*:\s*(.+)",
    re.IGNORECASE,
)

STANDING_PROMPT = (
    resources.files("atlas_integration.single_llm")
    .joinpath("assets", "standing_prompt.md")
    .read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class SingleLLMConfig:
    trace_output: Path
    atlas_model: str
    store_dir: Path = store.DEFAULT_STORE_DIR
    trace_root: Path = DEFAULT_TRACE_ROOT
    inherit: str | None = None
    max_retries: int = 3
    max_checkpoints: int = 20
    dashboard: bool = True
    repo: str | None = None
    repo_path: Path | None = None
    generation_stops: bool = False
    skip_judge: bool = False
    refinement_stops: bool = False
    advanced_refinement: bool = False


@dataclass(frozen=True)
class SingleLLMResult:
    answer: str
    gate_text: str
    checkpoint_count: int
    messages: tuple[dict[str, str], ...]
    session_end: SessionEndResult


def run_single_llm(
    task: str,
    call: MessageCall,
    config: SingleLLMConfig,
    *,
    problem_id: str | None = None,
) -> SingleLLMResult:
    """Run one no-harness LLM agent with dynamic ATLAS checkpoints."""
    if not task.strip():
        raise ValueError("task cannot be empty")
    inherit = config.inherit if config.inherit is not None else resolver.ABSENT
    run_id = problem_id or f"single-llm:{uuid.uuid4().hex}"
    session = start_session(
        inherit,
        trace_output=config.trace_output,
        store_dir=config.store_dir,
        trace_root=config.trace_root,
        session_id=run_id,
        atlas_model=config.atlas_model,
        max_retries=config.max_retries,
        dashboard=config.dashboard,
        repo=config.repo,
        repo_path=config.repo_path,
        generation_stops=config.generation_stops,
        skip_judge=config.skip_judge,
        refinement_stops=config.refinement_stops,
        advanced_refinement=config.advanced_refinement,
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": STANDING_PROMPT},
        {"role": "user", "content": task},
    ]
    checkpoint_count = 0
    repair_attempts = 0
    segment_start = 1
    answer = ""
    gate_text = ""
    try:
        while True:
            answer = _call(call, messages)
            messages.append({"role": "assistant", "content": answer})
            marker = CHECKPOINT_REQUEST.search(answer)
            if marker:
                checkpoint_count += 1
                if checkpoint_count > config.max_checkpoints:
                    raise RuntimeError(
                        f"single-LLM checkpoint limit exceeded "
                        f"({config.max_checkpoints})"
                    )
                recent = _render_messages(messages[segment_start:])
                reflection = _collect_reflection(
                    call,
                    messages,
                    session.delivery.taxonomy_id,
                    session.delivery.taxonomy,
                    recent_activity=recent,
                    gate_label="major-segment checkpoint",
                    full=False,
                    max_retries=config.max_retries,
                )
                _record(
                    config,
                    run_id,
                    session.delivery.taxonomy_id,
                    reflection,
                    gate="single_llm_checkpoint",
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "ATLAS checkpoint accepted. Apply the reflected "
                            "change only if Decide required one, then continue "
                            "the original task."
                        ),
                    }
                )
                segment_start = len(messages) - 1
                continue

            reflection, gate_text = _collect_final_gate(
                call,
                messages,
                session,
                max_retries=config.max_retries,
                repair_attempts_used=repair_attempts,
            )
            _record(
                config,
                run_id,
                session.delivery.taxonomy_id,
                reflection,
                gate="single_llm_stop",
            )
            decision = pre_submission(session, gate_text)
            if decision.allow:
                break
            repair_attempts += 1
            if repair_attempts > config.max_retries:
                raise RuntimeError("ATLAS final repair limit exceeded")
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"ATLAS blocked completion: {decision.reason}. "
                        "Perform the focused repair from Decide, verify it, "
                        "and return a corrected proposed final answer."
                    ),
                }
            )

        record_trace(
            session,
            GenerationTrace(
                problem_id=run_id,
                task=task,
                raw_trajectory=_render_messages(messages),
                metadata={
                    "harness": "single_llm",
                    "taxonomy_id": session.delivery.taxonomy_id,
                    "checkpoint_count": checkpoint_count,
                },
            ),
        )
        ended = end_session(session)
        return SingleLLMResult(
            answer=answer,
            gate_text=gate_text,
            checkpoint_count=checkpoint_count,
            messages=tuple(messages),
            session_end=ended,
        )
    except Exception:
        if not session._ended:
            session.workspace.finish_session(session.session_id)
            session._ended = True
        raise


def _collect_final_gate(
    call,
    messages,
    session,
    *,
    max_retries,
    repair_attempts_used,
):
    return _collect_reflection(
        call,
        messages,
        session.delivery.taxonomy_id,
        session.delivery.taxonomy,
        recent_activity=_render_messages(messages),
        gate_label="final submission gate",
        full=True,
        max_retries=max_retries,
        return_text=True,
        prompt_suffix=(
            "\nThe runtime-counted value for `Repair attempts used:` is "
            f"{repair_attempts_used}. Emit that exact integer."
        ),
    )


def _collect_reflection(
    call: MessageCall,
    messages: list[dict[str, str]],
    taxonomy_id: str,
    taxonomy: dict,
    *,
    recent_activity: str,
    gate_label: str,
    full: bool,
    max_retries: int,
    return_text: bool = False,
    prompt_suffix: str = "",
):
    checkpoint_id = uuid.uuid4().hex
    prompt = render_reflection_prompt(
        taxonomy_id=taxonomy_id,
        codes=taxonomy["codes"],
        checkpoint_id=checkpoint_id,
        gate_label=gate_label,
        recent_activity=recent_activity,
        full=full,
    ) + prompt_suffix
    known = [str(code["id"]) for code in taxonomy["codes"]]
    for attempt in range(max_retries + 1):
        messages.append({"role": "user", "content": prompt})
        text = _call(call, messages)
        messages.append({"role": "assistant", "content": text})
        try:
            reflection = parse_reflection(
                text,
                checkpoint_id=checkpoint_id,
                known_code_ids=known,
            )
            return (reflection, text) if return_text else reflection
        except ValueError as exc:
            if attempt >= max_retries:
                raise RuntimeError(
                    f"ATLAS reflection remained invalid: {exc}"
                ) from exc
            prompt = (
                f"ATLAS reflection was invalid: {exc}. Re-emit the complete "
                f"reflection for Checkpoint ID {checkpoint_id} in the exact "
                "required shape."
            )
    raise AssertionError("unreachable")


def _record(
    config: SingleLLMConfig,
    run_id: str,
    taxonomy_id: str,
    reflection: ReflectionResult,
    *,
    gate: str,
) -> None:
    record_reflection(
        Path(config.trace_output),
        {
            "taxonomy_id": taxonomy_id,
            "session_id": run_id,
        },
        reflection,
        gate=gate,
        task_id=run_id,
    )


def _call(call: MessageCall, messages: list[dict[str, str]]) -> str:
    result = call([dict(message) for message in messages])
    if not isinstance(result, str) or not result.strip():
        raise RuntimeError("single-LLM model call returned no text")
    return result.strip()


def _render_messages(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(
        f"[{message['role'].upper()}]\n{message['content']}"
        for message in messages
    )
