"""Trace loading, normalization, and signal extraction."""

from atlas.traces.loader import TraceLoader, load_traces
from atlas.traces.normalizer import (
    UnifiedTrace,
    normalize_trace,
    normalize_traces,
)
from atlas.traces.signals import SignalExtractor

__all__ = [
    "TraceLoader",
    "load_traces",
    "UnifiedTrace",
    "normalize_trace",
    "normalize_traces",
    "SignalExtractor",
]
