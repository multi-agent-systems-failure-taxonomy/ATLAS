"""Prompt assets for the Codex hook integration."""

from __future__ import annotations

from importlib import resources
from string import Template
from typing import Any

from atlas_runtime.checkpoint_prompt import render_reflection_prompt


def _text_asset(name: str) -> str:
    return (
        resources.files("atlas_integration.codex")
        .joinpath("assets", name)
        .read_text(encoding="utf-8")
    )


STANDING_PROMPT = _text_asset("standing_prompt.md")


def reflection_prompt(
    state: dict[str, Any],
    *,
    checkpoint_id: str,
    gate_label: str,
    recent_activity: str,
    full: bool,
) -> str:
    gate_tail = (
        Template(_text_asset("final_gate_tail.md")).substitute(
            repair_attempts_used=0
        )
        if full
        else ""
    )
    return render_reflection_prompt(
        taxonomy_id=str(state["taxonomy_id"]),
        codes=state["taxonomy"]["codes"],
        checkpoint_id=checkpoint_id,
        gate_label=gate_label,
        recent_activity=recent_activity,
        full=full,
        final_instructions=gate_tail,
    )
