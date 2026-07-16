"""Allow ``python -m adamast`` to work as the CLI."""

from vendor.adamast.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
