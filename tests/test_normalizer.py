"""Tests for trace normalization across input formats.

These exercise the format-detection logic without making any LLM calls.
"""

from __future__ import annotations

import pytest

from atlas.traces import normalize_trace, normalize_traces


def test_normalize_already_unified():
    item = {
        "problem_id": "p1",
        "task": "do it",
        "raw_trajectory": "step 1\nstep 2",
        "metadata": {"mas_name": "Test", "llm_name": "gpt-4"},
    }
    u = normalize_trace(item)
    assert u is not None
    assert u.problem_id == "p1"
    assert u.task == "do it"
    assert u.metadata["mas_name"] == "Test"
    assert u.raw_trajectory == "step 1\nstep 2"


def test_normalize_tau_bench():
    item = {
        "task_id": "T01",
        "trial": 1,
        "reward": 1.0,
        "info": {"task": {"instruction": "book a flight"}},
        "traj": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello",
             "tool_calls": [{"function": {"name": "search", "arguments": "{}"}}]},
            {"role": "tool", "name": "search", "content": "[]"},
        ],
    }
    u = normalize_trace(item)
    assert u is not None
    assert u.metadata["_format"] == "tau_bench"
    assert "T01" in u.problem_id
    assert "SUCCESS" in u.raw_trajectory


def test_normalize_conversation():
    conv = {
        "messages": [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "ok",
             "tool_calls": [{"function": {"name": "shell", "arguments": '{"command": "ls"}'}}]},
            {"role": "tool", "content": "file1\nfile2"},
        ]
    }
    u = normalize_trace(conv, problem_id="conv1", task="Run a command")
    assert u is not None
    assert u.metadata["_format"] == "conversation"
    assert u.metadata["commands_executed"] == ["ls"]
    assert u.task == "Run a command"


def test_normalize_raw_string():
    u = normalize_trace("just some trajectory text", problem_id="s1")
    assert u is not None
    assert u.problem_id == "s1"
    assert u.metadata["_format"] == "raw_string"
    assert u.raw_trajectory.startswith("just some")


def test_normalize_kira_trajectory_list():
    steps = [
        {"step_id": 1, "reasoning_content": "thinking",
         "tool_calls": [{"function_name": "execute_commands",
                         "arguments": {"commands": [{"keystrokes": "ls"}]}}],
         "observation": {"results": [{"content": "file1"}]}},
        {"step_id": 2,
         "tool_calls": [{"function_name": "task_complete", "arguments": {}}]},
    ]
    u = normalize_trace(steps, problem_id="kira1", task="task")
    assert u is not None
    assert u.metadata["_format"] == "kira_trajectory"
    assert u.metadata["commands_executed"] == ["ls"]


def test_normalize_handles_garbage():
    assert normalize_trace(None) is None
    assert normalize_trace(123) is None
    assert normalize_trace("") is None  # empty string -> None


def test_normalize_traces_iterable():
    items = [
        {"problem_id": "p1", "raw_trajectory": "a"},
        None,
        "raw text trace",
        {"problem_id": "p3", "raw_trajectory": "c"},
    ]
    out = normalize_traces(items)
    # Garbage is silently dropped; the string trace gets a synthetic id.
    assert len(out) == 3
    assert out[0].problem_id == "p1"
    assert out[2].problem_id == "p3"
