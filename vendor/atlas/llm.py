"""Unified LLM client wrapper for OpenAI- and Anthropic-compatible backends.

Both backends are addressed through a single ``LLMClient`` so the pipeline
does not have to branch on provider at every call site. JSON extraction is
also centralized here because every step ultimately parses a JSON response.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import anthropic as _anthropic_module  # type: ignore
except ImportError:
    _anthropic_module = None


class LLMClient:
    """Thin wrapper that calls either an OpenAI or Anthropic SDK client.

    The wrapped client is created lazily based on the model name. Models
    starting with ``claude`` go to the Anthropic SDK (when installed), unless
    an explicit ``OPENAI_BASE_URL`` is configured. An explicit
    OpenAI-compatible endpoint owns transport regardless of a Claude model
    name, allowing a local subscription proxy to preserve the honest model
    identity.
    """

    def __init__(self, model: str, timeout: int = 900):
        self.model = model
        self.timeout = timeout
        self._anthropic = None
        self._openai = None

        use_openai_endpoint = bool(os.environ.get("OPENAI_BASE_URL"))
        if (
            model.startswith("claude")
            and _anthropic_module is not None
            and not use_openai_endpoint
        ):
            self._anthropic = _anthropic_module.Anthropic()
        else:
            from openai import OpenAI
            self._openai = OpenAI()

    def chat(self, prompt: str, system: str = "") -> str:
        """Send a single-turn prompt and return the response text.

        Returns ``"{}"`` on error so downstream JSON extraction degrades
        gracefully rather than raising — the pipeline is built to tolerate
        an occasional empty response from any individual LLM call.
        """
        if self._anthropic is not None:
            return self._call_anthropic(prompt, system)
        return self._call_openai(prompt, system)

    def _call_anthropic(self, prompt: str, system: str) -> str:
        try:
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": 8192,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system
            response = self._anthropic.messages.create(**kwargs)
            if response.content:
                return response.content[0].text.strip()
            return "{}"
        except Exception as e:
            logger.warning("Anthropic LLM call failed: %s", e)
            return "{}"

    def _call_openai(self, prompt: str, system: str) -> str:
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self._openai.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=self.timeout,
            )
            content = response.choices[0].message.content
            return (content or "").strip()
        except Exception as e:
            logger.warning("OpenAI LLM call failed: %s", e)
            return "{}"


# ──────────────────────────────────────────────────────────────────────────
# JSON extraction
# ──────────────────────────────────────────────────────────────────────────

_JSON_PATTERNS = [
    re.compile(r"```json\s*([\s\S]*?)\s*```"),
    re.compile(r"```\s*([\s\S]*?)\s*```"),
    re.compile(r"\{[\s\S]*\}"),
]


def extract_json(text: str) -> Dict[str, Any]:
    """Best-effort JSON extraction from an LLM response.

    Tries strict parsing first, then walks through a few common patterns
    (fenced code blocks, raw braces). Returns ``{}`` on failure so callers
    can treat absent JSON as "no result" without try/except boilerplate.
    """
    if not text:
        return {}

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {"_root_list": result}
    except (json.JSONDecodeError, TypeError):
        pass

    for pattern in _JSON_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        candidate = match.group(1) if pattern.pattern.startswith("```") else match.group(0)
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"_root_list": result}
        except (json.JSONDecodeError, TypeError):
            continue

    return {}


def extract_json_list(text: str, key: str = "codes") -> List[Dict[str, Any]]:
    """Extract a list of dicts from an LLM response.

    Accepts: a top-level JSON list, a dict with the requested key, or a
    fenced JSON block. Always returns a list (possibly empty).
    """
    data = extract_json(text)
    if not data:
        return []
    if "_root_list" in data:
        items = data["_root_list"]
    else:
        items = data.get(key, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]
