"""Configuration for the Claude Code runtime skin."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from finding import store
from atlas_runtime.traces import DEFAULT_TRACE_ROOT

_HOOK_EVENTS = json.loads(
    files(__package__).joinpath("assets", "hook_events.json").read_text(
        encoding="utf-8"
    )
)

CUSTOM_HOOK_MODES = tuple(_HOOK_EVENTS["custom_hook_modes"])
CUSTOM_HOOK_CHECKPOINT_KEYS = tuple(_HOOK_EVENTS["custom_hook_checkpoint_keys"])
CUSTOM_HOOK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
BUILT_IN_HOOK_EVENTS = tuple(_HOOK_EVENTS["built_in_hook_events"])
BUILT_IN_MATCHER_EVENTS = tuple(_HOOK_EVENTS["built_in_matcher_events"])
CLAUDE_CODE_EVENTS = tuple(_HOOK_EVENTS["claude_code_events"])


@dataclass(frozen=True)
class CustomHookSpec:
    """A user-declared hook bound to the reflection-or-nudge runtime.

    Custom hooks let a project register a Claude Code event (PreToolUse,
    UserPromptSubmit, etc.) and have the same reflection<->refinement loop
    fire on it without writing any new Python. The dispatcher routes
    matching events here based on ``name``; the installer registers
    ``settings.local.json`` entries that point at this skin.
    """

    name: str
    event: str
    mode: str = "blocking"
    matcher: str | None = None
    command_pattern: str | None = None
    checkpoint_key: str = "tool_use_id"

    def __post_init__(self) -> None:
        if not CUSTOM_HOOK_NAME_RE.match(self.name):
            raise ValueError(
                f"custom hook name {self.name!r} must match "
                f"{CUSTOM_HOOK_NAME_RE.pattern}"
            )
        if self.event not in CLAUDE_CODE_EVENTS:
            raise ValueError(
                f"custom hook event {self.event!r} is not a Claude Code "
                f"hook event; expected one of {CLAUDE_CODE_EVENTS}"
            )
        if self.mode not in CUSTOM_HOOK_MODES:
            raise ValueError(
                f"custom hook mode {self.mode!r} must be one of "
                f"{CUSTOM_HOOK_MODES}"
            )
        if self.matcher is not None and not str(self.matcher).strip():
            raise ValueError("custom hook matcher cannot be empty string")
        if self.command_pattern is not None:
            pattern = str(self.command_pattern).strip()
            if not pattern:
                raise ValueError("custom hook command_pattern cannot be empty string")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"custom hook command_pattern is invalid regex: {exc}"
                ) from exc
            object.__setattr__(self, "command_pattern", pattern)
        if self.checkpoint_key not in CUSTOM_HOOK_CHECKPOINT_KEYS:
            raise ValueError(
                f"custom hook checkpoint_key {self.checkpoint_key!r} must "
                f"be one of {CUSTOM_HOOK_CHECKPOINT_KEYS}"
            )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "event": self.event,
            "mode": self.mode,
            "matcher": self.matcher,
            "command_pattern": self.command_pattern,
            "checkpoint_key": self.checkpoint_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CustomHookSpec":
        matcher = data.get("matcher")
        return cls(
            name=str(data["name"]),
            event=str(data["event"]),
            mode=str(data.get("mode", "blocking")),
            matcher=str(matcher) if matcher else None,
            command_pattern=(
                str(data["command_pattern"])
                if data.get("command_pattern")
                else None
            ),
            checkpoint_key=str(data.get("checkpoint_key", "tool_use_id")),
        )


@dataclass(frozen=True)
class BuiltInHookSpec:
    """Registration policy for one built-in Claude Code hook event."""

    event: str
    enabled: bool = True
    matchers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.event not in BUILT_IN_HOOK_EVENTS:
            raise ValueError(
                f"built-in hook event {self.event!r} must be one of "
                f"{BUILT_IN_HOOK_EVENTS}"
            )
        if self.matchers and self.event not in BUILT_IN_MATCHER_EVENTS:
            raise ValueError(
                f"built-in hook event {self.event!r} does not support matchers"
            )
        normalized = tuple(str(item).strip() for item in self.matchers)
        if any(not item for item in normalized):
            raise ValueError("built-in hook matcher cannot be empty string")
        if len(set(normalized)) != len(normalized):
            raise ValueError("built-in hook matchers must be unique per event")
        object.__setattr__(self, "matchers", normalized)

    def to_dict(self) -> dict:
        data = {"enabled": self.enabled}
        if self.event in BUILT_IN_MATCHER_EVENTS:
            data["matchers"] = list(self.matchers)
        return data

    @classmethod
    def from_value(
        cls,
        event: str,
        value,
        *,
        default: "BuiltInHookSpec | None" = None,
    ) -> "BuiltInHookSpec":
        default = default or default_built_in_hook(event)
        if isinstance(value, bool):
            return cls(event=event, enabled=value, matchers=default.matchers)
        if isinstance(value, list | tuple):
            return cls(event=event, enabled=True, matchers=_matchers(value))
        if isinstance(value, dict):
            enabled = bool(value.get("enabled", default.enabled))
            raw_matchers = value.get("matchers", default.matchers)
            return cls(event=event, enabled=enabled, matchers=_matchers(raw_matchers))
        raise ValueError(
            f"built_in_hooks.{event} must be a bool, matcher list, or object"
        )


def default_built_in_hook(event: str) -> BuiltInHookSpec:
    return BuiltInHookSpec(
        event=event,
        enabled=True,
        matchers=("*",) if event in BUILT_IN_MATCHER_EVENTS else (),
    )


def default_built_in_hooks() -> tuple[BuiltInHookSpec, ...]:
    return tuple(default_built_in_hook(event) for event in BUILT_IN_HOOK_EVENTS)


def parse_built_in_hooks(value=None) -> tuple[BuiltInHookSpec, ...]:
    defaults = {spec.event: spec for spec in default_built_in_hooks()}
    if value is None:
        return tuple(defaults[event] for event in BUILT_IN_HOOK_EVENTS)
    if isinstance(value, dict):
        unknown = set(value) - set(BUILT_IN_HOOK_EVENTS)
        if unknown:
            raise ValueError(f"unknown built_in_hooks event(s): {sorted(unknown)}")
        merged = dict(defaults)
        for event, event_value in value.items():
            merged[event] = BuiltInHookSpec.from_value(
                event,
                event_value,
                default=defaults[event],
            )
        return tuple(merged[event] for event in BUILT_IN_HOOK_EVENTS)
    if isinstance(value, list | tuple):
        merged = dict(defaults)
        for item in value:
            if not isinstance(item, dict) or "event" not in item:
                raise ValueError(
                    "built_in_hooks list entries must be objects with an event"
                )
            event = str(item["event"])
            merged[event] = BuiltInHookSpec.from_value(
                event,
                item,
                default=defaults.get(event),
            )
        return tuple(merged[event] for event in BUILT_IN_HOOK_EVENTS)
    raise ValueError("built_in_hooks must be an object or list")


def _matchers(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list | tuple):
        return tuple(str(item).strip() for item in value)
    raise ValueError("built-in hook matchers must be a string or list")


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
    skip_judge: bool = False
    k_init: int = 10
    k: int = 20
    refinement_stops: bool = False
    advanced_refinement: bool = False
    failure_throttle_calls: int = 5
    failure_recency_seconds: int = 30
    built_in_hooks: tuple[BuiltInHookSpec, ...] = field(
        default_factory=default_built_in_hooks
    )
    custom_hooks: tuple[CustomHookSpec, ...] = field(default_factory=tuple)

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
        seen_names: set[str] = set()
        for spec in self.custom_hooks:
            if not isinstance(spec, CustomHookSpec):
                raise TypeError(
                    "custom_hooks entries must be CustomHookSpec instances"
                )
            if spec.name in seen_names:
                raise ValueError(
                    f"duplicate custom_hook name {spec.name!r}; names must "
                    "be unique within a config"
                )
            seen_names.add(spec.name)
        seen_built_in: set[str] = set()
        for spec in self.built_in_hooks:
            if not isinstance(spec, BuiltInHookSpec):
                raise TypeError(
                    "built_in_hooks entries must be BuiltInHookSpec instances"
                )
            if spec.event in seen_built_in:
                raise ValueError(
                    f"duplicate built_in_hooks event {spec.event!r}"
                )
            seen_built_in.add(spec.event)

    def find_custom_hook(self, name: str) -> CustomHookSpec | None:
        for spec in self.custom_hooks:
            if spec.name == name:
                return spec
        return None

    @classmethod
    def load(cls, path: Path | str) -> "ClaudeCodeConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        scoped = data.get("claude_code") if isinstance(data.get("claude_code"), dict) else {}
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
        raw_hooks = scoped.get("custom_hooks", data.get("custom_hooks")) or ()
        if not isinstance(raw_hooks, list | tuple):
            raise ValueError("custom_hooks must be a list")
        custom_hooks = tuple(
            CustomHookSpec.from_dict(entry) for entry in raw_hooks
        )
        built_in_hooks = parse_built_in_hooks(
            scoped.get("built_in_hooks", data.get("built_in_hooks"))
        )
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
            skip_judge=bool(data.get("skip_judge", False)),
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
            built_in_hooks=built_in_hooks,
            custom_hooks=custom_hooks,
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
            "skip_judge": self.skip_judge,
            "k_init": self.k_init,
            "k": self.k,
            "refinement_stops": self.refinement_stops,
            "advanced_refinement": self.advanced_refinement,
            "failure_throttle_calls": self.failure_throttle_calls,
            "failure_recency_seconds": self.failure_recency_seconds,
            "claude_code": {
                "built_in_hooks": {
                    spec.event: spec.to_dict() for spec in self.built_in_hooks
                },
                "custom_hooks": [spec.to_dict() for spec in self.custom_hooks],
            },
        }
