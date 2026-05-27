"""Basic end-to-end usage of ATLAS.

This walks through the common workflow:

1. Load traces from a file (auto-detected format).
2. Generate a taxonomy.
3. Save it to disk.

You need an LLM API key in the environment. By default ATLAS uses the
OpenAI SDK; set ``OPENAI_API_KEY`` and (optionally) ``OPENAI_BASE_URL``
to point at an alternate compatible endpoint.

Run::

    export OPENAI_API_KEY=sk-...
    python examples/basic_usage.py path/to/traces.jsonl
"""

from __future__ import annotations

import sys
from pathlib import Path

from atlas import generate_taxonomy


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python basic_usage.py <traces_path> [output_dir]")
        return 1

    traces_path = Path(argv[1])
    output_dir = Path(argv[2]) if len(argv) > 2 else Path("./atlas_output")

    taxonomy = generate_taxonomy(
        traces=traces_path,
        output_dir=output_dir,
        # max_codes=25,            # optional cap on total codes
        # model="claude-haiku-4-7", # optional model override
    )

    counts = taxonomy["metadata"]["counts"]
    print(f"\nDone. {counts['total']} codes "
          f"(A={counts['category_a']}, B={counts['category_b']}, C={counts['category_c']})")
    print(f"Saved to: {output_dir}/taxonomy.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
