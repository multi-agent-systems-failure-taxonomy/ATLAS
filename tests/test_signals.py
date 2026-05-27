"""Tests for the cheap, LLM-free behavioral signal extractor."""

from __future__ import annotations

from atlas.traces import SignalExtractor


def _trace(problem_id: str, trajectory: str) -> dict:
    return {
        "problem_id": problem_id,
        "task": "",
        "raw_trajectory": trajectory,
        "metadata": {},
    }


def test_signals_empty_and_truncation():
    traces = [
        _trace("empty", ""),
        _trace("short", "x"),
        _trace("truncated", "looking good and then,"),  # ends with comma
    ]
    sig = SignalExtractor(verbose=False).extract(traces)
    assert "empty" in sig["empty_output"]
    assert "short" in sig["empty_output"]
    assert "truncated" in sig["truncated"]


def test_signals_errors():
    traces = [
        _trace("err", "something happened\nTraceback: something exploded"),
        _trace("rate", "we got 429 too many requests"),
        _trace("ok", "normal trace ends with a complete sentence."),
    ]
    sig = SignalExtractor(verbose=False).extract(traces)
    assert "err" in sig["has_errors"]
    assert "rate" in sig["has_errors"]
    assert "ok" not in sig["has_errors"]


def test_signals_repetition():
    # Repeat a sentence enough times (and long enough) to trip the
    # sentence-level detector even if chunks slide unfavorably.
    sentence = (
        "This particular sentence reappears verbatim multiple times to "
        "trigger the looping detector reliably across test runs."
    )
    body = (sentence + "\n") * 8
    traces = [_trace("loopy", body)]
    sig = SignalExtractor(verbose=False).extract(traces)
    assert "loopy" in sig["has_repetition"]


def test_signals_refusal():
    traces = [_trace("ref", "I cannot help with that, sorry.")]
    sig = SignalExtractor(verbose=False).extract(traces)
    assert "ref" in sig["has_refusal"]


def test_signals_tool_calls():
    traces = [
        _trace("tools", "[TOOL CALL] search(\"x\")\n[TOOL RESPONSE]\nresult"),
        _trace("plain", "just thinking through the problem"),
    ]
    sig = SignalExtractor(verbose=False).extract(traces)
    assert "tools" in sig["has_tool_calls"]
    assert "plain" not in sig["has_tool_calls"]


def test_signals_format_for_prompt():
    sig = SignalExtractor(verbose=False).extract([_trace("t1", "I cannot solve this")])
    text = SignalExtractor(verbose=False).format_for_prompt(sig)
    assert "BEHAVIORAL SIGNALS" in text
    assert "Total traces analyzed" in text
