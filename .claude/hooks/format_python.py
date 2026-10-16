"""PostToolUse hook: format and lint every Python file Claude edits."""

import json
import subprocess
import sys

event = json.load(sys.stdin)
path = event.get("tool_input", {}).get("file_path", "")

if not path.endswith(".py"):
    sys.exit(0)

result = subprocess.run(["ruff", "check", "--fix", "--quiet", path], capture_output=True, text=True)
subprocess.run(["ruff", "format", "--quiet", path])

if result.returncode != 0:
    # Exit 2 sends the remaining lint errors back to Claude so it fixes them.
    print(f"ruff found problems in {path}:\n{result.stdout}", file=sys.stderr)
    sys.exit(2)

sys.exit(0)
