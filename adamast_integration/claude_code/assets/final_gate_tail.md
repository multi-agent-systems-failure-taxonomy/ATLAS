

Your earlier task answer is PROVISIONAL. It has not been released or scored.
This Stop hook exists so you can still repair the work before submission.

If Decide says `change:`:
1. emit `Final AdaMAST status: REPAIR_REQUIRED`;
2. set `Final decision: repair`;
3. after this hook blocks, first run the check that indicts the current
   answer, with its execution and output visible in your work — if the check
   passes, keep the original answer and report READY_TO_SUBMIT at the next
   gate;
4. if the check fails, repair exactly what it exposed, verify the repair,
   then provide a corrected `<FINAL_ANSWER>` and run the reflection again.

Never say the answer was already submitted, never treat this as a post-hoc
audit, and never use statuses such as PASS, conditional pass, complete, or
accept with caveat.

If no change is needed, emit `Final AdaMAST status: READY_TO_SUBMIT` and
`Final decision: submit`.

After the reflection, emit exactly these five plain-text fields:
- `Final AdaMAST status:` READY_TO_SUBMIT or REPAIR_REQUIRED
- `Codes checked:` <codes or none>
- `Evidence:` <concrete evidence>
- `Repair attempts used:` $repair_attempts_used
- `Final decision:` submit or repair

The hook owns this counter. Emit exactly
`Repair attempts used: $repair_attempts_used` for this checkpoint.
