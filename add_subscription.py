#!/usr/bin/env python3
"""Add a phone's push subscription (pasted in a GitHub issue by the app) to subscriptions.json."""
import json
import os
import re
import sys
from pathlib import Path

body = os.environ.get("ISSUE_BODY", "")
m = re.search(r"```json\s*(\{.*?\})\s*```", body, re.S) or re.search(r"(\{.*\"endpoint\".*\})", body, re.S)
if not m:
    sys.exit("No subscription found in the issue.")
entry = json.loads(m.group(1))
sub = entry.get("subscription", entry)
if not str(sub.get("endpoint", "")).startswith("https://") or "keys" not in sub:
    sys.exit("That doesn't look like a valid subscription.")

f = Path(__file__).parent / "subscriptions.json"
subs = json.loads(f.read_text()) if f.exists() else []
subs = [s for s in subs if (s.get("subscription", s)).get("endpoint") != sub["endpoint"]]
subs.append({"device": entry.get("device", "phone"), "subscription": sub})
f.write_text(json.dumps(subs, indent=1))
print(f"Saved. {len(subs)} device(s) now get alerts.")
