#!/usr/bin/env bash
# Install the ATLAS Pattern-A skill into ~/.claude/skills/ and register hooks.
# Idempotent — safe to re-run; replaces existing install.
#
# Usage: bash install.sh
#
# What it does:
#   1. Copies the skill bundle to $HOME/.claude/skills/atlas-failure-modes/
#   2. Registers Stop + PostToolUse hooks in $HOME/.claude/settings.json
#   3. Verifies python3 + atlas package are available
set -euo pipefail

SKILL_NAME="atlas-failure-modes"
SKILL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/$SKILL_NAME"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

echo "==> Checking prerequisites"
# Pick whichever Python actually has the atlas package importable. On Windows,
# `python3` often resolves to a Microsoft Store stub that has nothing installed,
# so we prefer the candidate that imports atlas successfully — not the first
# one on PATH.
PY="${PYTHON:-}"
if [ -n "$PY" ]; then
    candidates=("$PY")
else
    candidates=(python python3)
fi
PY=""
for cand in "${candidates[@]}"; do
    if command -v "$cand" >/dev/null && "$cand" -c "import atlas" >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "ERROR: no python on PATH can import the atlas package. Install with:"
    echo "  python -m pip install git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
    echo "Or pass PYTHON=/path/to/python to point at a specific interpreter."
    exit 1
fi
echo "    using python: $("$PY" -c 'import sys; print(sys.executable)')"

echo "==> Installing skill to $TARGET_DIR"
mkdir -p "$(dirname "$TARGET_DIR")"
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
# Copy the active SKILL.md and the runtime python modules
cp "$SKILL_SRC/SKILL.md" "$TARGET_DIR/"
cp "$SKILL_SRC/mast_floor.md" "$TARGET_DIR/"
cp -r "$SKILL_SRC/templates" "$TARGET_DIR/"
cp "$SKILL_SRC/render.py" "$TARGET_DIR/"
cp "$SKILL_SRC/accumulator.py" "$TARGET_DIR/"
cp "$SKILL_SRC/seed_adapter.py" "$TARGET_DIR/"
cp "$SKILL_SRC/induction.py" "$TARGET_DIR/"
cp "$SKILL_SRC/refinement.py" "$TARGET_DIR/"
cp "$SKILL_SRC/config.toml" "$TARGET_DIR/"
cp -r "$SKILL_SRC/hooks" "$TARGET_DIR/"
cp "$SKILL_SRC/__init__.py" "$TARGET_DIR/"

echo "==> Registering Stop + PostToolUse hooks in $SETTINGS"
mkdir -p "$(dirname "$SETTINGS")"
PY="$PY" "$PY" - "$SETTINGS" "$TARGET_DIR" <<'PY'
import json, sys, os
settings_path = sys.argv[1]
target = sys.argv[2]
hooks_root = os.path.dirname(target)
stop = f"{os.environ.get('PY', 'python3')} {target}/hooks/stop.py"
ptu  = f"{os.environ.get('PY', 'python3')} {target}/hooks/post_tool_use.py"

if os.path.exists(settings_path):
    with open(settings_path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
else:
    data = {}

hooks = data.setdefault("hooks", {})
def _ensure(name, cmd):
    cur = hooks.setdefault(name, [])
    # Remove any prior atlas-failure-modes entries to keep idempotent
    cur = [h for h in cur if "atlas-failure-modes" not in json.dumps(h)]
    cur.append({"matcher": "*", "hooks": [{"type": "command", "command": cmd}]})
    hooks[name] = cur

_ensure("Stop", stop)
_ensure("PostToolUse", ptu)

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
print(f"updated {settings_path}")
PY

echo "==> Done."
echo "    Skill body  : $TARGET_DIR/SKILL.md"
echo "    Hooks       : $TARGET_DIR/hooks/{stop,post_tool_use}.py"
echo "    Settings    : $SETTINGS"
echo ""
echo "    To seed at startup: --seed-traces <path/to/seed.jsonl> when invoking"
echo "    the host script that imports claude_code_skill."
