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
from atlas_integration.shared import write_json_atomic
from atlas_integration.interactive.defaults import (
    INTERACTIVE_ATLAS_MODEL,
    default_interactive_trace_output,
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
        encoding="utf-8",
        errors="replace",
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
    user_level: bool = False,
) -> dict:
    project_dir = Path(project_dir).resolve()
    if verify:
        version = verify_installed_hooks()
    else:
        version = "verification skipped by caller"

    claude_dir = Path.home() / ".claude" if user_level else project_dir / ".claude"
    settings_path = claude_dir / (
        "settings.json" if user_level else "settings.local.json"
    )
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
    write_json_atomic(config_path, config.to_dict())
    command = _module_command(Path(python), config_path)
    remove_atlas_hooks(settings, include_legacy=user_level)
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
    write_json_atomic(settings_path, settings)
    migrated = None
    if migrate_legacy_global and not user_level:
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
        "scope": "user" if user_level else "project",
        "legacy_global_migration": migrated,
    }


def install_user(
    config: ClaudeCodeConfig,
    *,
    python: Path | str = sys.executable,
    verify: bool = True,
) -> dict:
    """Install ATLAS once for all Claude Code conversations for this user."""
    return install(
        Path.home(),
        config,
        python=python,
        verify=verify,
        user_level=True,
    )


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
                # Finalize hooks read the transcript and persist the trace;
                # 15s was tight enough that a slow disk or huge transcript
                # got the hook killed mid-finalize. Learning itself always
                # runs in background workers, never under this timeout.
                "timeout": 60,
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
    # Registered commands outlive the installation that wrote them, so they
    # must not embed the dispatcher's file location: switching between a
    # wheel and an editable install (or upgrading the package) relocates the
    # file and every hook event starts failing. Module invocation resolves
    # through whatever install is current.
    parts = [
        _hook_shell_path(python),
        "-m",
        "atlas_integration.claude_code.dispatcher",
        "--config",
        _hook_shell_path(config),
    ]
    return shlex.join(parts)


def _custom_command(python: Path, config: Path, spec_name: str) -> str:
    parts = [
        _hook_shell_path(python),
        "-m",
        "atlas_integration.claude_code.dispatcher",
        "--config",
        _hook_shell_path(config),
        "--custom",
        spec_name,
    ]
    return shlex.join(parts)


def _hook_shell_path(path: Path) -> str:
    resolved = str(path.resolve())
    return resolved.replace("\\", "/") if os.name == "nt" else resolved


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
    write_json_atomic(settings_path, settings)
    return {"settings": str(settings_path), "removed_hooks": removed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the project-local or user-level ATLAS Claude Code runtime."
    )
    add_config_argument(parser)
    parser.add_argument("--project-dir")
    parser.add_argument(
        "--user-level",
        action="store_true",
        help="install in ~/.claude/settings.json for all Claude Code projects",
    )
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
    parser.add_argument("--format-retries", type=int)
    parser.add_argument("--repair-rounds", type=int)
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
    parser.add_argument(
        "--freeze",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "inference-only mode: record traces/evidence but skip generation "
            "and refinement"
        ),
    )
    parser.add_argument(
        "--evidence-export",
        type=Path,
        help=(
            "optional external evidence export path; .json means exact file, "
            "otherwise the value is treated as a directory sink"
        ),
    )
    parser.add_argument("--failure-throttle-calls", type=int)
    parser.add_argument("--failure-recency-seconds", type=int)
    parser.add_argument(
        "--project-scope",
        choices=("explicit", "auto"),
        help="auto derives one shared program from the event cwd",
    )
    parser.add_argument("--project-id")
    parser.add_argument("--task-group")
    parser.add_argument("--session-selector", choices=("off", "prompt"))
    parser.add_argument(
        "--selector-surface",
        choices=("browser", "inline"),
        help="choose the local browser library or an inline numbered selector",
    )
    parser.add_argument(
        "--learning-backend",
        choices=("provider", "claude_subagent"),
    )
    parser.add_argument("--worker-model")
    parser.add_argument("--claude-cli-path", type=Path)
    parser.add_argument("--worker-timeout-seconds", type=int)
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
    if args.user_level and args.project_dir is not None:
        parser.error("--user-level cannot be combined with --project-dir")
    try:
        config = (
            load_atlas_config(args.config)
            if args.config is not None or not args.user_level
            else {}
        )
        adapter_config = (
            config.get("claude_code")
            if isinstance(config.get("claude_code"), dict)
            else {}
        )
        atlas_model_value = config_value(args, config, "atlas_model")
        trace_output_value = config_value(args, config, "trace_output")
        if args.user_level:
            atlas_model_value = atlas_model_value or INTERACTIVE_ATLAS_MODEL
            trace_output_value = trace_output_value or default_interactive_trace_output(
                Path.home()
            )
        else:
            atlas_model_value = require_config_value(
                args, config, "atlas_model", "--atlas-model"
            )
            trace_output_value = require_config_value(
                args, config, "trace_output", "--trace-output"
            )
        atlas_model = str(atlas_model_value)
        trace_output = Path(trace_output_value).expanduser().resolve()
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
        "format_retries": config_value(args, config, "format_retries", 2),
        "repair_rounds": config_value(args, config, "repair_rounds"),
        "generation_threshold": config_value(args, config, "generation_threshold", 5),
        "generation_stops": bool_config_value(args, config, "generation_stops", False),
        "skip_judge": skip_judge,
        "k_init": config_value(args, config, "k_init", 10),
        "k": config_value(args, config, "k", 20),
        "refinement_stops": bool_config_value(args, config, "refinement_stops", False),
        "advanced_refinement": bool_config_value(args, config, "advanced_refinement", False),
        "freeze": bool_config_value(args, config, "freeze", False),
        "redact_traces": bool_config_value(args, config, "redact_traces", True),
        "evidence_export": config_value(args, config, "evidence_export"),
        "failure_throttle_calls": config_value(args, config, "failure_throttle_calls", 5),
        "failure_recency_seconds": config_value(args, config, "failure_recency_seconds", 30),
        "project_scope": (
            args.project_scope
            or adapter_config.get("project_scope")
            or ("auto" if args.user_level else "explicit")
        ),
        "project_id": args.project_id or adapter_config.get("project_id"),
        "task_group": args.task_group or adapter_config.get("task_group", "default"),
        "session_selector": (
            args.session_selector
            or adapter_config.get(
                "session_selector",
                "prompt" if args.user_level else "off",
            )
        ),
        "selector_surface": (
            args.selector_surface
            or adapter_config.get("selector_surface", "browser")
        ),
        "learning_backend": (
            args.learning_backend
            or adapter_config.get(
                "learning_backend",
                "claude_subagent" if args.user_level else "provider",
            )
        ),
        "worker_model": args.worker_model or adapter_config.get("worker_model"),
        "claude_cli_path": (
            args.claude_cli_path
            or adapter_config.get("claude_cli_path")
        ),
        "worker_timeout_seconds": (
            args.worker_timeout_seconds
            or adapter_config.get("worker_timeout_seconds", 1800)
        ),
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
        user_level=args.user_level,
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
