"""Compatibility re-export for the shared ATLAS reflection parser."""

from atlas_runtime.reflection import (
    CodeAssignment,
    ReflectionResult,
    parse_reflection,
)

__all__ = ["CodeAssignment", "ReflectionResult", "parse_reflection"]
