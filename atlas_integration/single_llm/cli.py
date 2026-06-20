"""CLI for the single-model, no-harness ATLAS integration."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

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
    parser.add_argument("--task")
    parser.add_argument("--task-file")
    parser.add_argument("--model", required=True)
    parser.add_argument("--atlas-model")
    parser.add_argument("--trace-output", required=True)
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
    parser.add_argument("--no-dashboard", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.task) == bool(args.task_file):
        parser.error("provide exactly one of --task or --task-file")
    task = (
        args.task
        if args.task is not None
        else Path(args.task_file).read_text(encoding="utf-8")
    )
    store_dir = (
        Path(args.store_dir).resolve()
        if args.store_dir
        else store.DEFAULT_STORE_DIR
    )
    inherit = args.inherit
    if inherit == resolver.NO_ID:
        selected = resolver.resolve(
            resolver.NO_ID,
            store_dir=store_dir,
            launcher=webview.run_webview,
        )
        inherit = None if selected == resolver.NONE else selected
    fields = {
        "trace_output": Path(args.trace_output).resolve(),
        "atlas_model": args.atlas_model or args.model,
        "inherit": inherit,
        "dashboard": not args.no_dashboard,
    }
    if args.store_dir:
        fields["store_dir"] = store_dir
    if args.trace_root:
        fields["trace_root"] = Path(args.trace_root).resolve()
    try:
        result = run_single_llm(
            task,
            provider_call(args.model),
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
