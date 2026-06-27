

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
- `Repair attempts used:` $repair_attempts_used
- `Final decision:` submit or repair

The hook owns this counter. Emit exactly
`Repair attempts used: $repair_attempts_used` for this checkpoint.
