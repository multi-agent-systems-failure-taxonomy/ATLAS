"""Allow ``python -m atlas`` to work as the CLI."""

from vendor.atlas.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
