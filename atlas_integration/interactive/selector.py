"""Shared interactive-session taxonomy selector state and rendering."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from atlas_runtime import ProgramWorkspace
from atlas_runtime.project_scope import canonical_project_root
from finding import mast, store


def build_selection(
    *,
    trace_output: Path,
    store_dir: Path,
    cwd: str | Path | None,
) -> dict[str, Any]:
    """Build the compatible choices for one new interactive conversation."""
    workspace = ProgramWorkspace(trace_output, repo_path=cwd)
    active_id = workspace.load().get("taxonomy_id")
    options: list[dict[str, Any]] = []

    if active_id:
        options.append(_stored_option(str(active_id), store_dir, recommended=True))
    else:
        options.append(
            {
                "kind": "mast",
                "taxonomy_id": mast.MAST_ID,
                "label": "MAST",
                "description": "General-purpose failure modes for agentic work.",
                "domain": "General agent work",
                "origin": "Built-in",
                "recommended": True,
            }
        )
        for header in store.list_all(store_dir):
            taxonomy_id = str(header.get("taxonomy_id") or "").strip()
            if taxonomy_id:
                options.append(_stored_option(taxonomy_id, store_dir))

    options.append(
        {
            "kind": "disabled",
            "taxonomy_id": None,
            "label": "No taxonomy",
            "description": (
                "Disable ATLAS gates and trace learning for this conversation."
            ),
            "domain": "ATLAS off",
            "origin": "Session only",
            "recommended": False,
        }
    )
    for number, option in enumerate(options, start=1):
        option["number"] = number

    root = canonical_project_root(cwd)
    return {
        "status": "pending",
        "project": root.name or str(root),
        "project_root": str(root),
        "project_taxonomy_id": str(active_id) if active_id else None,
        "options": options,
        "pending_task": None,
    }


def render_selection(selection: dict[str, Any]) -> str:
    """Render the compact selector shown by an interactive host agent."""
    lines = [
        f"Hi! Current project: {selection.get('project') or 'unknown'}",
        f"ATLAS project scope: {selection.get('project_root') or 'unknown'}",
        "",
        "Which taxonomy should ATLAS use for this conversation?",
        "",
    ]
    for option in selection.get("options", []):
        suffix = "  [Recommended]" if option.get("recommended") else ""
        lines.extend(
            [
                f"{option['number']}. {option['label']}{suffix}",
                f"   {option['description']}",
                (
                    f"   Domain: {option['domain']} | "
                    f"Origin: {option['origin']}"
                ),
                "",
            ]
        )
    if selection.get("project_taxonomy_id"):
        lines.append(
            "This project already has a shared taxonomy. To use another stored "
            "taxonomy, create a separate ATLAS task group."
        )
    else:
        lines.append(
            "A stored taxonomy choice becomes the shared default for this "
            "project and task group."
        )
    lines.append(
        "If the work belongs to another repository, start the task from that "
        "repository or configure a stable project id before collecting traces."
    )
    lines.append("Reply with the number, taxonomy name, `MAST`, or `No taxonomy`.")
    return "\n".join(lines)


def parse_selection_choice(
    prompt: str,
    selection: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve a short user reply to one of the offered options."""
    text = str(prompt or "").strip()
    if not text or len(text) > 160:
        return None
    normalized = _normalize(text)

    number_match = re.fullmatch(r"(?:option\s+)?(\d+)(?:\s+please)?", normalized)
    if number_match:
        number = int(number_match.group(1))
        return next(
            (
                option
                for option in selection.get("options", [])
                if int(option.get("number", -1)) == number
            ),
            None,
        )

    aliases = {
        "mast": "mast",
        "use mast": "mast",
        "atlas mast": "mast",
        "atlas use mast": "mast",
        "none": "disabled",
        "off": "disabled",
        "atlas off": "disabled",
        "disable atlas": "disabled",
        "no taxonomy": "disabled",
        "use no taxonomy": "disabled",
    }
    kind = aliases.get(normalized)
    if kind:
        return next(
            (
                option
                for option in selection.get("options", [])
                if option.get("kind") == kind
            ),
            None,
        )

    for option in selection.get("options", []):
        names = {
            _normalize(str(option.get("label") or "")),
            _normalize(str(option.get("taxonomy_id") or "")),
        }
        if normalized in names:
            return option
    return None


def selection_interstitial(selection: dict[str, Any]) -> str:
    """Developer context that makes the first agent response the selector."""
    return (
        "ATLAS session setup is pending. Do not perform or analyze the user's "
        "substantive task yet. Show the selector below verbatim, ask the user "
        "to choose one option, and end this response. The original task is held "
        "and will resume automatically after selection.\n\n"
        + render_selection(selection)
    )


def _stored_option(
    taxonomy_id: str,
    store_dir: Path,
    *,
    recommended: bool = False,
) -> dict[str, Any]:
    try:
        record = store.fetch_by_id(taxonomy_id, store_dir)
    except store.TaxonomyNotFound:
        record = {
            "taxonomy_id": taxonomy_id,
            "repo": "",
            "domain": "Stored taxonomy",
        }
    domain = str(record.get("domain") or "Stored taxonomy").strip()
    repo = str(record.get("repo") or "").strip()
    description = str(
        record.get("summary")
        or record.get("description")
        or (f"Failure modes for {domain} work" + (f" in {repo}." if repo else "."))
    ).strip()
    origin = str(
        record.get("origin")
        or record.get("architecture_type")
        or record.get("architecture")
        or record.get("harness")
        or "Stored taxonomy"
    ).strip()
    return {
        "kind": "taxonomy",
        "taxonomy_id": taxonomy_id,
        "label": str(record.get("display_name") or taxonomy_id).strip(),
        "description": description,
        "domain": domain,
        "origin": origin,
        "recommended": recommended,
    }


def _normalize(value: str) -> str:
    text = value.strip().lower().replace("_", " ")
    text = re.sub(r"^atlas\s*:\s*", "atlas ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .")
