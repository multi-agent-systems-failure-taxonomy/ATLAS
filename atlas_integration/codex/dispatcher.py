"""Single command entry point registered for Codex lifecycle hooks."""

from __future__ import annotations

import argparse
import json
import os
import sys

try:  # pragma: no cover - script execution fallback
    from atlas_integration.codex.config import CodexConfig
    from atlas_integration.codex.runtime import (
        decisions_log,
        post_tool_use,
        session_start,
        stop,
        subagent_stop,
    )
except ModuleNotFoundError:  # pragma: no cover
    from .config import CodexConfig
    from .runtime import (
        decisions_log,
        post_tool_use,
        session_start,
        stop,
        subagent_stop,
    )

HANDLERS = {
    "SessionStart": session_start,
    "Stop": stop,
    "SubagentStop": subagent_stop,
    "PostToolUse": post_tool_use,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ATLAS Codex hook dispatcher.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--event")
    args = parser.parse_args(argv)
    try:
        config = CodexConfig.load(args.config)
        if config.openai_base_url:
            os.environ["OPENAI_BASE_URL"] = config.openai_base_url
        if config.openai_api_key_env:
            value = os.environ.get(config.openai_api_key_env)
            if not value:
                raise RuntimeError(
                    f"configured openai_api_key_env "
                    f"{config.openai_api_key_env!r} is not set"
                )
            os.environ["OPENAI_API_KEY"] = value
        event = json.loads(sys.stdin.read() or "{}")
        event_name = args.event or event.get("hook_event_name")
        if event_name not in HANDLERS:
            raise RuntimeError(f"unsupported Codex hook event: {event_name!r}")
        output = HANDLERS[event_name](event, config)
        decisions_log(config, event, output)
        if output:
            print(json.dumps(output, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ATLAS Codex hook failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
