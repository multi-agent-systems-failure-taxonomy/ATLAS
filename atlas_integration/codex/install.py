"""Install ATLAS project-local Codex hooks."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from atlas_runtime.config import (
    add_config_argument,
    bool_config_value,
    config_value,
    load_atlas_config,
    require_config_value,
)
from atlas_runtime.traces import DEFAULT_TRACE_ROOT
from finding import store

from .config import CodexConfig, parse_codex_hooks

SKILL_NAME = "atlas-failure-modes"
SKILL_MARKER_FILE = ".atlas-codex-skill.json"
HOOK_MARKERS = (
    "atlas_integration.codex.dispatcher",
    "atlas-skill.json",
)


@dataclass(frozen=True)
class CodexSkillInstallResult:
    skill_dir: Path
    skill_md: Path
    agents_openai_yaml: Path
    marker: Path
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_dir": str(self.skill_dir),
            "skill_md": str(self.skill_md),
            "agents_openai_yaml": str(self.agents_openai_yaml),
            "marker": str(self.marker),
            "dry_run": self.dry_run,
        }


def default_skills_dir() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return base / "skills"


def install(
    project_dir: Path | str,
    config: CodexConfig,
    *,
    python: Path | str = sys.executable,
) -> dict:
    """Install project-local Codex hooks plus the ATLAS hook config."""
    project_dir = Path(project_dir).resolve()
    codex_dir = project_dir / ".codex"
    hooks_path = codex_dir / "hooks.json"
    if hooks_path.is_file():
        try:
            hooks_doc = json.loads(hooks_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid Codex hooks JSON: {hooks_path}") from exc
        if not isinstance(hooks_doc, dict):
            raise RuntimeError(f"Codex hooks file must be a JSON object: {hooks_path}")
    else:
        hooks_doc = {}

    codex_dir.mkdir(parents=True, exist_ok=True)
    config_path = codex_dir / "atlas-skill.json"
    _write_json_atomic(config_path, config.to_dict())
    remove_atlas_hooks(hooks_doc)
    hooks = hooks_doc.setdefault("hooks", {})
    command = _module_command(Path(python), config_path)
    installed_events: list[str] = []
    for spec in config.hooks:
        if not spec.enabled:
            continue
        entries = hooks.setdefault(spec.event, [])
        matchers = spec.matchers or (None,)
        for matcher in matchers:
            _append_registration(entries, command=command, matcher=matcher)
        installed_events.append(spec.event)
    _write_json_atomic(hooks_path, hooks_doc)
    return {
        "config": str(config_path),
        "hooks": str(hooks_path),
        "events": installed_events,
        "trust_note": "Open /hooks in Codex and trust the new ATLAS hooks before use.",
    }


def install_skill(
    *,
    skills_dir: Path | None = None,
    name: str = SKILL_NAME,
    force: bool = False,
    dry_run: bool = False,
) -> CodexSkillInstallResult:
    """Install the optional ATLAS Codex skill guidance package."""
    if not name or "/" in name or "\\" in name:
        raise ValueError("skill name must be a single directory name")
    target_root = (skills_dir or default_skills_dir()).expanduser()
    skill_dir = target_root / name
    skill_md = skill_dir / "SKILL.md"
    agents_dir = skill_dir / "agents"
    openai_yaml = agents_dir / "openai.yaml"
    marker = skill_dir / SKILL_MARKER_FILE
    if skill_md.exists() and not force:
        raise FileExistsError(
            f"{skill_md} already exists; pass --force to replace the ATLAS "
            "managed files"
        )
    result = CodexSkillInstallResult(
        skill_dir=skill_dir,
        skill_md=skill_md,
        agents_openai_yaml=openai_yaml,
        marker=marker,
        dry_run=dry_run,
    )
    if dry_run:
        return result
    skill_dir.mkdir(parents=True, exist_ok=True)
    agents_dir.mkdir(parents=True, exist_ok=True)
    skill_md.write_text(_asset_text("SKILL.md"), encoding="utf-8")
    openai_yaml.write_text(_asset_text("openai.yaml"), encoding="utf-8")
    marker.write_text(
        json.dumps(
            {
                "managed_by": "atlas-skill",
                "integration": "codex",
                "skill_name": name,
                "files": ["SKILL.md", "agents/openai.yaml"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def remove_atlas_hooks(hooks_doc: dict) -> int:
    hooks = hooks_doc.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            text = json.dumps(entry, sort_keys=True)
            if any(marker in text for marker in HOOK_MARKERS):
                removed += 1
            else:
                kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        hooks_doc.pop("hooks", None)
    return removed


def _append_registration(entries: list, *, command: str, matcher: str | None) -> None:
    registration = {
        **({"matcher": matcher} if matcher else {}),
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 30,
                "statusMessage": "Running ATLAS gate",
            }
        ],
    }
    if not any(
        entry.get("matcher") == matcher
        and any(hook.get("command") == command for hook in entry.get("hooks", []))
        for entry in entries
    ):
        entries.append(registration)


def _module_command(python: Path, config: Path) -> str:
    parts = [
        _hook_shell_path(python),
        "-m",
        "atlas_integration.codex.dispatcher",
        "--config",
        _hook_shell_path(config),
    ]
    return shlex.join(parts)


def _hook_shell_path(path: Path) -> str:
    resolved = str(path.resolve())
    return resolved.replace("\\", "/") if os.name == "nt" else resolved


def _asset_text(name: str) -> str:
    return (
        files("atlas_integration.codex")
        .joinpath("assets", name)
        .read_text(encoding="utf-8")
    )


def _write_json_atomic(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install project-local ATLAS Codex hooks."
    )
    add_config_argument(parser)
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--trace-output", "--trace_output", dest="trace_output", type=Path)
    parser.add_argument("--atlas-model", "--atlas_model", dest="atlas_model")
    parser.add_argument("--store-dir", "--store_dir", dest="store_dir", type=Path)
    parser.add_argument("--trace-root", "--trace_root", dest="trace_root", type=Path)
    parser.add_argument("--inherit")
    parser.add_argument("--max-retries", "--max_retries", dest="max_retries", type=int)
    parser.add_argument("--generation-threshold", "--generation_threshold", dest="generation_threshold", type=int)
    parser.add_argument("--generation-stops", "--generation_stops", dest="generation_stops", action=argparse.BooleanOptionalAction)
    parser.add_argument("--skip-judge", "--skip_judge", dest="skip_judge", action="store_true", default=None)
    parser.add_argument("--k-init", "--k_init", dest="k_init", type=int)
    parser.add_argument("--k", type=int)
    parser.add_argument("--refinement-stops", "--refinement_stops", dest="refinement_stops", action=argparse.BooleanOptionalAction)
    parser.add_argument("--advanced-refinement", "--advanced_refinement", dest="advanced_refinement", action=argparse.BooleanOptionalAction)
    parser.add_argument("--no-dashboard", dest="dashboard", action="store_false", default=None)
    parser.add_argument("--openai-base-url", "--openai_base_url", dest="openai_base_url")
    parser.add_argument("--openai-api-key-env", "--openai_api_key_env", dest="openai_api_key_env")
    parser.add_argument(
        "--disable-hook",
        action="append",
        default=[],
        choices=("SessionStart", "Stop", "SubagentStop", "PostToolUse"),
        help="do not install a built-in Codex hook event",
    )
    parser.add_argument(
        "--post-tool-use-matchers",
        default=None,
        help="comma-separated Codex PostToolUse matcher regexes",
    )
    parser.add_argument(
        "--install-skill",
        action="store_true",
        help="also install the optional ATLAS Codex skill guidance package",
    )
    parser.add_argument("--skills-dir", type=Path, default=None)
    parser.add_argument("--force-skill", action="store_true")
    args = parser.parse_args(argv)
    config_doc = load_atlas_config(args.config)
    adapter_config = (
        config_doc.get("codex")
        if isinstance(config_doc.get("codex"), dict)
        else {}
    )
    hooks_doc = dict(adapter_config.get("hooks", config_doc.get("codex_hooks")) or {})
    for event in args.disable_hook:
        hooks_doc[event] = False
    if args.post_tool_use_matchers is not None:
        hooks_doc["PostToolUse"] = {
            "enabled": True,
            "matchers": [
                item.strip()
                for item in args.post_tool_use_matchers.split(",")
                if item.strip()
            ],
        }
    cfg = CodexConfig(
        trace_output=Path(require_config_value(args, config_doc, "trace_output", "--trace-output")),
        atlas_model=str(require_config_value(args, config_doc, "atlas_model", "--atlas-model")),
        store_dir=Path(config_value(args, config_doc, "store_dir", store.DEFAULT_STORE_DIR)),
        trace_root=Path(config_value(args, config_doc, "trace_root", DEFAULT_TRACE_ROOT)),
        inherit=args.inherit if args.inherit is not None else config_doc.get("inherit"),
        dashboard=bool_config_value(args, config_doc, "dashboard", True),
        openai_base_url=config_value(args, config_doc, "openai_base_url"),
        openai_api_key_env=config_value(args, config_doc, "openai_api_key_env"),
        max_retries=int(config_value(args, config_doc, "max_retries", 3)),
        generation_threshold=int(config_value(args, config_doc, "generation_threshold", 5)),
        generation_stops=bool_config_value(args, config_doc, "generation_stops", False),
        skip_judge=bool_config_value(args, config_doc, "skip_judge", False),
        k_init=int(config_value(args, config_doc, "k_init", 10)),
        k=int(config_value(args, config_doc, "k", 20)),
        refinement_stops=bool_config_value(args, config_doc, "refinement_stops", False),
        advanced_refinement=bool_config_value(args, config_doc, "advanced_refinement", False),
        hooks=parse_codex_hooks(hooks_doc),
    )
    result = install(config_value(args, config_doc, "project_dir", "."), cfg)
    if args.install_skill:
        result["skill"] = install_skill(
            skills_dir=args.skills_dir,
            force=args.force_skill,
        ).to_dict()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
