---
name: atlas-failure-modes
description: Use ATLAS runtime checkpoints to diagnose an agent trajectory against the active failure-mode taxonomy, make repairs only when evidence warrants them, and complete the required final submission gate.
---

# ATLAS runtime behavior

Follow checkpoint instructions emitted by the active ATLAS integration.

- After completing a sub-task or major task segment, request an ATLAS checkpoint when the integration supports it.
- At a checkpoint, inspect only the trajectory since the previous checkpoint.
- Follow the emitted reflection order: Observe concrete failure points or missing expected steps, Correlate supported causes, Map to taxonomy codes only after that, then Decide.
- In Decide, recognize that the trajectory is yours, make one focused change if evidence warrants it, or explain why no change is needed.
- Treat `none apply` as valid. Do not invent a failure or force an edit.
- Complete the final ATLAS submission gate before declaring the task finished.

The active taxonomy is intentionally not embedded here. The runtime supplies the relevant taxonomy content when a checkpoint fires.
