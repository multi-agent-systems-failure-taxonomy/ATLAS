# Contributing

## Development setup

```bash
git clone https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git
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
- [atlas_integration/interactive/README.md](atlas_integration/interactive/README.md) — shared selectors, routes, jobs, and receipts
- [finding/README.md](finding/README.md) — taxonomy store, picker, and built-in MAST
- [judge_types/README.md](judge_types/README.md) — judge implementations
- [ATLAS_as_a_Judge/README.md](ATLAS_as_a_Judge/README.md) — judge evaluation checks
- [runs/README.md](runs/README.md) — reproducible experiment artifacts
- [tests/README.md](tests/README.md) — test suite map

User-facing behavior (prompts, hooks, judge specs) lives in Markdown/JSON
assets where possible; start with
[docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md) before editing Python.

Before adding behavior to a host adapter, check
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Event and transcript translation
belong in the host folder; selector, routing, browser transport, learning-job,
and receipt behavior shared by Codex and Claude Code belongs in
`atlas_integration/interactive/`.

## Documentation

- Markdown pages in [docs/](docs/) are the source of truth. The website is
  built from them with MkDocs Material ([mkdocs.yml](mkdocs.yml)) and deployed
  by [.github/workflows/docs.yml](.github/workflows/docs.yml) on pushes to
  `main`.
- Preview locally:

  ```bash
  python -m pip install -e ".[docs]"
  python -m mkdocs serve
  ```

- The canonical config reference is
  [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — other pages should show
  minimal configs and link there rather than duplicating field tables.

Release versioning, artifact checks, tags, and the future PyPI trusted-publisher
path are documented in [RELEASING.md](RELEASING.md).
