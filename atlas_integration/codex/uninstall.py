"""Uninstall ATLAS Codex hooks and optional skill files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .install import (
    SKILL_MARKER_FILE,
    SKILL_NAME,
    default_skills_dir,
    remove_atlas_hooks,
)


def uninstall(project_dir: Path | str) -> dict[str, Any]:
    project_dir = Path(project_dir).resolve()
    codex_dir = project_dir / ".codex"
    hooks_path = codex_dir / "hooks.json"
    removed_hooks = _clean_hooks(hooks_path)
    config_path = codex_dir / "atlas-skill.json"
    config_removed = False
    if config_path.is_file():
        config_path.unlink()
        config_removed = True
    return {
        "hooks": str(hooks_path),
        "removed_hooks": removed_hooks,
        "config_removed": config_removed,
    }


def uninstall_skill(
    *,
    skills_dir: Path | None = None,
    name: str = SKILL_NAME,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    target_root = (skills_dir or default_skills_dir()).expanduser()
    skill_dir = target_root / name
    marker = skill_dir / SKILL_MARKER_FILE
    if not skill_dir.exists():
        return {"skill_dir": str(skill_dir), "removed": [], "dry_run": dry_run}
    if not marker.exists() and not force:
        raise FileNotFoundError(
            f"{marker} not found; refusing to uninstall a skill not marked as "
            "ATLAS-managed. Pass --force to remove known ATLAS file names."
        )
    candidates = [
        skill_dir / "SKILL.md",
        skill_dir / "agents" / "openai.yaml",
        marker,
    ]
    removed: list[str] = []
    for path in candidates:
        if path.exists():
            removed.append(str(path))
            if not dry_run:
                path.unlink()
    if not dry_run:
        agents_dir = skill_dir / "agents"
        if agents_dir.exists() and not any(agents_dir.iterdir()):
            agents_dir.rmdir()
        if skill_dir.exists() and not any(skill_dir.iterdir()):
            skill_dir.rmdir()
    return {"skill_dir": str(skill_dir), "removed": removed, "dry_run": dry_run}


def _clean_hooks(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        hooks_doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid Codex hooks JSON: {path}") from exc
    removed = remove_atlas_hooks(hooks_doc)
    path.write_text(json.dumps(hooks_doc, indent=2) + "\n", encoding="utf-8")
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Uninstall project-local ATLAS Codex hooks."
    )
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--remove-skill", action="store_true")
    parser.add_argument("--skills-dir", type=Path, default=None)
    parser.add_argument("--force-skill", action="store_true")
    args = parser.parse_args(argv)
    result = uninstall(args.project_dir)
    if args.remove_skill:
        result["skill"] = uninstall_skill(
            skills_dir=args.skills_dir,
            force=args.force_skill,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
