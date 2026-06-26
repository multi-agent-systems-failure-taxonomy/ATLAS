"""Persistent localhost dashboard for a program's current taxonomy.

Unlike the blocking inheritance picker, this server stays alive until stopped.
The browser polls ``/api/taxonomy`` so generation and refinement transitions
appear without restarting the dashboard.
"""

from __future__ import annotations

import argparse
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
        data = json.loads(path.read_text(encoding="utf-8"))
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
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(
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
            encoding="utf-8",
        )
        os.replace(temporary, state_path)
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


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ATLAS taxonomy field manual</title>
  <style>
    :root {
      --ink: #172033;
      --muted: #667085;
      --paper: #edf2f7;
      --panel: #f9fbfd;
      --line: #cbd5e1;
      --cobalt: #2457d6;
      --amber: #e8a317;
      --error: #b42318;
      --shadow: 0 18px 60px rgba(23, 32, 51, .12);
    }
    * { box-sizing: border-box; }
    html { background: var(--paper); color: var(--ink); }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", "Aptos", sans-serif;
      background:
        linear-gradient(rgba(36,87,214,.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(36,87,214,.045) 1px, transparent 1px),
        var(--paper);
      background-size: 24px 24px;
    }
    button, input { font: inherit; }
    button:focus-visible, input:focus-visible, summary:focus-visible {
      outline: 3px solid rgba(36,87,214,.35);
      outline-offset: 3px;
    }
    .shell { width: min(1180px, calc(100% - 32px)); margin: 32px auto 72px; }
    .masthead {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 24px;
      align-items: end;
      padding: 30px 32px 26px;
      background: var(--ink);
      color: white;
      box-shadow: var(--shadow);
      border-top: 5px solid var(--amber);
    }
    .eyebrow, .utility, .code-id, .status {
      font-family: Consolas, "SFMono-Regular", monospace;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .eyebrow { color: #aabef7; font-size: .72rem; margin-bottom: 10px; }
    h1 {
      font-family: "Arial Narrow", "Aptos Display", sans-serif;
      font-stretch: condensed;
      font-size: clamp(2rem, 5vw, 4.2rem);
      line-height: .95;
      letter-spacing: -.035em;
      margin: 0;
      max-width: 800px;
    }
    .status {
      display: inline-flex;
      gap: 9px;
      align-items: center;
      font-size: .7rem;
      color: #d8e1ff;
      white-space: nowrap;
    }
    .status::before {
      content: "";
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #6ee7a8;
      box-shadow: 0 0 0 5px rgba(110,231,168,.14);
    }
    .meta {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      background: var(--panel);
      border: 1px solid var(--line);
      border-top: 0;
    }
    .meta-item { padding: 18px 22px; border-right: 1px solid var(--line); }
    .meta-item:last-child { border-right: 0; }
    .meta-label { color: var(--muted); font-size: .72rem; margin-bottom: 5px; }
    .meta-value {
      font-family: Consolas, "SFMono-Regular", monospace;
      font-size: .88rem;
      overflow-wrap: anywhere;
    }
    .toolbar {
      display: flex;
      gap: 12px;
      align-items: center;
      margin: 28px 0 18px;
    }
    .search {
      flex: 1;
      min-width: 0;
      border: 1px solid #aebdcd;
      background: rgba(255,255,255,.84);
      color: var(--ink);
      padding: 12px 14px;
      border-radius: 2px;
    }
    .tool-button {
      border: 1px solid var(--ink);
      background: transparent;
      color: var(--ink);
      padding: 11px 14px;
      cursor: pointer;
    }
    .tool-button:hover { background: var(--ink); color: white; }
    .count {
      margin-left: auto;
      color: var(--muted);
      font-size: .82rem;
      white-space: nowrap;
    }
    .codes { display: grid; gap: 12px; }
    .clean-panel {
      margin: 0 0 18px;
      border: 1px solid var(--line);
      background: rgba(249,251,253,.94);
      box-shadow: 0 5px 20px rgba(23,32,51,.05);
    }
    .clean-panel summary {
      padding: 18px 56px 18px 22px;
      font-family: Consolas, "SFMono-Regular", monospace;
      font-size: .8rem;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: #344054;
    }
    .clean-list {
      display: grid;
      gap: 10px;
      padding: 0 22px 20px;
    }
    .clean-item {
      border-left: 4px solid #98a2b3;
      background: white;
      padding: 12px 14px;
      line-height: 1.45;
    }
    .clean-meta {
      color: var(--muted);
      font: .7rem/1.3 Consolas, monospace;
      margin-bottom: 6px;
    }
    .clean-tag {
      display: inline-block;
      margin-right: 8px;
      padding: 2px 6px;
      background: #e8eefc;
      color: var(--cobalt);
      font: .68rem/1.3 Consolas, monospace;
      text-transform: uppercase;
    }
    .code-card {
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      background: rgba(249,251,253,.94);
      border: 1px solid var(--line);
      box-shadow: 0 5px 20px rgba(23,32,51,.05);
    }
    .code-rail {
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 116px;
      background: var(--cobalt);
      color: white;
      border-bottom: 5px solid var(--amber);
    }
    .code-id {
      writing-mode: vertical-rl;
      transform: rotate(180deg);
      font-size: .78rem;
      font-weight: 700;
    }
    details { padding: 0 24px; }
    summary {
      cursor: pointer;
      list-style: none;
      padding: 25px 36px 25px 0;
      position: relative;
    }
    summary::-webkit-details-marker { display: none; }
    summary::after {
      content: "+";
      position: absolute;
      right: 0;
      top: 20px;
      font: 300 1.7rem/1 Consolas, monospace;
      color: var(--cobalt);
    }
    details[open] summary::after { content: "−"; }
    .code-name {
      font-family: "Arial Narrow", "Aptos Display", sans-serif;
      font-size: clamp(1.15rem, 2.2vw, 1.55rem);
      font-weight: 750;
      line-height: 1.1;
    }
    .description {
      margin: -5px 0 22px;
      max-width: 860px;
      line-height: 1.68;
      color: #344054;
    }
    .evidence-strip {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 16px;
      align-items: start;
      padding: 14px 0 19px;
      margin: -7px 0 22px;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .firing-total {
      min-width: 96px;
      padding-right: 16px;
      border-right: 1px solid var(--line);
    }
    .firing-number {
      font-family: "Arial Narrow", "Aptos Display", sans-serif;
      font-size: 2rem;
      font-weight: 800;
      line-height: 1;
      color: var(--cobalt);
    }
    .firing-label, .task-label {
      color: var(--muted);
      font-size: .68rem;
      margin-top: 5px;
    }
    .task-chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 8px; }
    .task-chip {
      display: inline-flex;
      gap: 7px;
      align-items: center;
      padding: 5px 8px;
      background: #e8eefc;
      border-left: 3px solid var(--cobalt);
      font: .72rem/1.2 Consolas, monospace;
    }
    .task-chip strong { color: var(--cobalt); }
    .runtime-evidence {
      margin: -8px 0 24px;
      border-left: 4px solid var(--amber);
      background: #fff8e7;
      padding: 15px 17px;
    }
    .runtime-evidence-title {
      color: #7a4b00;
      font-size: .72rem;
      margin-bottom: 10px;
    }
    .runtime-event {
      padding: 10px 0;
      border-top: 1px solid #e7cf99;
      line-height: 1.45;
    }
    .runtime-event:first-of-type { border-top: 0; }
    .runtime-event-meta {
      color: var(--muted);
      font: .7rem/1.3 Consolas, monospace;
      margin-bottom: 5px;
    }
    .runtime-event strong { color: #563500; }
    .fields {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1px;
      background: var(--line);
      border: 1px solid var(--line);
      margin: 0 0 24px;
    }
    .field { background: white; padding: 13px 15px; }
    .field-name { color: var(--muted); font-size: .7rem; margin-bottom: 4px; }
    .field-value { font-family: Consolas, monospace; font-size: .82rem; overflow-wrap: anywhere; }
    .empty, .error {
      padding: 44px;
      background: var(--panel);
      border: 1px solid var(--line);
      text-align: center;
    }
    .error { color: var(--error); border-color: #f1a7a1; }
    [hidden] { display: none !important; }
    @media (max-width: 760px) {
      .shell { width: min(100% - 20px, 1180px); margin-top: 10px; }
      .masthead { grid-template-columns: 1fr; padding: 24px 20px; }
      .meta { grid-template-columns: 1fr 1fr; }
      .meta-item:nth-child(2) { border-right: 0; }
      .meta-item:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
      .toolbar { flex-wrap: wrap; }
      .search { flex-basis: 100%; }
      .code-card { grid-template-columns: 58px minmax(0, 1fr); }
      details { padding: 0 16px; }
      .fields { grid-template-columns: 1fr; }
      .evidence-strip { grid-template-columns: 1fr; }
      .firing-total {
        display: flex;
        gap: 10px;
        align-items: baseline;
        border-right: 0;
        padding-right: 0;
      }
    }
    @media (prefers-reduced-motion: no-preference) {
      .code-card { animation: arrive .35s ease both; }
      @keyframes arrive {
        from { opacity: 0; transform: translateY(7px); }
        to { opacity: 1; transform: translateY(0); }
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="masthead">
      <div>
        <div class="eyebrow">ATLAS / live taxonomy field manual</div>
        <h1 id="taxonomy-title">Loading current taxonomy…</h1>
      </div>
      <div class="status" id="live-status">connecting</div>
    </header>

    <section class="meta" aria-label="Taxonomy metadata">
      <div class="meta-item">
        <div class="meta-label utility">Repository</div>
        <div class="meta-value" id="repo">—</div>
      </div>
      <div class="meta-item">
        <div class="meta-label utility">Domain</div>
        <div class="meta-value" id="domain">—</div>
      </div>
      <div class="meta-item">
        <div class="meta-label utility">Program</div>
        <div class="meta-value" id="program">—</div>
      </div>
      <div class="meta-item">
        <div class="meta-label utility">Last checked</div>
        <div class="meta-value" id="checked">—</div>
      </div>
    </section>

    <section class="toolbar" aria-label="Taxonomy controls">
      <input class="search" id="search" type="search"
             placeholder="Filter codes by id, name, or description"
             aria-label="Filter taxonomy codes">
      <button class="tool-button" id="expand" type="button">Expand all</button>
      <button class="tool-button" id="collapse" type="button">Collapse all</button>
      <div class="count" id="count">0 codes</div>
    </section>

    <section id="clean-checkpoints" hidden></section>
    <section class="codes" id="codes" aria-live="polite"></section>
  </main>

  <script>
    const els = {
      title: document.querySelector("#taxonomy-title"),
      status: document.querySelector("#live-status"),
      repo: document.querySelector("#repo"),
      domain: document.querySelector("#domain"),
      program: document.querySelector("#program"),
      checked: document.querySelector("#checked"),
      search: document.querySelector("#search"),
      count: document.querySelector("#count"),
      clean: document.querySelector("#clean-checkpoints"),
      codes: document.querySelector("#codes")
    };
    let state = null;
    let signature = "";

    function text(value) {
      return value === null || value === undefined ? "" : String(value);
    }

    function render(data) {
      state = data;
      els.title.textContent = data.taxonomy_id;
      els.repo.textContent = data.repo || "not recorded";
      els.domain.textContent = data.domain || "not recorded";
      els.program.textContent = data.program_id;
      els.checked.textContent = new Date().toLocaleTimeString();
      els.status.textContent = data.is_latest_successor ? "latest successor" : "live";
      renderCleanCheckpoints(data.clean_checkpoints || []);
      applyFilter();
    }

    function checkpointLabel(item) {
      const parts = [];
      if (item.seq) parts.push(`#${item.seq}`);
      if (item.gate) parts.push(item.gate);
      if (item.task_label || item.task_id) parts.push(item.task_label || item.task_id);
      if (item.checkpoint_id) parts.push(item.checkpoint_id);
      return parts.join(" / ");
    }

    function renderCleanCheckpoints(items) {
      if (!items.length) {
        els.clean.hidden = true;
        els.clean.replaceChildren();
        return;
      }
      els.clean.hidden = false;
      const panel = document.createElement("details");
      panel.className = "clean-panel";
      const summary = document.createElement("summary");
      summary.textContent = `Clean checkpoints — reflection fired no code (${items.length})`;
      panel.append(summary);
      const list = document.createElement("div");
      list.className = "clean-list";
      for (const item of items.slice().reverse()) {
        const row = document.createElement("div");
        row.className = "clean-item";
        const meta = document.createElement("div");
        meta.className = "clean-meta";
        meta.textContent = checkpointLabel(item);
        const tag = document.createElement("span");
        tag.className = "clean-tag";
        tag.textContent = item.none_apply ? "none apply" : "no firing";
        const considered = document.createElement("span");
        considered.textContent = item.considered && item.considered.length
          ? `Considered: ${item.considered.join(", ")}`
          : "Considered codes not recorded";
        const observe = document.createElement("div");
        observe.textContent = `Observe: ${item.observe || "not recorded"}`;
        const correlate = document.createElement("div");
        correlate.textContent = `Reasoning: ${item.correlate || "not recorded"}`;
        const decide = document.createElement("div");
        decide.textContent = `Decision: ${item.decide || "not recorded"}`;
        row.append(meta, tag, considered, observe, correlate, decide);
        list.append(row);
      }
      panel.append(list);
      els.clean.replaceChildren(panel);
    }

    function applyFilter() {
      if (!state) return;
      const query = els.search.value.trim().toLowerCase();
      const visible = state.codes.filter(code =>
        [code.code_id, code.name, code.description]
          .some(value => text(value).toLowerCase().includes(query))
      );
      els.count.textContent = `${visible.length} of ${state.codes.length} codes`;
      els.codes.replaceChildren(...visible.map(codeCard));
      if (!visible.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No codes match this filter.";
        els.codes.append(empty);
      }
    }

    function codeCard(code) {
      const article = document.createElement("article");
      article.className = "code-card";
      const rail = document.createElement("div");
      rail.className = "code-rail";
      const id = document.createElement("span");
      id.className = "code-id";
      id.textContent = code.code_id;
      rail.append(id);

      const details = document.createElement("details");
      details.open = true;
      const summary = document.createElement("summary");
      const name = document.createElement("div");
      name.className = "code-name";
      name.textContent = code.name || "Unnamed failure mode";
      summary.append(name);
      details.append(summary);

      const description = document.createElement("p");
      description.className = "description";
      description.textContent = code.description || "No description recorded.";
      details.append(description);

      if (code.fire_count !== null || code.task_firings.length) {
        const evidence = document.createElement("div");
        evidence.className = "evidence-strip";
        const total = document.createElement("div");
        total.className = "firing-total";
        const number = document.createElement("div");
        number.className = "firing-number";
        number.textContent = code.fire_count ?? "—";
        const firingLabel = document.createElement("div");
        firingLabel.className = "firing-label utility";
        firingLabel.textContent = "Total firings";
        total.append(number, firingLabel);

        const tasks = document.createElement("div");
        const taskLabel = document.createElement("div");
        taskLabel.className = "task-label utility";
        taskLabel.textContent = `${code.task_firings.length} task(s)`;
        const chips = document.createElement("div");
        chips.className = "task-chips";
        for (const firing of code.task_firings) {
          const chip = document.createElement("span");
          chip.className = "task-chip";
          const taskId = document.createElement("span");
          taskId.textContent = firing.label || firing.task_id;
          const count = document.createElement("strong");
          count.textContent = `×${firing.count}`;
          chip.append(taskId, count);
          chips.append(chip);
        }
        tasks.append(taskLabel, chips);
        evidence.append(total, tasks);
        details.append(evidence);
      }

      if (code.runtime_evidence.length) {
        const runtime = document.createElement("div");
        runtime.className = "runtime-evidence";
        const runtimeTitle = document.createElement("div");
        runtimeTitle.className = "runtime-evidence-title utility";
        runtimeTitle.textContent = "Runtime evidence";
        runtime.append(runtimeTitle);
        for (const item of code.runtime_evidence.slice().reverse()) {
          const event = document.createElement("div");
          event.className = "runtime-event";
          const meta = document.createElement("div");
          meta.className = "runtime-event-meta";
          meta.textContent = [
            item.seq ? `#${item.seq}` : "",
            item.gate,
            item.task_label || item.task_id,
            item.checkpoint_id
          ]
            .filter(Boolean).join(" / ");
          const evidenceLabel = document.createElement("strong");
          evidenceLabel.textContent = "Evidence: ";
          const evidenceText = document.createElement("span");
          evidenceText.textContent = item.evidence || "not recorded";
          const correlate = document.createElement("div");
          correlate.textContent = `Reasoning: ${item.correlate || "not recorded"}`;
          const decide = document.createElement("div");
          decide.textContent = `Decision: ${item.decide || "not recorded"}`;
          event.append(meta, evidenceLabel, evidenceText, correlate, decide);
          runtime.append(event);
        }
        details.append(runtime);
      }

      if (code.fields.length) {
        const fields = document.createElement("div");
        fields.className = "fields";
        for (const item of code.fields) {
          const field = document.createElement("div");
          field.className = "field";
          const label = document.createElement("div");
          label.className = "field-name utility";
          label.textContent = item.name;
          const value = document.createElement("div");
          value.className = "field-value";
          value.textContent = typeof item.value === "object"
            ? JSON.stringify(item.value) : text(item.value);
          field.append(label, value);
          fields.append(field);
        }
        details.append(fields);
      }
      article.append(rail, details);
      return article;
    }

    function showError(message) {
      els.status.textContent = "disconnected";
      const box = document.createElement("div");
      box.className = "error";
      box.textContent = `Dashboard could not refresh: ${message}`;
      els.codes.replaceChildren(box);
    }

    async function refresh() {
      try {
        const response = await fetch("/api/taxonomy", {cache: "no-store"});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        const next = JSON.stringify(data);
        if (next !== signature) {
          signature = next;
          render(data);
        } else {
          els.checked.textContent = new Date().toLocaleTimeString();
          els.status.textContent = data.is_latest_successor ? "latest successor" : "live";
        }
      } catch (error) {
        showError(error.message);
      }
    }

    els.search.addEventListener("input", applyFilter);
    document.querySelector("#expand").addEventListener("click", () => {
      document.querySelectorAll("details").forEach(item => item.open = true);
    });
    document.querySelector("#collapse").addEventListener("click", () => {
      document.querySelectorAll("details").forEach(item => item.open = false);
    });
    refresh();
    setInterval(refresh, 1500);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
