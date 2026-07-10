# Vendored ATLAS

This directory contains a faithful copy of the `atlas` Python package from:

- Source: https://github.com/multi-agent-systems-failure-taxonomy/ATLAS
- Commit: `85efae436daf5a4c8299ff7e9a46a6717cb0a3bd`
- Upstream package version: `1.0.0`
- License: Apache License 2.0; see `LICENSE` in this directory.

The vendored source is intentionally distinct from atlas_skill-owned runtime code.

## Local import-path adjustment

The upstream package uses absolute imports beginning with `atlas`. Those imports
were changed mechanically to begin with `vendor.atlas` so this copy is importable
under its local namespace and does not depend on, or shadow, an externally
installed `atlas` package. No other vendored pipeline logic was changed.
