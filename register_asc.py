#!/usr/bin/env python3
"""One-time: registers @asc with a registration key read from stdin, and stores its id and API key in .env.

    pbpaste | python3 register_asc.py

The person who created the key owns @asc, and must also own the other agents, so that @asc can start their turns.
"""
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

ENV = pathlib.Path(__file__).parent / ".env"
if not ENV.exists():
    raise SystemExit("No .env yet. Copy .env.example to .env first.")
text = ENV.read_text()
api = re.search(r"^SWITCH_API=(.*)$", text, re.M).group(1)
key = sys.stdin.read().strip()
if not key or " " in key:
    raise SystemExit("Expected a registration key on stdin.")

body = {
    "name": "asc",
    "description": "Reports App Store Connect changes and new customer reviews. Only reports, never acts.",
    "connector_type": "asc-poster",
    "integration_profile": {"connection_model": "session_passive", "message_exchange": True,
                            "pre_invocation_mediation": [], "post_invocation_mediation": [], "event_reporting": []},
}
req = urllib.request.Request(api + "/agents", data=json.dumps(body).encode(),
                             headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
try:
    agent = json.load(urllib.request.urlopen(req, timeout=30))
except urllib.error.HTTPError as e:
    raise SystemExit(f"Switch refused the registration: {e.code} {e.read().decode()[:300]}")
text = re.sub(r"^SWITCH_ASC_ID=.*$", "SWITCH_ASC_ID=" + agent["id"], text, flags=re.M)
text = re.sub(r"^SWITCH_ASC_KEY=.*$", "SWITCH_ASC_KEY=" + agent["api_key"], text, flags=re.M)
ENV.write_text(text)
os.chmod(ENV, 0o600)
print("registered @asc, id", agent["id"])
