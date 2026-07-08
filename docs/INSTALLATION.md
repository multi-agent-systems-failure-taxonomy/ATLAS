# Installation

ATLAS supports a dependency-light base install plus optional model-provider extras.

## Requirements

- Python 3.10 or newer
- A project directory where ATLAS can write local hook config, if you use a harness integration
- A writable trace directory

## Install from GitHub

```bash
python -m pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

## Install from a local checkout

```bash
cd /path/to/ATLAS
python -m pip install .
```

For editable development:

```bash
python -m pip install -e ".[test]"
```

## Optional provider extras

Anthropic SDK:

```bash
python -m pip install "atlas-skill[anthropic] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

AWS Bedrock Converse through boto3:

```bash
python -m pip install "atlas-skill[bedrock] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

For Bedrock, set credentials in the environment:

```bash
export AWS_BEARER_TOKEN_BEDROCK="..."
export AWS_REGION="us-east-1"
```

ATLAS reads provider credentials from the environment. Do not put tokens in `atlas.json`.

## Minimal project config

Create `atlas.json` in the project using ATLAS:

```json
{
  "version": 1,
  "trace_output": "./atlas-program",
  "trace_root": "~/.atlas-skill/traces",
  "store_dir": "~/.atlas-skill/taxonomies",
  "atlas_model": "gpt-5",
  "inherit": null,
  "generation_threshold": 5,
  "generation_stops": false,
  "skip_judge": false,
  "k_init": 10,
  "k": 20,
  "refinement_stops": false,
  "advanced_refinement": false,
  "max_retries": 3,
  "gate_exhaustion_policy": "raise",
  "recent_activity_messages": 8,
  "recent_activity_chars": 12000,
  "dashboard": true,
  "claude_code": {
    "built_in_hooks": {
      "SubagentStop": true,
      "PostToolUse": ["Bash", "Edit", "Write"]
    },
    "custom_hooks": []
  },
  "codex": {
    "hooks": {
      "SessionStart": true,
      "Stop": true,
      "SubagentStop": true,
      "PostToolUse": ["shell_command", "apply_patch"]
    }
  }
}
```

Relative paths are resolved relative to the config file.

Use `atlas_model` for ATLAS generation, checking, and refinement calls. If your task-solving program also has a model flag, keep it separate.

## Verify the install

```bash
atlas-doctor --config atlas.json
```

For harness-specific checks:

```bash
atlas-doctor --config atlas.json --claude-code
atlas-doctor --config atlas.json --codex
```

Errors mean the requested setup is not ready. Warnings usually mean ATLAS can run, but an optional integration or dependency is incomplete.
