"""Prompt fragments, role definitions, and category templates.

Keeping these here lets the stage modules stay focused on flow control —
the static text that defines what "Category A" or "role-specific failure"
means lives in one place and can be reviewed independently.
"""

from __future__ import annotations

import json
from importlib.resources import files
from string import Template
from typing import Any, Dict

# Default role definitions used as hints when the LLM classifies agents.
# The actual roles in a taxonomy are discovered dynamically from trace
# content; this is just the seed vocabulary the LLM can choose from.
DEFAULT_ROLE_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "solver": {
        "definition": "Agent that generates solutions, answers, code, or content in response to a problem or task.",
        "key_behavior": "Produces output that attempts to solve/answer the given problem.",
        "purpose": "Generate solutions, code, or outputs",
    },
    "checker": {
        "definition": "Agent that verifies, validates, or evaluates solutions produced by other agents.",
        "key_behavior": "Assesses correctness and provides accept/reject judgment.",
        "purpose": "Verify, review, or test solutions",
    },
    "refiner": {
        "definition": "Agent that improves solutions based on feedback, critique, or failed verification.",
        "key_behavior": "Takes existing output + feedback and produces improved version.",
        "purpose": "Improve solutions based on feedback",
    },
    "coordinator": {
        "definition": "Agent that orchestrates workflow, routes tasks, or makes selection decisions between multiple outputs.",
        "key_behavior": "Controls flow, chooses between options, decides when to terminate.",
        "purpose": "Orchestrate workflow and make decisions",
    },
}


def load_prompt_asset(name: str) -> str:
    """Load a model-facing prompt asset bundled with the pipeline package."""
    return files(__package__).joinpath("assets", name).read_text(encoding="utf-8")


def render_prompt_asset(name: str, **context: Any) -> str:
    """Render a prompt asset with string.Template placeholders.

    ``string.Template`` keeps JSON examples readable in the assets because
    braces do not need escaping.
    """
    rendered_context = {key: _prompt_value(value) for key, value in context.items()}
    return Template(load_prompt_asset(name)).safe_substitute(rendered_context)


def _prompt_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2)


A_FAILURE_CATEGORIES = load_prompt_asset("a_failure_categories.md").strip()


# Keywords that indicate a B code is really an A code (system/output failure, not quality).
B_CODE_A_TYPE_KEYWORDS = [
    "no output", "empty output", "unable to provide", "placeholder",
    "truncated", "incomplete output", "no response", "missing output",
    "format violation", "malformed output", "unable to produce",
    "failed to generate", "timed out", "crashed",
]


# Keywords used by TaxonomyChecker to verify category-A coverage.
A_FAILURE_CATEGORY_KEYWORDS: Dict[str, list] = {
    "output_issues": [
        "output", "empty", "truncat", "malform", "no response", "garble",
        "missing output", "partial output", "incomplete output",
    ],
    "context_memory": [
        "context", "memory", "overflow", "forgot", "contradict",
        "lost track", "window", "capacity", "re-deriv",
    ],
    "communication": [
        "handoff", "communication", "passed", "routing", "downstream",
        "upstream", "inter-agent", "misroute", "relay",
    ],
    "behavioral": [
        "loop", "repetit", "refusal", "abandon", "circular",
        "degrad", "stuck", "regress", "pathological",
    ],
    "execution": [
        "timeout", "crash", "error", "exception", "rate limit",
        "resource", "runtime", "api error", "fail",
    ],
    "instruction": [
        "instruction", "compliance", "system prompt", "ignored constraint",
        "wrong problem", "format requirement", "disobey", "non-compliance",
    ],
    "tool_api": [
        "tool", "api", "function call", "tool call", "wrong tool",
        "wrong argument", "tool error", "tool response", "tool fail",
        "malformed argument", "invoke", "tool misuse",
    ],
}


# Placeholder-quality regexes used by the checker to flag low-effort heuristics.
PLACEHOLDER_PATTERNS = [
    r"trace_field_\d",
    r"trace_field\d",
    r"field_\d+",
    r"trace\.field",
    r"\bTBD\b",
    r"\bTODO\b",
    r"\bplaceholder\b",
    r"\.{3,}",
]


def build_b_role_guidance(role_details: Dict[str, Dict[str, Any]]) -> str:
    """Build the dynamic B-code role guidance section.

    The B generator's prompt needs to remind the LLM what "quality failure"
    means for each *active* role in the system being analyzed — so this is
    built fresh from the discovered roles rather than baked in.
    """
    lines = [
        "When generating Category B (Role-Specific Quality Failure) codes, consider",
        "quality failure categories per role. Not all will apply to every system — generate",
        "codes only for ACTIVE roles and only for failures relevant to the system's architecture",
        "and capabilities.",
        "",
    ]

    for role_name, details in role_details.items():
        if not details.get("agents"):
            continue
        purpose = details.get("purpose", "Unknown purpose")
        definition = details.get("definition", "")
        lines.append(f"{role_name.upper()} quality failures (purpose: {purpose}):")
        lines.append(f"  Role definition: {definition}")
        lines.append(f"  Consider: What ways can an agent whose job is to '{purpose}' do that job INCORRECTLY?")
        lines.append("  Think about: wrong output, poor quality output, missed important aspects,")
        lines.append("  inappropriate method/strategy, superficial work, ignoring relevant information.")
        lines.append("")

    lines.extend([
        "CRITICAL RULE — A/B BOUNDARY:",
        "B codes are NEVER about system-level failures. These belong in Category A:",
        "  - Agent produced no output, empty output, or truncated output -> A code",
        "  - Agent timed out, crashed, or hit token limits -> A code",
        "  - Output is malformed or unparseable -> A code",
        "  - Agent refused to engage or abandoned the task -> A code",
        "B codes are ONLY about the agent doing its job INCORRECTLY — it functioned,",
        "produced output, but the QUALITY of that output was wrong.",
    ])

    return "\n".join(lines)
