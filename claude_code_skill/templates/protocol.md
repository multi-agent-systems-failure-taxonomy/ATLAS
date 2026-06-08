## ATLAS checkpoint protocol

Use the failure-mode taxonomy above at meaningful checkpoints — not after every small edit.

The full taxonomy is available above. Treat it as a diagnostic reference. Do not assume every code applies. A code is relevant only when the current task state, trace, tool output, or verification evidence matches it. Do not force a finding — if no code clearly applies, say so and proceed.

### Major segment checkpoints

Re-check the taxonomy only after meaningful work segments:

- after investigation, before patching;
- after a substantive patch, before verification;
- after a failed test or tool error changes your direction;
- after switching root-cause hypothesis;
- during any existing self-verification loop;
- before final submission.

At each checkpoint, write a compact check (four lines, plain text):

- `Checkpoint:` <type>
- `Relevant codes:` <codes from the taxonomy, or "none clearly applies">
- `Evidence:` <tool output / trace fact / reason>
- `Next action:` <what you will do next>

Keep this compact. Do not interrupt every minor edit. The protocol is the contract for *meaningful segments*, not a per-call audit.

### Final submission gate

Before returning the final answer or marking the task complete, you MUST run a final check against the full taxonomy and the workflow checklist above.

Return one of:

- `READY_TO_SUBMIT` — no unresolved taxonomy-relevant issue or checklist violation remains.
- `REPAIR_REQUIRED` — one or more issues remain.

If `REPAIR_REQUIRED`, do NOT submit. Choose the highest-impact unresolved issue, perform one focused repair attempt, run the relevant verification command (or explain why it cannot be run), and re-run the final check. You may perform at most {max_retries} final-gate repair attempts.

If after {max_retries} repair attempts issues remain, stop repairing. Do NOT claim clean success. Report:

- what remains unresolved (which codes, which checklist items);
- what was tried in each attempt;
- what evidence supports or contradicts each unresolved issue;
- what the user should know before trusting the result.

Final-gate output format (always include all five fields):

- `Final ATLAS status:` READY_TO_SUBMIT or REPAIR_REQUIRED
- `Codes checked:` <relevant codes from the taxonomy>
- `Evidence:` <tests / tool output / trace facts>
- `Repair attempts used:` <0-{max_retries}>
- `Final decision:` <submit / repair / report unresolved>
