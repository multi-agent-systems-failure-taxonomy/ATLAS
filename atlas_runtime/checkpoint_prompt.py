"""Shared ATLAS checkpoint-reflection prompt body."""

from __future__ import annotations

from importlib import resources
from string import Template
from typing import Any


def _text_asset(name: str) -> str:
    return (
        resources.files("atlas_runtime")
        .joinpath("assets", name)
        .read_text(encoding="utf-8")
    )


def render_reflection_prompt(
    *,
    taxonomy_id: str,
    codes: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    checkpoint_id: str,
    gate_label: str,
    recent_activity: str,
    full: bool,
    final_instructions: str = "",
) -> str:
    """Render the agent-agnostic checkpoint reflection prompt."""
    code_list = "\n".join(
        f"- {code['id']} — {code['name']}: {code['description']}"
        for code in codes
    )
    scope = "the full task trajectory" if full else (
        "only the recent activity since the previous ATLAS checkpoint"
    )
    return Template(_text_asset("checkpoint_reflection.md")).substitute(
        gate_label=gate_label,
        checkpoint_id=checkpoint_id,
        taxonomy_id=taxonomy_id,
        code_list=code_list,
        scope=scope,
        recent_activity=(
            recent_activity[-12000:]
            or "(no transcript text was available; use the activity in context)"
        ),
        final_instructions=final_instructions,
    )
