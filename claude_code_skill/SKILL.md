---
name: mast-failure-modes
description: When working on a software-engineering task with tests to pass — bug fixes, patch submission, multi-step debugging on a real codebase — consult this list of common multi-agent system (MAST) failure modes before submitting your final patch. Applies to SWE-bench-style tasks where you must read an issue, navigate code, make targeted edits, and submit a diff for hidden-test evaluation.
---

# MAST failure-mode checklist

This skill lists 14 cross-cutting failure modes observed across multi-agent LLM systems on software-engineering and reasoning tasks (Cemri et al., 2025). Before declaring a task complete and submitting your final diff, work through each mode and ask: *"Could my current trajectory exhibit this?"* Take corrective action before submitting if any apply.

## Specification failures

- **MAST-1: Disobedient to task specification.** AVOID deviating from what the issue actually asks for. DO re-read the issue text just before submitting; confirm your patch addresses the specific reported behavior, not an adjacent problem you noticed along the way.

- **MAST-2: Disobedient to role specification.** AVOID drifting from a software-engineering bug-fix task into refactoring, optimization, or unrelated improvements. DO stay scoped to the minimum change required to satisfy the issue and its hidden tests.

- **MAST-3: Step repetition.** AVOID repeating identical or near-identical actions (re-running the same grep, re-reading the same file, re-attempting an already-failed approach) without new information. DO break out of repeated patterns by changing approach: try a different file, a different search term, a different hypothesis.

- **MAST-4: Loss of conversation history.** AVOID forgetting facts established earlier in the trajectory (e.g., where the relevant code lives, what the gold behavior should be). DO refer back to your own earlier observations before acting; restate key facts inline when in doubt.

- **MAST-5: Unaware of termination conditions.** AVOID submitting without a clear signal you're done. DO define your termination criterion explicitly: "I will submit when the targeted file is patched AND the patch addresses the specific symptom in the issue AND I have no remaining hypotheses to test."

## Coordination failures

- **MAST-6: Conversation reset.** AVOID losing the thread of what you were working on after an error or tool failure. DO reorient briefly after errors: state where you were, what failed, what you'll do next.

- **MAST-7: Failure to ask for clarification.** AVOID pressing forward on ambiguous task specifications by guessing. DO state your interpretation of an ambiguity inline and proceed with it — but flag the assumption so you can revise if evidence contradicts it later.

- **MAST-8: Task derailment.** AVOID following interesting tangents (a tempting unrelated bug, a code-quality improvement, an architectural concern) at the expense of the original task. DO note the tangent for later and return to the original.

- **MAST-9: Information withholding.** AVOID making decisions based on facts you've discovered but haven't surfaced in your own trajectory text. DO write down what you found before acting on it; future-you (and the verification step) needs to see your reasoning.

- **MAST-10: Ignored other agent's input.** AVOID dismissing the output of tools you've called (test results, file contents, error messages) when they contradict your plan. DO update your plan when tool output disagrees with your model of the code.

## Verification failures

- **MAST-11: Premature termination.** AVOID submitting a patch before you've confirmed it addresses the issue's symptoms. DO at least mentally trace through the patch: "given my edit, when the failing scenario in the issue runs, what changes?"

- **MAST-12: No or incomplete verification.** AVOID assuming a patch works because it compiles or because the model output looks plausible. DO seek concrete evidence: re-read the issue's reproducer, walk through the changed code path mentally, check whether other call sites would be affected.

- **MAST-13: Weak verification.** AVOID accepting trivial evidence as proof (e.g., "the file now exists," "the import worked"). DO ask whether the verification you ran would actually catch a wrong fix: does it exercise the path the issue describes?

- **MAST-14: Incorrect verification.** AVOID running the wrong tests, checking the wrong file, or misreading test output. DO double-check what you're verifying: the right file, the right symptom, with output you've actually parsed correctly.

## Workflow

Apply this checklist as a pre-submission gate. Before your final patch submission:

1. Re-read the original issue text in full
2. Confirm your patch addresses the issue's specific symptom (MAST-1, MAST-2)
3. Confirm your patch is scoped to the minimal required change (MAST-2, MAST-8)
4. Confirm you haven't lost track of earlier findings (MAST-4, MAST-9)
5. Confirm your verification, if any, actually exercises the failing path (MAST-12, MAST-13, MAST-14)
6. Confirm there's no remaining hypothesis worth testing before submission (MAST-5, MAST-11)

If any check fails, revise before submitting.

---

_Reference: Cemri et al. (2025), "Why Do Multi-Agent LLM Systems Fail?", arXiv:2503.13657. MAST is a hand-curated 14-code taxonomy designed to apply universally across multi-agent LLM systems, independent of any specific benchmark or system. Used here as the FLOOR taxonomy: this is what the skill ships with before any in-conversation induction. Once enough traces accumulate, the live taxonomy switches to an induced one and this body is replaced via the render step._

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

If `REPAIR_REQUIRED`, do NOT submit. Choose the highest-impact unresolved issue, perform one focused repair attempt, run the relevant verification command (or explain why it cannot be run), and re-run the final check. You may perform at most 3 final-gate repair attempts.

If after 3 repair attempts issues remain, stop repairing. Do NOT claim clean success. Report:

- what remains unresolved (which codes, which checklist items);
- what was tried in each attempt;
- what evidence supports or contradicts each unresolved issue;
- what the user should know before trusting the result.

Final-gate output format (always include all five fields):

- `Final ATLAS status:` READY_TO_SUBMIT or REPAIR_REQUIRED
- `Codes checked:` <relevant codes from the taxonomy>
- `Evidence:` <tests / tool output / trace facts>
- `Repair attempts used:` <0-3>
- `Final decision:` <submit / repair / report unresolved>
