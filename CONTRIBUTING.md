# Contributing

## Development setup

```bash
git clone -b ATLAS_SKILL https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git
cd ATLAS
python -m pip install -e .
```

Python 3.10 or newer is required.

## Verify before submitting

```bash
python -m compileall atlas_runtime atlas_integration finding judge_types vendor
python -m pytest -q
git diff --check
```

## Where things live

Each package has a README mapping every file to its purpose:

- [atlas_runtime/README.md](atlas_runtime/README.md) — harness-neutral runtime engine
- [atlas_integration/README.md](atlas_integration/README.md) — Claude Code, Codex, and single-LLM adapters
- [finding/README.md](finding/README.md) — taxonomy store, picker, and built-in MAST
- [judge_types/README.md](judge_types/README.md) — judge implementations
- [tests/README.md](tests/README.md) — test suite map

User-facing behavior (prompts, hooks, judge specs) lives in Markdown/JSON
assets where possible; start with
[docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md) before editing Python.

## Documentation

- Markdown pages in [docs/](docs/) are the source of truth.
- [docs/index.html](docs/index.html) is the GitHub Pages landing page; when
  you change behavior, update the matching Markdown page first, then check
  whether the landing page mentions the same detail.
- The canonical config reference is
  [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — other pages should show
  minimal configs and link there rather than duplicating field tables.
