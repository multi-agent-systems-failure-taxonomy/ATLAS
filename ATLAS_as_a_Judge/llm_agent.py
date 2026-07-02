"""The LLM agent every A1 pass runs on.

Model-agnostic and defaults to Sonnet 4.5. Reuses atlas_skill's existing
transport (``atlas_runtime.learning_calls``), which routes by model id
(Anthropic / Bedrock / Gemini / OpenAI) and already does JSON repair-retry.
Inject ``transport`` to run fully offline in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from atlas_runtime.learning_calls import judge_json

# The forward pass, backward pass, and merge are all made by this agent.
DEFAULT_MODEL = "claude-sonnet-4-5"

# (combined_prompt, model) -> raw_text | None  — same shape as support_model_call.
Transport = Callable[[str, str], Optional[str]]


@dataclass
class LLMAgent:
    """A thin JSON-returning agent bound to one model.

    ``json(prompt)`` returns a parsed dict (``{}`` on failure), with bounded
    JSON repair-retry handled by ``judge_json``.
    """

    model: str = DEFAULT_MODEL
    transport: Optional[Transport] = None
    max_retries: int = 1

    def json(self, prompt: str) -> dict[str, Any]:
        return judge_json(
            prompt,
            self.model,
            max_retries=self.max_retries,
            call=self.transport,
        ) or {}
