"""OpenAI-compatible shim -> headless Claude Code (claude.exe), Sonnet on the login.

Lets atlas_skill's learning calls (the vendored 8-stage inducer, the support judge, and the
refiner) run on the Claude Code **login** with NO API key. `atlas_runtime.learning_calls`
(support_model_call / refinement_model_call) and `vendor.atlas.llm.LLMClient` all take an
"OpenAI path" for any model id that does not start with 'claude'/'gemini'. Point that path
here (OPENAI_BASE_URL=http://127.0.0.1:<port>/v1) and use a gpt-family atlas_model id (e.g.
'gpt-5') so `models.resolve_model_profile` still resolves a token-budget window.

This is the same proven pattern the old OfficeQA harness used (officeqa/cc_proxy.py).

Run:  python cc_proxy.py [--port 8742] [--model claude-sonnet-4-6]
(The driver `run_officeqa_atlas.py` starts this for you automatically.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLAUDE = os.path.join(
    os.environ.get("APPDATA", ""), "npm", "node_modules",
    "@anthropic-ai", "claude-code", "bin", "claude.exe",
)
MODEL = os.environ.get("CC_PROXY_MODEL", "claude-sonnet-4-6")
CALL_TIMEOUT = int(os.environ.get("CC_PROXY_TIMEOUT", "600"))
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> str:
    """Claude wraps JSON in ```json fences / preamble; the ATLAS parsers need raw JSON."""
    t = (text or "").strip()
    m = _FENCE.search(t)
    if m:
        cand = m.group(1).strip()
        try:
            json.loads(cand)
            return cand
        except Exception:
            t = cand
    for o, c in (("{", "}"), ("[", "]")):
        i, j = t.find(o), t.rfind(c)
        if 0 <= i < j:
            cand = t[i:j + 1]
            try:
                json.loads(cand)
                return cand
            except Exception:
                pass
    return t


def call_claude(prompt: str) -> str:
    cmd = [CLAUDE, "-p", "--model", MODEL, "--dangerously-skip-permissions",
           "--output-format", "json"]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=CALL_TIMEOUT)
        out = proc.stdout or ""
        try:
            text = json.loads(out).get("result", "") or ""
        except Exception:
            text = out
        return extract_json(text)
    except Exception as e:  # noqa: BLE001
        return f'{{"error": "claude call failed: {e!r}"}}'


def render_prompt(messages: list[dict]) -> str:
    # Content only — no 'SYSTEM:'/'USER:' labels (Claude flags an embedded 'SYSTEM:' as a
    # prompt-injection attempt and refuses). System instruction becomes leading context.
    parts = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        content = str(content).strip()
        if content:
            parts.append(content)
    return "\n\n".join(parts)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        out = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad request"})
        text = call_claude(render_prompt(body.get("messages", [])))
        self._json(200, {
            "id": "cc-proxy", "object": "chat.completion", "created": 0,
            "model": body.get("model", "gpt-5"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    def do_GET(self):
        self._json(200, {"object": "list", "data": [{"id": "gpt-5", "object": "model"}]})

    def log_message(self, *a):
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8742)
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args()
    globals()["MODEL"] = args.model
    print(f"cc_proxy on 127.0.0.1:{args.port} -> {args.model}", flush=True)
    print(f"  claude.exe: {CLAUDE}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
