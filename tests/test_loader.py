"""Tests for the file/directory trace loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas import TraceLoader, load_traces


def test_load_jsonl(tmp_path: Path):
    p = tmp_path / "traces.jsonl"
    items = [
        {"problem_id": "a", "raw_trajectory": "trace a", "metadata": {"mas_name": "X"}},
        {"problem_id": "b", "raw_trajectory": "trace b", "metadata": {"mas_name": "X"}},
    ]
    p.write_text("\n".join(json.dumps(i) for i in items))
    out = load_traces(p, verbose=False)
    assert len(out) == 2
    assert {t["problem_id"] for t in out} == {"a", "b"}


def test_load_json_array(tmp_path: Path):
    p = tmp_path / "traces.json"
    p.write_text(json.dumps([
        {"problem_id": "x", "raw_trajectory": "ttt", "metadata": {"mas_name": "Y"}},
    ]))
    out = load_traces(p, verbose=False)
    assert len(out) == 1
    assert out[0]["problem_id"] == "x"


def test_load_dir(tmp_path: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.json").write_text(json.dumps(
        {"problem_id": "a", "raw_trajectory": "...", "metadata": {}}
    ))
    (sub / "b.jsonl").write_text(json.dumps(
        {"problem_id": "b", "raw_trajectory": "...", "metadata": {}}
    ))
    out = load_traces(sub, verbose=False)
    assert len(out) == 2


def test_load_iterable():
    items = [
        {"problem_id": "a", "raw_trajectory": "x"},
        "string trace",
    ]
    out = TraceLoader(verbose=False).load_iterable(items)
    assert len(out) == 2


def test_load_missing_path():
    with pytest.raises(FileNotFoundError):
        load_traces("/this/does/not/exist.json", verbose=False)


def test_load_tau_bench_file(tmp_path: Path):
    p = tmp_path / "airline_gpt-4o.json"
    items = [{
        "task_id": "T1", "trial": 0, "reward": 0.0,
        "info": {"task": {"instruction": "book"}},
        "traj": [{"role": "user", "content": "hi"}],
    }]
    p.write_text(json.dumps(items))
    out = load_traces(p, verbose=False)
    assert len(out) == 1
    assert out[0]["metadata"]["_format"] == "tau_bench"
    assert out[0]["metadata"]["benchmark_name"] == "airline"
