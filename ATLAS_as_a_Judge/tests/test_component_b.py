"""Offline Component B tests (verdict) — no network.

Run:  python -m ATLAS_as_a_Judge.tests.test_component_b
"""

from __future__ import annotations

import json

from ATLAS_as_a_Judge import LLMAgent, judge_correctness
from ATLAS_as_a_Judge.models import A2Result, CausalEdge, FailurePoint


def _graph():
    nodes = [
        FailurePoint(0, 1, ["MAST-1"], "wrong approach", 1, 3, "", "merged"),
        FailurePoint(1, 3, ["MAST-12"], "no verification", 3, 5, "", "merged"),
    ]
    edges = [CausalEdge(0, 1, "a->b")]
    return A2Result(nodes=nodes, edges=edges, levels={0: 0, 1: 1}, standalone=[], warnings=[])


def test_verdict_parsing():
    def t(prompt, model):
        assert "SOLVED its task" in prompt          # B prompt reached the model
        assert "Causal edges" in prompt             # graph rendered into the prompt
        return json.dumps({
            "verdict": "incorrect", "confidence": 0.8,
            "failure_codes": ["MAST-12"], "evidence": ["no tests were run"],
        })

    out = judge_correctness("task", "trace", _graph(), agent=LLMAgent(transport=t))
    assert out["verdict"] == "incorrect"
    assert out["confidence"] == 0.8
    assert out["failure_codes"] == ["MAST-12"]
    assert out["evidence"] == ["no tests were run"]


def test_correct_verdict():
    def t(prompt, model):
        return json.dumps({"verdict": "correct", "confidence": 0.9, "failure_codes": []})
    out = judge_correctness("task", "trace", _graph(), agent=LLMAgent(transport=t))
    assert out["verdict"] == "correct"
    assert out["confidence"] == 0.9
    assert out["failure_codes"] == []


def test_malformed_defaults_to_incorrect():
    out = judge_correctness("t", "tr", _graph(), agent=LLMAgent(transport=lambda p, m: "not json"))
    assert out["verdict"] == "incorrect"          # safe default
    assert 0.0 <= out["confidence"] <= 1.0


def test_cross_node_rendered_with_marker():
    """A cross-source node must be flagged as consensus evidence in B's prompt."""
    nodes = [FailurePoint(0, 4, ["C.21"], "consensus divergence", 4, 5, "", "cross")]
    g = A2Result(nodes=nodes, edges=[], levels={0: 0}, standalone=[0], warnings=[])

    def t(prompt, model):
        assert "CROSS-EXAMINATION" in prompt          # marker rendered
        assert "Weigh such nodes HEAVILY" in prompt   # instruction present
        return json.dumps({"verdict": "incorrect", "confidence": 0.9,
                           "failure_codes": ["C.21"]})

    out = judge_correctness("task", "trace", g, agent=LLMAgent(transport=t))
    assert out["verdict"] == "incorrect"


def test_empty_graph_still_judges():
    empty = A2Result(nodes=[], edges=[], levels={}, standalone=[], warnings=[])
    def t(prompt, model):
        assert "no failure points detected" in prompt
        return json.dumps({"verdict": "correct", "confidence": 0.6})
    out = judge_correctness("t", "tr", empty, agent=LLMAgent(transport=t))
    assert out["verdict"] == "correct"


if __name__ == "__main__":
    test_verdict_parsing()
    test_correct_verdict()
    test_malformed_defaults_to_incorrect()
    test_cross_node_rendered_with_marker()
    test_empty_graph_still_judges()
    print("ALL COMPONENT B OFFLINE TESTS PASSED")
