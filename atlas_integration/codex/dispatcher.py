"""Single command entry point registered for Codex lifecycle hooks."""

from __future__ import annotations

import argparse
import json
import os
import sys

try:  # pragma: no cover - script execution fallback
    from atlas_integration.codex.config import CodexConfig
    from atlas_integration.codex.learning_jobs import (
        drain_learning_notices,
        reconcile_learning_jobs,
    )
    from atlas_integration.codex.runtime import (
        decisions_log,
        post_tool_use,
        session_start,
        stop,
        subagent_stop,
        user_prompt_submit,
    )
    from atlas_integration.shared import force_utf8_stdio
except ModuleNotFoundError:  # pragma: no cover
    from .config import CodexConfig
    from .learning_jobs import drain_learning_notices, reconcile_learning_jobs
    from .runtime import (
        decisions_log,
        post_tool_use,
        session_start,
        stop,
        subagent_stop,
        user_prompt_submit,
    )
    from ..shared import force_utf8_stdio

HANDLERS = {
    "SessionStart": session_start,
    "UserPromptSubmit": user_prompt_submit,
    "Stop": stop,
    "SubagentStop": subagent_stop,
    "PostToolUse": post_tool_use,
}


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description="ATLAS Codex hook dispatcher.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--event")
    args = parser.parse_args(argv)
    event: dict = {}
    config: CodexConfig | None = None
    try:
        event = json.loads(sys.stdin.read() or "{}")
        config = CodexConfig.load(args.config).for_event(event)
        if config.learning_backend == "provider" and config.openai_base_url:
            os.environ["OPENAI_BASE_URL"] = config.openai_base_url
        if config.learning_backend == "provider" and config.openai_api_key_env:
            value = os.environ.get(config.openai_api_key_env)
            if not value:
                raise RuntimeError(
                    f"configured openai_api_key_env "
                    f"{config.openai_api_key_env!r} is not set"
                )
            os.environ["OPENAI_API_KEY"] = value
        event_name = args.event or event.get("hook_event_name")
        if event_name not in HANDLERS:
            raise RuntimeError(f"unsupported Codex hook event: {event_name!r}")
        if config.learning_backend == "codex_subagent":
            reconcile_learning_jobs(
                _workspace(config, event),
                store_dir=config.store_dir,
                trace_root=config.trace_root,
            )
        output = HANDLERS[event_name](event, config)
        if config.learning_backend == "codex_subagent":
            workspace = _workspace(config, event)
            reconcile_learning_jobs(
                workspace,
                store_dir=config.store_dir,
                trace_root=config.trace_root,
            )
            output = _merge_notices(
                output,
                drain_learning_notices(workspace, _conversation_id(event)),
            )
        decisions_log(config, event, output)
        if output:
            print(json.dumps(output, ensure_ascii=False))
        return 0
    except Exception as exc:
        if config is not None:
            try:
                decisions_log(
                    config,
                    event,
                    {
                        "hookError": type(exc).__name__,
                        "message": str(exc),
                    },
                )
            except Exception:
                pass
        print(f"ATLAS Codex hook failed: {exc}", file=sys.stderr)
        return 1


def _workspace(config: CodexConfig, event: dict):
    from atlas_runtime import ProgramWorkspace

    return ProgramWorkspace(config.trace_output, repo_path=event.get("cwd"))


def _conversation_id(event: dict) -> str:
    for key in ("session_id", "thread_id", "conversation_id"):
        value = event.get(key)
        if value:
            return str(value)
    transcript = event.get("transcript_path")
    if transcript:
        return str(transcript)
    return "codex-session"


def _merge_notices(output: dict | None, notices: list[str]) -> dict | None:
    if not notices:
        return output
    merged = dict(output or {})
    merged.setdefault("continue", True)
    messages = []
    existing = merged.get("systemMessage")
    if isinstance(existing, str) and existing.strip():
        messages.append(existing.strip())
    messages.extend(notice.strip() for notice in notices if notice.strip())
    merged["systemMessage"] = "\n\n".join(messages)
    return merged


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
