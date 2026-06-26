"""LLM prompts for the ATLAS Reflection Judge.

Pure stdlib prompt builders with no provider-specific imports.

Two prompts (default ``mode="two_call"``):

  - ``ANALYSIS_SYSTEM`` + ``analysis_user_prompt(...)``: Stage 1-7. The judge
    reconstructs trace events, identifies failure points, performs backward
    AND forward causal sweeps, classifies each failure point's causal role,
    recovery status, severity, etc. **Taxonomy is NOT in this prompt** so the
    causal analysis isn't biased by label-availability.

  - ``MAPPING_SYSTEM`` + ``mapping_user_prompt(...)``: Stage 8. Given the
    failure points produced by the analysis call AND the taxonomy, assign one
    or more codes per failure point.

A single-call mode collapses both into ``SINGLE_CALL_SYSTEM`` +
``single_call_user_prompt``. Recommended only for cost-sensitive workloads.
"""

from __future__ import annotations

from typing import Any, Mapping

JUDGE_PROMPT_VERSION = "v1"


# ──────────────────────────────────────────────────────────────────────────
# Stage 1-7 — analysis (NO taxonomy in this prompt)
# ──────────────────────────────────────────────────────────────────────────

ANALYSIS_SYSTEM = (
    "You are the ATLAS Reflection Judge. You analyze execution traces of a "
    "multi-step agent/pipeline to identify FAILURE POINTS (concrete observed "
    "locations in the trace where something went wrong) and the causal "
    "relationships between them.\n"
    "\n"
    "Key conceptual rule: a FAILURE POINT is NOT a failure mode. A failure "
    "point is a concrete event/location in the trace with evidence. A failure "
    "mode is a taxonomy label assigned LATER. In this stage you do not assign "
    "any labels — you build the causal picture from observable behavior.\n"
    "\n"
    "Reasoning principles:\n"
    "  * BACKWARD-FIRST. For every identified failure point, look earlier in "
    "the trace for direct causes. Stop at evidence-grounded parents. Do not "
    "speculate long chains.\n"
    "  * ALSO one FORWARD SWEEP at the end: scan for steps that the task "
    "objective expected (planning, verification, error handling, "
    "decomposition, fallback) but that are ABSENT from the trace. Absent-"
    "expected steps are real failure points even though they leave no event.\n"
    "  * Conservative downstream causality. Only link A → B if the trace "
    "shows clear evidence; otherwise keep them independent.\n"
    "  * Evidence required. Do not create a failure point without trace-"
    "grounded evidence. If you create no failure points, say so explicitly.\n"
    "  * Mark uncertainty explicitly. Use 'unclear' freely; do not fake "
    "confidence.\n"
    "\n"
    "You will receive: task objective, expected output (optional), final "
    "candidate output, score (optional), and the full trace. Return ONLY "
    "JSON in the exact schema described in the user prompt."
)


def _enum(name: str, values) -> str:
    return f"{name} — one of: {', '.join(sorted(values))}"


def analysis_user_prompt(judge_input: Mapping[str, Any]) -> str:
    """Render the analysis user prompt for a single trace."""
    ji = judge_input
    return f"""\
## INPUT

task_id:        {ji.get("task_id")!r}
candidate_id:   {ji.get("candidate_id")!r}
run_id:         {ji.get("run_id")!r}

### task_objective
{ji.get("task_prompt") or "(not provided)"}

### expected_output (optional)
{ji.get("expected_output") or "(not provided)"}

### candidate_output
{ji.get("candidate_output") or "(not provided)"}

### score (optional, do not use to assign blame directly)
{ji.get("score")!r}

### trace
{ji.get("trace")}

## PROCESS (stages 1-7)

Stage 1 — TRACE EVENT RECONSTRUCTION
  Reconstruct the IMPORTANT events. Not a full transcript: only events that
  matter for success, failure, recovery, or final output. Each event needs:
    event_id (E1, E2, ...), summary, trace_location, stage, agent_role
    (if available), evidence (short quote or paraphrase from the trace).

Stage 2 — FAILURE POINT IDENTIFICATION
  From the reconstructed events, identify CONCRETE failure points. A failure
  point is created only with trace-grounded evidence. Possible kinds include
  wrong reasoning, unsupported assumption, ignored requirement, bad
  decomposition, failed tool call, poor recovery, premature termination,
  weak verification, checker rubber-stamping, refiner missing an error,
  coordination breakdown, context loss, invalid final output, cost blowup,
  unproductive loop, format violation, external/environmental failure.

  After backward identification, do ONE FORWARD SWEEP for absent-expected
  steps (e.g. planning without verification, tool call without error
  handling, multi-step problem without decomposition). Add those as failure
  points too, with the absence itself as evidence.

Stage 3 — EVIDENCE & LOCAL MECHANISM
  For each failure point, fill:
    observed_evidence (what the trace directly shows),
    inferred_mechanism (what you infer the local cause is),
    reason_observed_or_inferred ({_enum("", ["observed","inferred","mixed","unclear"])}),
    evidence_strength ({_enum("", ["low","medium","high","direct"])}),
    judge_confidence (float in [0.0, 1.0] — how sure you are the failure
    point EXISTS at all; NOT how well a label fits).

Stage 4 — BACKWARD CAUSE ANALYSIS
  For each failure point, search EARLIER in the trace for direct causes.
  When a parent exists, emit a relation with parent → child semantics
  ({_enum("relation_type", ["caused","contributed_to","enabled","amplified","masked","recovered","partially_recovered","made_irrelevant"])}).
  Only link when evidence supports it. Do not speculate.

Stage 5 — CAUSAL ROLE
  Assign EXACTLY ONE causal_role per failure point:
    root_cause                — true root cause of downstream failures
    upstream_cause            — causes other failures but is itself caused
    intermediate_cause        — both caused and causes
    downstream_symptom        — caused by upstream; not a fresh failure
    terminal_symptom          — the visible final symptom in the output
    recovered_failure         — happened but was repaired before output
    isolated_irrelevant       — real failure, did NOT contribute to task
                                failure or any other failure (low value)
    isolated_terminal_root    — the LAST upstream failure that bent the
                                rest of the run wrong; trace AFTER may
                                look clean (internally consistent) but is
                                on the wrong basis. HIGH value root.
                                REQUIRED: also fill
                                'downstream_clean_rationale' explaining
                                why downstream looked clean.
    external_condition        — environmental, not the candidate's behavior
    unclear                   — evidence does not support a confident pick

  An isolated_irrelevant call REQUIRES you to state which earlier events
  you considered as candidate parents and ruled out, in
  'ruled_out_parent_events'. Do NOT default to "isolated" — only when you
  actively looked and found nothing.

Stage 6 — RECOVERY & FINAL-PRESENCE
  For each failure point:
    recovery_status     ({_enum("", ["unrecovered","partially_recovered","fully_recovered","made_irrelevant","unclear","not_applicable"])})
    recovery_source     ({_enum("", ["same_agent","checker","refiner","arbiter","tool_result","external_feedback","later_strategy_change","none","unclear","not_applicable"])})
    present_in_final_output ({_enum("", ["yes","no","partial","unclear","not_applicable"])})

Stage 7 — RELEVANCE, SEVERITY, OUTCOME LINKAGE, ATTRIBUTION, ACTIONABILITY
    objective_relevance       ({_enum("", ["irrelevant","peripheral","subtask_relevant","main_objective_relevant","final_output_relevant"])})
    severity                  ({_enum("", ["minor","moderate","major","critical","unclear"])})
    outcome_link              ({_enum("", ["none","unlikely","possible","likely","direct","unclear"])})  Be conservative.
    candidate_attribution     ({_enum("", ["none","low","medium","high","unclear"])})  How much was this the
                              candidate/system's fault? External failure that
                              the candidate handled correctly = none/low.
                              External failure the candidate failed to
                              respond to = candidate-attributable.
    external_attribution      ({_enum("", ["none","low","medium","high","unclear"])})  Environmental fault.
    actionability             ({_enum("", ["none","low","medium","high","very_high","unclear"])})  How fixable
                              by changing the candidate's behavior.
    suggested_intervention    (short text, optional)

## OUTPUT (JSON ONLY)

{{
  "trace_summary": {{
    "task_objective": "...",
    "final_output_summary": "...",
    "score": null,
    "overall_judgment": "success | failure | partial | unknown",
    "summary": "one-paragraph what-happened"
  }},
  "events": [
    {{ "event_id": "E1", "summary": "...", "trace_location": "...",
       "stage": "planning|...|other", "agent_role": "...", "evidence": "..." }}
  ],
  "failure_points": [
    {{
      "failure_point_id": "F1",
      "event_ids": ["E2"],
      "summary": "...",
      "observed_evidence": "...",
      "inferred_mechanism": "...",
      "reason_observed_or_inferred": "observed|inferred|mixed|unclear",
      "evidence_strength": "low|medium|high|direct",
      "judge_confidence": 0.0,
      "stage": "...",
      "trace_location": "...",
      "responsible_agent": "...",
      "responsible_role": "...",
      "causal_role": "root_cause|...|unclear",
      "ruled_out_parent_events": [
        {{ "event_id": "E1", "reason": "no causal link because ..." }}
      ],
      "downstream_clean_rationale": "REQUIRED for isolated_terminal_root only",
      "recovery_status": "...",
      "recovery_source": "...",
      "present_in_final_output": "...",
      "objective_relevance": "...",
      "severity": "...",
      "outcome_link": "...",
      "candidate_attribution": "...",
      "external_attribution": "...",
      "actionability": "...",
      "suggested_intervention": "..."
    }}
  ],
  "relations": [
    {{ "source_failure_point_id": "F1", "target_failure_point_id": "F2",
       "relation_type": "caused|...|made_irrelevant", "evidence": "...",
       "confidence": 0.0 }}
  ]
}}

Constraints:
  1. Every failure point MUST have non-empty observed_evidence.
  2. Every relation MUST connect two existing failure points.
  3. Relations MUST be backward-grounded (source earlier than target).
  4. Causal role isolated_irrelevant REQUIRES non-empty
     'ruled_out_parent_events' explaining which earlier events you ruled out.
  5. Causal role isolated_terminal_root REQUIRES
     'downstream_clean_rationale'.
  6. Do NOT include taxonomy codes or 'taxonomy_mappings' in this stage.
  7. If no failure point is supported by the trace, return an empty
     'failure_points' list AND set 'trace_summary.overall_judgment' = success
     (or partial / unknown as appropriate).

Return ONLY the JSON object. No commentary.
"""


# ──────────────────────────────────────────────────────────────────────────
# Stage 8 — taxonomy mapping
# ──────────────────────────────────────────────────────────────────────────

MAPPING_SYSTEM = (
    "You are the ATLAS Reflection Judge — taxonomy mapping stage. You are "
    "given a list of FAILURE POINTS already identified from a trace, plus a "
    "failure-mode taxonomy catalog. Your job is to assign one or more "
    "taxonomy codes to each failure point.\n"
    "\n"
    "Policy:\n"
    "  * ALWAYS try to map an existing code first, even if the fit is "
    "partial. Set mapping_confidence to reflect the actual quality of the "
    "fit (0.7+ = good fit; 0.4-0.6 = stretched but plausible; <0.3 = poor).\n"
    "  * MULTIPLE codes per failure point are allowed when each describes a "
    "DIFFERENT aspect of the same failure. Mark one as 'primary' and the "
    "rest 'secondary'.\n"
    "  * The SAME code may appear on MULTIPLE failure points when the same "
    "pattern recurs in distinct locations.\n"
    "  * ONLY set unmapped=true when you cannot find ANY taxonomy code that "
    "even partially applies. You MUST then provide:\n"
    "      ruled_out_codes:  list of the 2-3 closest existing codes you "
    "considered, each with a reason for ruling it out;\n"
    "      proposed_failure_mode: {name, definition, detection_heuristics}\n"
    "    describing the uncovered pattern in taxonomy form (this becomes a "
    "signal for the refinement gate to add a new code).\n"
    "  * Return ONLY JSON in the schema described in the user prompt."
)


def mapping_user_prompt(failure_points: list, taxonomy_catalog: str) -> str:
    """Render the mapping user prompt given Stage-1 failure points + taxonomy text."""
    import json as _json
    fps_text = _json.dumps(failure_points, indent=2, ensure_ascii=False)
    return f"""\
## FAILURE POINTS (from Stage 1-7)
{fps_text}

## TAXONOMY CATALOG
{taxonomy_catalog}

## TASK
For each failure point above, assign taxonomy code(s) per the policy. Return
ONLY JSON in this shape:

{{
  "mappings_by_failure_point": [
    {{
      "failure_point_id": "F1",
      "taxonomy_mappings": [
        {{ "code": "C.3", "name": "...", "primary_or_secondary": "primary",
           "mapping_confidence": 0.0, "mapping_rationale": "why this fits" }}
      ],
      "unmapped": false,
      "ruled_out_codes": [
        {{ "code": "C.5", "reason": "why this close code does not fit" }}
      ],
      "proposed_failure_mode": null
    }}
  ]
}}

If a failure point gets mapped (unmapped=false): 'ruled_out_codes' should be
[] or omitted, and 'proposed_failure_mode' should be null.

If unmapped=true: 'taxonomy_mappings' MUST be [], 'ruled_out_codes' MUST have
>= 1 entry with code+reason, and 'proposed_failure_mode' MUST be a non-null
object with 'name', 'definition', and (optionally) 'detection_heuristics'.

Return ONLY the JSON object. No commentary.
"""


# ──────────────────────────────────────────────────────────────────────────
# Single-call mode
# ──────────────────────────────────────────────────────────────────────────

SINGLE_CALL_SYSTEM = (
    "You are the ATLAS Reflection Judge. You analyze an execution trace to "
    "identify FAILURE POINTS, build the causal graph, and then assign "
    "taxonomy codes — IN THAT ORDER. The taxonomy must NOT drive the "
    "analysis; it annotates failure points discovered from the trace itself.\n"
    "\n"
    "All principles from the analysis stage apply (backward-first + one "
    "forward sweep, evidence required, conservative downstream causality, "
    "explicit uncertainty). All policies from the mapping stage apply "
    "(prefer mapping over inventing; unmapped requires ruled_out_codes + "
    "proposed_failure_mode).\n"
    "\n"
    "Return ONLY JSON in the combined schema in the user prompt."
)


def single_call_user_prompt(judge_input: Mapping[str, Any], taxonomy_catalog: str) -> str:
    """One-shot version: analysis + mapping in one call (cost-sensitive use)."""
    analysis_part = analysis_user_prompt(judge_input)
    return f"""\
{analysis_part}

## TAXONOMY CATALOG (for Stage 8)
{taxonomy_catalog}

## ADDITIONAL OUTPUT (Stage 8 — mapping)

In each failure point, ADD the fields 'taxonomy_mappings', 'unmapped',
'ruled_out_codes' (when unmapped=true), and 'proposed_failure_mode' (when
unmapped=true) per the mapping policy:

  - ALWAYS try to map an existing code first (with appropriate
    mapping_confidence).
  - Multiple codes per failure point are allowed (mark one primary, rest
    secondary).
  - unmapped=true ONLY when no existing code even partially applies, and
    you MUST then provide ruled_out_codes (>= 1) and proposed_failure_mode
    ({{name, definition, detection_heuristics?}}).

Return ONLY the JSON object (with both analysis and mapping fields).
"""


# ──────────────────────────────────────────────────────────────────────────
# Retry prompt
# ──────────────────────────────────────────────────────────────────────────

def retry_user_prompt(previous_output_text: str, validation_errors: list[str]) -> str:
    """Brief retry: show the previous output + validator errors, ask for a
    corrected JSON. One-shot only."""
    errs = "\n".join(f"  - {e}" for e in validation_errors)
    return f"""\
Your previous JSON output failed schema validation with the following errors:

{errs}

Below is your previous output. Please return a CORRECTED JSON object that
fixes ONLY these errors. Keep the rest of the content. Return ONLY the JSON.

PREVIOUS OUTPUT:
{previous_output_text}
"""
