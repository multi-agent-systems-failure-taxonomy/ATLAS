"""Standing and gate-specific prompts for Claude Code."""

from __future__ import annotations

from typing import Any

STANDING_PROMPT = """ATLAS runtime interaction is active for this session.

Do not ask for or load the taxonomy at task start. Continue normal work.
After completing a sub-task or a major part of the task, request an ATLAS
checkpoint by ending that segment with:

`ATLAS checkpoint request: <one-sentence segment summary>`

Claude Code task completions, subagent completions, observable tool failures,
and final completion can also trigger ATLAS automatically. At a trigger, the
active taxonomy will be injected. Analyze only activity since the previous
ATLAS checkpoint. Diagnose it in third person, then remember it is your own
execution and change course only when necessary. A well-supported “none apply”
is fully valid; never manufacture a change.
"""


def reflection_prompt(
    state: dict[str, Any],
    *,
    checkpoint_id: str,
    gate_label: str,
    recent_activity: str,
    full: bool,
    repair_attempts_used: int = 0,
) -> str:
    codes = "\n".join(
        f"- {code['id']} — {code['name']}: {code['description']}"
        for code in state["taxonomy"]["codes"]
    )
    scope = "the full task trajectory" if full else (
        "only the recent activity since the previous ATLAS checkpoint"
    )
    gate_tail = (
        f"""

Your earlier task answer is PROVISIONAL. It has not been released or scored.
This Stop hook exists so you can still repair the work before submission.

If Decide says `change:`:
1. emit `Final ATLAS status: REPAIR_REQUIRED`;
2. set `Final decision: repair`;
3. after this hook blocks, perform the change and verify it;
4. then provide a corrected `<FINAL_ANSWER>` and run the reflection again.

Never say the answer was already submitted, never treat this as a post-hoc
audit, and never use statuses such as PASS, conditional pass, complete, or
accept with caveat.

If no change is needed, emit `Final ATLAS status: READY_TO_SUBMIT` and
`Final decision: submit`.

After the reflection, emit exactly these five plain-text fields:
- `Final ATLAS status:` READY_TO_SUBMIT or REPAIR_REQUIRED
- `Codes checked:` <codes or none>
- `Evidence:` <concrete evidence>
- `Repair attempts used:` {repair_attempts_used}
- `Final decision:` submit or repair

The hook owns this counter. Emit exactly
`Repair attempts used: {repair_attempts_used}` for this checkpoint.
"""
        if full else ""
    )
    return f"""ATLAS {gate_label} — reflection required before this boundary can pass.

Checkpoint ID: {checkpoint_id}
Active taxonomy: {state['taxonomy_id']}

Failure modes to consider:
{codes}

Scope: {scope}.

Recent trajectory excerpt:
--- begin recent activity ---
{recent_activity[-12000:] or "(no transcript text was available; use the activity in context)"}
--- end recent activity ---

Emit this structured block:

ATLAS reflection:
- Checkpoint ID: {checkpoint_id}
- Observe: assess the scoped execution trace as a neutral third-person reviewer.
- Map:
  - `<CODE> | exhibited | evidence: "<verbatim trace fact>"`
  - or `none apply | considered: <CODE,...> | evidence: "<why the trace is clean>"`
- Correlate: explain whether each apparent match truly constitutes that failure.
- Decide: switch to first person and write exactly one of:
  - `change: <one focused change>`
  - `no change needed, because <reason>`

The Map must name at least one code and contain evidence. Do not force a
failure or a change merely to satisfy the checkpoint.{gate_tail}
"""


def failure_nudge(
    state: dict[str, Any],
    *,
    checkpoint_id: str,
    failure_summary: str,
) -> str:
    return reflection_prompt(
        state,
        checkpoint_id=checkpoint_id,
        gate_label="reactive failure nudge (advisory; non-blocking)",
        recent_activity=failure_summary,
        full=False,
    )
