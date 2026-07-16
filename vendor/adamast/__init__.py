"""AdaMAST: induce a failure taxonomy from an agent system's own traces.

The taxonomy is organized along three axes:

- **A** — system-level: failures any agent can produce (truncation,
  context exhaustion, looping, refusal, format violations).
- **B** — role-specific: quality failures tied to a role the system
  contains (e.g. ``Solver_*``, ``Checker_*``, ``Refiner_*``).
- **C** — domain-specific: reasoning errors that require task knowledge.

The same taxonomy can then be used to classify new traces.

Example
-------

    from vendor.adamast import generate_taxonomy, classify_trace

    taxonomy = generate_taxonomy("traces.jsonl", output_dir="./out")
    diagnosis = classify_trace(taxonomy, new_trace)
    print(diagnosis.code, diagnosis.label)
"""

from vendor.adamast.api import classify_trace, classify_traces, generate_taxonomy
from vendor.adamast.classifier import Diagnosis, TaxonomyClassifier
from vendor.adamast.config import PipelineConfig
from vendor.adamast.pipeline.pipeline import ADAMAST_VERSION, TaxonomyPipeline
from vendor.adamast.traces import (
    SignalExtractor,
    TraceLoader,
    UnifiedTrace,
    load_traces,
    normalize_trace,
    normalize_traces,
)

__version__ = ADAMAST_VERSION

__all__ = [
    "__version__",
    "generate_taxonomy",
    "classify_trace",
    "classify_traces",
    "Diagnosis",
    "PipelineConfig",
    "TaxonomyClassifier",
    "TaxonomyPipeline",
    "TraceLoader",
    "UnifiedTrace",
    "SignalExtractor",
    "load_traces",
    "normalize_trace",
    "normalize_traces",
]
