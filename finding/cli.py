"""Command-line entry point for Taxonomy Finding.

Usage::

    python -m finding                       # no --inherit  -> prints "none"
    python -m finding --inherit <id>        # explicit id   -> prints that id
    python -m finding --inherit             # no id         -> web picker
    python -m finding --list                # list stored taxonomies (id, repo, domain)

Prints the resolved taxonomy_id (or "none") to stdout. On a missing
explicit id it prints a clear error to stderr and exits non-zero — never
a silent "none".

``--list`` is a separate mode: it ignores ``--inherit`` and instead prints
one line per stored record in the store directory.
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
        "--list",
        action="store_true",
        help="List every taxonomy stored under --store-dir "
             "(taxonomy_id, repo, domain — one per line). Skips --inherit.",
    )
    parser.add_argument(
        "--store-dir",
        default=store.DEFAULT_STORE_DIR,
        help=f"Path to the flat taxonomy store (default: {store.DEFAULT_STORE_DIR}).",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        records = store.list_all(args.store_dir)
        if not records:
            print(f"(no taxonomies in {args.store_dir})")
            return 0
        width = max(len(r["taxonomy_id"]) for r in records)
        for rec in sorted(records, key=lambda r: r["taxonomy_id"]):
            tid = rec["taxonomy_id"].ljust(width)
            print(f"{tid}  {rec.get('repo','')!s:30s}  {rec.get('domain','')}")
        return 0
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
