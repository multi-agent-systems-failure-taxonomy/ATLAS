"""Offline A2 tests (causal edges + leveling) — no network.

Run:  python -m ATLAS_as_a_Judge.tests.test_a2_edges
Or:   python -m pytest ATLAS_as_a_Judge/tests/test_a2_edges.py -q
"""

from __future__ import annotations

import json

from ATLAS_as_a_Judge import LLMAgent, build_causal_edges
from ATLAS_as_a_Judge.models import FailurePoint

TASK = "Verify the claim."
# minimal trajectory; content is irrelevant to edge validation (fake transport)
TRAJ = json.dumps({"claim": "c", "steps": [{"name": f"s{i}"} for i in range(8)]})


def _nodes():
    # three nodes at units 2, 4, 6 (distinct units, ascending)
    return [
        FailurePoint(0, 2, ["C.1"], "A", 2, 4, "", "merged"),
        FailurePoint(1, 4, ["C.2"], "B", 4, 6, "", "merged"),
        FailurePoint(2, 6, ["C.3"], "C", 6, 8, "", "merged"),
    ]


def _edges_transport(edges):
    def t(prompt, model):
        if "CAUSAL edges" in prompt:
            return json.dumps({"edges": edges})
        return json.dumps({"edges": []})
    return t


def test_chain_levels():
    agent = LLMAgent(transport=_edges_transport([
        {"cause": 0, "effect": 1, "rationale": "a->b"},
        {"cause": 1, "effect": 2, "rationale": "b->c"},
    ]))
    res = build_causal_edges(TASK, TRAJ, _nodes(), agent=agent)
    assert res.warnings == [], res.warnings
    assert {(e.cause, e.effect) for e in res.edges} == {(0, 1), (1, 2)}
    assert res.levels == {0: 0, 1: 1, 2: 2}
    assert res.standalone == []


def test_multiparent_levels():
    # 0 and 1 both cause 2 -> node 2 is a level-1 effect with two parents
    agent = LLMAgent(transport=_edges_transport([
        {"cause": 0, "effect": 2},
        {"cause": 1, "effect": 2},
    ]))
    res = build_causal_edges(TASK, TRAJ, _nodes(), agent=agent)
    assert res.levels == {0: 0, 1: 0, 2: 1}
    assert res.standalone == []


def test_non_forward_edge_pruned():
    # cause node 2 (unit 6) -> effect node 0 (unit 2) is backward in time
    agent = LLMAgent(transport=_edges_transport([
        {"cause": 2, "effect": 0, "rationale": "backwards"},
    ]))
    res = build_causal_edges(TASK, TRAJ, _nodes(), agent=agent)
    assert res.edges == []
    assert any("non-forward" in w for w in res.warnings)
    assert set(res.standalone) == {0, 1, 2}


def test_self_edge_pruned():
    agent = LLMAgent(transport=_edges_transport([{"cause": 1, "effect": 1}]))
    res = build_causal_edges(TASK, TRAJ, _nodes(), agent=agent)
    assert res.edges == []
    assert any("self-edge" in w for w in res.warnings)


def test_unknown_node_pruned():
    agent = LLMAgent(transport=_edges_transport([{"cause": 0, "effect": 99}]))
    res = build_causal_edges(TASK, TRAJ, _nodes(), agent=agent)
    assert res.edges == []
    assert any("unknown node id" in w for w in res.warnings)


def test_no_edges_all_standalone():
    agent = LLMAgent(transport=_edges_transport([]))
    res = build_causal_edges(TASK, TRAJ, _nodes(), agent=agent)
    assert res.edges == []
    assert set(res.standalone) == {0, 1, 2}
    assert res.levels == {0: 0, 1: 0, 2: 0}


def test_single_node_no_call():
    # <=1 node: no edge possible, no LLM call needed
    one = [FailurePoint(0, 2, ["C.1"], "A", 2, 8, "", "merged")]
    res = build_causal_edges(TASK, TRAJ, one, agent=LLMAgent(transport=lambda p, m: (_ for _ in ()).throw(AssertionError("should not call"))))
    assert res.edges == []
    assert res.standalone == [0]


if __name__ == "__main__":
    test_chain_levels()
    test_multiparent_levels()
    test_non_forward_edge_pruned()
    test_self_edge_pruned()
    test_unknown_node_pruned()
    test_no_edges_all_standalone()
    test_single_node_no_call()
    print("ALL A2 OFFLINE TESTS PASSED")
