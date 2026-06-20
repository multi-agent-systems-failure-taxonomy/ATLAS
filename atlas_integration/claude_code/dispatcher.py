"""Single command entry point registered for all Claude Code hooks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from atlas_integration.claude_code.config import ClaudeCodeConfig
    from atlas_integration.claude_code.hooks import (
        post_tool_use,
        post_tool_use_failure,
        session_end,
        session_start,
        stop,
        subagent_stop,
        task_completed,
    )
else:
    from .config import ClaudeCodeConfig
    from .hooks import (
        post_tool_use,
        post_tool_use_failure,
        session_end,
        session_start,
        stop,
        subagent_stop,
        task_completed,
    )

HANDLERS = {
    "SessionStart": session_start.handle,
    "SessionEnd": session_end.handle,
    "Stop": stop.handle,
    "TaskCompleted": task_completed.handle,
    "SubagentStop": subagent_stop.handle,
    "PostToolUse": post_tool_use.handle,
    "PostToolUseFailure": post_tool_use_failure.handle,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        event = json.load(sys.stdin)
        event_name = event.get("hook_event_name")
        if event_name not in HANDLERS:
            raise ValueError(f"unsupported Claude Code hook event {event_name!r}")
        config = ClaudeCodeConfig.load(args.config)
        if config.openai_base_url:
            os.environ["OPENAI_BASE_URL"] = config.openai_base_url
        if config.openai_api_key_env:
            value = os.environ.get(config.openai_api_key_env)
            if not value:
                raise RuntimeError(
                    f"credential environment variable "
                    f"{config.openai_api_key_env!r} is not set"
                )
            os.environ["OPENAI_API_KEY"] = value
        code, output = HANDLERS[event_name](event, config)
        if output:
            rendered = (
                json.dumps(output, ensure_ascii=False)
                if isinstance(output, dict)
                else str(output)
            )
            print(rendered, file=sys.stderr if code == 2 else sys.stdout)
        return code
    except Exception as exc:
        print(f"ATLAS Claude Code hook error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
