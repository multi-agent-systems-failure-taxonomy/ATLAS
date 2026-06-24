"""CLI for the single-model, no-harness ATLAS integration."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from atlas_runtime.config import (
    add_config_argument,
    bool_config_value,
    config_value,
    load_atlas_config,
    require_config_value,
)
from finding import resolver, store, webview

from .runtime import SingleLLMConfig, run_single_llm


def provider_call(model: str):
    if model.startswith(("claude", "anthropic")):
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic models require `pip install atlas-skill[anthropic]`"
            ) from exc
        client = Anthropic()

        def call(messages):
            system = "\n\n".join(
                item["content"] for item in messages if item["role"] == "system"
            )
            turns = [
                item for item in messages if item["role"] in {"user", "assistant"}
            ]
            response = client.messages.create(
                model=model,
                max_tokens=8192,
                system=system,
                messages=turns,
            )
            return "".join(
                block.text for block in response.content if hasattr(block, "text")
            )

        return call

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI-compatible models require `pip install atlas-skill`"
        ) from exc
    client = OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=os.environ.get("OPENAI_API_KEY") or None,
    )

    def call(messages):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    return call


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one LLM agent task through ATLAS without a harness."
    )
    add_config_argument(parser)
    parser.add_argument("--task")
    parser.add_argument("--task-file")
    parser.add_argument("--model")
    parser.add_argument("--atlas-model")
    parser.add_argument("--trace-output")
    parser.add_argument("--store-dir")
    parser.add_argument("--trace-root")
    parser.add_argument(
        "--inherit",
        nargs="?",
        const=resolver.NO_ID,
        help=(
            "taxonomy ID to inherit; pass without a value to open the local "
            "taxonomy picker"
        ),
    )
    parser.add_argument("--problem-id")
    parser.add_argument("--dashboard", dest="dashboard", action="store_true", default=None)
    parser.add_argument("--no-dashboard", dest="dashboard", action="store_false")
    args = parser.parse_args(argv)
    try:
        config = load_atlas_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if bool(args.task) == bool(args.task_file):
        parser.error("provide exactly one of --task or --task-file")
    try:
        model = str(require_config_value(args, config, "model", "--model"))
        trace_output = Path(
            require_config_value(args, config, "trace_output", "--trace-output")
        ).resolve()
    except ValueError as exc:
        parser.error(str(exc))
    task = (
        args.task
        if args.task is not None
        else Path(args.task_file).read_text(encoding="utf-8")
    )
    store_dir = config_value(args, config, "store_dir", store.DEFAULT_STORE_DIR)
    inherit = args.inherit if args.inherit is not None else config.get("inherit")
    if inherit == resolver.NO_ID:
        selected = resolver.resolve(
            resolver.NO_ID,
            store_dir=store_dir,
            launcher=webview.run_webview,
        )
        inherit = None if selected == resolver.NONE else selected
    fields = {
        "trace_output": trace_output,
        "atlas_model": config_value(args, config, "atlas_model", model),
        "inherit": inherit,
        "dashboard": bool_config_value(args, config, "dashboard", True),
    }
    if store_dir:
        fields["store_dir"] = Path(store_dir).resolve()
    trace_root = config_value(args, config, "trace_root")
    if trace_root:
        fields["trace_root"] = Path(trace_root).resolve()
    try:
        result = run_single_llm(
            task,
            provider_call(model),
            SingleLLMConfig(**fields),
            problem_id=args.problem_id,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
