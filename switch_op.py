#!/usr/bin/env python3
"""Calls one Switch operation as @asc and prints the result. Prints no credentials.

    python3 switch_op.py                      # list operation names
    python3 switch_op.py NAME '{"arg": 1}'    # for example: list_all_rooms
    python3 switch_op.py --schema NAME
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from asc_poster import env


def call(path: str, body: dict | None = None):
    cfg = env()
    if not cfg.get("SWITCH_ASC_KEY"):
        raise SystemExit("@asc isn't registered yet: run make demo, or python3 register_asc.py. See docs/setup.md.")
    req = urllib.request.Request(f"{cfg['SWITCH_API']}/agents/{cfg['SWITCH_ASC_ID']}{path}",
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + cfg["SWITCH_ASC_KEY"],
                                          "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{e.code} {e.read().decode()[:600]}")
    except OSError as e:
        raise SystemExit(f"Can't reach Switch at {cfg['SWITCH_API']}: {e}. Is the server running in Switch Console?")


def op(name: str, args: dict | None = None):
    return call(f"/ops/{name}", args or {})["result"]


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv:
        print("\n".join(sorted(call("/ops")["operations"])))
    elif argv[0] == "--schema":
        operation = call("/ops")["operations"][argv[1]]
        print(operation["description"], json.dumps(operation["input_schema"].get("properties", {}), indent=1))
    else:
        print(json.dumps(op(argv[0], json.loads(argv[1]) if len(argv) > 1 else {}), indent=1, ensure_ascii=False))
