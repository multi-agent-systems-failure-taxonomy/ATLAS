# ATLAS as a judge

This directory owns evaluation-only checks for using an ATLAS taxonomy to
classify completed agent traces. It is separate from the production runtime:
the tests exercise scoring and evidence behavior without becoming an import
dependency of `atlas_runtime` or any host integration.

## Contents

| Path | Purpose |
|---|---|
| [`tests/`](tests/) | Judge-oriented regression and evaluation tests |

Run this surface from the repository root with:

```bash
python -m pytest ATLAS_as_a_Judge/tests -q
```
