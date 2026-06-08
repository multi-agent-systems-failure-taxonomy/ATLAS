"""Runtime orchestrator — the lifecycle glue.

Wires the accumulator → induction → refinement → render chain. The simple
scenario lives entirely inside one conversation:

  startup    →  if seed: load_seeds(); attempt_induction(); render
                otherwise: ensure SKILL.md is the MAST floor
  per-attempt → Stop hook pushes a Trace
                tick() checks T1 / ΔN, induces or refines, re-renders SKILL.md

Live taxonomy is in-memory only (a dict on this module). No durable writes
across conversations.
"""
from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from claude_code_skill.accumulator import get_accumulator
from claude_code_skill.induction import induce
from claude_code_skill.refinement import refine
from claude_code_skill.render import render_to_file, MAST_FLOOR_PATH, SKILL_DIR

logger = logging.getLogger(__name__)

CONFIG_PATH = SKILL_DIR / "config.toml"


@dataclass
class SkillState:
    live_taxonomy: Optional[dict[str, Any]] = None  # None means MAST is live
    last_induction_count: int = 0
    last_refinement_count: int = 0
    promoted: bool = False
    last_swap_reason: str = "MAST floor active"


_STATE = SkillState()


def _config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def _knob(section: str, key: str, env: str, default: Any) -> Any:
    if (env_val := os.environ.get(env)) is not None:
        # Coerce to default's type
        try:
            return type(default)(env_val)
        except (TypeError, ValueError):
            return env_val
    cfg = _config().get(section, {})
    return cfg.get(key, default)


def ensure_floor_rendered(target: Optional[Path] = None) -> Path:
    """Make sure SKILL.md is at least the MAST floor (idempotent)."""
    max_retries = int(_knob("gate", "max_retries", "ATLAS_MAX_FINAL_RETRIES", 3))
    target = target or (SKILL_DIR / "SKILL.md")
    render_to_file(MAST_FLOOR_PATH, target, max_retries=max_retries)
    return target


def attempt_induction(target_skill_md: Optional[Path] = None) -> str:
    """Try inducing from the current accumulator state. Promote on success;
    keep MAST on floor failure.

    Returns a short status string."""
    acc = get_accumulator()
    if acc.count() == 0:
        return "no traces, MAST floor active"

    model = _knob("induction", "inducer_model", "ATLAS_INDUCER_MODEL", "claude-opus-4-8")
    min_sup = int(_knob("induction", "min_support_per_code", "ATLAS_MIN_SUPPORT", 2))
    min_codes = int(_knob("induction", "min_total_codes", "ATLAS_MIN_CODES", 8))
    max_codes = int(_knob("induction", "max_codes_cap", "ATLAS_MAX_CODES_CAP", 30))
    max_retries = int(_knob("gate", "max_retries", "ATLAS_MAX_FINAL_RETRIES", 3))

    res = induce(
        acc.all_traces(),
        model=model,
        min_support_per_code=min_sup,
        min_total_codes=min_codes,
        max_codes=max_codes,
    )

    if not res.promoted:
        _STATE.last_swap_reason = f"low-confidence, using MAST: {res.reason}"
        logger.warning(_STATE.last_swap_reason)
        return _STATE.last_swap_reason

    _STATE.live_taxonomy = res.taxonomy
    _STATE.promoted = True
    _STATE.last_induction_count = acc.count()
    _STATE.last_swap_reason = f"promoted to induced taxonomy: {res.reason}"
    target = target_skill_md or (SKILL_DIR / "SKILL.md")
    render_to_file(_STATE.live_taxonomy, target, max_retries=max_retries)
    acc.mark_refined()
    return _STATE.last_swap_reason


def attempt_refinement(target_skill_md: Optional[Path] = None) -> str:
    """Refine the live induced taxonomy. No-op if MAST is still live."""
    if not _STATE.promoted or not _STATE.live_taxonomy:
        return "MAST floor active, no taxonomy to refine"

    acc = get_accumulator()
    delta_n = int(_knob("refinement", "delta_n", "ATLAS_DELTA_N", 5))
    min_interval = int(_knob("refinement", "min_interval", "ATLAS_MIN_REFINE_INTERVAL", 3))
    model = _knob("refinement", "refiner_model", "ATLAS_REFINER_MODEL", "claude-opus-4-8")
    max_retries = int(_knob("gate", "max_retries", "ATLAS_MAX_FINAL_RETRIES", 3))

    since = acc.since_last_refinement()
    if since < delta_n or since < min_interval:
        return f"no refinement: only {since} new traces since last (need >= {max(delta_n, min_interval)})"

    res = refine(
        _STATE.live_taxonomy,
        recent_traces=acc.recent(min(since, 10)),
        model=model,
        iterations_since_last=since,
    )
    if not res.taxonomy:
        _STATE.last_swap_reason = f"refinement failed: {res.reason}"
        logger.warning(_STATE.last_swap_reason)
        return _STATE.last_swap_reason

    _STATE.live_taxonomy = res.taxonomy
    target = target_skill_md or (SKILL_DIR / "SKILL.md")
    render_to_file(_STATE.live_taxonomy, target, max_retries=max_retries)
    acc.mark_refined()
    _STATE.last_swap_reason = res.reason
    return res.reason


def tick(target_skill_md: Optional[Path] = None) -> str:
    """Called after each Stop hook fires. Decides if T1 or ΔN was crossed and
    runs the appropriate engine. Idempotent if nothing crossed."""
    acc = get_accumulator()
    t1 = int(_knob("induction", "t1_threshold", "ATLAS_T1", 5))
    if not _STATE.promoted and acc.count() >= t1:
        return attempt_induction(target_skill_md)
    if _STATE.promoted:
        return attempt_refinement(target_skill_md)
    return f"T1 not reached: {acc.count()}/{t1} traces"


def reset_state() -> None:
    """Used by tests to clear the module-level state between runs."""
    global _STATE
    _STATE = SkillState()
    get_accumulator().reset()
