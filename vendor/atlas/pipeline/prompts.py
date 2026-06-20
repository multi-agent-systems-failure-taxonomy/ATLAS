"""Prompt fragments, role definitions, and category templates.

Keeping these here lets the stage modules stay focused on flow control —
the static text that defines what "Category A" or "role-specific failure"
means lives in one place and can be reviewed independently.
"""

from __future__ import annotations

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


A_FAILURE_CATEGORIES = """
When generating Category A (System Failure) codes, consider these failure categories.
Not all categories will apply to every system — generate codes only for categories
that are relevant based on the architecture and trace evidence.

1. OUTPUT ISSUES: Agent produces no output, partial output, garbled output, or
   output that cannot be used by downstream agents. Consider: empty responses,
   truncated mid-sentence, malformed structure, output that doesn't match
   expected format for the system.

2. CONTEXT / MEMORY ISSUES: Agent loses track of prior information, contradicts
   its own earlier reasoning, forgets constraints, or cannot process all input
   because it exceeds capacity. Consider: context window overflow, information
   loss across long traces, re-deriving already established facts.

3. INTER-AGENT COMMUNICATION ISSUES: Information is lost, corrupted, or
   misrouted between agents. Consider: handoff failures, information not
   properly passed to next stage, downstream agent missing upstream context,
   miscommunication between agents.

4. BEHAVIORAL ANOMALIES: Agent exhibits pathological behavior patterns.
   Consider: repetitive/looping output, circular reasoning, refusal to engage,
   abandonment mid-task, degrading output quality over the course of the trace.

5. EXECUTION ERRORS: System-level failures during agent execution. Consider:
   timeouts, crashes, API errors, rate limiting, resource exhaustion, runtime
   exceptions visible in the trace.

6. INSTRUCTION COMPLIANCE: Agent fails to follow its system prompt or task
   instructions. Consider: ignoring constraints, responding to a different
   problem than asked, not adhering to output format requirements specified
   in the prompt.

7. TOOL / API INTERACTION ISSUES: Agent fails when invoking external tools,
   APIs, or function calls. Consider: calling wrong tool for the task,
   passing incorrect or malformed arguments, misinterpreting tool response
   data, tool returning errors that agent doesn't handle, agent retrying
   failed tool calls without adjusting, agent ignoring tool results.
   This applies to any system where agents interact with external tools,
   databases, or APIs as part of their workflow.

IMPORTANT GUIDELINES:
- Generate codes that describe CAUSES, not just symptoms. "Token limit caused
  truncation" is better than "output is missing its ending."
- Keep codes format-agnostic — they should apply regardless of specific trace
  delimiters or markers used by this particular system.
- Each code should represent a genuinely distinct failure mode. Do NOT generate
  multiple codes that describe variants of the same underlying problem.
- If a failure mode is plausible based on the architecture but not observed in
  traces, include it and mark evidence as "theoretical".
"""


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
