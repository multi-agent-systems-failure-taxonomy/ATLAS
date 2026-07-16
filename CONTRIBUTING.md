# Contributing

## Development setup

```bash
git clone https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git
cd AdaMAST
python -m pip install -e ".[test]"
```

Python 3.10 or newer is required.

## Verify before submitting

```bash
python -m compileall adamast_runtime adamast_integration finding judge_types vendor
python -m ruff check adamast_runtime adamast_integration finding judge_types tests
python -m pytest -q --cov=adamast_runtime --cov=adamast_integration --cov=finding --cov=judge_types --cov-report=term --cov-fail-under=78
git diff --check
```

## Where things live

Each package has a README mapping every file to its purpose:

- [adamast_runtime/README.md](adamast_runtime/README.md) — harness-neutral runtime engine
- [adamast_integration/README.md](adamast_integration/README.md) — Claude Code, Codex, and single-LLM adapters
- [adamast_integration/interactive/README.md](adamast_integration/interactive/README.md) — shared selectors, routes, jobs, and receipts
- [finding/README.md](finding/README.md) — taxonomy store, picker, and built-in MAST
- [judge_types/README.md](judge_types/README.md) — judge implementations
- [AdaMAST_as_a_Judge/README.md](AdaMAST_as_a_Judge/README.md) — judge evaluation checks
- [runs/README.md](runs/README.md) — reproducible experiment artifacts
- [tests/README.md](tests/README.md) — test suite map

User-facing behavior (prompts, hooks, judge specs) lives in Markdown/JSON
assets where possible; start with
[docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md) before editing Python.

Before adding behavior to a host adapter, check
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Event and transcript translation
belong in the host folder; selector, routing, browser transport, learning-job,
and receipt behavior shared by Codex and Claude Code belongs in
`adamast_integration/interactive/`.

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
