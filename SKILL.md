---
name: atlas-failure-modes
description: Use ATLAS runtime checkpoints to diagnose an agent trajectory against the active failure-mode taxonomy, make repairs only when evidence warrants them, and complete the required final submission gate.
---

# ATLAS runtime behavior

Follow checkpoint instructions emitted by the active ATLAS integration.

- After completing a sub-task or major task segment, request an ATLAS checkpoint when the integration supports it.
- At a checkpoint, inspect only the trajectory since the previous checkpoint.
- First analyze the trajectory from a third-person perspective and map supported failure-mode codes with concrete evidence.
- Then recognize that the trajectory is yours, decide whether a change is necessary, and change course only when the evidence warrants it.
- Treat `none apply` as valid. Do not invent a failure or force an edit.
- Complete the final ATLAS submission gate before declaring the task finished.

The active taxonomy is intentionally not embedded here. The runtime supplies the relevant taxonomy content when a checkpoint fires.
