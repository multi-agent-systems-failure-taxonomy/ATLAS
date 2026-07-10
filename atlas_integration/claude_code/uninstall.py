"""Remove project-local ATLAS Claude Code hook registration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas_integration.shared import write_json_atomic

CURRENT_MARKERS = (
    "atlas_integration.claude_code.dispatcher",
    "atlas-skill.json",
)
LEGACY_MARKERS = (
    "atlas-failure-modes",
    "atlas_claude_code",
)


def remove_atlas_hooks(
    settings: dict,
    *,
    include_legacy: bool = True,
) -> int:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    markers = CURRENT_MARKERS + (LEGACY_MARKERS if include_legacy else ())
    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            text = json.dumps(entry, sort_keys=True)
            if any(marker in text for marker in markers):
                removed += 1
            else:
                kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    return removed


def uninstall(
    project_dir: Path | str,
    *,
    migrate_legacy_global: bool = False,
) -> dict:
    project_dir = Path(project_dir).resolve()
    claude_dir = project_dir / ".claude"
    settings_path = claude_dir / "settings.local.json"
    removed = _clean_settings(settings_path, include_legacy=True)
    config_path = claude_dir / "atlas-skill.json"
    config_removed = False
    if config_path.is_file():
        config_path.unlink()
        config_removed = True

    legacy = None
    if migrate_legacy_global:
        legacy = _clean_settings(
            Path.home() / ".claude" / "settings.json",
            include_legacy=True,
        )
    return {
        "settings": str(settings_path),
        "removed_hooks": removed,
        "config_removed": config_removed,
        "legacy_global_removed_hooks": legacy,
    }


def _clean_settings(path: Path, *, include_legacy: bool) -> int:
    if not path.is_file():
        return 0
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid Claude settings JSON: {path}") from exc
    removed = remove_atlas_hooks(settings, include_legacy=include_legacy)
    write_json_atomic(path, settings)
    return removed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Uninstall project-local ATLAS Claude Code hooks."
    )
    parser.add_argument("--project-dir", default=".")
    parser.add_argument(
        "--migrate-legacy-global",
        action="store_true",
        help="also remove legacy ATLAS hooks from ~/.claude/settings.json",
    )
    args = parser.parse_args(argv)
    result = uninstall(
        args.project_dir,
        migrate_legacy_global=args.migrate_legacy_global,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
