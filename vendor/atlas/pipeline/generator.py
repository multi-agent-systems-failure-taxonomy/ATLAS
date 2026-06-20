"""Steps 3-5: CategoryGenerator (A, B, C).

Each category is built by two LLM "agents" running in parallel:

- **Category A** (system failures, agent-independent):
  - Architectural: pure risk analysis from the topology, no traces.
  - Empirical: behavioral anomalies grounded in observed traces + signals.

- **Category B** (role-specific quality failures):
  - Theoretical: derived from architecture + role definitions.
  - Empirical: derived from observed trace content.

- **Category C** (domain reasoning failures):
  - Domain-Seeded: built from the domain analyzer's error patterns.
  - Trace-Grounded: built from observed reasoning flaws in traces.

The two stages are then merged and deduplicated via the LLM, and
A-specific sanitization removes any codes that turned out to be role-
specific (which means they belong in B, not A).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from vendor.atlas.config import PipelineConfig
from vendor.atlas.llm import LLMClient, extract_json
from vendor.atlas.pipeline.prompts import (
    A_FAILURE_CATEGORIES,
    build_b_role_guidance,
)
from vendor.atlas.traces.signals import SignalExtractor
from vendor.atlas.utils import (
    format_trace_for_prompt,
    normalize_code_ids,
    progress,
    stratified_sample,
    truncate_text,
)


class CategoryGenerator:
    """Generate codes for one taxonomy category (A, B, or C) via two parallel stages."""

    def __init__(
        self,
        client: LLMClient,
        config: PipelineConfig,
        category: str,
        domain_info: Dict[str, Any],
        structure_info: Dict[str, Any],
        trace_signals: Optional[Dict[str, Any]] = None,
    ):
        assert category in ("A", "B", "C"), f"Bad category: {category}"
        self.client = client
        self.config = config
        self.category = category
        self.domain_info = domain_info or {}
        self.structure_info = structure_info or {}
        self.trace_signals = trace_signals or {}

    def generate(
        self,
        traces: List[Dict[str, Any]],
        existing_codes: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        progress(f"\nStep {3 + ['A', 'B', 'C'].index(self.category)}: Category {self.category} Generator")
        progress("  No base codes — fully generated from analysis")

        if self.category == "B":
            active_roles = self._active_roles()
            progress(f"  Active roles with agents: {active_roles}")
            if not active_roles:
                progress("  WARNING: No agents discovered for any role - B codes will be empty")
                return []

        if self.category == "A":
            stage1_name, stage2_name = "Architectural", "Empirical"
        elif self.category == "C":
            stage1_name, stage2_name = "Domain-Seeded", "Trace-Grounded"
        else:
            stage1_name, stage2_name = "Theoretical", "Empirical"

        # A-Architectural runs without traces; everyone else gets a slice.
        mid = len(traces) // 2
        traces_stage1 = stratified_sample(traces[:mid] if mid > 0 else traces, self.config.traces_per_agent)
        traces_stage2 = stratified_sample(traces[mid:] if mid > 0 else traces, self.config.traces_per_agent)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(
                self._run_stage,
                [] if self.category == "A" else traces_stage1,
                stage1_name, existing_codes,
            )
            future2 = executor.submit(
                self._run_stage, traces_stage2, stage2_name, existing_codes,
            )
            codes_stage1 = future1.result()
            codes_stage2 = future2.result()

        progress(f"  {stage1_name} stage: {len(codes_stage1)} codes")
        progress(f"  {stage2_name} stage: {len(codes_stage2)} codes")

        merged = self._merge_codes(codes_stage1, codes_stage2)
        progress(f"  Merged total: {len(merged)} codes")

        if self.category == "A":
            merged = self._sanitize_a_codes(merged)

        return merged

    # ───── A-code sanitization ─────

    def _sanitize_a_codes(self, codes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop A codes whose names imply they're really role-specific (-> B).

        The "swap test": if replacing the agent with one of a different role
        would make the code inapplicable, the code belongs in B. We approximate
        the swap test by checking whether role-related vocabulary appears in
        the code's *name* (a much stronger signal than appearing in the body).
        """
        role_details = self.structure_info.get("discovered_agents", {}).get("role_details", {})
        indicators: Dict[str, List[str]] = {}
        for role, details in role_details.items():
            agent_names = [a.lower() for a in details.get("agents", []) if len(a) > 2]
            purpose_words = [w for w in details.get("purpose", "").lower().split() if len(w) > 4]
            indicators[role] = [role, *agent_names, *purpose_words]

        sanitized: List[Dict[str, Any]] = []
        removed: List[tuple] = []
        for code in codes:
            name_lower = code.get("name", "").lower()
            is_role_specific = False
            for role, role_indicators in indicators.items():
                if any(ind in name_lower for ind in role_indicators):
                    is_role_specific = True
                    removed.append((code.get("code", ""), code.get("name", ""), role))
                    break
            if not is_role_specific:
                sanitized.append(code)

        if removed:
            progress(f"  A-code sanitization: removed {len(removed)} role-specific codes:")
            for code_id, name, role in removed:
                progress(f"    {code_id} '{name}' -> role-specific to {role}")

        return sanitized

    # ───── Context builders ─────

    def _active_roles(self) -> List[str]:
        role_details = self.structure_info.get("discovered_agents", {}).get("role_details", {})
        return [role for role, details in role_details.items() if details.get("agents")]

    def _trace_format_context(self) -> str:
        trace_format = self.structure_info.get("trace_format", {}) or {}
        lines = ["\n=== TRACE FORMAT CONTEXT ==="]
        markers = trace_format.get("agent_markers", [])
        if markers:
            lines.append(f"Agent markers in traces: {markers}")
        key_fields = trace_format.get("key_fields", [])
        if key_fields:
            lines.append("\nDiscovered fields:")
            for field in key_fields:
                name = field.get("field_name", field.get("field", "?"))
                desc = field.get("description", "")
                lines.append(f"  * {name}: {desc}")
        else:
            lines.append("\nUse general trace content patterns for heuristics.")
        return "\n".join(lines)

    def _architecture_context(self) -> str:
        arch = self.structure_info.get("architecture", {}) or {}
        agents = self.structure_info.get("discovered_agents", {}) or {}
        lines = ["\n=== SYSTEM ARCHITECTURE ==="]
        lines.append(f"Topology: {arch.get('topology', 'Unknown')}")
        if arch.get("topology_details"):
            lines.append(f"Details: {arch['topology_details']}")
        lines.append(f"\nVerification: {arch.get('verification_pattern', 'Unknown')}")
        if arch.get("verification_details"):
            lines.append(f"Details: {arch['verification_details']}")
        lines.append(f"\nTermination owner: {arch.get('termination_owner', 'Unknown')}")

        handoffs = arch.get("critical_handoffs", [])
        if handoffs:
            lines.append("\nCritical handoffs:")
            for h in handoffs:
                lines.append(
                    f"  {h.get('from_agent','?')} -> {h.get('to_agent','?')}: "
                    f"passes {h.get('what_is_passed','?')} "
                    f"(risk: {h.get('failure_risk','?')})"
                )

        role_details = agents.get("role_details", {})
        if role_details:
            lines.append("\n=== AGENTS & ROLES ===")
            for role, details in role_details.items():
                agent_list = details.get("agents", [])
                if not agent_list:
                    continue
                purpose = details.get("purpose", "")
                shown = agent_list[:5]
                more = f" (+{len(agent_list)-5} more)" if len(agent_list) > 5 else ""
                purpose_str = f" ({purpose})" if purpose else ""
                lines.append(f"{role.upper()}{purpose_str}: {', '.join(shown)}{more}")

        return "\n".join(lines)

    def _agent_context(self) -> str:
        agents = self.structure_info.get("discovered_agents", {})
        if not agents:
            return ""
        lines = ["\n=== DISCOVERED AGENTS ==="]
        for role, details in agents.get("role_details", {}).items():
            agent_list = details.get("agents", [])
            if not agent_list:
                continue
            purpose = details.get("purpose", "")
            shown = agent_list[:5]
            more = f" (+{len(agent_list)-5} more)" if len(agent_list) > 5 else ""
            purpose_str = f" ({purpose})" if purpose else ""
            lines.append(f"{role.upper()}{purpose_str}: {', '.join(shown)}{more}")
        return "\n".join(lines)

    def _domain_context(self) -> str:
        if not self.domain_info:
            return ""
        lines = ["\n=== DOMAIN KNOWLEDGE ==="]
        lines.append(f"Domain: {self.domain_info.get('domain', {}).get('name', 'Unknown')}")
        if self.domain_info.get("subdomains"):
            lines.append(f"Subdomains: {', '.join(self.domain_info['subdomains'][:5])}")
        patterns = self.domain_info.get("common_error_patterns", [])
        if patterns:
            lines.append("Common error patterns:")
            for p in patterns[:5]:
                lines.append(f"  - {p.get('name', '')}: {p.get('description', '')}")
        return "\n".join(lines)

    def _signal_context(self) -> str:
        if not self.trace_signals:
            return ""
        return SignalExtractor(verbose=False).format_for_prompt(self.trace_signals)

    def _lightweight_domain_context(self) -> str:
        if not self.domain_info:
            return ""
        domain = self.domain_info.get("domain", {})
        return (
            "\n=== DOMAIN CONTEXT ===\n"
            f"Domain: {domain.get('name', 'Unknown')}\n"
            f"Content type: {domain.get('content_type', 'Unknown')}\n"
            f"Task complexity: {domain.get('task_complexity', 'Unknown')}"
        )

    def _capabilities_context(self) -> str:
        caps = self.structure_info.get("capabilities", {}) or {}
        if not caps:
            return ""
        lines = ["\n=== AGENT CAPABILITIES ==="]
        style = caps.get("interaction_style", "direct_reasoning")
        lines.append(f"Primary interaction style: {style}")

        if style == "tool_calling":
            lines.extend([
                "Agents primarily interact with external tools/APIs to accomplish tasks.",
                "B codes should focus on quality of TOOL USAGE and DECISION-MAKING:",
                "  - Did the agent select the right tool for the situation?",
                "  - Did it pass correct arguments?",
                "  - Did it correctly interpret tool responses?",
                "  - Did it follow required procedures (e.g., confirmation before action)?",
                "  - Did it chain tool calls in the right sequence?",
            ])
        elif style == "code_execution":
            lines.extend([
                "Agents write and execute code to accomplish tasks.",
                "B codes should focus on quality of CODE and APPROACH:",
                "  - Is the code correct for the problem?",
                "  - Does it handle edge cases?",
                "  - Is the approach appropriate?",
            ])
        elif style == "mixed":
            lines.append("Agents use a mix of direct reasoning and tool/API calls.")

        tools = caps.get("tool_names_seen", [])
        if tools:
            lines.append(f"\nTools/APIs available: {', '.join(tools[:15])}")
        return "\n".join(lines)

    def _domain_error_seed_context(self) -> str:
        if not self.domain_info:
            return ""
        lines = ["\n=== DOMAIN ERROR PATTERNS (from domain analysis) ==="]

        subdomains = self.domain_info.get("subdomains", [])
        if subdomains:
            lines.append(f"\nSUBDOMAINS in this domain: {', '.join(subdomains)}")
            lines.extend([
                "IMPORTANT: Generate C codes that cover reasoning failures across ALL these",
                "subdomains, not just the most common ones. Each subdomain may have its own",
                "characteristic error types. If a subdomain has distinctive reasoning patterns",
                "(e.g., spatial reasoning, inequality chains, inductive proofs), ensure those",
                "failure modes are represented.",
            ])

        patterns = self.domain_info.get("common_error_patterns", [])
        if patterns:
            lines.append("\nKnown error patterns in this domain:")
            for p in patterns:
                lines.append(f"  - {p.get('name', '')}: {p.get('description', '')}")
                for h in p.get("detection_hints", [])[:2]:
                    lines.append(f"      detection hint: {h}")
            lines.extend([
                "\nThese known patterns are a STARTING POINT, not a complete list.",
                "You must also identify error types NOT listed above that are common",
                "in the subdomains. Consider:",
                "  - Errors specific to each subdomain's characteristic techniques",
                "  - Errors in logical structure (proof direction, quantifier scope, etc.)",
                "  - Errors in algebraic/symbolic manipulation (sign errors, invalid transforms)",
                "  - Errors in applying standard inequalities or estimates",
                "  - Errors in geometric or spatial reasoning if applicable",
                "  - Errors in proof strategy (proving wrong direction, circular reasoning)",
            ])

        terms = self.domain_info.get("domain_terminology", [])
        error_terms = [t for t in terms if t.get("error_associations")]
        if error_terms:
            lines.append("\nDomain concepts with known error-prone usage:")
            for t in error_terms[:10]:
                lines.append(f"  - {t.get('term', '')} ({t.get('meaning', '')})")
                for a in t.get("error_associations", [])[:2]:
                    lines.append(f"      common error: {a}")

        criteria = self.domain_info.get("correctness_criteria", [])
        if criteria:
            lines.append("\nCorrectness criteria (violations = potential C codes):")
            for c in criteria:
                lines.append(f"  - {c.get('criterion', '')}: {c.get('description', '')}")

        return "\n".join(lines)

    # ───── Stage prompts ─────

    def _stage_prompt(self, stage_name: str) -> str:
        active_roles = self._active_roles()
        role_str = ", ".join(r.capitalize() for r in active_roles)

        if self.category == "A":
            arch_ctx = self._architecture_context()
            caps_ctx = self._capabilities_context()
            domain_lite = self._lightweight_domain_context()
            signal_ctx = self._signal_context()

            common_header = f"""CATEGORY A - System Failures (Agent-Independent)

These are failures that can happen to ANY agent regardless of role.
NOT about correctness — about system-level issues that prevent agents from
functioning properly or producing usable output.

NAMING RULE: A-codes must NEVER contain agent role names ({role_str}).
ROLE-NEUTRALITY RULE: A-codes must describe GENERIC system failures, not failures specific to
one agent's purpose. Apply the "swap test": if replacing the agent with a different-role agent
would make the code inapplicable, it belongs in B, not A. For example:
  - GOOD A code: "Output truncation" — any agent can produce truncated output
  - GOOD A code: "Inter-agent information loss" — any handoff can lose information
  - BAD A code: "Verdict misreporting" — only a checker produces verdicts -> this is B
  - BAD A code: "Refinement inconsistency" — only a refiner refines -> this is B
"""

            if stage_name == "Architectural":
                return f"""{common_header}

YOUR TASK (Architectural Risk Analysis):
Given the system architecture below, identify ALL plausible system-level failure
modes that could occur in this pipeline. Think about:
- What happens at each handoff point? What can go wrong?
- What happens if an agent runs too long, or its context fills up?
- What happens if an agent produces no output, or garbled output?
- What if an agent contradicts itself or loops?
- What if an agent refuses to engage or abandons the task?
- What if the pipeline terminates prematurely?

You do NOT need to see traces for this — reason purely from the architecture.
Generate codes for failures that are PLAUSIBLE based on how this system is designed.

For each code, set "evidence": "theoretical" since these come from architectural
reasoning rather than observed trace data.

{A_FAILURE_CATEGORIES}

{arch_ctx}
{caps_ctx}
{domain_lite}

{signal_ctx}
"""
            return f"""{common_header}

YOUR TASK (Empirical Behavioral Analysis):
Analyze the BEHAVIORAL SIGNALS extracted from all traces (below) and the
SAMPLE TRACES to identify system failures that ACTUALLY OCCURRED.

Focus on:
- Behavioral anomalies: looping, repetition, refusal, degrading quality
- Output issues: truncation, empty output, malformed responses
- Communication issues: information lost between agents, handoff failures
- Any system-level problems visible in the trace content

Do NOT generate codes for trace FORMAT validation rules (e.g., "missing tag X"
or "wrong delimiter Y"). Focus on the underlying system failures, not their
surface-level formatting symptoms.

For each code, set "evidence": "observed" since these come from actual trace data.

{A_FAILURE_CATEGORIES}

{signal_ctx}

{arch_ctx}
{caps_ctx}
{domain_lite}
"""

        if self.category == "B":
            arch_ctx = self._architecture_context()
            caps_ctx = self._capabilities_context()
            trace_ctx = self._trace_format_context()
            role_details = self.structure_info.get("discovered_agents", {}).get("role_details", {})

            agents_per_role: Dict[str, List[str]] = {}
            for role in active_roles:
                lst = role_details.get(role, {}).get("agents", [])[:5]
                if lst:
                    agents_per_role[role] = lst

            role_defs_text = "\n".join(
                f"- {role}: {role_details.get(role, {}).get('definition', 'N/A')}"
                for role in active_roles
            )
            role_name_prefixes = ", ".join(f"{r.capitalize()}_" for r in active_roles)
            b_guidance = build_b_role_guidance(role_details)

            return f"""CATEGORY B - Role-Specific Quality Failures

NAMING RULE: B-codes MUST contain role name prefix ({role_name_prefixes})

ROLE DEFINITIONS:
{role_defs_text}

ACTIVE ROLES (only generate for these): {active_roles}

DISCOVERED AGENTS PER ROLE:
{json.dumps(agents_per_role, indent=2)}

{b_guidance}

YOUR TASK ({stage_name} Stage):
{"Analyze the system ARCHITECTURE and identify role-specific quality failures based on how agents interact and what decisions they make." if stage_name == "Theoretical" else "Analyze ACTUAL TRACE CONTENT and find role-specific quality failures that occurred."}

Generate codes for complete coverage of all distinct quality failure modes per active role.
Each code must represent a genuinely distinct failure — do NOT create multiple codes
for variants of the same quality problem.

{caps_ctx}
{arch_ctx}
{trace_ctx}
"""

        # Category C
        domain_error_ctx = self._domain_error_seed_context()
        domain_ctx = self._domain_context()
        common_header = f"""CATEGORY C - Domain Reasoning Failures

These are failures in the REASONING PROCESS itself, specific to the problem domain.
C codes describe WHAT went wrong in the reasoning — not WHO made the error or WHETHER
the system broke. A judge should be able to identify these by reading the reasoning
in a trace, WITHOUT needing to independently solve the problem or know the correct answer.

NAMING RULE: C-codes must NEVER contain agent role names ({role_str}).
A valid C code applies equally whether the flawed reasoning appeared in any agent's output.
"""

        if stage_name == "Domain-Seeded":
            return f"""{common_header}

YOUR TASK (Domain-Seeded Stage):
Using the domain error patterns, subdomains, and terminology pitfalls below as scaffolding,
generate categories of reasoning failure that:
1. Are DETECTABLE from the trace alone — a judge reading the reasoning can spot the flaw
   without solving the problem independently
2. Describe ERROR TYPES, not error instances — each code should apply across many problems,
   not just one specific scenario
3. Are at the right GRANULARITY — not too broad ("mathematical error") and not too narrow
   ("forgot to check n=0 in induction")
4. COVER ALL SUBDOMAINS — ensure each subdomain's characteristic reasoning failures are
   represented. Don't cluster all codes around one subdomain while ignoring others.

COVERAGE CHECK: After generating codes, verify you have at least one code relevant to
each subdomain listed below. If a subdomain has no coverage, add a code for its most
common reasoning failure type.

For each code, provide a concrete example of when it applies vs when it does NOT,
to ensure the code is operationally distinguishable from other codes.

DISTINGUISHABILITY RULE: If two codes cannot be told apart by a judge reading a trace,
they must be merged into one code.

{domain_error_ctx}
{domain_ctx}
"""
        return f"""{common_header}

YOUR TASK (Trace-Grounded Stage):
Analyze the SAMPLE TRACES below. For each trace where reasoning appears flawed,
identify WHAT TYPE of reasoning error is present. Then cluster these into distinct
categories of reasoning failure.

Focus on patterns of flawed reasoning that are DETECTABLE from the trace content:
- Internal contradictions within the reasoning
- Unjustified logical leaps or unsupported claims
- Misapplication of domain concepts or techniques
- Gaps in case analysis or missing considerations
- Incorrect manipulation of domain-specific objects (formulas, data structures, etc.)
- Errors in algebraic or symbolic transformations (sign errors, invalid cancellations)
- Wrong direction of inequalities or estimates
- Geometric/spatial reasoning errors (wrong angle relations, invalid similarity claims)
- Proof structure errors (proving only one direction, assuming the conclusion)
- Logical errors (quantifier confusion, affirming the consequent)

Do NOT generate codes for:
- System-level failures (timeouts, crashes, truncation) — those are A codes
- Agent role failures (weak validation, wrong routing) — those are B codes
- Outcome-level judgments ("answer is wrong") — C codes describe the PROCESS flaw

{domain_error_ctx}
{domain_ctx}
"""

    # ───── Stage execution ─────

    def _run_stage(
        self,
        traces: List[Dict[str, Any]],
        stage_name: str,
        existing_codes: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        progress(f"  Running {self.category}-{stage_name}...")

        if self.category == "A" and stage_name == "Architectural":
            traces_text = ""
        else:
            traces_text = "\n\n".join(
                format_trace_for_prompt(t, max_length=3000) for t in traces[:15]
            )

        existing_str = ""
        if existing_codes:
            existing_str = "\nEXISTING CODES FROM OTHER CATEGORIES (don't duplicate concepts):\n"
            for cat_key, codes in existing_codes.items():
                if not codes:
                    continue
                items = codes if isinstance(codes, list) else list(codes.values())
                names = [c.get("name", "")[:40] for c in items][:8]
                existing_str += f"  {cat_key}: {', '.join(names)}\n"

        evidence_field = ', "evidence": "theoretical|observed"' if self.category == "A" else ""

        if self.category == "C":
            requirements = f"""REQUIREMENTS:
1. Each code describes an ERROR TYPE (not an error instance) — it should apply across
   many problems, not just one specific scenario
2. Each code must be DETECTABLE by a judge reading the trace — the judge should NOT need
   to solve the problem independently or know the correct answer
3. Each code must be DISTINGUISHABLE from every other code — if two codes cannot be told
   apart by a judge, merge them
4. Do NOT include system failures (A codes) or role-specific failures (B codes)
5. C codes must NEVER reference agent roles ({', '.join(self._active_roles())})
6. detection_heuristics must describe what a judge would look for in the trace text
7. Definitions should be concise and clear
8. Prioritize clarity over quantity — fewer clear codes is better than many overlapping ones"""
        else:
            requirements = """REQUIREMENTS:
1. Generate codes for complete coverage of all distinct system failure modes
2. Each code must represent a genuinely distinct failure — do NOT create multiple
   codes for variants of the same problem (e.g., do not have separate codes for
   "output missing" and "output empty" — those are the same failure)
3. Prefer CAUSAL codes over SYMPTOM codes. "Token limit caused truncation" is one
   code, not two separate codes for "token limit hit" and "output truncated"
4. Each code needs detection_heuristics grounded in observable signals
5. Definitions should be concise and clear
6. Follow naming rules strictly"""

        traces_section = f"\nSAMPLE TRACES:\n{traces_text}" if traces_text else ""

        b_extra = ""
        if self.category == "B":
            roles = "|".join(self._active_roles())
            b_extra = (
                f', "applies_to_role": "{roles}", '
                f'"agent_heuristics": {{"AgentName": ["agent-specific signal"]}}'
            )

        prompt = f"""You are the {stage_name} Agent generating Category {self.category} codes.

{self._stage_prompt(stage_name)}
{existing_str}
{traces_section}

{requirements}

OUTPUT JSON:
{{
  "codes": [
    {{
      "code": "{self.category}.X",
      "name": "Descriptive_Name",
      "definition": "Concise definition.",
      "when_to_use": "When to apply",
      "when_not_to_use": "When NOT to apply",
      "detection_heuristics": ["observable signal from trace content", "..."],
      "severity": "critical|major|minor"{evidence_field}{b_extra}
    }}
  ]
}}"""

        try:
            response = self.client.chat(prompt)
            result = extract_json(response)
            if "_root_list" in result:
                codes = result["_root_list"]
            else:
                codes = result.get("codes", [])
            return [c for c in codes if isinstance(c, dict)]
        except Exception as e:  # noqa: BLE001
            progress(f"  [!] {stage_name} error: {e}")
            return []

    # ───── Merge / dedupe ─────

    def _merge_codes(
        self,
        stage1_codes: List[Dict[str, Any]],
        stage2_codes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        stage1_codes = [c for c in stage1_codes if isinstance(c, dict)]
        stage2_codes = [c for c in stage2_codes if isinstance(c, dict)]
        all_codes = stage1_codes + stage2_codes
        if not all_codes:
            return []

        def summarize(codes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return [{
                "name": c.get("name", "")[:60],
                "definition": truncate_text(c.get("definition", ""), 150),
                "evidence": c.get("evidence", ""),
            } for c in codes]

        prompt = f"""Deduplicate these Category {self.category} codes.

ALL GENERATED CODES (from two analysis stages):
{json.dumps(summarize(all_codes), indent=2)}

DEDUPLICATION RULES:
1. Two codes are duplicates if they describe the SAME underlying failure, even if
   worded differently. E.g., "output missing" and "no output produced" are duplicates.
2. If one code describes a CAUSE and another describes its SYMPTOM, keep the CAUSAL
   code and remove the symptom code. E.g., keep "token limit exhaustion" over
   "output truncated mid-sentence" — the truncation is a symptom of the token limit.
3. When merging duplicates, prefer the code with more specific detection_heuristics
   or the one with "evidence": "observed" over "evidence": "theoretical".
4. Be aggressive about merging — it is better to have fewer distinct codes than
   many overlapping ones.

OUTPUT JSON:
{{
  "kept_codes": [{{"name": "...", "definition": "..."}}],
  "removed": [{{"name": "...", "reason": "Duplicate of / symptom of ..."}}]
}}"""

        try:
            result = extract_json(self.client.chat(prompt))
            kept_names = {c.get("name", "").lower() for c in result.get("kept_codes", [])}
            kept = [c for c in all_codes if c.get("name", "").lower() in kept_names]
            if not kept:
                progress("  [!] Dedup removed all codes, falling back")
                kept = all_codes
            return normalize_code_ids(kept, self.category)
        except Exception as e:  # noqa: BLE001
            progress(f"  [!] Merge error: {e}")
            return normalize_code_ids(all_codes, self.category)
