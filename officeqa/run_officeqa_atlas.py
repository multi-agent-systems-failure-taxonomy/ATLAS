#!/usr/bin/env python
"""Drive the new atlas_skill Claude Code integration over OfficeQA tasks.

  Task agent : Claude **Haiku** (headless `claude -p`, on your Claude Code login).
  Learning   : Claude **Sonnet** for the generator / support-judge / refiner, reached
               through `cc_proxy.py` (an OpenAI shim) so it also runs on the login —
               NO API key needed anywhere.

Each iteration is one Claude Code session against one OfficeQA question (oracle mode: the
source Treasury-Bulletin doc is copied into the agent's working dir). The ATLAS hooks,
installed once into `run/work/.claude`, inject the standing prompt, gate the reflections,
capture one trace per session, and trigger generation (at 5 traces) / refinement (at 10)
automatically. Learning runs as detached workers that inherit the proxy env.

This script only ORCHESTRATES — it makes no edits to atlas_skill. All run artifacts land
under ./run/ (gitignored).

Single command:
    python run_officeqa_atlas.py --n 20            # 20 iterations from the top of the set
    python run_officeqa_atlas.py --n 5 --reset     # fresh program, first 5 questions
    python run_officeqa_atlas.py --n 20 --wait-learning   # block on each gen/refine so you
                                                           # can watch the taxonomy appear

Prereqs: `claude` logged in (`claude /login`), and `pip install openai`.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent           # atlas_skill/officeqa
ATLAS = HERE.parent                              # atlas_skill
SKYLAB = ATLAS.parent                            # repo root

DEFAULT_CORPUS = (
    SKYLAB / ("olympiad" + "-agents") / "officeqa" / "officeqa_corpus"
    / "treasury_bulletins_parsed" / "transformed"
)
DEFAULT_QUESTIONS = (
    SKYLAB / ("olympiad" + "-agents") / "officeqa"
    / "officeqa_out" / "officeqa_pro.csv"
)
CLAUDE = (
    Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules"
    / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
)

RUN = HERE / "run"
PROGRAM = RUN / "program"        # trace_output (the ATLAS program)
STORE = RUN / "taxonomies"       # generated taxonomy store
TRACE_ROOT = RUN / "traces"      # generated/refined-taxonomy learning traces
WORK = RUN / "work"              # the agent's working directory (hooks installed here)
SESSION_DIR = PROGRAM / ".atlas-claude-code"
EMPTY_MCP_CONFIG = WORK / ".claude" / "empty-mcp.json"
OFFICEQA_SYSTEM_PROMPT = """You are a focused document-analysis agent.
Solve only the user's OfficeQA question using files in the working directory.
Use Read/Grep/Glob to inspect sources and Bash only for calculations.
Do not browse the web, edit files, create subagents, or add unrelated work.
Show enough source-grounded arithmetic to verify the result. End task answers
with exactly <FINAL_ANSWER>answer</FINAL_ANSWER>. Follow hook instructions."""
OFFICEQA_TOOLS = "Read,Grep,Glob,Bash"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── preflight ─────────────────────────────────────────────────────────────────────────
def preflight(args) -> list[str]:
    problems = []
    if not CLAUDE.is_file():
        problems.append(f"claude.exe not found at {CLAUDE} (install Claude Code, then `claude /login`)")
    if not Path(args.questions).is_file():
        problems.append(f"questions CSV not found: {args.questions} (pass --questions)")
    if not Path(args.corpus).is_dir():
        problems.append(f"corpus dir not found: {args.corpus} (pass --corpus)")
    try:
        import openai  # noqa: F401
    except Exception:
        problems.append("python package 'openai' not importable — run: pip install openai")
    if not (ATLAS / "atlas_integration" / "claude_code" / "install.py").is_file():
        problems.append(f"atlas_skill integration not found under {ATLAS}")
    return problems


# ── proxy lifecycle ───────────────────────────────────────────────────────────────────
def start_proxy(port: int, model: str) -> subprocess.Popen | None:
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "cc_proxy.py"), "--port", str(port), "--model", model],
        stdout=open(RUN / "cc_proxy.log", "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}/v1/models"
    for _ in range(40):
        try:
            urllib.request.urlopen(url, timeout=2)
            log(f"cc_proxy up on 127.0.0.1:{port} -> {model} (Sonnet on the login)")
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError(
        "cc_proxy did not answer its health check in 20s; "
        "see run/cc_proxy.log"
    )


def proxy_alive(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2)
        return True
    except Exception:
        return False


def start_dashboard(port: int, expected_program_id: str) -> subprocess.Popen:
    """Start one live dashboard (with a real browser tab) on a fixed port, pointed at this
    run's program + store. Opens immediately; updates live as iterations land."""
    cmd = [
        sys.executable, "-m", "atlas_runtime.dashboard",
        "--trace-output", str(PROGRAM), "--store-dir", str(STORE), "--port", str(port),
    ]
    proc = subprocess.Popen(
        cmd, cwd=str(ATLAS),
        stdout=open(RUN / "dashboard.log", "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}/api/health"
    for _ in range(40):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                health = json.loads(response.read().decode("utf-8"))
            if health.get("program_id") != expected_program_id:
                raise RuntimeError(
                    f"dashboard port {port} belongs to another ATLAS program "
                    f"({health.get('program_id')})"
                )
            return proc
        except RuntimeError:
            proc.terminate()
            raise
        except Exception:
            if proc.poll() is not None:
                break
            time.sleep(0.25)
    proc.terminate()
    raise RuntimeError(
        f"dashboard did not start correctly on port {port}; "
        "choose another --dashboard-port or stop the process using that port"
    )


# ── ATLAS hook install ────────────────────────────────────────────────────────────────
def install_hooks(atlas_model: str, max_retries: int, proxy_port: int) -> None:
    sys.path.insert(0, str(ATLAS))
    from atlas_integration.claude_code.config import ClaudeCodeConfig
    from atlas_integration.claude_code.install import install

    cfg = ClaudeCodeConfig(
        trace_output=PROGRAM,
        atlas_model=atlas_model,
        store_dir=STORE,
        trace_root=TRACE_ROOT,
        dashboard=False,
        openai_base_url=f"http://127.0.0.1:{proxy_port}/v1",
        openai_api_key_env="ATLAS_CC_PROXY_KEY",
        max_retries=max_retries,
    )
    info = install(WORK, cfg, verify=True)
    EMPTY_MCP_CONFIG.write_text(
        json.dumps({"mcpServers": {}}, indent=2) + "\n",
        encoding="utf-8",
    )
    log(f"hooks installed: Claude {info['claude_version']}")
    log(f"  settings: {info['settings']}")


# ── tasks ─────────────────────────────────────────────────────────────────────────────
def load_tasks(questions: Path, limit: int, start: int) -> list[dict]:
    rows = list(csv.DictReader(Path(questions).open(encoding="utf-8")))
    return rows[start:start + limit]


def place_docs(
    task: dict,
    corpus: Path,
    previous: list[str],
) -> list[str]:
    for name in previous:
        try:
            (WORK / name).unlink()
        except FileNotFoundError:
            pass
    files = [
        f.strip()
        for f in (task.get("source_files") or "").replace(";", ",").split(",")
        if f.strip()
    ]
    placed = []
    for name in files:
        src = Path(corpus) / name
        if src.is_file():
            shutil.copy(src, WORK / name)
            placed.append(name)
    return placed


def build_prompt(task: dict, placed: list[str]) -> str:
    doc_line = (
        f"The source document(s) are in your working directory: {', '.join(placed)}. "
        "Read them with your tools before answering."
        if placed
        else "No source document was provided; answer as best you can."
    )
    return (
        f"OfficeQA task {task['uid']} (difficulty: {task.get('difficulty', '?')}).\n\n"
        f"Question: {task['question']}\n\n"
        f"{doc_line}\n\n"
        "Do the multi-step arithmetic carefully and end with your answer on its own line as:\n"
        "<FINAL_ANSWER>your answer</FINAL_ANSWER>"
    )


def run_agent(prompt: str, agent_model: str, timeout: int) -> dict:
    cmd = agent_command(agent_model)
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=str(WORK), timeout=timeout,
            env={**os.environ, "ATLAS_CC_PROXY_KEY": "local-proxy"},
        )
        return {
            "returncode": proc.returncode,
            "elapsed": round(time.time() - t0, 1),
            "stdout": proc.stdout or "",
            "stderr": (proc.stderr or "")[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "elapsed": round(time.time() - t0, 1),
                "stdout": "", "stderr": f"agent timed out after {timeout}s"}


def agent_command(agent_model: str) -> list[str]:
    """Minimal Claude Code harness that retains project-local ATLAS hooks."""
    return [
        str(CLAUDE),
        "-p",
        "--model",
        agent_model,
        "--dangerously-skip-permissions",
        "--system-prompt",
        OFFICEQA_SYSTEM_PROMPT,
        "--tools",
        OFFICEQA_TOOLS,
        "--setting-sources",
        "local",
        "--strict-mcp-config",
        "--mcp-config",
        str(EMPTY_MCP_CONFIG),
        "--disable-slash-commands",
        "--no-chrome",
        "--prompt-suggestions",
        "false",
        "--effort",
        "low",
    ]


# ── scoring (for YOUR benefit only — never feeds ATLAS; the loop is outcome-blind) ──────
_FINAL = re.compile(r"<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>", re.IGNORECASE | re.DOTALL)


def _norm_num(text: str) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", text or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def answer_from_trajectory(raw_trajectory: str) -> str | None:
    """Extract the benchmark answer from assistant messages, excluding prompts."""
    answers: list[str] = []
    for line in (raw_trajectory or "").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") != "assistant":
            continue
        message = item.get("message")
        content = message.get("content", []) if isinstance(message, dict) else []
        text = "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
        for match in _FINAL.finditer(text):
            answer = match.group(1).strip()
            if answer and answer.lower() != "your answer":
                answers.append(answer)
    return answers[-1] if answers else None


def score_answer(answer: str | None, gold: str, tol: float = 0.0) -> bool | None:
    if answer is None:
        return None
    got, exp = _norm_num(answer), _norm_num(gold)
    if got is None or exp is None:
        return answer.strip().lower() == (gold or "").strip().lower()
    return abs(got - exp) <= max(tol, abs(exp) * tol)


def usage_from_trajectory(raw_trajectory: str) -> dict[str, int]:
    """Aggregate Claude usage so subscription-harness bloat is observable."""
    totals = {
        "input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
    }
    for line in (raw_trajectory or "").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") != "assistant":
            continue
        message = item.get("message")
        usage = message.get("usage", {}) if isinstance(message, dict) else {}
        for key in totals:
            totals[key] += int(usage.get(key, 0) or 0)
    return totals


def session_state_files() -> set[Path]:
    return set(SESSION_DIR.glob("*.json")) if SESSION_DIR.exists() else set()


def captured_trace_after(
    previous_states: set[Path],
    *,
    timeout: float = 15.0,
) -> tuple[str | None, dict | None]:
    """Find the one session and canonical trace created by the latest agent run."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        candidates = sorted(
            session_state_files() - previous_states,
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for state_path in candidates:
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not state.get("trace_captured"):
                continue
            session_id = str(state.get("session_id", ""))
            for root in (PROGRAM / "pending", TRACE_ROOT):
                if not root.exists():
                    continue
                for trace_path in root.rglob("trace-*.json"):
                    try:
                        trace = json.loads(trace_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    metadata = trace.get("metadata") or {}
                    if metadata.get("claude_session_id") == session_id:
                        return session_id, trace
        time.sleep(0.25)
    return None, None


# ── ATLAS state snapshot ──────────────────────────────────────────────────────────────
def snapshot() -> dict:
    manifest = {}
    try:
        manifest = json.loads((PROGRAM / ".atlas-program.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    pending = (
        len(list((PROGRAM / "pending").glob("trace-*.json")))
        if (PROGRAM / "pending").exists()
        else 0
    )
    stored = sorted(p.stem for p in STORE.glob("tax-*.json")) if STORE.exists() else []
    evidence: dict = {}
    try:
        ev = json.loads((PROGRAM / ".atlas-runtime-evidence.json").read_text(encoding="utf-8"))
        for tid, t in ev.get("taxonomies", {}).items():
            fired = {c: d.get("fire_count", 0) for c, d in t.get("codes", {}).items()}
            fired = {k: v for k, v in fired.items() if v}
            if fired:
                evidence[tid] = fired
    except Exception:
        pass
    return {
        "taxonomy_id": manifest.get("taxonomy_id"),
        "generation_state": (manifest.get("generation") or {}).get("state"),
        "generation_error": (manifest.get("generation") or {}).get("last_error"),
        "refine_rounds": (manifest.get("refinement") or {}).get("rounds_completed"),
        "pending_traces": pending,
        "stored_taxonomies": stored,
        "fired_codes": evidence,
    }


def wait_for_learning(timeout: float, poll: float = 15.0) -> dict:
    """Wait for learning, raising on timeout or a failed worker."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = json.loads((PROGRAM / ".atlas-program.json").read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"could not read ATLAS learning state: {exc}") from exc
        gen = (m.get("generation") or {}).get("state")
        ref = (m.get("refinement") or {}).get("state")
        if gen != "running" and ref != "running":
            errors = [
                value
                for value in (
                    (m.get("generation") or {}).get("last_error")
                    if gen == "failed" else None,
                    (m.get("refinement") or {}).get("last_error")
                    if ref == "failed" else None,
                )
                if value
            ]
            if errors:
                raise RuntimeError("ATLAS learning failed: " + " | ".join(errors))
            return {"generation": gen, "refinement": ref}
        time.sleep(poll)
    raise TimeoutError(
        f"ATLAS learning was still running after {timeout:.0f}s"
    )


# ── main ──────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=20, help="number of iterations (default 20)")
    ap.add_argument("--start", type=int, default=0, help="row offset into the questions CSV")
    ap.add_argument("--agent-model", default="claude-haiku-4-5", help="task-agent model")
    ap.add_argument("--taxonomy-model", default="claude-sonnet-4-6", help="generator/judge/refiner model (via proxy)")
    ap.add_argument("--atlas-model", default="gpt-5",
                    help="model id handed to the framework — must be gpt-family so the OpenAI path "
                         "hits the proxy AND resolve_model_profile works (default gpt-5)")
    ap.add_argument("--proxy-port", type=int, default=8742)
    ap.add_argument("--dashboard-port", type=int, default=8765)
    ap.add_argument("--no-proxy", action="store_true", help="reuse an already-running proxy on --proxy-port")
    ap.add_argument("--max-retries", type=int, default=2, help="ATLAS pre-submission repair cap")
    ap.add_argument("--agent-timeout", type=int, default=900, help="per-task agent timeout (s)")
    ap.add_argument("--wait-learning", action="store_true",
                    help="after each iteration, block until any gen/refine worker finishes")
    ap.add_argument("--learning-timeout", type=float, default=1800.0)
    ap.add_argument("--dashboard", action=argparse.BooleanOptionalAction, default=True,
                    help="start the live dashboard (default: on; pass --no-dashboard to suppress)")
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    ap.add_argument("--reset", action="store_true", help="wipe ./run (fresh program + store) first")
    args = ap.parse_args()

    problems = preflight(args)
    if problems:
        print("PREFLIGHT FAILED:", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        return 2

    if args.reset and RUN.exists():
        shutil.rmtree(RUN, ignore_errors=True)
        if (PROGRAM / ".atlas-program.json").exists():
            print("ERROR: officeqa/run could not be fully cleared — a process still holds it "
                  "(an open dashboard window or a previous run). Stop it (Ctrl+C / close the "
                  "dashboard), then re-run with --reset.", file=sys.stderr)
            return 2
    for d in (RUN, PROGRAM, STORE, TRACE_ROOT, WORK):
        d.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(ATLAS))
    from atlas_runtime import ProgramWorkspace

    program_id = ProgramWorkspace(PROGRAM, repo_path=WORK).program_id

    dash = None
    if args.dashboard:
        dash = start_dashboard(args.dashboard_port, program_id)
        log(f"dashboard: http://127.0.0.1:{args.dashboard_port}/  "
            "(a browser tab should open now; it shows MAST, then the generated taxonomy live)")

    proxy = None
    try:
        if not args.no_proxy:
            proxy = start_proxy(args.proxy_port, args.taxonomy_model)
        elif not proxy_alive(args.proxy_port):
            raise RuntimeError(
                f"--no-proxy was set but nothing is answering on port "
                f"{args.proxy_port}"
            )
    except Exception:
        if dash is not None:
            dash.terminate()
            try:
                dash.wait(timeout=10)
            except Exception:
                dash.kill()
        raise

    try:
        install_hooks(args.atlas_model, args.max_retries, args.proxy_port)
        tasks = load_tasks(args.questions, args.n, args.start)
        log(f"running {len(tasks)} OfficeQA iteration(s): agent={args.agent_model}, "
            f"learning={args.taxonomy_model} via proxy, atlas_model={args.atlas_model}")
        log(f"artifacts under: {RUN}")

        results_path = RUN / "results.jsonl"
        labels_path = PROGRAM / ".atlas-task-labels.json"
        task_labels: dict[str, dict] = {}
        staged_docs: list[str] = []
        for i, task in enumerate(tasks, 1):
            placed = place_docs(task, Path(args.corpus), staged_docs)
            staged_docs = placed
            prompt = build_prompt(task, placed)
            log(f"--- iter {i}/{len(tasks)}  {task['uid']}  docs={placed or 'none'} ---")
            states_before = session_state_files()
            res = run_agent(prompt, args.agent_model, args.agent_timeout)
            session_id, trace = captured_trace_after(states_before)
            if res["returncode"] != 0 or trace is None:
                detail = res["stderr"].strip() or "no captured ATLAS trace"
                raise RuntimeError(
                    f"OfficeQA iteration {i} ({task['uid']}) failed before "
                    f"completion: returncode={res['returncode']}; {detail}"
                )
            answer = answer_from_trajectory(
                str((trace or {}).get("raw_trajectory", ""))
            )
            usage = usage_from_trajectory(
                str((trace or {}).get("raw_trajectory", ""))
            )
            ok = score_answer(answer, task.get("answer", ""))
            tail = res["stdout"][-400:].replace("\n", " ")
            log(
                f"agent rc={res['returncode']} {res['elapsed']}s "
                f"answer={answer!r} correct={ok} usage={json.dumps(usage)} "
                f"...{tail}"
            )
            if res["stderr"].strip():
                log(f"agent stderr: ...{res['stderr'][-300:]}")
            if args.wait_learning:
                state = wait_for_learning(args.learning_timeout)
                log(f"learning settled: {json.dumps(state)}")
            snap = snapshot()
            log(f"ATLAS: {json.dumps(snap)}")
            # Sidecar the dashboard reads to label firing chips by OfficeQA task
            # (the runtime only knows the opaque Claude session id).
            if session_id:
                task_labels[session_id] = {"label": task["uid"], "correct": ok}
                labels_path.write_text(
                    json.dumps(task_labels, indent=2), encoding="utf-8"
                )
            with results_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "iter": i, "uid": task["uid"], "correct": ok,
                    "answer": answer, "claude_session_id": session_id,
                    "usage": usage,
                    "agent_rc": res["returncode"], "elapsed": res["elapsed"],
                    "gold": task.get("answer", ""), "atlas": snap,
                }) + "\n")

        final_learning = wait_for_learning(args.learning_timeout)
        log(f"final learning settled: {json.dumps(final_learning)}")
        final = snapshot()
        log("=== RUN COMPLETE ===")
        log(f"final taxonomy_id : {final['taxonomy_id']}")
        log(f"stored taxonomies : {final['stored_taxonomies']}")
        log(f"refine rounds     : {final['refine_rounds']}")
        log(f"fired codes       : {json.dumps(final['fired_codes'])}")
        log(f"per-iter results  : {results_path}")
        return 0
    finally:
        for proc in (proxy, dash):
            if proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except Exception:
                    proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
