"""Launch a disposable taxonomy dashboard populated with placeholder evidence.

Run from the repository root:

    python -m examples.dashboard_demo

The temporary program and taxonomy store disappear when the server stops.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from atlas_runtime.dashboard import run_dashboard
from atlas_runtime.program import ProgramWorkspace
from finding import store

DEMO_TAXONOMY_ID = "tax-skylab-orbital-demo-001"

DEMO_TAXONOMY = {
    "taxonomy_id": DEMO_TAXONOMY_ID,
    "repo": "demo/skylab-control",
    "domain": "orbital-task-scheduling",
    "codes": [
        {
            "id": "ORB-01",
            "name": "Stale ephemeris used for scheduling",
            "description": (
                "A task window is computed from cached orbital data after a "
                "new ephemeris has arrived, placing the operation outside its "
                "valid visibility interval."
            ),
            "severity": "high",
            "fire_count": 7,
            "task_firings": [
                {"task_id": "TASK-1042", "count": 3},
                {"task_id": "TASK-1061", "count": 1},
                {"task_id": "TASK-1098", "count": 2},
                {"task_id": "TASK-1120", "count": 1},
            ],
        },
        {
            "id": "ORB-02",
            "name": "Resource lock released before handoff",
            "description": (
                "Exclusive antenna or compute capacity is released before the "
                "downstream task confirms ownership, allowing overlapping "
                "operations to claim the same resource."
            ),
            "severity": "critical",
            "fire_count": 4,
            "task_firings": [
                {"task_id": "TASK-1033", "count": 1},
                {"task_id": "TASK-1087", "count": 2},
                {"task_id": "TASK-1120", "count": 1},
            ],
        },
        {
            "id": "ORB-03",
            "name": "Retry duplicates a completed command",
            "description": (
                "A timeout is treated as proof that the remote command failed, "
                "so the scheduler repeats an operation that actually completed."
            ),
            "severity": "medium",
            "fire_count": 2,
            "task_firings": [
                {"task_id": "TASK-1074", "count": 1},
                {"task_id": "TASK-1135", "count": 1},
            ],
        },
        {
            "id": "ORB-04",
            "name": "Clock offset omitted at a boundary",
            "description": (
                "One scheduling boundary uses local station time while the "
                "rest of the plan uses UTC, shifting a narrow operation window."
            ),
            "severity": "high",
            "fire_count": 5,
            "task_firings": [
                {"task_id": "TASK-1019", "count": 2},
                {"task_id": "TASK-1055", "count": 1},
                {"task_id": "TASK-1114", "count": 2},
            ],
        },
        {
            "id": "ORB-05",
            "name": "Validation covers the plan but not execution",
            "description": (
                "The generated schedule is validated before dispatch, but the "
                "mutated execution payload is never checked against the same "
                "constraints."
            ),
            "severity": "medium",
            "fire_count": 0,
            "task_firings": [],
        },
    ],
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Open a disposable ATLAS dashboard with placeholder metrics."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="atlas-dashboard-demo-") as td:
        root = Path(td)
        store_dir = root / "taxonomies"
        program_dir = root / "program"
        store.register(DEMO_TAXONOMY, store_dir)
        ProgramWorkspace(program_dir).bind_inherited_taxonomy(DEMO_TAXONOMY_ID)

        print("Loading disposable demo data.")
        print("Counts and task IDs are placeholders for layout review only.")
        print("Press Ctrl+C to stop the dashboard and remove the demo data.")
        run_dashboard(
            program_dir,
            store_dir,
            args.host,
            args.port,
            open_browser=not args.no_browser,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
