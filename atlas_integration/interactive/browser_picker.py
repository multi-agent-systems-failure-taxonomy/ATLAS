"""Shared localhost taxonomy-picker transport for interactive hosts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

from atlas_runtime import ProgramWorkspace
from atlas_runtime.fsio import read_text_retry, write_text_atomic_retry
from finding import mast, store, webview


def start_browser_picker(
    trace_output: Path,
    session_id: str,
    *,
    store_dir: Path,
    picker_dir: str,
    worker_module: str,
    selection: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    routing_root: Path | None = None,
    default_trace_output: Path | None = None,
    task_group: str = "default",
    project_scope: str = "explicit",
    project_id: str | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Launch a detached picker whose choice is applied to one session."""
    trace_output = Path(trace_output).expanduser().resolve()
    root = trace_output / picker_dir
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(session_id).encode("utf-8", "replace")).hexdigest()
    request_path = root / f"{key}.request.json"
    ready_path = root / f"{key}.ready.json"
    result_path = root / f"{key}.result.json"
    for path in (ready_path, result_path):
        path.unlink(missing_ok=True)

    request = {
        "version": 1,
        "session_id": str(session_id),
        "trace_output": str(trace_output),
        "store_dir": str(Path(store_dir).expanduser().resolve()),
        "selection": selection,
        "event": {
            key: value
            for key, value in (event or {}).items()
            if key in {"cwd", "session_id", "thread_id", "conversation_id"}
        },
        "routing_root": str(Path(routing_root or trace_output).expanduser().resolve()),
        "default_trace_output": str(
            Path(default_trace_output or trace_output).expanduser().resolve()
        ),
        "task_group": str(task_group),
        "project_scope": str(project_scope),
        "project_id": project_id,
        "result_path": str(result_path),
    }
    write_text_atomic_retry(
        request_path,
        json.dumps(request, indent=2, ensure_ascii=False) + "\n",
    )
    command = [
        sys.executable,
        "-m",
        worker_module,
        "--serve",
        "--store-dir",
        str(Path(store_dir).expanduser().resolve()),
        "--ready-path",
        str(ready_path),
        "--result-path",
        str(result_path),
        "--request-path",
        str(request_path),
        "--timeout-seconds",
        str(max(60, int(timeout_seconds))),
        "--no-open-browser",
    ]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)

    deadline = time.monotonic() + 4
    ready: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            ready = json.loads(read_text_retry(ready_path))
            break
        except (OSError, json.JSONDecodeError):
            if process.poll() is not None:
                break
            time.sleep(0.05)
    if not ready.get("url"):
        raise RuntimeError("local taxonomy picker did not become ready")
    return {
        "pid": process.pid,
        "url": str(ready["url"]),
        "request_path": str(request_path),
        "ready_path": str(ready_path),
        "result_path": str(result_path),
        "started_at": time.time(),
    }


def open_browser_picker(picker: dict[str, Any]) -> bool:
    """Open a prepared picker only after its session state is durable."""
    url = str(picker.get("url") or "").strip()
    try:
        return bool(url and webbrowser.open(url))
    except OSError:
        return False


def read_browser_choice(
    picker: dict[str, Any] | None,
    *,
    store_dir: Path,
) -> str | None:
    """Return a validated choice from the picker receipt, when present."""
    if not isinstance(picker, dict) or not picker.get("result_path"):
        return None
    try:
        result = json.loads(read_text_retry(Path(str(picker["result_path"]))))
    except (OSError, json.JSONDecodeError):
        return None
    value = str(result.get("choice") or result.get("taxonomy_id") or "").strip()
    if value in {mast.MAST_ID, "none"}:
        return value
    return value if value and store.exists(value, store_dir) else None


def apply_browser_choice(
    request: dict[str, Any],
    choice: str,
    *,
    host_label: str,
    load_state: Callable[[Path, str], dict[str, Any]],
    save_state: Callable[[Path, str, dict[str, Any]], None],
    create_fresh_session_route: Callable[..., Any],
) -> dict[str, Any]:
    """Apply one browser choice using host-provided state and route facades."""
    session_id = str(request.get("session_id") or "").strip()
    if not session_id:
        raise ValueError(f"picker request is missing the {host_label} conversation id")
    trace_output = Path(str(request["trace_output"])).expanduser().resolve()
    store_dir = Path(str(request["store_dir"])).expanduser().resolve()
    state = load_state(trace_output, session_id)
    if not state:
        raise ValueError(f"the {host_label} selector state no longer exists")
    selection = state.get("selection") or request.get("selection") or {}
    if selection.get("status") not in {"pending", "browser_pending"}:
        selected = str(selection.get("selected_taxonomy_id") or "")
        if choice == selected or (
            choice == "none" and selection.get("status") == "disabled"
        ):
            return {
                "choice": choice,
                "status": selection.get("status"),
                "trace_output": str(trace_output),
            }
        raise ValueError(f"this {host_label} conversation already has a choice")

    option = allowed_option(selection, choice, store_dir)
    selection["selected_kind"] = option["kind"]
    selection["selected_taxonomy_id"] = option.get("taxonomy_id")
    selection["selected_label"] = option["label"]
    state["finished"] = True
    target_output = trace_output
    target_task_group = str(request.get("task_group") or "default")
    if option["kind"] == "disabled":
        selection["status"] = "disabled"
        state["selection"] = selection
        save_state(trace_output, session_id, state)
    else:
        if option.get("starts_fresh"):
            route = create_fresh_session_route(
                Path(str(request["routing_root"])),
                request.get("event") or {"session_id": session_id},
                default_trace_output=Path(str(request["default_trace_output"])),
                project_scope=str(request.get("project_scope") or "explicit"),
                project_id=request.get("project_id"),
            )
            target_output = route.trace_output
            target_task_group = route.task_group
            selection["fresh_task_group"] = route.task_group
            selection["shared_taxonomy_preserved"] = selection.get(
                "project_taxonomy_id"
            )
            source_state = dict(state)
            source_state["selection"] = {**selection, "status": "routed"}
            save_state(trace_output, session_id, source_state)
        elif option["kind"] == "taxonomy":
            ProgramWorkspace(
                trace_output,
                repo_path=(request.get("event") or {}).get("cwd"),
            ).bind_inherited_taxonomy(str(option["taxonomy_id"]))
        selection["status"] = "selected"
        state["selection"] = selection
        save_state(target_output, session_id, state)

    receipt = {
        "version": 1,
        "choice": choice,
        "taxonomy_id": option.get("taxonomy_id"),
        "label": option["label"],
        "status": selection["status"],
        "trace_output": str(target_output),
        "task_group": target_task_group,
        "applied_at": time.time(),
    }
    result_path = Path(str(request["result_path"]))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic_retry(
        result_path,
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
    )
    return receipt


def allowed_option(
    selection: dict[str, Any],
    choice: str,
    store_dir: Path,
) -> dict[str, Any]:
    normalized = str(choice or "").strip()
    for option in [
        *selection.get("options", []),
        *selection.get("catalog_options", []),
    ]:
        kind = option.get("kind")
        if kind == "browser":
            continue
        value = (
            "none"
            if kind == "disabled"
            else str(option.get("taxonomy_id") or "").strip()
        )
        if normalized != value:
            continue
        if kind == "taxonomy" and not store.exists(normalized, store_dir):
            break
        return dict(option)
    raise ValueError(f"taxonomy choice {normalized!r} is not allowed for this session")


def serve_picker(
    *,
    store_dir: Path,
    ready_path: Path,
    result_path: Path,
    timeout_seconds: int,
    request_path: Path | None,
    open_browser: bool,
    apply_choice: Callable[[dict[str, Any], str], dict[str, Any]],
    open_url: Callable[[str], Any] = webbrowser.open,
) -> int:
    request = None
    selection = None
    picker_context = None
    on_choose = None
    if request_path is not None:
        request = json.loads(read_text_retry(request_path))
        selection = request.get("selection")
        picker_context = {
            "project": (selection or {}).get("project"),
            "project_root": (selection or {}).get("project_root"),
            "project_taxonomy_id": (selection or {}).get("project_taxonomy_id"),
        }
        on_choose = lambda value: apply_choice(request, value)

    server, result, done = webview.build_server(
        store_dir,
        allow_none=request is None,
        choice_options=picker_options(selection),
        picker_context=picker_context,
        on_choose=on_choose,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic_retry(
            ready_path,
            json.dumps({"url": url}, ensure_ascii=False) + "\n",
        )
        if open_browser:
            open_url(url)
        if not done.wait(timeout=max(60, int(timeout_seconds))):
            return 2
        choice = str(result.get("value") or "").strip()
        if not choice:
            return 3
        if request is None:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic_retry(
                result_path,
                json.dumps({"taxonomy_id": choice}, ensure_ascii=False) + "\n",
            )
        return 0
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def picker_options(
    selection: dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    if not selection:
        return None
    options: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for option in [
        *selection.get("options", []),
        *selection.get("catalog_options", []),
    ]:
        kind = str(option.get("kind") or "")
        if kind == "browser":
            continue
        value = "none" if kind == "disabled" else str(
            option.get("taxonomy_id") or ""
        )
        key = (kind, value)
        if value and key not in seen:
            options.append(dict(option))
            seen.add(key)
    return options
