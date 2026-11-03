#!/usr/bin/env python3
"""@asc: posts App Store Connect changes and new customer reviews into Switch rooms. It only reports, never acts.

    python3 asc_poster.py [--once] [--every SECONDS] [--rooms rooms.json] [--state state]

rooms.json: [{"room_id": "...", "app": "1000000001"}], one room per app, plus optional "release" and "reviews"
agent names. The first poll only records, so a fresh start doesn't replay history.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
RELEASE, REVIEWS = "release", "reviews"
# The states the release checklist waits for. Other changes are posted for the room, with no mention, so they cost no turn.
WAITED_FOR = {"VALID", "INVALID", "FAILED", "PENDING_DEVELOPER_RELEASE", "REJECTED", "METADATA_REJECTED", "DEVELOPER_REJECTED",
              "INVALID_BINARY", "READY_FOR_DISTRIBUTION"}


def env() -> dict:
    path = ROOT / ".env"
    return dict(line.split("=", 1) for line in (path.read_text().splitlines() if path.exists() else [])
                if "=" in line and not line.startswith("#"))


def asc(*args: str) -> list[dict]:
    out = subprocess.run([ROOT / "bin/asc", *args], capture_output=True, text=True, cwd=ROOT)
    if out.returncode:
        print("asc failed:", " ".join(args), out.stderr.strip()[-300:], flush=True)
        return []
    return [json.loads(line) for line in out.stdout.split("\n") if line.strip()]  # not splitlines: reviews can hold U+2028


def post(room_id: str, content: str) -> None:
    cfg = env()
    req = urllib.request.Request(f"{cfg['SWITCH_API']}/agents/{cfg['SWITCH_ASC_ID']}/message",
                                 data=json.dumps({"room_id": room_id, "content": content}).encode(),
                                 headers={"Authorization": "Bearer " + cfg["SWITCH_ASC_KEY"],
                                          "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


def flush(outbox: pathlib.Path) -> None:
    """Sends queued posts in order. asc.py has already moved its state on, so nothing leaves until it's delivered."""
    lines = [line for line in outbox.read_text().split("\n") if line] if outbox.exists() else []
    while lines:
        try:
            post(**json.loads(lines[0]))
        except urllib.error.HTTPError as e:
            if e.code not in (400, 404, 410, 422):  # a bad key or a Switch outage: the post itself is fine
                print("post failed, will retry. Check SWITCH_ASC_KEY if this persists:", e, flush=True)
                return
            print("post refused, dropping it:", e, lines[0][:200], flush=True)
        except OSError as e:
            print("post failed, will retry:", e, flush=True)
            return
        except (ValueError, TypeError):
            print("dropping a damaged outbox line:", lines[0][:200], flush=True)
        lines.pop(0)
        outbox.write_text("".join(line + "\n" for line in lines))


def poll(room: dict, state: pathlib.Path) -> None:
    app, out = room["app"], []
    changes = asc("watch", app, "--state", str(state / f"{app}.watch.json"))
    if changes:  # one event can change several things; one post means one turn for the agent
        mention = f"@{room.get('release', RELEASE)} " if any(c["to"] in WAITED_FOR for c in changes) else ""
        out.append(mention + "\n".join(c["text"] for c in changes))
    for review in asc("customer-reviews", app, "--state", str(state / f"{app}.reviews.json")):
        out.append(f"@{room.get('reviews', REVIEWS)} new customer review {review['id']}: {review['text']}")
    with (state / "outbox.jsonl").open("a") as f:
        for content in out:
            f.write(json.dumps({"room_id": room["room_id"], "content": content}, ensure_ascii=False) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Posts App Store Connect changes and new reviews into Switch rooms.")
    p.add_argument("--once", action="store_true", help="poll once and exit")
    p.add_argument("--every", type=int, default=120, help="seconds between polls")
    p.add_argument("--rooms", default=str(ROOT / "rooms.json"), help="rooms file")
    p.add_argument("--state", default=str(ROOT / "state"), help="state folder")
    a = p.parse_args()
    state = pathlib.Path(a.state)
    state.mkdir(exist_ok=True)
    while True:
        for room in json.loads(pathlib.Path(a.rooms).read_text()):
            poll(room, state)
        flush(state / "outbox.jsonl")
        if a.once:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
