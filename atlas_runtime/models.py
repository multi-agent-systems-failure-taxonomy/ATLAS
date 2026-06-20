"""Recognized ATLAS model profiles used for adaptive judge batching."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    context_tokens: int
    output_reserve_tokens: int = 8_192
    safety_ratio: float = 0.90


def resolve_model_profile(model: str) -> ModelProfile:
    """Resolve a conservative context profile from a recognized model family."""
    name = (model or "").strip().lower()
    if not name:
        raise ValueError("atlas_model is required")
    if name.startswith("claude"):
        return ModelProfile(context_tokens=200_000)
    if name.startswith(("gpt-5", "o3", "o4")):
        return ModelProfile(context_tokens=400_000)
    if name.startswith(("gpt-4.1", "gpt-4o")):
        return ModelProfile(context_tokens=128_000)
    if name.startswith("gemini"):
        return ModelProfile(context_tokens=1_000_000)
    raise ValueError(f"unrecognized ATLAS model {model!r}")


def estimate_tokens(text: str) -> int:
    """Conservative dependency-free estimate for packing, not billing."""
    return max(1, (len(text.encode("utf-8")) + 2) // 3)
