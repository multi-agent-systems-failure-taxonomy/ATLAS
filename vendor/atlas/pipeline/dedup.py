"""Step 6: CrossCategoryDeduplicator.

After A, B, C are generated independently, this stage looks across the
three categories for true semantic duplicates. The boundary rules here
matter: a B code and an A code that describe the same *event* from
different levels of analysis are NOT duplicates — only codes that are
truly synonymous get merged.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from vendor.atlas.llm import LLMClient, extract_json
from vendor.atlas.utils import progress, truncate_text


class CrossCategoryDeduplicator:
    """Find and remove duplicate concepts that ended up in two categories."""

    def __init__(self, client: LLMClient):
        self.client = client

    def deduplicate(
        self,
        a_codes: List[Dict[str, Any]],
        b_codes: List[Dict[str, Any]],
        c_codes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        progress("\nStep 6: Cross-Category Deduplicator")

        a_codes = [c for c in a_codes if isinstance(c, dict)]
        b_codes = [c for c in b_codes if isinstance(c, dict)]
        c_codes = [c for c in c_codes if isinstance(c, dict)]

        def summarize(codes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return [{
                "code": c.get("code", ""),
                "name": str(c.get("name", ""))[:60],
                "definition": truncate_text(str(c.get("definition", "")), 150),
            } for c in codes]

        prompt = f"""Review codes across all three categories for semantic duplicates.

CATEGORY RULES:
A: System failures - agent-independent (can happen to ANY agent)
B: Role-specific QUALITY failures - WHO did their job wrong
C: Domain reasoning failures - WHY the reasoning is wrong

CRITICAL BOUNDARY RULES — read carefully before marking duplicates:
1. An A code and a B code that describe the SAME EVENT from different levels of analysis
   are NOT duplicates. Example: "Inter-agent information loss" (A) and "Checker performs
   weak validation" (B) may co-occur but describe different things — the system-level
   symptom vs the role-specific cause.
2. A B code is a duplicate of another B code ONLY if they describe the same quality failure
   for the same role. B codes for DIFFERENT roles are never duplicates of each other.
3. A C code is a duplicate of another code ONLY if it describes the exact same reasoning
   error type. A C code describing a reasoning flaw is NOT a duplicate of a B code
   describing a role doing its job poorly, even if the reasoning flaw is what caused
   the role failure.
4. Cross-category duplicates (A<->B, A<->C, B<->C) should be RARE. Only mark as duplicate
   when codes are truly synonymous — same concept, same granularity, same perspective.

CATEGORY A:
{json.dumps(summarize(a_codes), indent=2)}

CATEGORY B:
{json.dumps(summarize(b_codes), indent=2)}

CATEGORY C:
{json.dumps(summarize(c_codes), indent=2)}

Find semantic duplicates. Each concept in exactly ONE category.
Remember: cross-category duplicates should be rare. Most duplicates will be WITHIN a category.

OUTPUT JSON:
{{
  "duplicates_found": [{{"concept": "...", "found_in": ["A.1", "B.3"], "keep_in": "A.1", "remove": "B.3"}}]
}}"""

        try:
            result = extract_json(self.client.chat(prompt))
            duplicates = result.get("duplicates_found", [])
            if duplicates:
                progress(f"  Duplicates found: {len(duplicates)}")

            to_remove: set[str] = set()
            for d in duplicates:
                remove = d.get("remove")
                if isinstance(remove, str) and remove:
                    to_remove.add(remove)
                elif isinstance(remove, list):
                    for r in remove:
                        if isinstance(r, str) and r:
                            to_remove.add(r)

            return {
                "category_a": [c for c in a_codes if c.get("code", "") not in to_remove],
                "category_b": [c for c in b_codes if c.get("code", "") not in to_remove],
                "category_c": [c for c in c_codes if c.get("code", "") not in to_remove],
                "duplicates_found": duplicates,
            }
        except Exception as e:  # noqa: BLE001
            progress(f"  [!] Deduplication error: {e}")
            return {
                "category_a": a_codes,
                "category_b": b_codes,
                "category_c": c_codes,
                "duplicates_found": [],
            }
