"""Classify a new trace against a previously-generated taxonomy.

Run::

    python examples/classify_example.py path/to/taxonomy.json path/to/trace.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from atlas import classify_trace, load_traces


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("Usage: python classify_example.py <taxonomy.json> <trace_file>")
        return 1

    taxonomy_path = Path(argv[1])
    trace_path = Path(argv[2])

    # The loader handles any supported trace format, even if the file
    # contains just one trace.
    traces = load_traces(trace_path, verbose=False)
    if not traces:
        print(f"Could not load any traces from {trace_path}")
        return 1

    diagnosis = classify_trace(taxonomy_path, traces[0])
    if diagnosis is None:
        print("Classification failed (LLM returned no usable output).")
        return 1

    print(json.dumps(diagnosis.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
