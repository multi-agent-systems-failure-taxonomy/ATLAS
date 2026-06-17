#!/usr/bin/env python
"""Local test-run harness for Taxonomy Finding.

Just a thin, friendly wrapper around the real Finding resolver so you can
exercise all three --inherit forms (including the blocking web picker) from
one script:

    python test.py                          # no --inherit  -> none
    python test.py --inherit tax-django-orm-001   # explicit id
    python test.py --inherit tax-nope-999         # missing id -> error
    python test.py --inherit                       # NO id -> opens web picker

The only difference from `python -m finding` is the banner printed around
the resolved result, so it's obvious what Finding returned.
"""

from __future__ import annotations

import argparse
import sys

from finding import resolver, store, webview


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="test.py",
        description="Test-run Taxonomy Finding (opens the web picker for bare --inherit).",
    )
    p.add_argument(
        "--inherit",
        nargs="?",
        const=resolver.NO_ID,      # --inherit with no value -> web picker
        default=resolver.ABSENT,   # --inherit absent        -> none
        metavar="taxonomy_id",
        help="Omit for none; pass an id to inherit it; pass with no value to open the picker.",
    )
    p.add_argument(
        "--store-dir",
        default=store.DEFAULT_STORE_DIR,
        help="Path to the taxonomy store (default: ./taxonomies).",
    )
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.inherit is resolver.NO_ID:
        print("Opening the taxonomy web picker... your browser should pop up.")
        print("If it doesn't, copy the http://127.0.0.1:<port>/ URL below into a browser.\n")

    try:
        result = resolver.resolve(
            args.inherit,
            store_dir=args.store_dir,
            launcher=webview.run_webview,
        )
    except store.TaxonomyNotFound as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print("(an explicit --inherit <id> that doesn't exist is an error, not a silent none)",
              file=sys.stderr)
        return 2

    print("\n" + "=" * 48)
    print(f"  Finding resolved to: {result}")
    print("=" * 48)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
