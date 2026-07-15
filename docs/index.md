---
hide:
  - navigation
  - toc
---

<div class="atlas-home" markdown="1">

<section class="atlas-intro" markdown="1">

<p class="atlas-eyebrow">Adaptive failure taxonomies</p>

# ATLAS

ATLAS checks work, records failures, and learns a project vocabulary from
completed traces.

<div class="atlas-actions">
  <a class="atlas-action atlas-action--primary" href="INTERACTIVE_SETUP/">Install in Codex or Claude</a>
  <a class="atlas-action" href="EXAMPLE_RUN/">See a complete run</a>
  <a class="atlas-action" href="ARCHITECTURE/">View architecture</a>
</div>

<div class="atlas-runtime-rail" aria-label="ATLAS reflection sequence">
  <span><b>Observe</b> concrete activity</span>
  <span><b>Correlate</b> supported causes</span>
  <span><b>Map</b> failure codes</span>
  <span><b>Decide</b> continue or repair</span>
</div>

</section>

<section class="atlas-install" markdown="1">

## Install where you work

No `atlas.json`, external model API key, standalone host CLI, or second login
is required for the interactive path.

<div class="atlas-host-grid">

<article class="atlas-host" markdown="1">

### Codex

Install once for every Codex task:

```bash
atlas-codex-install --user-level
atlas-doctor --codex
```

[Codex guide ->](CODEX.md)

</article>

<article class="atlas-host" markdown="1">

### Claude Code

Install once for every Claude session:

```bash
atlas-claude-install --user-level
atlas-doctor --claude-code
```

[Claude Code guide ->](CLAUDE_CODE.md)

</article>

<article class="atlas-host" markdown="1">

### Your harness

Wrap a direct call or use the runtime API:

```python
from atlas_runtime import start_session
```

[Integration guide ->](INTEGRATION.md)

</article>

</div>

Install the package first:

```bash
python -m pip install --upgrade "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
```

</section>

<section class="atlas-flow" markdown="1">

## From MAST to your taxonomy

1. **Select.** A new conversation opens the local taxonomy library. Choose
   MAST, a stored project taxonomy, or No taxonomy.
2. **Work.** The main agent keeps owning the task. One completed assistant
   episode becomes one canonical trace.
3. **Learn.** At the default five-trace threshold, a native generator proposes
   an evidence-grounded taxonomy while normal work continues.
4. **Validate.** Foreground checks verify exact spans, then a separate native
   support reviewer evaluates every replacement code before atomic activation.
   The current taxonomy stays active on failure.

<div class="atlas-note">
When a project already has a learned taxonomy, choosing MAST creates an
isolated <code>fresh-*</code> task group for that conversation. The shared
project taxonomy remains unchanged.
</div>

[Read the native learning contract ->](NATIVE_LEARNING.md)

</section>

<section class="atlas-proof" markdown="1">

## Inspect what ATLAS recorded

The local dashboard shows fired codes, clean checkpoints, affected task IDs,
and evidence without changing the taxonomy record.

![ATLAS runtime dashboard showing taxonomy evidence](assets/screenshots/dashboard-demo.png)

<div class="atlas-proof-links">
  <a href="EXAMPLE_RUN/">Walk through this example</a>
  <a href="DASHBOARD/">Run the dashboard locally</a>
  <a href="TAXONOMIES/">Inspect taxonomy records</a>
</div>

</section>

<section class="atlas-start" markdown="1">

## Continue from here

| You want to... | Read... |
|---|---|
| understand the vocabulary and runtime loop | [Concepts](CONCEPTS.md) |
| see which package owns each behavior | [Architecture](ARCHITECTURE.md) |
| configure one repository | [Getting started](GETTING_STARTED.md) |
| change thresholds or providers | [Configuration reference](CONFIGURATION.md) |
| diagnose a queued worker or missing hook | [Troubleshooting](TROUBLESHOOTING.md) |
| review the research and evaluation artifacts | [Paper](atlas_paper.pdf) and [example results](EXAMPLE_RUN.md) |

</section>

</div>
