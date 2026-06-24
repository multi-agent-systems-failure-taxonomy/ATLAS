"""Recognized ATLAS model profiles used for adaptive judge batching."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    context_tokens: int
    output_reserve_tokens: int = 8_192
    safety_ratio: float = 0.90


def resolve_model_profile(model: str) -> ModelProfile:
    """Resolve a conservative context profile from a recognized model family.

    Recognizes plain model ids (``claude-sonnet-4-5``) as well as Bedrock
    inference-profile shapes that carry a region prefix
    (``us.anthropic.claude-sonnet-4-5-...``, ``eu.anthropic.claude-...``) and
    the bare ``anthropic.claude-...`` form. All of these route to the Claude
    context profile.
    """
    name = (model or "").strip().lower()
    if not name:
        raise ValueError("atlas_model is required")
    if _is_anthropic_model(name):
        return ModelProfile(context_tokens=200_000)
    if name.startswith(("gpt-5", "o3", "o4")):
        return ModelProfile(context_tokens=400_000)
    if name.startswith(("gpt-4.1", "gpt-4o")):
        return ModelProfile(context_tokens=128_000)
    if name.startswith("gemini"):
        return ModelProfile(context_tokens=1_000_000)
    raise ValueError(f"unrecognized ATLAS model {model!r}")


_REGION_PREFIXES = ("us.", "eu.", "apac.", "ap-", "global.")


def _is_anthropic_model(name: str) -> bool:
    """True for plain Claude ids AND Bedrock inference-profile ids."""
    if name.startswith(("claude", "anthropic", "anthropic.claude")):
        return True
    if name.startswith("bedrock/") and "anthropic" in name:
        return True
    for prefix in _REGION_PREFIXES:
        if name.startswith(prefix) and "anthropic.claude" in name:
            return True
    return False


def is_anthropic_model(model: str) -> bool:
    """Public predicate — True iff the model id routes to a Claude transport."""
    return _is_anthropic_model((model or "").strip().lower())


def is_bedrock_model(model: str) -> bool:
    """True iff the model id looks like an AWS Bedrock inference profile.

    Used by the LLM transport to choose ``AnthropicBedrock()`` over the
    vanilla ``Anthropic()`` client.
    """
    name = (model or "").strip().lower()
    if not name:
        return False
    for prefix in _REGION_PREFIXES:
        if name.startswith(prefix) and "anthropic" in name:
            return True
    return name.startswith("bedrock/") or name.startswith("anthropic.")


def estimate_tokens(text: str) -> int:
    """Conservative dependency-free estimate for packing, not billing."""
    return max(1, (len(text.encode("utf-8")) + 2) // 3)
