# Edge construction guide

You are drawing directed causal edges between failure points that were already identified. Read this before deciding which edges to draw.

## The test

Draw an edge **A → B** only when all three hold:
1. A occurs before B in the trace.
2. A's content reaches B.
3. **B's fault would not have occurred had A been correct.**

Clause 3 is the real test. If B would still fail with a correct A, there is no edge.

## Cause and effect are roles, not fixed labels

A node is not permanently "a cause" or "an effect." The same node can be the **effect** of an earlier failure and the **cause** of a later one — that is a mediator, and it is normal. A node may have several incoming edges (many causes) and several outgoing edges (many effects). Draw every edge the test supports.

## Shapes you will see (in edge-list form)

- **Chain:** A → B → C — each link passes the test on its own.
- **Convergence:** A → C and B → C — several failures jointly cause one; draw an edge from each cause that actually mattered.
- **Divergence:** A → B and A → C — one failure directly causes several.
- **Mediator:** A → B and B → C — B is the effect of A and the cause of C. Expected, not an error.
- **Standalone:** no edges — a failure nothing caused and that caused nothing.

## Draw an edge WHEN

- B fails **because** it used A's wrong content (correct A ⇒ B would be fine).
- A's fault made B **choose wrongly** (wrong method, query, or tool) — the cause is A even if B's fault looks self-inflicted.

## Do NOT draw an edge WHEN

- **Independent fault** — B commits its own fault that would be wrong even on correct input. A's data flowed in, but A did not cause B's fault.
- **Over-determined** — B would fail for its own reason regardless of A. No edge from the redundant cause.
- **Common cause** — A and B both come from the same earlier failure or the same bad strategy, but neither triggers the other. Connect each to the shared cause, not to each other. *(Most common mistake — e.g. two "duplicate retrieval" failures, or two "repeated query" failures, do not cause each other; the query strategy causes both.)*
- **Mere order** — B just comes after A. Sequence is not causation.

## Rule of thumb

If you cannot answer *"would B still fail with a correct A?"* with a clean **no**, do not draw the edge.
