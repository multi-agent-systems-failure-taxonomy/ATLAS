"""Fine-grained programmatic use of ATLAS.

Demonstrates direct use of the components when the high-level
:func:`generate_taxonomy` helper isn't flexible enough — for example,
when you want to provide already-normalized traces, run only a subset
of the pipeline, or customize the model on a per-stage basis.
"""

from __future__ import annotations

from atlas import (
    PipelineConfig,
    SignalExtractor,
    TaxonomyPipeline,
    UnifiedTrace,
    normalize_traces,
)


def main():
    # Build traces in-memory from any source you like.
    raw_inputs = [
        {
            "problem_id": "demo_1",
            "task": "Compute 2 + 2.",
            "raw_trajectory": "=== SOLVER ===\nLet me compute. The answer is 4.\n=== CHECKER ===\nVerdict: ACCEPT",
            "metadata": {"mas_name": "demo", "llm_name": "gpt-4o"},
        },
        {
            "problem_id": "demo_2",
            "task": "Compute 9 * 11.",
            "raw_trajectory": "=== SOLVER ===\nProbably 89.\n=== CHECKER ===\nVerdict: ACCEPT",
            "metadata": {"mas_name": "demo", "llm_name": "gpt-4o"},
        },
    ]
    traces = [t.to_dict() for t in normalize_traces(raw_inputs)]

    # Run the LLM-free signal extractor on its own (no API key needed).
    signals = SignalExtractor(verbose=False).extract(traces)
    print("Signal summary:")
    print(SignalExtractor(verbose=False).format_for_prompt(signals))

    # If you want to run the full pipeline:
    # config = PipelineConfig(model="gpt-5-nano", max_codes=15)
    # pipeline = TaxonomyPipeline(config=config, output_dir="./demo_output")
    # taxonomy = pipeline.run(traces)
    # print(f"Generated {taxonomy['metadata']['counts']['total']} codes.")


if __name__ == "__main__":
    main()
