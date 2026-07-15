# Evaluation runs

This directory contains reported ATLAS evaluation summaries, the exact
taxonomies used, and reproduction notes. It does **not** contain per-example
result rows, raw scorer outputs, prompts, seeds, or complete run manifests.
Consequently, the reported numbers cannot be independently recomputed from this
repository alone; repeating the experiments also requires the external datasets,
harnesses, model access, and configuration named by each run.

| Run | Question |
|---|---|
| [`OfficeQA/`](OfficeQA/) | Does taxonomy-guided reflection improve a fixed document-QA harness? |
| [`Circle-Packing/`](Circle-Packing/) | Can failure-mode guidance make a constrained search more sample-efficient? |

These files document the claims in the root [`README.md`](../README.md); they
are not a complete reproducibility bundle. They are not runtime state and are
never loaded by an installed ATLAS integration.
