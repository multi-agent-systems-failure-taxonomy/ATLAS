"""Trace loading, normalization, and signal extraction."""

from vendor.atlas.traces.loader import TraceLoader, load_traces
from vendor.atlas.traces.normalizer import (
    UnifiedTrace,
    normalize_trace,
    normalize_traces,
)
from vendor.atlas.traces.signals import SignalExtractor

__all__ = [
    "TraceLoader",
    "load_traces",
    "UnifiedTrace",
    "normalize_trace",
    "normalize_traces",
    "SignalExtractor",
]
