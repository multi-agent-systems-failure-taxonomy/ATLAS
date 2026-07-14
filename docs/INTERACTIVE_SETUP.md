# Interactive setup

This is the shortest path for using ATLAS in ordinary Codex or Claude Code
conversations. It does not require `atlas.json` or a separate model API key.

## Choose a host

| Host | Install command | Native learning process |
|---|---|---|
| Codex | `atlas-codex-install --user-level` | Signed-in `codex exec` CLI |
| Claude Code | `atlas-claude-install --user-level` | Signed-in `claude -p` CLI |
| Both | Run both commands | Shared project/task-group taxonomy state |

The hooks and trace runtime work in the host conversation. Taxonomy generation
and refinement run in a detached, tool-disabled worker so the main agent keeps
working normally.

## 1. Install the package

Until the first PyPI release is published, install directly from GitHub:

```bash
python -m pip install --upgrade "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
```

## 2A. Enable Codex

```bash
atlas-codex-install --user-level
atlas-doctor --codex
```

The installer writes `~/.codex/hooks.json` and
`~/.codex/atlas-skill.json`, then installs the guidance skill under
`~/.agents/skills/atlas-failure-modes`. Open `/hooks` in Codex and trust the
ATLAS hooks.

Codex taxonomy learning needs a separately runnable, signed-in Codex CLI. A
desktop-app executable that exists but cannot run in a background process is
not enough. `atlas-doctor --codex` reports this as an error before generation
reaches its default five-trace threshold. Gates and trace capture can still run
with MAST while the CLI issue is repaired.

## 2B. Enable Claude Code

```bash
atlas-claude-install --user-level
atlas-doctor --claude-code
```

The installer merges ATLAS hooks into `~/.claude/settings.json` and writes
`~/.claude/atlas-skill.json`. It preserves unrelated settings and plugins.
The doctor verifies the installed hook contract and checks `claude auth status`
without making a model call.

## 3. Start a conversation

A new task begins with a compact selector:

```text
Hi! Current project: example-project
Which taxonomy should ATLAS use for this conversation?
MAST  [Recommended]
No taxonomy
```

The first substantive request is held until the choice is resolved, then
resumes automatically. `No taxonomy` disables ATLAS only for that conversation.

One completed assistant episode becomes one trace. By default:

- trace 5 queues the first learned taxonomy;
- trace 10 after activation queues the first refinement review;
- later reviews run every 20 new traces.

The active taxonomy remains stable while a worker runs. Trigger and completion
notices appear in the conversation; completion appears on the next lifecycle
event when the host cannot inject into an idle conversation.

## Shared project state

User-level installations resolve the Git root for each task and store state at:

```text
~/.atlas-skill/interactive/projects/<project-key>/groups/default/program
```

Codex and Claude Code use the same path and runtime identity, so tasks started
from the same Git project share the active taxonomy and refinement history.
Different projects remain isolated. Set a stable `project_id` when the host
workspace differs from the repository being edited.

## Remove the integration

```bash
atlas-codex-uninstall --user-level
atlas-claude-uninstall --user-level
```

Uninstalling hooks does not delete learned taxonomies or trace history under
`~/.atlas-skill`.

For explicit provider models, custom thresholds, or repository-committed hook
configuration, use the [project-local setup](GETTING_STARTED.md).
