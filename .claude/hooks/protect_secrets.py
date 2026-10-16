"""PreToolUse hook: stop Claude from reading or changing secret files like .env."""

import json
import re
import sys

event = json.load(sys.stdin)
tool_input = event.get("tool_input", {})
target = tool_input.get("file_path") or tool_input.get("command") or ""

# Matches ".env" and ".env.local" etc., but not ".env.example" (safe template, no real keys).
SECRET_FILE = re.compile(r"(^|[\s/\\'\"=])\.env(?!\.example)(\.[\w-]+)?(\b|$)")

if SECRET_FILE.search(target):
    print(
        "Blocked: .env holds secrets and must not be read or changed by Claude. "
        "Use .env.example for variable names, and ask the user to edit .env themselves.",
        file=sys.stderr,
    )
    sys.exit(2)

sys.exit(0)
