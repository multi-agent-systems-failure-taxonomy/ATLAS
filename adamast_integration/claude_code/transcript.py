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


def read_raw_transcript(
    path: Path | str | None,
    *,
    after: int = 0,
) -> str:
    """Return raw JSONL after a byte cursor, retaining tool interactions."""
    if not path:
        return ""
    try:
        source = Path(path)
        with source.open("rb") as handle:
            handle.seek(min(max(0, after), source.stat().st_size))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def first_user_message(
    path: Path | str | None,
    *,
    after: int = 0,
) -> str:
    """Return the first human-authored message after a byte cursor."""
    messages = user_messages(path, after=after)
    return messages[0] if messages else ""


def user_messages(
    path: Path | str | None,
    *,
    after: int = 0,
) -> list[str]:
    """Return human-authored messages in transcript order."""
    if not path:
        return []
    try:
        source = Path(path)
        with source.open("rb") as handle:
            handle.seek(min(max(0, after), source.stat().st_size))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    messages: list[str] = []
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
            messages.append(text)
    return messages


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
