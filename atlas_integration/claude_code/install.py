"""Install project-local Claude Code hook registration."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from atlas_runtime.config import (
    add_config_argument,
    bool_config_value,
    config_value,
    load_atlas_config,
    require_config_value,
)
from finding import resolver, store, webview

from .config import (
    BUILT_IN_HOOK_EVENTS,
    BuiltInHookSpec,
    ClaudeCodeConfig,
    CustomHookSpec,
    parse_built_in_hooks,
)
from .uninstall import remove_atlas_hooks

REQUIRED_EVENTS = BUILT_IN_HOOK_EVENTS


def installed_claude_executable() -> Path:
    candidates: list[Path] = []
    explicit = os.environ.get("CLAUDE_CODE_EXECUTABLE")
    if explicit:
        candidates.append(Path(explicit).expanduser())
    discovered = shutil.which("claude")
    if discovered:
        candidates.append(Path(discovered))

    candidates.extend(_known_claude_candidates())
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(
        "installed Claude Code executable was not found; put `claude` on "
        "PATH or set CLAUDE_CODE_EXECUTABLE"
    )


def verify_installed_hooks(executable: Path | None = None) -> str:
    """Verify the event names and blocking/additional-context contracts in situ."""
    executable = executable or installed_claude_executable()
    version_text = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout.strip()
    if not re.search(r"\d+\.\d+\.\d+", version_text):
        raise RuntimeError(f"could not parse Claude Code version: {version_text}")
    required_markers = [event.encode() for event in REQUIRED_EVENTS] + list((
        b"prevent task completion",
        b"show stderr to subagent and continue having it run",
        b"show stderr to model and continue conversation",
        b"hookSpecificOutput.additionalContext",
    ))
    missing = set(required_markers)
    for source in _contract_sources(executable):
        try:
            payload = source.read_bytes()
        except OSError:
            continue
        missing = {marker for marker in missing if marker not in payload}
        if not missing:
            break
    if missing:
        labels = ", ".join(repr(marker.decode()) for marker in sorted(missing))
        raise RuntimeError(
            f"installed Claude Code {version_text} lacks required hook "
            f"contract marker(s): {labels}"
        )
    return version_text


def _known_claude_candidates() -> list[Path]:
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roaming = Path(appdata)
        candidates.extend(
            [
                roaming
                / "npm"
                / "node_modules"
                / "@anthropic-ai"
                / "claude-code"
                / "bin"
                / "claude.exe",
                roaming / "npm" / "claude.cmd",
                roaming / "npm" / "claude.exe",
            ]
        )
        version_root = roaming / "Claude" / "claude-code"
        if version_root.is_dir():
            candidates.extend(
                sorted(version_root.glob("*/claude.exe"), reverse=True)
            )
    home = Path.home()
    candidates.extend(
        [
            home / ".local" / "bin" / "claude",
            home / ".npm-global" / "bin" / "claude",
            Path("/usr/local/bin/claude"),
            Path("/opt/homebrew/bin/claude"),
        ]
    )
    native_root = home / ".local" / "share" / "claude" / "versions"
    if native_root.is_dir():
        candidates.extend(sorted(native_root.glob("*/claude"), reverse=True))
    return candidates


def _contract_sources(executable: Path) -> list[Path]:
    sources = [executable.resolve(), *_known_claude_candidates()]
    for root in {executable.parent, executable.parent.parent}:
        package = (
            root
            / "node_modules"
            / "@anthropic-ai"
            / "claude-code"
        )
        sources.extend(
            [
                package / "cli.js",
                package / "index.js",
                package / "bin" / "claude.exe",
            ]
        )
    unique: list[Path] = []
    seen: set[str] = set()
    for source in sources:
        key = str(source)
        if key not in seen and source.is_file():
            seen.add(key)
            unique.append(source)
    return unique


def install(
    project_dir: Path | str,
    config: ClaudeCodeConfig,
    *,
    python: Path | str = sys.executable,
    verify: bool = True,
    migrate_legacy_global: bool = False,
) -> dict:
    project_dir = Path(project_dir).resolve()
    if verify:
        version = verify_installed_hooks()
    else:
        version = "verification skipped by caller"

    claude_dir = project_dir / ".claude"
    settings_path = claude_dir / "settings.local.json"
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"invalid Claude settings JSON; refusing to overwrite "
                f"{settings_path}"
            ) from exc
        if not isinstance(settings, dict):
            raise RuntimeError(
                f"Claude settings must be a JSON object: {settings_path}"
            )
    else:
        settings = {}

    claude_dir.mkdir(parents=True, exist_ok=True)
    config_path = claude_dir / "atlas-skill.json"
    _write_json_atomic(config_path, config.to_dict())
    command = _module_command(Path(python), config_path)
    remove_atlas_hooks(settings, include_legacy=False)
    hooks = settings.setdefault("hooks", {})
    installed_events: list[str] = []
    for spec in config.built_in_hooks:
        if not spec.enabled:
            continue
        entries = hooks.setdefault(spec.event, [])
        matchers = spec.matchers or (None,)
        for matcher in matchers:
            _append_registration(
                entries,
                command=command,
                matcher=matcher,
            )
        installed_events.append(spec.event)
    for spec in config.custom_hooks:
        custom_command = _custom_command(
            Path(python), config_path, spec.name,
        )
        entries = hooks.setdefault(spec.event, [])
        _append_registration(
            entries,
            command=custom_command,
            matcher=spec.matcher,
        )
    _write_json_atomic(settings_path, settings)
    migrated = None
    if migrate_legacy_global:
        global_settings = Path.home() / ".claude" / "settings.json"
        migrated = remove_from_settings_file(
            global_settings,
            include_legacy=True,
        )
    return {
        "claude_version": version,
        "config": str(config_path),
        "settings": str(settings_path),
        "events": installed_events,
        "legacy_global_migration": migrated,
    }


def _append_registration(
    entries: list,
    *,
    command: str,
    matcher: str | None,
) -> None:
    registration = {
        **({"matcher": matcher} if matcher else {}),
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 15,
            }
        ],
    }
    if not any(
        entry.get("matcher") == matcher
        and any(
            hook.get("command") == command
            for hook in entry.get("hooks", [])
        )
        for entry in entries
    ):
        entries.append(registration)


def _module_command(python: Path, config: Path) -> str:
    dispatcher = Path(__file__).resolve().with_name("dispatcher.py")
    parts = [
        _hook_shell_path(python),
        _hook_shell_path(dispatcher),
        "--config",
        _hook_shell_path(config),
    ]
    return shlex.join(parts)


def _custom_command(python: Path, config: Path, spec_name: str) -> str:
    dispatcher = Path(__file__).resolve().with_name("dispatcher.py")
    parts = [
        _hook_shell_path(python),
        _hook_shell_path(dispatcher),
        "--config",
        _hook_shell_path(config),
        "--custom",
        spec_name,
    ]
    return shlex.join(parts)


def _hook_shell_path(path: Path) -> str:
    resolved = str(path.resolve())
    return resolved.replace("\\", "/") if os.name == "nt" else resolved


def _write_json_atomic(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def remove_from_settings_file(
    settings_path: Path,
    *,
    include_legacy: bool,
) -> dict:
    if not settings_path.is_file():
        return {"settings": str(settings_path), "removed_hooks": 0}
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"cannot migrate invalid Claude settings JSON: {settings_path}"
        ) from exc
    removed = remove_atlas_hooks(settings, include_legacy=include_legacy)
    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"settings": str(settings_path), "removed_hooks": removed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the project-local ATLAS Claude Code runtime skin."
    )
    add_config_argument(parser)
    parser.add_argument("--project-dir")
    parser.add_argument("--trace-output")
    parser.add_argument("--atlas-model")
    parser.add_argument("--store-dir")
    parser.add_argument("--trace-root")
    parser.add_argument(
        "--inherit",
        nargs="?",
        const=resolver.NO_ID,
        help=(
            "taxonomy ID to inherit; the no-value picker form is deprecated, "
            "use --inherit-pick instead"
        ),
    )
    parser.add_argument(
        "--inherit-pick",
        action="store_true",
        help="open the local taxonomy picker at install time",
    )
    parser.add_argument("--max-retries", type=int)
    parser.add_argument("--generation-threshold", type=int)
    parser.add_argument(
        "--generation-stops",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--skip-judge",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "skip the Reflection Judge + refiner step at the end of "
            "generation. Generated taxonomies are then accepted on "
            "structural validity alone"
        ),
    )
    parser.add_argument("--k-init", type=int)
    parser.add_argument("--k", type=int)
    parser.add_argument(
        "--refinement-stops",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--advanced-refinement",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--failure-throttle-calls", type=int)
    parser.add_argument("--failure-recency-seconds", type=int)
    parser.add_argument(
        "--disable-hook",
        action="append",
        choices=BUILT_IN_HOOK_EVENTS,
        help=(
            "do not install this built-in Claude Code hook event. Repeat for "
            "multiple events, e.g. --disable-hook SubagentStop"
        ),
    )
    parser.add_argument(
        "--post-tool-use-matchers",
        help=(
            "comma-separated Claude Code tool matchers for PostToolUse "
            "(default: *). Example: Bash,Edit,Write"
        ),
    )
    parser.add_argument(
        "--post-tool-use-failure-matchers",
        help=(
            "comma-separated Claude Code tool matchers for PostToolUseFailure "
            "(default: *). Example: Bash"
        ),
    )
    parser.add_argument("--dashboard", dest="dashboard", action="store_true", default=None)
    parser.add_argument("--no-dashboard", dest="dashboard", action="store_false")
    parser.add_argument("--openai-base-url")
    parser.add_argument(
        "--openai-api-key-env",
        help=(
            "name of an environment variable containing the OpenAI-compatible "
            "credential; the credential itself is never persisted"
        ),
    )
    parser.add_argument(
        "--migrate-legacy-global",
        action="store_true",
        help=(
            "remove old atlas-failure-modes hook registrations from "
            "~/.claude/settings.json"
        ),
    )
    parser.add_argument(
        "--traces",
        help=(
            "OPTIONAL convenience: pass a trace file/dir to atlas-import-traces "
            "first, then install the resulting taxonomy as --inherit in one "
            "command. Mutually exclusive with --inherit; --skip-judge is honored "
            "for the import step too"
        ),
    )
    args = parser.parse_args(argv)
    try:
        config = load_atlas_config(args.config)
        adapter_config = (
            config.get("claude_code")
            if isinstance(config.get("claude_code"), dict)
            else {}
        )
        atlas_model = str(require_config_value(
            args, config, "atlas_model", "--atlas-model"
        ))
        trace_output = Path(require_config_value(
            args, config, "trace_output", "--trace-output"
        )).resolve()
    except Exception as exc:  # noqa: BLE001
        parser.error(str(exc))
    if args.inherit_pick and args.inherit is not None:
        parser.error("--inherit-pick cannot be combined with --inherit")
    if args.traces and (args.inherit is not None or args.inherit_pick):
        parser.error("--traces and inheritance selection are mutually exclusive")
    if args.inherit_pick:
        inherit = resolver.NO_ID
    else:
        inherit = args.inherit if args.inherit is not None else config.get("inherit")
    store_dir_value = config_value(args, config, "store_dir")
    trace_root_value = config_value(args, config, "trace_root")
    skip_judge = bool_config_value(args, config, "skip_judge", False)
    try:
        built_in_hooks = _built_in_hooks_from_options(args, config, adapter_config)
    except ValueError as exc:
        parser.error(str(exc))
    if args.traces:
        # Compose: import traces -> get a taxonomy_id -> use as --inherit.
        from atlas_runtime.import_generation import generate_imported_taxonomy

        resolved_store_dir = (
            Path(store_dir_value).resolve()
            if store_dir_value
            else store.DEFAULT_STORE_DIR
        )
        resolved_trace_root = (
            Path(trace_root_value).resolve()
            if trace_root_value
            else None
        )
        import_kwargs: dict[str, Any] = {
            "atlas_model": atlas_model,
            "store_dir": resolved_store_dir,
            "skip_judge": skip_judge,
            "verbose": True,
        }
        if resolved_trace_root is not None:
            import_kwargs["trace_root"] = resolved_trace_root
        imported = generate_imported_taxonomy(args.traces, **import_kwargs)
        inherit = imported.taxonomy_id
        print(
            f"[atlas-claude-install] imported traces -> taxonomy {inherit}",
            file=sys.stderr,
        )
    elif inherit == resolver.NO_ID:
        if not args.inherit_pick:
            print(
                "warning: bare --inherit is deprecated; use --inherit-pick "
                "for the interactive picker.",
                file=sys.stderr,
            )
        selected = resolver.resolve(
            resolver.NO_ID,
            store_dir=(
                Path(store_dir_value).resolve()
                if store_dir_value
                else None
            ) or store.DEFAULT_STORE_DIR,
            launcher=webview.run_webview,
        )
        inherit = None if selected == resolver.NONE else selected
    fields = {
        "trace_output": trace_output,
        "atlas_model": atlas_model,
        "inherit": inherit,
        "max_retries": config_value(args, config, "max_retries", 3),
        "generation_threshold": config_value(args, config, "generation_threshold", 5),
        "generation_stops": bool_config_value(args, config, "generation_stops", False),
        "skip_judge": skip_judge,
        "k_init": config_value(args, config, "k_init", 10),
        "k": config_value(args, config, "k", 20),
        "refinement_stops": bool_config_value(args, config, "refinement_stops", False),
        "advanced_refinement": bool_config_value(args, config, "advanced_refinement", False),
        "failure_throttle_calls": config_value(args, config, "failure_throttle_calls", 5),
        "failure_recency_seconds": config_value(args, config, "failure_recency_seconds", 30),
        "built_in_hooks": built_in_hooks,
        "custom_hooks": tuple(
            CustomHookSpec.from_dict(entry)
            for entry in adapter_config.get(
                "custom_hooks",
                config.get("custom_hooks", ()),
            )
        ),
        "dashboard": bool_config_value(args, config, "dashboard", True),
        "openai_base_url": config_value(args, config, "openai_base_url"),
        "openai_api_key_env": config_value(args, config, "openai_api_key_env"),
    }
    if store_dir_value:
        fields["store_dir"] = Path(store_dir_value).resolve()
    if trace_root_value:
        fields["trace_root"] = Path(trace_root_value).resolve()
    result = install(
        config_value(args, config, "project_dir", "."),
        ClaudeCodeConfig(**fields),
        migrate_legacy_global=args.migrate_legacy_global,
    )
    # Make the learning cadence honest at install time so single-run users
    # don't expect taxonomy improvement that will never fire from one trace.
    print(
        f"Learning thresholds: generation at {fields['generation_threshold']} traces, "
        f"refinement at K_init={fields['k_init']} / K={fields['k']}. With fewer traces, "
        f"the active taxonomy stays static.",
        file=sys.stderr,
    )
    print(json.dumps(result, indent=2))
    return 0


def _built_in_hooks_from_options(
    args: argparse.Namespace,
    config: dict,
    adapter_config: dict | None = None,
) -> tuple[BuiltInHookSpec, ...]:
    adapter_config = adapter_config or {}
    specs = {
        spec.event: spec
        for spec in parse_built_in_hooks(
            adapter_config.get("built_in_hooks", config.get("built_in_hooks"))
        )
    }
    disabled = set(args.disable_hook or ())
    matcher_overrides = {
        "PostToolUse": args.post_tool_use_matchers,
        "PostToolUseFailure": args.post_tool_use_failure_matchers,
    }
    conflicts = sorted(
        event
        for event, value in matcher_overrides.items()
        if event in disabled and value is not None
    )
    if conflicts:
        raise ValueError(
            "--disable-hook cannot be combined with matcher overrides for "
            + ", ".join(conflicts)
        )
    for event in disabled:
        specs[event] = replace(specs[event], enabled=False)
    for event, value in matcher_overrides.items():
        if value is not None:
            specs[event] = replace(
                specs[event],
                enabled=True,
                matchers=_split_matchers(value),
            )
    return tuple(specs[event] for event in BUILT_IN_HOOK_EVENTS)


def _split_matchers(value: str) -> tuple[str, ...]:
    matchers = tuple(part.strip() for part in value.split(",") if part.strip())
    if not matchers:
        raise ValueError("hook matcher list cannot be empty")
    if len(set(matchers)) != len(matchers):
        raise ValueError("hook matcher list contains duplicates")
    return matchers


if __name__ == "__main__":
    raise SystemExit(main())
