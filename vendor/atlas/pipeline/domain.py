"""Step 1: SystemDomainAnalyzer.

Reads a stratified sample of traces and asks the LLM to characterize the
task domain — what kind of problem this MAS is solving, what makes it
hard, what domain-specific terminology it uses, and what common error
patterns are characteristic. The output feeds C-code generation, which
needs domain context to surface reasoning failures.
"""

from __future__ import annotations

from typing import Any, Dict, List

from vendor.atlas.config import PipelineConfig
from vendor.atlas.llm import LLMClient, extract_json
from vendor.atlas.utils import format_trace_for_prompt, progress, stratified_sample


class SystemDomainAnalyzer:
    """Analyze traces to extract domain knowledge that informs C-code generation."""

    def __init__(self, client: LLMClient, config: PipelineConfig):
        self.client = client
        self.config = config

    def analyze(self, traces: List[Dict[str, Any]]) -> Dict[str, Any]:
        progress("Step 1: System Domain Analyzer")

        sample = stratified_sample(traces, self.config.traces_for_analysis)
        traces_text = "\n\n".join(format_trace_for_prompt(t, max_length=3000) for t in sample)

        prompt = f"""Analyze these system traces to understand the DOMAIN and TASK TYPE.

TRACES:
{traces_text}

Extract:
1. What domain is this? (math, code repair, incident response, etc.)
2. What makes tasks difficult in this domain?
3. Key terminology used in this domain
4. Common error patterns you observe

OUTPUT JSON:
{{
  "domain": {{
    "name": "e.g., Mathematics, Code Repair, Incident Response",
    "content_type": "e.g., proofs, numerical answers, code patches",
    "task_complexity": "What makes tasks hard in this domain"
  }},
  "subdomains": ["algebra", "geometry", "combinatorics"],
  "domain_terminology": [
    {{
      "term": "permutation",
      "meaning": "Ordered arrangement of elements",
      "error_associations": ["confused with combination"]
    }}
  ],
  "common_error_patterns": [
    {{
      "name": "off_by_one",
      "description": "Counting n items but getting n-1 or n+1",
      "detection_hints": ["fence post", "inclusive vs exclusive"]
    }}
  ],
  "correctness_criteria": [
    {{
      "criterion": "numerical_accuracy",
      "description": "Final number must be exactly correct",
      "how_to_verify": "Compare with ground truth"
    }}
  ]
}}"""

        response = self.client.chat(prompt)
        result = extract_json(response)

        progress(f"  Domain: {result.get('domain', {}).get('name', 'Unknown')}")
        progress(f"  Subdomains: {result.get('subdomains', [])}")
        progress(f"  Error patterns: {len(result.get('common_error_patterns', []))}")

        return result
