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
from pathlib import Path

from finding import resolver, store, webview

from .config import ClaudeCodeConfig
from .uninstall import remove_atlas_hooks

REQUIRED_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "Stop",
    "TaskCompleted",
    "SubagentStop",
    "PostToolUse",
    "PostToolUseFailure",
)


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
    for event in REQUIRED_EVENTS:
        entries = hooks.setdefault(event, [])
        matcher = "*" if event in ("PostToolUse", "PostToolUseFailure") else None
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
            any(
                hook.get("command") == command
                for hook in entry.get("hooks", [])
            )
            for entry in entries
        ):
            entries.append(registration)
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
        "events": list(REQUIRED_EVENTS),
        "legacy_global_migration": migrated,
    }


def _module_command(python: Path, config: Path) -> str:
    dispatcher = Path(__file__).resolve().with_name("dispatcher.py")
    parts = [
        _hook_shell_path(python),
        _hook_shell_path(dispatcher),
        "--config",
        _hook_shell_path(config),
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
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--trace-output", required=True)
    parser.add_argument("--atlas-model", required=True)
    parser.add_argument("--store-dir")
    parser.add_argument("--trace-root")
    parser.add_argument(
        "--inherit",
        nargs="?",
        const=resolver.NO_ID,
        help=(
            "taxonomy ID to inherit; pass without a value to open the local "
            "taxonomy picker"
        ),
    )
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--generation-threshold", type=int, default=5)
    parser.add_argument(
        "--generation-stops",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        default=False,
        help=(
            "skip the Reflection Judge + refiner step at the end of "
            "generation. Generated taxonomies are then accepted on "
            "structural validity alone"
        ),
    )
    parser.add_argument("--k-init", type=int, default=10)
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument(
        "--refinement-stops",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--advanced-refinement",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--failure-throttle-calls", type=int, default=5)
    parser.add_argument("--failure-recency-seconds", type=int, default=30)
    parser.add_argument("--no-dashboard", action="store_true")
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
    if args.traces and args.inherit is not None:
        parser.error("--traces and --inherit are mutually exclusive")
    inherit = args.inherit
    if args.traces:
        # Compose: import traces -> get a taxonomy_id -> use as --inherit.
        from atlas_runtime.import_generation import generate_imported_taxonomy

        resolved_store_dir = (
            Path(args.store_dir).resolve()
            if args.store_dir
            else store.DEFAULT_STORE_DIR
        )
        resolved_trace_root = (
            Path(args.trace_root).resolve()
            if args.trace_root
            else None
        )
        import_kwargs: dict[str, Any] = {
            "atlas_model": args.atlas_model,
            "store_dir": resolved_store_dir,
            "skip_judge": args.skip_judge,
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
        selected = resolver.resolve(
            resolver.NO_ID,
            store_dir=(
                Path(args.store_dir).resolve()
                if args.store_dir
                else None
            ) or store.DEFAULT_STORE_DIR,
            launcher=webview.run_webview,
        )
        inherit = None if selected == resolver.NONE else selected
    fields = {
        "trace_output": Path(args.trace_output).resolve(),
        "atlas_model": args.atlas_model,
        "inherit": inherit,
        "max_retries": args.max_retries,
        "generation_threshold": args.generation_threshold,
        "generation_stops": args.generation_stops,
        "skip_judge": args.skip_judge,
        "k_init": args.k_init,
        "k": args.k,
        "refinement_stops": args.refinement_stops,
        "advanced_refinement": args.advanced_refinement,
        "failure_throttle_calls": args.failure_throttle_calls,
        "failure_recency_seconds": args.failure_recency_seconds,
        "dashboard": not args.no_dashboard,
        "openai_base_url": args.openai_base_url,
        "openai_api_key_env": args.openai_api_key_env,
    }
    if args.store_dir:
        fields["store_dir"] = Path(args.store_dir).resolve()
    if args.trace_root:
        fields["trace_root"] = Path(args.trace_root).resolve()
    result = install(
        args.project_dir,
        ClaudeCodeConfig(**fields),
        migrate_legacy_global=args.migrate_legacy_global,
    )
    # Make the learning cadence honest at install time so single-run users
    # don't expect taxonomy improvement that will never fire from one trace.
    print(
        f"Learning thresholds: generation at {args.generation_threshold} traces, "
        f"refinement at K_init={args.k_init} / K={args.k}. With fewer traces, "
        f"the active taxonomy stays static.",
        file=sys.stderr,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
