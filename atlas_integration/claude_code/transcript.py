"""Claude Code JSONL transcript helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def transcript_size(path: Path | str | None) -> int:
    if not path:
        return 0
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def read_transcript(path: Path | str | None, *, after: int = 0) -> str:
    if not path:
        return ""
    source = Path(path)
    try:
        with source.open("rb") as handle:
            handle.seek(min(max(0, after), source.stat().st_size))
            raw = handle.read().decode("utf-8", "replace")
    except OSError:
        return ""
    chunks: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            chunks.append(line)
            continue
        chunks.extend(_text_chunks(item))
    return "\n".join(chunk for chunk in chunks if chunk.strip())


def read_raw_transcript(path: Path | str | None) -> str:
    """Return the complete Claude JSONL so learning retains tool interactions."""
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def first_user_message(path: Path | str | None) -> str:
    """Return the first human-authored message from a Claude JSONL transcript."""
    if not path:
        return ""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = item.get("message") if isinstance(item, dict) else None
        role = (
            message.get("role")
            if isinstance(message, dict)
            else item.get("type") if isinstance(item, dict) else None
        )
        if role != "user":
            continue
        chunks = list(_text_chunks(message if message is not None else item))
        text = "\n".join(chunk for chunk in chunks if chunk.strip()).strip()
        if text:
            return text
    return ""


def _text_chunks(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _text_chunks(item)
        return
    if not isinstance(value, dict):
        return

    content = value.get("content")
    if isinstance(content, (str, list, dict)):
        yield from _text_chunks(content)
    for key in (
        "message",
        "result",
        "text",
        "thinking",
        "last_assistant_message",
    ):
        item = value.get(key)
        if isinstance(item, (str, list, dict)):
            yield from _text_chunks(item)
