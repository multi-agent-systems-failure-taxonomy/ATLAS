"""Offline A1 tests (unit-index anchoring) — no network.

Run:  python -m ATLAS_as_a_Judge.tests.test_a1_nodes
Or:   python -m pytest ATLAS_as_a_Judge/tests/test_a1_nodes.py -q
"""

from __future__ import annotations

import json

from ATLAS_as_a_Judge import LLMAgent, identify_failure_points, split_units

TASK = "Verify the claim."

# A JSON-with-steps trace: split_units -> unit 0 = context, units 1..4 = steps.
RAW = json.dumps({
    "claim": "X directed Y",
    "steps": [
        {"name": "retrieve_hop1", "query": "good query about X"},
        {"name": "summarize1", "summary": "used the wrong hypothesis about X"},   # unit 2
        {"name": "create_query_hop2", "query": "same query again, no new info"},  # consequence
        {"name": "finalize", "answer": "submitted without checking anything"},    # unit 4
    ],
})

MAST = {
    "taxonomy_id": "mast",
    "codes": [
        {"id": "MAST-1", "name": "Disobedient to task specification", "description": "deviates"},
        {"id": "MAST-12", "name": "No or incomplete verification", "description": "no checking"},
    ],
}


def test_split_units():
    units = split_units(RAW)
    assert len(units) == 5
    assert units[0].label == "context"
    assert units[2].label == "step:summarize1"


def test_split_step_markers():
    raw = ("preamble text\n--- Agent Step 1 ---\nran ls\n"
           "--- Agent Step 2 ---\nedited file\n--- Final Code Patch ---\nthe patch")
    units = split_units(raw)
    assert len(units) == 3                      # preamble + 2 steps (patch folds into step 2)
    assert units[0].label == "preamble"
    assert "Agent Step 1" in units[1].text
    assert "Final Code Patch" in units[2].text


def _fake_transport(prompt: str, model: str):
    if "FORWARD failure-point pass" in prompt:
        return json.dumps({"failure_points": [
            {"unit_index": 2, "codes": ["MAST-1"], "description": "wrong hypothesis"},
        ]})
    if "BACKWARD failure-point pass" in prompt:
        # backward catches the missing-verification fault forward missed
        return json.dumps({"failure_points": [
            {"unit_index": 2, "codes": ["MAST-1"], "description": "wrong hypothesis"},
            {"unit_index": 4, "codes": ["MAST-12"], "description": "no verification"},
        ]})
    if "MERGING two independent" in prompt:
        return json.dumps({"failure_points": [
            {"unit_index": 2, "codes": ["MAST-1"], "description": "wrong hypothesis"},
            {"unit_index": 4, "codes": ["MAST-12"], "description": "no verification"},
        ]})
    return json.dumps({"failure_points": []})


def test_two_pass_merge_and_tiling():
    agent = LLMAgent(model="claude-sonnet-4-5", transport=_fake_transport)
    res = identify_failure_points(TASK, RAW, MAST, agent=agent)

    assert res.n_units == 5
    assert res.warnings == [], res.warnings
    fps = res.failure_points
    assert len(fps) == 2, [fp.to_dict() for fp in fps]

    fp0, fp1 = fps
    assert (fp0.unit_index, fp0.codes) == (2, ["MAST-1"])
    assert (fp1.unit_index, fp1.codes) == (4, ["MAST-12"])

    # spans tile in unit space: node0 owns units [2,4); node1 owns [4,5)
    assert (fp0.start_unit, fp0.end_unit) == (2, 4)
    assert (fp1.start_unit, fp1.end_unit) == (4, 5)

    # node0's span swallows its downstream consequence (unit 3, the repeated query)
    assert "same query again" in fp0.span_text


def test_backward_only_adds_recall():
    def transport(prompt, model):
        if "FORWARD failure-point pass" in prompt:
            return json.dumps({"failure_points": []})
        if "BACKWARD failure-point pass" in prompt:
            return json.dumps({"failure_points": [
                {"unit_index": 4, "codes": ["MAST-12"], "description": "no verification"},
            ]})
        return json.dumps({"failure_points": []})

    res = identify_failure_points(TASK, RAW, MAST, agent=LLMAgent(transport=transport))
    assert len(res.failure_points) == 1
    assert res.failure_points[0].unit_index == 4
    assert res.failure_points[0].end_unit == 5


def test_out_of_range_index_dropped_with_warning():
    def transport(prompt, model):
        if "FORWARD failure-point pass" in prompt:
            return json.dumps({"failure_points": [
                {"unit_index": 99, "codes": ["MAST-1"], "description": "bad index"},
            ]})
        return json.dumps({"failure_points": []})

    res = identify_failure_points(TASK, RAW, MAST, agent=LLMAgent(transport=transport))
    assert res.failure_points == []
    assert any("out-of-range" in w for w in res.warnings)


def test_two_pass_false_skips_backward():
    calls = []
    def transport(prompt, model):
        if "FORWARD failure-point pass" in prompt:
            calls.append("fwd")
            return json.dumps({"failure_points": [{"unit_index": 2, "codes": ["MAST-1"], "description": "x"}]})
        if "BACKWARD failure-point pass" in prompt:
            calls.append("bwd")
        if "MERGING" in prompt:
            calls.append("merge")
        return json.dumps({"failure_points": []})

    res = identify_failure_points(TASK, RAW, MAST, agent=LLMAgent(transport=transport), two_pass=False)
    assert calls == ["fwd"]                       # only the forward pass ran
    assert len(res.failure_points) == 1
    assert res.failure_points[0].unit_index == 2


def test_at_end_snaps_to_last_unit():
    # model reports an end-state fault at the WRONG unit (1) with at_end=true;
    # it must be anchored to the last unit (n_units - 1 == 4) regardless.
    def transport(prompt, model):
        if "FORWARD failure-point pass" in prompt:
            return json.dumps({"failure_points": [
                {"unit_index": 1, "codes": ["MAST-12"], "description": "no final verdict", "at_end": True},
            ]})
        return json.dumps({"failure_points": []})

    res = identify_failure_points(TASK, RAW, MAST, agent=LLMAgent(transport=transport))
    assert res.n_units == 5
    assert len(res.failure_points) == 1
    fp = res.failure_points[0]
    assert fp.unit_index == 4, fp.unit_index          # snapped to the last unit
    assert fp.end_unit == 5                            # spans to end of trace


def test_cross_pass_adds_end_anchored_node():
    """Cross-examination fires only with references; node lands on last unit."""
    def transport(prompt, model):
        if "CROSS-EXAMINATION" in prompt:
            assert "[REFERENCE 1]" in prompt and "[REFERENCE 2]" in prompt
            return json.dumps({"failure_points": [
                {"unit_index": 0, "at_end": True, "codes": ["MAST-1"],
                 "description": "references converge on handling X; agent's patch lacks it"},
            ]})
        return json.dumps({"failure_points": []})

    res = identify_failure_points(
        TASK, RAW, MAST, agent=LLMAgent(transport=transport),
        two_pass=False, references=["ref patch A", "ref patch B"],
    )
    assert len(res.cross) == 1
    assert len(res.failure_points) == 1
    fp = res.failure_points[0]
    assert fp.unit_index == 4               # snapped to last unit
    assert fp.source == "cross"
    assert fp.codes == ["MAST-1"]


def test_cross_pass_skipped_without_references():
    def transport(prompt, model):
        assert "CROSS-EXAMINATION" not in prompt
        return json.dumps({"failure_points": []})

    res = identify_failure_points(TASK, RAW, MAST, agent=LLMAgent(transport=transport))
    assert res.cross == []


def test_cross_merges_codes_with_trace_node_on_same_unit():
    """A trace onset at the last unit and a cross onset union their codes."""
    def transport(prompt, model):
        if "FORWARD failure-point pass" in prompt:
            return json.dumps({"failure_points": [
                {"unit_index": 4, "codes": ["MAST-12"], "description": "no verification"},
            ]})
        if "CROSS-EXAMINATION" in prompt:
            return json.dumps({"failure_points": [
                {"at_end": True, "codes": ["MAST-1"], "description": "consensus divergence"},
            ]})
        return json.dumps({"failure_points": []})

    res = identify_failure_points(
        TASK, RAW, MAST, agent=LLMAgent(transport=transport),
        two_pass=False, references=["r1", "r2"],
    )
    assert len(res.failure_points) == 1
    assert set(res.failure_points[0].codes) == {"MAST-12", "MAST-1"}
    assert res.failure_points[0].unit_index == 4


if __name__ == "__main__":
    test_split_units()
    test_split_step_markers()
    test_two_pass_merge_and_tiling()
    test_backward_only_adds_recall()
    test_out_of_range_index_dropped_with_warning()
    test_two_pass_false_skips_backward()
    test_at_end_snaps_to_last_unit()
    test_cross_pass_adds_end_anchored_node()
    test_cross_pass_skipped_without_references()
    test_cross_merges_codes_with_trace_node_on_same_unit()
    print("ALL A1 OFFLINE TESTS PASSED")
