"""Shared interactive-session taxonomy selector state and rendering."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from adamast_runtime import ProgramWorkspace
from adamast_runtime.project_scope import canonical_project_root
from finding import mast, store

SELECTOR_VERSION = 2


def build_selection(
    *,
    trace_output: Path,
    store_dir: Path,
    cwd: str | Path | None,
    catalog_mode: str = "inline",
) -> dict[str, Any]:
    """Build the compatible choices for one new interactive conversation."""
    workspace = ProgramWorkspace(trace_output, repo_path=cwd)
    active_id = workspace.load().get("taxonomy_id")
    options: list[dict[str, Any]] = []
    catalog_options: list[dict[str, Any]] = []

    if active_id:
        options.append(stored_option(str(active_id), store_dir, recommended=True))
    options.append(
        {
            "kind": "mast",
            "taxonomy_id": mast.MAST_ID,
            "label": "MAST",
            "description": (
                "Start this conversation from MAST in a separate task group; "
                "learn a new taxonomy from zero."
                if active_id
                else "General-purpose failure modes for agentic work."
            ),
            "domain": "General agent work",
            "origin": "Built-in",
            "recommended": not bool(active_id),
            "starts_fresh": bool(active_id),
        }
    )
    if not active_id and catalog_mode == "browser":
        for header in store.list_all(store_dir):
            taxonomy_id = str(header.get("taxonomy_id") or "").strip()
            if taxonomy_id:
                catalog_options.append(stored_option(taxonomy_id, store_dir))
    if not active_id and catalog_mode == "browser" and catalog_options:
        options.append(
            {
                "kind": "browser",
                "taxonomy_id": None,
                "label": "Browse taxonomy library",
                "description": (
                    "Open the local AdaMAST catalog to compare stored taxonomies."
                ),
                "domain": "All stored taxonomies",
                "origin": "Local browser",
                "recommended": False,
            }
        )
    elif not active_id:
        for header in store.list_all(store_dir):
            taxonomy_id = str(header.get("taxonomy_id") or "").strip()
            if taxonomy_id:
                options.append(stored_option(taxonomy_id, store_dir))

    options.append(
        {
            "kind": "disabled",
            "taxonomy_id": None,
            "label": "No taxonomy",
            "description": (
                "Disable AdaMAST gates and trace learning for this conversation."
            ),
            "domain": "AdaMAST off",
            "origin": "Session only",
            "recommended": False,
        }
    )
    for number, option in enumerate(options, start=1):
        option["number"] = number

    root = canonical_project_root(cwd)
    return {
        "version": SELECTOR_VERSION,
        "catalog_mode": catalog_mode,
        "status": "pending",
        "project": root.name or str(root),
        "project_root": str(root),
        "project_taxonomy_id": str(active_id) if active_id else None,
        "options": options,
        "catalog_options": catalog_options,
        "pending_task": None,
    }


def render_selection(selection: dict[str, Any]) -> str:
    """Render the compact selector shown by an interactive host agent."""
    lines = [
        f"Hi! Current project: {selection.get('project') or 'unknown'}",
        f"AdaMAST project scope: {selection.get('project_root') or 'unknown'}",
        "",
        "Which taxonomy should AdaMAST use for this conversation?",
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
            "This project already has a shared taxonomy. Choosing MAST creates "
            "a separate task group for this conversation and leaves the shared "
            "project taxonomy unchanged."
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
        "adamast mast": "mast",
        "adamast use mast": "mast",
        "browse": "browser",
        "browse taxonomies": "browser",
        "browse taxonomy library": "browser",
        "taxonomy library": "browser",
        "open catalog": "browser",
        "none": "disabled",
        "off": "disabled",
        "adamast off": "disabled",
        "disable adamast": "disabled",
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

    for option in [
        *selection.get("options", []),
        *selection.get("catalog_options", []),
    ]:
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
        "AdaMAST session setup is pending. Do not perform or analyze the user's "
        "substantive task yet. Show the selector below verbatim, ask the user "
        "to choose one option, and end this response. The original task is held "
        "and will resume automatically after selection.\n\n"
        + render_selection(selection)
    )


def stored_option(
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
        "label": store.display_name(record),
        "description": description,
        "domain": domain,
        "origin": origin,
        "recommended": recommended,
    }


def render_active_selection_context(
    selection: dict[str, Any],
    *,
    active_taxonomy_id: str | None,
    store_dir: Path,
) -> str:
    """Describe the active taxonomy without erasing the user's seed choice."""
    selected_id = str(selection.get("selected_taxonomy_id") or "").strip()
    selected_label = str(
        selection.get("selected_label") or selected_id or "the selected taxonomy"
    ).strip()
    active_id = str(active_taxonomy_id or selected_id).strip()
    if active_id and active_id != selected_id:
        if active_id == mast.MAST_ID:
            active_label = "MAST"
        else:
            active_label = str(stored_option(active_id, store_dir)["label"])
        active_reference = (
            active_label
            if active_label == active_id
            else f"{active_label} ({active_id})"
        )
        context = (
            f"AdaMAST active taxonomy is {active_reference} for this conversation. "
            f"It was learned from the selected {selected_label} lineage. Use "
            "only codes from the active taxonomy. Do not ask for taxonomy "
            "selection again."
        )
    else:
        context = (
            f"AdaMAST taxonomy is pinned to {selected_label} for this "
            "conversation. Do not ask for taxonomy selection again."
        )
    if selection.get("fresh_task_group"):
        tense = "started" if active_id != selected_id else "starts"
        context += (
            f" This conversation {tense} a new taxonomy from MAST in isolated "
            f"task group {selection['fresh_task_group']}; the existing shared "
            "project taxonomy remains unchanged."
        )
    return context


def _normalize(value: str) -> str:
    text = value.strip().lower().replace("_", " ")
    text = re.sub(r"^adamast\s*:\s*", "adamast ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .")
