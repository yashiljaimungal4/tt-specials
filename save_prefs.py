#!/usr/bin/env python3
"""Save alert settings sent from the app (via a GitHub issue) into alert_prefs.json."""
import json
import os
import re
import sys
from pathlib import Path

CATS = ["rubber", "blade", "racket", "balls", "clothing", "shoes", "bags", "accessories", "robots", "tables"]
body = os.environ.get("ISSUE_BODY", "")
m = re.search(r"```json\s*(\{.*?\})\s*```", body, re.S)
if not m:
    sys.exit("No settings found in the issue.")
new = json.loads(m.group(1))

f = Path(__file__).parent / "alert_prefs.json"
prefs = json.loads(f.read_text()) if f.exists() else {}


def num(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, v)) if v > 0 else None


cats = prefs.setdefault("categories", {})
for c in CATS:
    src = (new.get("categories") or {}).get(c, {})
    cats[c] = {"on": bool(src.get("on")), "max_zar": num(src.get("max_zar"), 1, 1_000_000),
               "min_pct": num(src.get("min_pct"), 0, 95) or 0}
prefs["watch_items_on"] = bool(new.get("watch_items_on", True))
extra = []
for w in (new.get("watch_extra") or [])[:30]:
    label = re.sub(r"\s+", " ", str(w.get("label", "")))[:60].strip()
    words = [x for x in re.split(r"\s+", label.lower()) if x][:6]
    if words:
        extra.append({"label": label, "search": label.lower(), "must_contain": words})
prefs["watch_extra"] = extra
prefs["stores_off"] = [str(x)[:40] for x in (new.get("stores_off") or [])][:20]
f.write_text(json.dumps(prefs, indent=1))
print("Saved alert settings:", json.dumps(prefs)[:400])
