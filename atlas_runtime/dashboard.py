"""Persistent localhost dashboard for a program's current taxonomy.

Unlike the blocking inheritance picker, this server stays alive until stopped.
The browser polls ``/api/taxonomy`` so generation and refinement transitions
appear without restarting the dashboard.
"""

from __future__ import annotations

import argparse
from importlib import resources
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from finding import mast, store

from .fsio import read_text_retry, write_text_atomic_retry
from .lineage import TaxonomyLineage
from .program import ProgramWorkspace

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DASHBOARD_STATE = ".atlas-dashboard.json"
RUNTIME_EVIDENCE = ".atlas-runtime-evidence.json"
TASK_LABELS = ".atlas-task-labels.json"
# Reflection evidence/reasoning can be very long; the dashboard only needs a
# readable preview, so each field is clipped server-side before it is sent.
EVIDENCE_PREVIEW_CHARS = 8000
_MANAGED_PROCESSES: dict[str, subprocess.Popen] = {}


def _text_asset(name: str) -> str:
    return (
        resources.files("atlas_runtime")
        .joinpath("assets", name)
        .read_text(encoding="utf-8")
    )


def _load_task_labels(root: Path) -> dict[str, Any]:
    """Optional session-id -> {label, correct} map written by a runner."""
    try:
        data = json.loads((root / TASK_LABELS).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _task_label(task_id: str, labels: dict[str, Any] | None) -> str:
    """Human label for a firing: the runner's task id + a solved marker, or a
    short prefix of the opaque session id when no map is available."""
    entry = (labels or {}).get(task_id)
    if isinstance(entry, dict) and entry.get("label"):
        correct = entry.get("correct")
        mark = " ✓" if correct is True else " ✗" if correct is False else ""
        return f"{entry['label']}{mark}"
    if isinstance(entry, str) and entry:
        return entry
    return task_id[:8] if task_id else "—"


def _clip(text: Any, limit: int = EVIDENCE_PREVIEW_CHARS) -> str:
    value = ("" if text is None else str(text)).strip()
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


def current_taxonomy(
    workspace: ProgramWorkspace,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
) -> dict[str, Any]:
    """Resolve the latest taxonomy visible to this program."""
    store_dir = Path(store_dir)
    manifest = workspace.load()
    bound_id = manifest.get("taxonomy_id")
    if not bound_id:
        record = mast.MAST
        latest_id = mast.MAST_ID
    else:
        latest_id = TaxonomyLineage(store_dir).resolve_latest(str(bound_id))
        record = store.fetch_by_id(latest_id, store_dir)

    # Runtime interaction evidence is program-local and taxonomy-version
    # scoped. It overlays the read-only taxonomy view without mutating the
    # global taxonomy record or the built-in MAST constant.
    labels = _load_task_labels(workspace.root)
    record = json.loads(json.dumps(record))
    _overlay_runtime_evidence(
        record,
        workspace.root / RUNTIME_EVIDENCE,
        latest_id,
        labels,
    )

    return {
        "program_id": manifest["program_id"],
        "taxonomy_id": latest_id,
        "bound_taxonomy_id": bound_id or mast.MAST_ID,
        "is_latest_successor": latest_id != (bound_id or mast.MAST_ID),
        "repo": (
            manifest.get("repo", "")
            if latest_id == mast.MAST_ID
            else record.get("repo", "")
        ),
        "domain": record.get("domain", ""),
        "codes": [_code_view(code, labels) for code in record["codes"]],
        "clean_checkpoints": _clean_checkpoints(
            workspace.root / RUNTIME_EVIDENCE,
            latest_id,
            labels,
        ),
    }


def _checkpoint_seq_map(
    evidence: dict[str, Any],
    taxonomy_id: str,
) -> dict[str, int]:
    """Number checkpoints for a taxonomy in chronological order."""
    ordered = sorted(
        (
            checkpoint
            for checkpoint in evidence.get("checkpoints", [])
            if isinstance(checkpoint, dict)
            and str(checkpoint.get("taxonomy_id")) == str(taxonomy_id)
        ),
        key=lambda checkpoint: checkpoint.get("timestamp") or 0,
    )
    sequence: dict[str, int] = {}
    for index, checkpoint in enumerate(ordered, 1):
        checkpoint_id = checkpoint.get("checkpoint_id")
        if checkpoint_id is not None and checkpoint_id not in sequence:
            sequence[str(checkpoint_id)] = index
    return sequence


def _overlay_runtime_evidence(
    record: dict[str, Any],
    evidence_path: Path,
    taxonomy_id: str,
    labels: dict[str, Any] | None = None,
) -> None:
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    sequence = _checkpoint_seq_map(evidence, taxonomy_id)
    codes = (
        evidence.get("taxonomies", {})
        .get(taxonomy_id, {})
        .get("codes", {})
    )
    if not isinstance(codes, dict):
        return
    for code in record.get("codes", []):
        runtime = codes.get(str(code.get("id")))
        if not isinstance(runtime, dict):
            continue
        code["fire_count"] = max(0, int(runtime.get("fire_count", 0)))
        task_firings = runtime.get("task_firings", {})
        if isinstance(task_firings, dict):
            code["task_firings"] = [
                {
                    "task_id": str(task_id),
                    "label": _task_label(str(task_id), labels),
                    "count": max(1, int(count)),
                }
                for task_id, count in sorted(task_firings.items())
            ]
        events = runtime.get("events")
        if isinstance(events, list):
            code["runtime_evidence"] = [
                {
                    "seq": sequence.get(str(event.get("checkpoint_id"))),
                    "timestamp": event.get("timestamp"),
                    "gate": event.get("gate"),
                    "task_id": event.get("task_id"),
                    "task_label": _task_label(
                        str(event.get("task_id", "")), labels
                    ),
                    "checkpoint_id": event.get("checkpoint_id"),
                    "evidence": _clip(event.get("evidence")),
                    "correlate": _clip(event.get("correlate")),
                    "decide": _clip(event.get("decide")),
                }
                for event in events
                if isinstance(event, dict)
            ]


def _clean_checkpoints(
    evidence_path: Path,
    taxonomy_id: str,
    labels: dict[str, Any] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return accepted checkpoints that did not fire a code."""
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    sequence = _checkpoint_seq_map(evidence, taxonomy_id)
    checkpoints: list[dict[str, Any]] = []
    for checkpoint in evidence.get("checkpoints", []):
        if not isinstance(checkpoint, dict):
            continue
        if str(checkpoint.get("taxonomy_id")) != str(taxonomy_id):
            continue
        if checkpoint.get("fired_codes"):
            continue
        checkpoints.append(
            {
                "seq": sequence.get(str(checkpoint.get("checkpoint_id"))),
                "timestamp": checkpoint.get("timestamp"),
                "checkpoint_id": checkpoint.get("checkpoint_id"),
                "gate": checkpoint.get("gate"),
                "task_id": checkpoint.get("task_id"),
                "task_label": _task_label(
                    str(checkpoint.get("task_id", "")),
                    labels,
                ),
                "none_apply": bool(checkpoint.get("none_apply")),
                "considered": list(checkpoint.get("considered_codes") or []),
                "observe": _clip(checkpoint.get("observe")),
                "correlate": _clip(checkpoint.get("correlate")),
                "decide": _clip(checkpoint.get("decide")),
            }
        )
    return checkpoints[-limit:]


def _code_view(
    code: dict[str, Any], labels: dict[str, Any] | None = None
) -> dict[str, Any]:
    task_firings = _task_firings(code, labels)
    fire_count = code.get("fire_count")
    if fire_count is None and task_firings:
        fire_count = sum(item["count"] for item in task_firings)
    primary = {
        "id",
        "name",
        "description",
        "fire_count",
        "task_ids",
        "task_firings",
        "runtime_evidence",
    }
    return {
        "code_id": code["id"],
        "name": code["name"],
        "description": code["description"],
        "fire_count": int(fire_count) if fire_count is not None else None,
        "task_firings": task_firings,
        "runtime_evidence": (
            code.get("runtime_evidence")
            if isinstance(code.get("runtime_evidence"), list)
            else []
        ),
        "fields": [
            {"name": str(key), "value": value}
            for key, value in code.items()
            if key not in primary
        ],
    }


def _task_firings(
    code: dict[str, Any], labels: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    raw = code.get("task_firings")
    if isinstance(raw, list):
        normalized = []
        for item in raw:
            if not isinstance(item, dict) or "task_id" not in item:
                continue
            task_id = str(item["task_id"])
            normalized.append(
                {
                    "task_id": task_id,
                    "label": item.get("label") or _task_label(task_id, labels),
                    "count": max(1, int(item.get("count", 1))),
                }
            )
        return normalized
    task_ids = code.get("task_ids")
    if isinstance(task_ids, list):
        return [
            {
                "task_id": str(task_id),
                "label": _task_label(str(task_id), labels),
                "count": 1,
            }
            for task_id in task_ids
        ]
    return []


def build_server(
    trace_output: Path | str,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    shutdown_token: str | None = None,
) -> ThreadingHTTPServer:
    """Build the persistent dashboard server without starting it."""
    workspace = ProgramWorkspace(trace_output)
    store_dir = Path(store_dir)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def _send(
            self,
            body: bytes,
            *,
            status: int = 200,
            content_type: str,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._send(
                    _PAGE.encode("utf-8"),
                    content_type="text/html; charset=utf-8",
                )
                return
            if path == "/api/taxonomy":
                try:
                    payload = current_taxonomy(workspace, store_dir)
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    self._send(
                        body,
                        content_type="application/json; charset=utf-8",
                    )
                except Exception as exc:
                    body = json.dumps(
                        {"error": str(exc)}, ensure_ascii=False
                    ).encode("utf-8")
                    self._send(
                        body,
                        status=500,
                        content_type="application/json; charset=utf-8",
                    )
                return
            if path == "/api/health":
                body = json.dumps(
                    {
                        "program_id": workspace.program_id,
                        "status": "ok",
                    }
                ).encode("utf-8")
                self._send(
                    body,
                    content_type="application/json; charset=utf-8",
                )
                return
            self._send(
                b'{"error":"not found"}',
                status=404,
                content_type="application/json; charset=utf-8",
            )

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path != "/api/shutdown" or shutdown_token is None:
                self._send(
                    b'{"error":"not found"}',
                    status=404,
                    content_type="application/json; charset=utf-8",
                )
                return
            if self.headers.get("X-ATLAS-Token") != shutdown_token:
                self._send(
                    b'{"error":"forbidden"}',
                    status=403,
                    content_type="application/json; charset=utf-8",
                )
                return
            self._send(
                b'{"status":"stopping"}',
                content_type="application/json; charset=utf-8",
            )
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    return ThreadingHTTPServer((host, port), Handler)


def run_dashboard(
    trace_output: Path | str,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    open_browser: bool = True,
    on_serving=None,
) -> None:
    """Serve until interrupted; taxonomy changes are picked up live."""
    server = build_server(trace_output, store_dir, host, port)
    actual_port = int(server.server_address[1])
    url = f"http://{host}:{actual_port}/"
    if on_serving is not None:
        on_serving(host, actual_port)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"WARNING: dashboard is binding to {host!r} and serves trace and "
            "evidence text UNAUTHENTICATED. Do not expose it beyond localhost "
            "without an external authentication layer.",
            file=sys.stderr,
        )
    print(f"ATLAS taxonomy dashboard: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def start_dashboard_thread(
    trace_output: Path | str,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
    host: str = DEFAULT_HOST,
    port: int = 0,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start a daemon dashboard for embedding and tests."""
    server = build_server(trace_output, store_dir, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def ensure_dashboard(
    workspace: ProgramWorkspace,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
    *,
    timeout: float = 5.0,
) -> str | None:
    """Start or reuse one managed dashboard process for this program."""
    if os.environ.get("ATLAS_DISABLE_DASHBOARD", "").lower() in {
        "1", "true", "yes",
    }:
        return None
    state_path = workspace.root / DASHBOARD_STATE
    with _dashboard_lock(workspace.root):
        state = _read_state(state_path)
        if state and _dashboard_is_live(state, workspace.program_id):
            return str(state["url"])
        state_path.unlink(missing_ok=True)
        token = secrets.token_urlsafe(24)
        command = [
            sys.executable,
            "-m",
            "atlas_runtime.dashboard",
            "--trace-output",
            str(workspace.root),
            "--store-dir",
            str(Path(store_dir)),
            "--port",
            "0",
            "--no-browser",
            "--managed-token",
            token,
            "--state-file",
            str(state_path),
        ]
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "cwd": str(Path(__file__).resolve().parent.parent),
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
        _MANAGED_PROCESSES[str(state_path)] = process
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = _read_state(state_path)
            if state and _dashboard_is_live(state, workspace.program_id):
                return str(state["url"])
            time.sleep(0.05)
    return None


def stop_dashboard_if_idle(workspace: ProgramWorkspace) -> bool:
    """Stop the managed dashboard once no task or learning job remains."""
    manifest = workspace.load()
    if manifest.get("active_sessions"):
        return False
    if manifest.get("generation", {}).get("state") == "running":
        return False
    if manifest.get("refinement", {}).get("state") == "running":
        return False
    return stop_dashboard(workspace)


def stop_dashboard(workspace: ProgramWorkspace, *, timeout: float = 3.0) -> bool:
    state_path = workspace.root / DASHBOARD_STATE
    with _dashboard_lock(workspace.root):
        state = _read_state(state_path)
        if not state:
            return False
        try:
            request = Request(
                str(state["shutdown_url"]),
                method="POST",
                headers={"X-ATLAS-Token": str(state["token"])},
            )
            with urlopen(request, timeout=timeout):
                pass
        except Exception:
            pass
        process = _MANAGED_PROCESSES.pop(str(state_path), None)
        if process is not None:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
        state_path.unlink(missing_ok=True)
        return True


def _dashboard_is_live(state: dict[str, Any], program_id: str) -> bool:
    try:
        with urlopen(str(state["health_url"]), timeout=0.5) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("program_id") == program_id and data.get("status") == "ok"
    except Exception:
        return False


def _read_state(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(read_text_retry(path))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


class _dashboard_lock:
    def __init__(self, root: Path):
        self.path = root / ".dashboard.lock"

    def __enter__(self):
        deadline = time.monotonic() + 5
        while True:
            try:
                self.path.mkdir()
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out waiting for dashboard lock")
                time.sleep(0.05)

    def __exit__(self, *_args):
        try:
            self.path.rmdir()
        except FileNotFoundError:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Keep a live local view of one program's current taxonomy."
    )
    parser.add_argument("--trace-output", "--trace_output", required=True)
    parser.add_argument("--store-dir", default=store.DEFAULT_STORE_DIR)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--managed-token")
    parser.add_argument("--state-file")
    args = parser.parse_args(argv)
    if args.managed_token:
        server = build_server(
            args.trace_output,
            args.store_dir,
            args.host,
            args.port,
            shutdown_token=args.managed_token,
        )
        actual_port = int(server.server_address[1])
        url = f"http://{args.host}:{actual_port}/"
        if not args.state_file:
            parser.error("--state-file is required with --managed-token")
        state_path = Path(args.state_file)
        write_text_atomic_retry(
            state_path,
            json.dumps(
                {
                    "pid": os.getpid(),
                    "url": url,
                    "health_url": f"{url}api/health",
                    "shutdown_url": f"{url}api/shutdown",
                    "token": args.managed_token,
                },
                indent=2,
            ) + "\n",
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
            state_path.unlink(missing_ok=True)
        return 0
    run_dashboard(
        args.trace_output,
        args.store_dir,
        args.host,
        args.port,
        open_browser=not args.no_browser,
    )
    return 0


_PAGE = _text_asset("dashboard.html")


if __name__ == "__main__":
    raise SystemExit(main())
