# Releasing AdaMAST

Releases publish to GitHub and to PyPI as `adamast` through Trusted
Publishing. The pending publisher was claimed by the v0.1.0 release and the
public docs advertise `pip install adamast`.

## Prepare

1. Update `pyproject.toml` and move the matching `CHANGELOG.md` section out of
   `Unreleased`.
2. Run the verification bundle:

   ```bash
   python -m compileall -q adamast_runtime adamast_integration finding judge_types vendor
   python -m pytest -q
   python -m mkdocs build --strict
   python -m build
   python -m twine check dist/*
   git diff --check
   ```

3. Merge the reviewed release commit to `main` and confirm the `ci` and `docs`
   workflows pass.

## Publish a GitHub release

Create and push a tag that exactly matches the package version:

```bash
git tag -a v0.1.0 -m "AdaMAST 0.1.0"
git push origin v0.1.0
```

The `release` workflow reruns tests and the strict documentation build, builds
the wheel and source distribution, validates both with Twine, attaches them to
a generated GitHub release, and then publishes to PyPI through the
`pypi-publish` job (Trusted Publishing, no stored token). Alpha, beta, and
release-candidate tags are marked as prereleases.

## PyPI Trusted Publishing (one-time setup)

The `pypi-publish` job authenticates with an OIDC id-token; PyPI must be told
to trust this repository first:

1. On pypi.org → Account → Publishing, add a **pending publisher** for the
   project name `adamast` with owner `multi-agent-systems-failure-taxonomy`,
   repository `ATLAS`, workflow `release.yml`, and environment `pypi`.
2. Optionally protect the `pypi` environment in the GitHub repository
   settings (it is created automatically on the first run otherwise).
3. Push a version tag; the first successful publish claims the `adamast`
   name. Verify `python -m pip install adamast` in a clean environment.
4. Only then change public docs to `python -m pip install adamast`.
5. If the repository is later migrated (e.g. to the `AdaMAST` repo), update
   the trusted publisher's repository field on pypi.org to match.
