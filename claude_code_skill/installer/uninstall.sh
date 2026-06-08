#!/usr/bin/env bash
# Remove the ATLAS Pattern-A skill and unregister its hooks.
# Idempotent — safe to re-run.
set -euo pipefail

SKILL_NAME="atlas-failure-modes"
TARGET_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/$SKILL_NAME"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

if [ -d "$TARGET_DIR" ]; then
    echo "==> Removing $TARGET_DIR"
    rm -rf "$TARGET_DIR"
fi

if [ -f "$SETTINGS" ]; then
    echo "==> Unregistering hooks from $SETTINGS"
    PY="${PYTHON:-}"
    if [ -z "$PY" ]; then
        if   command -v python3 >/dev/null; then PY=python3
        elif command -v python  >/dev/null; then PY=python
        else echo "skipping settings rewrite: no python found"; exit 0; fi
    fi
    "$PY" - "$SETTINGS" <<'PY'
import json, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    sys.exit(0)
hooks = data.get("hooks", {})
for name in ("Stop", "PostToolUse"):
    cur = hooks.get(name, [])
    cur = [h for h in cur if "atlas-failure-modes" not in json.dumps(h)]
    if cur:
        hooks[name] = cur
    else:
        hooks.pop(name, None)
if not hooks:
    data.pop("hooks", None)
else:
    data["hooks"] = hooks
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
print(f"updated {path}")
PY
fi

echo "==> Done."
