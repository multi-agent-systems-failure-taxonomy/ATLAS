"""Placeholder end-to-end harness for the full atlas_skill pipeline.

This walks EVERY pipeline step with the *real* step code, but with the model
transport replaced by a single deterministic PLACEHOLDER stub that returns
canned, schema-valid responses. It proves each step's real code path runs and
that the handoffs (seams) between steps hold.

LIMITATIONS (read before trusting a green run):
  * This is NOT a test of model quality. The placeholder returns fixed answers;
    it says nothing about whether a real model would induce a good taxonomy,
    fire the right codes, or refine sensibly.
  * It makes NO real/paid API calls and needs NO credentials. Every model
    transport (vendored induction LLMClient, support judge, refiner) is stubbed.
  * It asserts structure, schema, seam contracts, and the outcome-blindness
    guard — not semantic correctness.

Run as a one-command smoke test (prints per-step PASS/FAIL):

    python -m tests.test_pipeline_e2e_placeholder

or under the normal suite:

    python -m unittest tests.test_pipeline_e2e_placeholder
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen

# Allow `python tests/test_pipeline_e2e_placeholder.py` as well as -m.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from finding import mast, resolver, store  # noqa: E402
from atlas_runtime.dashboard import build_server, current_taxonomy  # noqa: E402
from atlas_runtime.generation import run_generation_job  # noqa: E402
from atlas_runtime.learning_calls import (  # noqa: E402
    ANTHROPIC_OPENAI_MAX_TOKENS,
    support_model_call,
)
from atlas_runtime.lifecycle import end_session, record_trace, start_session  # noqa: E402
from atlas_runtime.lineage import TaxonomyLineage  # noqa: E402
from atlas_runtime.models import ModelProfile  # noqa: E402
from atlas_runtime.program import ProgramWorkspace  # noqa: E402
from atlas_runtime.taxonomy_check import check_taxonomy  # noqa: E402
from atlas_runtime.traces import GenerationTrace  # noqa: E402
from tests.test_learning_calls import FakeVendoredModel  # noqa: E402

TAXONOMIES = _ROOT / "tests" / "fixtures" / "taxonomies"
BASE_ID = "tax-django-orm-001"
CANONICAL = {"id", "name", "description", "category"}
# A recognized model family id. NO real call is ever made — every transport is
# stubbed. The id is only used to resolve a token-budget profile for batching.
MODEL = "claude-sonnet-4-6"

# Outcome tokens planted ONLY in trace metadata; a clean pipeline must never
# let them reach any model transport.
SECRET_OUTCOME = "SECRET_OUTCOME_LEAK"
SECRET_GATE = "SECRET_GATE_LEAK"


def _trace(problem_id: str, *, secret: bool = False) -> GenerationTrace:
    """A canonical trace. With secret=True, outcome lives in metadata only."""
    metadata = {"_format": "atlas-unified"}
    if secret:
        metadata["outcome"] = SECRET_OUTCOME
        metadata["final_gate_status"] = SECRET_GATE
    return GenerationTrace(
        problem_id=problem_id,
        task="repair the failing inclusive-boundary test",
        raw_trajectory=(
            "Agent_Solver inspected a failing test and repaired an inclusive "
            "boundary off-by-one in the range helper."
        ),
        metadata=metadata,
    )


def _copy_store(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for source in TAXONOMIES.glob("*.json"):
        (destination / source.name).write_bytes(source.read_bytes())


class PlaceholderLLM:
    """One injectable stub standing in for every model transport.

    It records every prompt it is asked to answer (``all_prompts``) so tests can
    prove no outcome/score ever reaches a model, and returns deterministic,
    schema-valid responses. Parameterizable where a step needs specific output.
    """

    def __init__(self) -> None:
        self.all_prompts: list[str] = []
        self.chat_prompts: list[str] = []
        self.judge_prompts: list[str] = []
        self.refine_prompts: list[str] = []
        self._vendored = FakeVendoredModel()
        self.judge_fire: list[str] = ["C.1", "C.2", "C.3", "C.4", "C.5"]
        self.refine_bad_once = False
        self.refine_calls = 0

    # Vendored induction transport — matches LLMClient.chat(prompt, system="").
    def chat(self, prompt: str, system: str = "") -> str:
        self.all_prompts.append(prompt)
        self.chat_prompts.append(prompt)
        return self._vendored(prompt, system)

    # Support-judge transport — matches JudgeCall(prompt, model).
    def judge(self, prompt: str, model: str) -> str:
        self.all_prompts.append(prompt)
        self.judge_prompts.append(prompt)
        units = []
        for line in prompt.splitlines():
            if line.startswith("### UNIT "):
                unit_id = line.split("### UNIT ", 1)[1].split(" ", 1)[0]
                units.append(
                    {
                        "unit_id": unit_id,
                        "codes_fired": [
                            {"code": cid, "evidence": "observed"}
                            for cid in self.judge_fire
                        ],
                    }
                )
        return json.dumps({"per_unit": units})

    # Refiner transport — matches refinement_model_call(prompt, model).
    def refine(self, prompt: str, model: str) -> str:
        self.all_prompts.append(prompt)
        self.refine_prompts.append(prompt)
        self.refine_calls += 1
        if self.refine_bad_once and self.refine_calls == 1:
            return "this is not valid json {{{"
        return json.dumps(
            {
                "repo": "django/django",
                "domain": "web-backend",
                "codes": [
                    {
                        "id": "1",
                        "name": "Refined boundary mode",
                        "description": "A sharpened, trace-grounded failure mode.",
                        "category": "Performance",
                    },
                    {
                        "id": "2",
                        "name": "Second refined mode",
                        "description": "Another concrete observable failure.",
                        "category": "Schema",
                    },
                ],
            }
        )


def _candidate(count: int = 5) -> dict:
    return {
        "repo": "",
        "domain": "",
        "codes": [
            {
                "id": f"C.{i}",
                "name": f"Mode {i}",
                "description": f"Failure mode {i} description.",
                "category": "A",
            }
            for i in range(1, count + 1)
        ],
    }


class PlaceholderPipelineE2E(unittest.TestCase):
    # ---- Step 1: Finding resolves the three --inherit forms -----------------
    def test_step1_finding_forms(self):
        self.assertEqual(resolver.resolve(resolver.ABSENT, TAXONOMIES), "none")
        self.assertEqual(resolver.resolve(BASE_ID, TAXONOMIES), BASE_ID)
        with self.assertRaises(store.TaxonomyNotFound):
            resolver.resolve("tax-does-not-exist", TAXONOMIES)

    # ---- Step 2: none resolves to the canonical 14-mode MAST floor ----------
    def test_step2_mast_fallback_canonical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = start_session(
                trace_output=root / "program",
                store_dir=root / "tax",
                trace_root=root / "traces",
                atlas_model=MODEL,
                dashboard=False,
            )
            self.assertEqual(session.delivery.taxonomy_id, mast.MAST_ID)
            codes = session.delivery.taxonomy["codes"]
            self.assertEqual(len(codes), 14)
            for code in codes:
                self.assertTrue(CANONICAL <= set(code))
                self.assertIn(
                    code["category"],
                    {"Specification", "Coordination", "Verification"},
                )

    # ---- Step 3: real vendored induction + conversion + activation ----------
    def test_step3_generation_real_pipeline(self):
        llm = PlaceholderLLM()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = ProgramWorkspace(root / "program")
            workspace.pending.append_many([_trace("gen-1", secret=True)])
            with patch(
                "vendor.atlas.pipeline.pipeline.LLMClient",
                return_value=SimpleNamespace(chat=llm.chat),
            ):
                result = run_generation_job(
                    workspace,
                    store_dir=root / "tax",
                    trace_root=root / "traces",
                    atlas_model=MODEL,
                    taxonomy_check=False,
                )
            self.assertEqual(result.action, "activated")
            record = store.fetch_by_id(result.taxonomy_id, root / "tax")
            store._validate_record(record)  # canonical schema enforced
            self.assertEqual(record["taxonomy_id"], result.taxonomy_id)
            self.assertEqual(record["domain"], "Code Repair")  # from Step 1
            for code in record["codes"]:
                self.assertEqual(set(code) & CANONICAL, CANONICAL)
                self.assertIn(code["category"], {"A", "B", "C"})  # short label
            # Outcome-blindness: nothing the stub saw mentions the planted tokens.
            blob = "\n".join(llm.chat_prompts)
            self.assertNotIn(SECRET_OUTCOME, blob)
            self.assertNotIn(SECRET_GATE, blob)

    # ---- Step 4: judge labeling, >=5 gate, one-vote-per-trace, output cap ----
    def test_step4_judge_labeling_gate_onevote_and_cap(self):
        llm = PlaceholderLLM()
        # 4a: all five fire in >=1 trace -> 5 ACTIVE -> accepted.
        with tempfile.TemporaryDirectory() as td:
            ws = ProgramWorkspace(Path(td) / "program")
            ws.pending.append_many([_trace("j1"), _trace("j2")])
            llm.judge_fire = ["C.1", "C.2", "C.3", "C.4", "C.5"]
            res = check_taxonomy(ws, _candidate(), atlas_model=MODEL, judge_call=llm.judge)
            self.assertTrue(res.accepted)
            self.assertEqual(len(res.active_codes), 5)
            self.assertTrue(
                all(c["support_tier"] == "ACTIVE" for c in res.candidate["codes"])
            )

        # 4b: only two fire -> 2 ACTIVE / 3 PROVISIONAL -> rejected (<5).
        with tempfile.TemporaryDirectory() as td:
            ws = ProgramWorkspace(Path(td) / "program")
            ws.pending.append_many([_trace("j1")])
            llm.judge_fire = ["C.1", "C.2"]
            res = check_taxonomy(ws, _candidate(), atlas_model=MODEL, judge_call=llm.judge)
            self.assertFalse(res.accepted)
            self.assertEqual(res.active_codes, ["C.1", "C.2"])
            tiers = {c["id"]: c["support_tier"] for c in res.candidate["codes"]}
            self.assertEqual(tiers["C.1"], "ACTIVE")
            self.assertEqual(tiers["C.3"], "PROVISIONAL")

        # 4c: one trace split into chunks still contributes ONE vote per code.
        with tempfile.TemporaryDirectory() as td:
            ws = ProgramWorkspace(Path(td) / "program")
            ws.pending.append_many(
                [
                    GenerationTrace(
                        problem_id="big",
                        task="t",
                        raw_trajectory="failure boundary " * 400,
                        metadata={},
                    )
                ]
            )
            llm.judge_fire = ["C.1", "C.2", "C.3", "C.4", "C.5"]
            with patch(
                "atlas_runtime.taxonomy_check.resolve_model_profile",
                return_value=ModelProfile(
                    context_tokens=500, output_reserve_tokens=50, safety_ratio=0.9
                ),
            ):
                res = check_taxonomy(ws, _candidate(), atlas_model=MODEL, judge_call=llm.judge)
            unit_ids = [a["unit_id"] for a in res.annotations]
            self.assertTrue(any(u.startswith("big:chunk-2") for u in unit_ids))
            self.assertTrue(all(c["support"] == 1 for c in res.candidate["codes"]))

        # 4d: the real judge transport sets an explicit output-token cap.
        captured: dict = {}

        class _FakeAnthropic:
            def __init__(self):
                self.messages = SimpleNamespace(create=self._create)

            def _create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(content=[SimpleNamespace(text="{}")])

        fake_anthropic = ModuleType("anthropic")
        fake_anthropic.Anthropic = _FakeAnthropic
        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            support_model_call("judge this trace", "claude-placeholder")
        self.assertEqual(captured.get("max_tokens"), ANTHROPIC_OPENAI_MAX_TOKENS)

    # ---- Step 5: refiner runs, repair-retry recovers, no outcome leaks -------
    def test_step5_refinement_repair_retry_and_blind(self):
        llm = PlaceholderLLM()
        llm.refine_bad_once = True  # bad JSON once, good on retry
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store_dir = root / "tax"
            _copy_store(store_dir)
            with patch(
                "atlas_runtime.learning_calls.refinement_model_call", llm.refine
            ):
                session = start_session(
                    BASE_ID,
                    trace_output=root / "program",
                    store_dir=store_dir,
                    trace_root=root / "traces",
                    k_init=1,
                    refinement_stops=True,
                    atlas_model=MODEL,
                    dashboard=False,
                )
                record_trace(session, _trace("ref-1", secret=True))
                outcome = end_session(session)

            self.assertEqual(outcome.refinement.action, "activated")
            successor = outcome.refinement.taxonomy_id
            record = store.fetch_by_id(successor, store_dir)
            store._validate_record(record)
            self.assertEqual(
                TaxonomyLineage(store_dir).resolve_latest(BASE_ID), successor
            )
            # repair-retry actually fired (bad once -> good): transport hit twice.
            self.assertEqual(llm.refine_calls, 2)
            blob = "\n".join(llm.refine_prompts)
            self.assertNotIn(SECRET_OUTCOME, blob)
            self.assertNotIn(SECRET_GATE, blob)

    # ---- Step 6: activation gated on no running session; lineage links -------
    def test_step6_register_activate_gate_and_lineage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = ProgramWorkspace(root / "program")
            ws.register_session("s1", mast.MAST_ID)
            # A running session blocks activation (two loops never simultaneous).
            self.assertFalse(ws.activate_if_idle("tax-new"))
            self.assertIsNone(ws.load().get("taxonomy_id"))
            ws.finish_session("s1")
            self.assertTrue(ws.activate_if_idle("tax-new"))
            self.assertEqual(ws.load()["taxonomy_id"], "tax-new")
            # Lineage links id -> successor id.
            lineage = TaxonomyLineage(root / "tax")
            lineage.add_successor("tax-new", "tax-newer")
            self.assertEqual(lineage.resolve_latest("tax-new"), "tax-newer")

    # ---- Step 7: dashboard reads the canonical record and serves it ----------
    def test_step7_dashboard_reads_and_serves_canonical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store_dir = root / "tax"
            _copy_store(store_dir)
            ws = ProgramWorkspace(root / "program")
            ws.bind_inherited_taxonomy(BASE_ID)

            data = current_taxonomy(ws, store_dir)
            self.assertEqual(data["taxonomy_id"], BASE_ID)
            self.assertEqual(data["codes"][0]["code_id"], "1")
            for code in data["codes"]:
                self.assertIn("code_id", code)
                self.assertIn("name", code)
                self.assertIn("description", code)

            server = build_server(ws.root, store_dir, port=0)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/taxonomy") as response:
                    served = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
            self.assertEqual(served["taxonomy_id"], BASE_ID)
            self.assertEqual(served["codes"][0]["code_id"], "1")

    # ---- Seam: generation -> store -> dashboard is ONE schema (no drift) -----
    def test_seam_one_schema_no_drift(self):
        llm = PlaceholderLLM()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store_dir = root / "tax"
            workspace = ProgramWorkspace(root / "program")
            workspace.pending.append_many([_trace("seam-1")])
            with patch(
                "vendor.atlas.pipeline.pipeline.LLMClient",
                return_value=SimpleNamespace(chat=llm.chat),
            ):
                result = run_generation_job(
                    workspace,
                    store_dir=store_dir,
                    trace_root=root / "traces",
                    atlas_model=MODEL,
                    taxonomy_check=False,
                )
            produced = store.fetch_by_id(result.taxonomy_id, store_dir)
            workspace.bind_inherited_taxonomy(result.taxonomy_id)
            served = current_taxonomy(workspace, store_dir)
            # The ids generation produced == the store kept == the dashboard reads.
            produced_ids = [c["id"] for c in produced["codes"]]
            served_ids = [c["code_id"] for c in served["codes"]]
            self.assertEqual(produced_ids, served_ids)
            self.assertEqual(served["taxonomy_id"], result.taxonomy_id)

    # ---- Seam: an outcome in metadata never reaches ANY stub end-to-end ------
    def test_seam_end_to_end_outcome_blind(self):
        llm = PlaceholderLLM()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store_dir = root / "tax"
            _copy_store(store_dir)

            # induction path
            gen_ws = ProgramWorkspace(root / "gen")
            gen_ws.pending.append_many([_trace("e2e-gen", secret=True)])
            with patch(
                "vendor.atlas.pipeline.pipeline.LLMClient",
                return_value=SimpleNamespace(chat=llm.chat),
            ):
                run_generation_job(
                    gen_ws,
                    store_dir=root / "gentax",
                    trace_root=root / "gentraces",
                    atlas_model=MODEL,
                    taxonomy_check=False,
                )

            # judge path
            judge_ws = ProgramWorkspace(root / "judge")
            judge_ws.pending.append_many([_trace("e2e-judge", secret=True)])
            check_taxonomy(judge_ws, _candidate(), atlas_model=MODEL, judge_call=llm.judge)

            # refiner path
            with patch(
                "atlas_runtime.learning_calls.refinement_model_call", llm.refine
            ):
                session = start_session(
                    BASE_ID,
                    trace_output=root / "ref",
                    store_dir=store_dir,
                    trace_root=root / "reftraces",
                    k_init=1,
                    refinement_stops=True,
                    atlas_model=MODEL,
                    dashboard=False,
                )
                record_trace(session, _trace("e2e-ref", secret=True))
                end_session(session)

            # Not one model transport, on any path, ever saw the planted tokens.
            everything = "\n".join(llm.all_prompts)
            self.assertNotIn(SECRET_OUTCOME, everything)
            self.assertNotIn(SECRET_GATE, everything)
            self.assertTrue(llm.chat_prompts and llm.judge_prompts and llm.refine_prompts)

    # ---- Seam: none -> MAST at every consumer -------------------------------
    def test_seam_none_to_mast_every_consumer(self):
        # Finding decision is the literal "none"; the floor is applied downstream.
        self.assertEqual(resolver.resolve(resolver.ABSENT, TAXONOMIES), "none")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # consumer 1: session binding
            session = start_session(
                trace_output=root / "program",
                store_dir=root / "tax",
                trace_root=root / "traces",
                atlas_model=MODEL,
                dashboard=False,
            )
            self.assertEqual(session.delivery.taxonomy_id, mast.MAST_ID)
            # consumer 2: dashboard for an unbound program
            data = current_taxonomy(session.workspace, root / "tax")
            self.assertEqual(data["taxonomy_id"], mast.MAST_ID)
            self.assertEqual(len(data["codes"]), 14)


_ORDER = [
    ("1  Finding forms (none / id / missing)", "test_step1_finding_forms"),
    ("2  MAST fallback is canonical 14-mode", "test_step2_mast_fallback_canonical"),
    ("3  Generation: vendored induction + activate", "test_step3_generation_real_pipeline"),
    ("4  Judge: labels / >=5 gate / 1-vote / cap", "test_step4_judge_labeling_gate_onevote_and_cap"),
    ("5  Refinement: repair-retry + outcome-blind", "test_step5_refinement_repair_retry_and_blind"),
    ("6  Register/activate gate + lineage", "test_step6_register_activate_gate_and_lineage"),
    ("7  Dashboard reads + serves canonical", "test_step7_dashboard_reads_and_serves_canonical"),
    ("S  Seam: one schema gen->store->dashboard", "test_seam_one_schema_no_drift"),
    ("S  Seam: end-to-end outcome-blindness", "test_seam_end_to_end_outcome_blind"),
    ("S  Seam: none->MAST every consumer", "test_seam_none_to_mast_every_consumer"),
]


def run_smoke() -> int:
    print("ATLAS placeholder pipeline smoke test (no API calls, deterministic)\n")
    overall = True
    for label, method in _ORDER:
        result = unittest.TestResult()
        PlaceholderPipelineE2E(method).run(result)
        passed = result.wasSuccessful()
        print(f"  STEP {label:48s} {'PASS' if passed else 'FAIL'}")
        if not passed:
            overall = False
            for _, traceback_text in result.failures + result.errors:
                print(traceback_text)
    print("\nRESULT:", "ALL STEPS PASS" if overall else "FAILURES ABOVE")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(run_smoke())
