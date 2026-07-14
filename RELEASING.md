# Releasing ATLAS

GitHub releases are the current public distribution channel. PyPI does not yet
contain `atlas-skill`; do not advertise `pip install atlas-skill` until trusted
publishing is configured and a release has succeeded there.

## Prepare

1. Update `pyproject.toml` and move the matching `CHANGELOG.md` section out of
   `Unreleased`.
2. Run the verification bundle:

   ```bash
   python -m compileall -q atlas_runtime atlas_integration finding judge_types vendor
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
git tag -a v1.1.0b1 -m "ATLAS 1.1.0b1"
git push origin v1.1.0b1
```

The `release` workflow reruns tests and the strict documentation build, builds
the wheel and source distribution, validates both with Twine, and attaches them
to a generated GitHub release. Alpha, beta, and release-candidate tags are
marked as prereleases.

## Enable PyPI later

Use PyPI Trusted Publishing rather than a long-lived token:

1. Create the `atlas-skill` PyPI project or a pending publisher for this GitHub
   repository and the release workflow.
2. Add a protected `pypi` environment in GitHub.
3. Add a release job with `id-token: write` and
   `pypa/gh-action-pypi-publish` pinned to a reviewed release.
4. Publish a prerelease first and verify installation in a clean environment.
5. Only then change public docs to `python -m pip install atlas-skill`.
