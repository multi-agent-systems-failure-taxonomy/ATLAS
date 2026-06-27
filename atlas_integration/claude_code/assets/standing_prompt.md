ATLAS runtime interaction is active for this session.

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
