"""ATLAS Reflection Judge — multi-stage trace-analysis judge.

Ported from GEPA's ``ATLAS_Taxonomy/atlas_reflection_judge/``. Two adaptations:

  1. The LLM transport routes through atlas_skill's existing
     ``atlas_runtime.learning_calls.support_model_call`` (Anthropic + OpenAI +
     Gemini, env-driven) instead of litellm + a hardcoded Bedrock Sonnet 4.5.
  2. ``judge_model`` is a required parameter at construction time; there is no
     hidden default model.

Public API:

    AtlasReflectionJudge   : the orchestration class.
    validate_output        : schema validator for the judge's output.
    derive_selection_summary: deterministic compression from failure points
                              + relations to the selection-oriented summary.

The judge identifies failure POINTS (concrete trace locations), builds a
backward-grounded causal graph between them, and only AFTER that assigns
taxonomy codes. See ``prompts.py`` for the exact LLM instructions.
"""

from .judge import AtlasReflectionJudge
from .schema import validate_output
from .selection import derive_selection_summary

__all__ = ["AtlasReflectionJudge", "validate_output", "derive_selection_summary"]
