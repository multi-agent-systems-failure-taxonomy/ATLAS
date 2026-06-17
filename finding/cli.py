"""Command-line entry point for Taxonomy Finding.

Usage::

    python -m finding                       # no --inherit  -> prints "none"
    python -m finding --inherit <id>        # explicit id   -> prints that id
    python -m finding --inherit             # no id         -> web picker

Prints the resolved taxonomy_id (or "none") to stdout. On a missing
explicit id it prints a clear error to stderr and exits non-zero — never
a silent "none".
"""

from __future__ import annotations

import argparse
import sys

from . import resolver, store, webview


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finding",
        description="ATLAS Taxonomy Finding: resolve which taxonomy a run inherits.",
    )
    parser.add_argument(
        "--inherit",
        nargs="?",
        const=resolver.NO_ID,      # flag present, no value -> interactive picker
        default=resolver.ABSENT,   # flag absent            -> "none"
        metavar="taxonomy_id",
        help="Omit for none; pass a taxonomy_id to inherit it; "
             "pass with no value to open the web picker.",
    )
    parser.add_argument(
        "--store-dir",
        default=store.DEFAULT_STORE_DIR,
        help="Path to the flat taxonomy store (default: <repo>/taxonomies).",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = resolver.resolve(
            args.inherit,
            store_dir=args.store_dir,
            launcher=webview.run_webview,
        )
    except store.TaxonomyNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
