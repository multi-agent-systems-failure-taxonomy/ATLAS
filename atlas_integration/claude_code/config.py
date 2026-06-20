"""Configuration for the Claude Code runtime skin."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from finding import store
from atlas_runtime.traces import DEFAULT_TRACE_ROOT


@dataclass(frozen=True)
class ClaudeCodeConfig:
    trace_output: Path
    atlas_model: str
    store_dir: Path = store.DEFAULT_STORE_DIR
    trace_root: Path = DEFAULT_TRACE_ROOT
    inherit: str | None = None
    dashboard: bool = True
    openai_base_url: str | None = None
    openai_api_key_env: str | None = None
    max_retries: int = 3
    generation_threshold: int = 5
    generation_stops: bool = False
    taxonomy_check: bool = True
    k_init: int = 10
    k: int = 20
    refinement_stops: bool = False
    advanced_refinement: bool = False
    failure_throttle_calls: int = 5
    failure_recency_seconds: int = 30

    def __post_init__(self) -> None:
        if not str(self.atlas_model).strip():
            raise ValueError("Claude Code integration requires atlas_model")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        for name, value in (
            ("generation_threshold", self.generation_threshold),
            ("k_init", self.k_init),
            ("k", self.k),
            ("failure_throttle_calls", self.failure_throttle_calls),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.failure_recency_seconds < 0:
            raise ValueError("failure_recency_seconds cannot be negative")
        if self.openai_api_key_env and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*",
            self.openai_api_key_env,
        ):
            raise ValueError("openai_api_key_env must be an environment name")

    @classmethod
    def load(cls, path: Path | str) -> "ClaudeCodeConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        trace_output = str(data.get("trace_output", "")).strip()
        atlas_model = str(data.get("atlas_model", "")).strip()
        if not trace_output:
            raise ValueError("Claude Code integration requires trace_output")
        if not atlas_model:
            raise ValueError("Claude Code integration requires atlas_model")
        if data.get("openai_api_key"):
            raise ValueError(
                "plaintext openai_api_key is no longer supported; rerun "
                "atlas-claude-install with --openai-api-key-env"
            )
        inherit = data.get("inherit")
        if inherit in ("", "none"):
            inherit = None
        return cls(
            trace_output=Path(trace_output).expanduser().resolve(),
            atlas_model=atlas_model,
            store_dir=Path(
                data.get("store_dir", store.DEFAULT_STORE_DIR)
            ).expanduser().resolve(),
            trace_root=Path(
                data.get("trace_root", DEFAULT_TRACE_ROOT)
            ).expanduser().resolve(),
            inherit=str(inherit) if inherit is not None else None,
            dashboard=bool(data.get("dashboard", True)),
            openai_base_url=(
                str(data["openai_base_url"]).strip()
                if data.get("openai_base_url")
                else None
            ),
            openai_api_key_env=(
                str(data["openai_api_key_env"]).strip()
                if data.get("openai_api_key_env")
                else None
            ),
            max_retries=max(0, int(data.get("max_retries", 3))),
            generation_threshold=max(
                1, int(data.get("generation_threshold", 5))
            ),
            generation_stops=bool(data.get("generation_stops", False)),
            taxonomy_check=bool(data.get("taxonomy_check", True)),
            k_init=max(1, int(data.get("k_init", 10))),
            k=max(1, int(data.get("k", 20))),
            refinement_stops=bool(data.get("refinement_stops", False)),
            advanced_refinement=bool(
                data.get("advanced_refinement", False)
            ),
            failure_throttle_calls=max(
                1, int(data.get("failure_throttle_calls", 5))
            ),
            failure_recency_seconds=max(
                0, int(data.get("failure_recency_seconds", 30))
            ),
        )

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "trace_output": str(self.trace_output),
            "atlas_model": self.atlas_model,
            "store_dir": str(self.store_dir),
            "trace_root": str(self.trace_root),
            "inherit": self.inherit or "none",
            "dashboard": self.dashboard,
            "openai_base_url": self.openai_base_url,
            "openai_api_key_env": self.openai_api_key_env,
            "max_retries": self.max_retries,
            "generation_threshold": self.generation_threshold,
            "generation_stops": self.generation_stops,
            "taxonomy_check": self.taxonomy_check,
            "k_init": self.k_init,
            "k": self.k,
            "refinement_stops": self.refinement_stops,
            "advanced_refinement": self.advanced_refinement,
            "failure_throttle_calls": self.failure_throttle_calls,
            "failure_recency_seconds": self.failure_recency_seconds,
        }
