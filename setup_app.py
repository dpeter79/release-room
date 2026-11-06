#!/usr/bin/env python3
"""Sets Release Room up for your own apps. Run it again to add another app: it keeps what's already done.

    make setup

It fills in .env, lists your apps from App Store Connect, checks each app's repo, limits what agents can read,
registers @asc and saves a template with your answers in it. You choose Use on that template in Switch Console,
and it then points @asc at the new room. It never writes to App Store Connect.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "demo")]

from lock_agents import lock  # noqa: E402
from save_template import AGENTS, fixed_template, save  # noqa: E402
from setup import local_api, register_asc  # noqa: E402
from switch_op import op  # noqa: E402

ENV = ROOT / ".env"
APPS = ROOT / "apps.json"
ROOMS = ROOT / "rooms.json"
KEYS = pathlib.Path.home() / ".appstoreconnect/private_keys"


def ask(question: str, default: str = "") -> str:
    answer = input(f"{question} [{default}]: " if default else f"{question}: ").strip()
    return answer or default


def check_tools() -> None:
    missing = [hint for tool, hint in (("uv", "uv (https://docs.astral.sh/uv/) runs the App Store Connect commands"),
                                       ("claude", "Claude Code (https://code.claude.com/docs) runs the agents")) if not shutil.which(tool)]
    if missing:
        raise SystemExit("Install these first:\n  " + "\n  ".join(missing))
    if not shutil.which("xcodegen"):
        print("No xcodegen: @release can't build or upload, but the rest of a release works once you've uploaded a build another way.")


def value(text: str, key: str) -> str:
    found = re.search(rf"^{key}=(.*)$", text, re.M)
    return found[1].strip() if found else ""


def setup_env() -> None:
    """Asks only for what it can't find. Nothing here is printed back."""
    fresh = not ENV.exists()
    text = (ROOT / ".env.example").read_text() if fresh else ENV.read_text()
    if value(text, "ASC_MOCK"):
        raise SystemExit("This clone's .env runs the demo against a fake. Clone a fresh copy for your own apps.")
    new = {}
    if not value(text, "APP_STORE_KEY_ID"):
        keys = sorted(KEYS.glob("AuthKey_*.p8"))
        if len(keys) == 1:
            new["APP_STORE_KEY_ID"] = keys[0].stem.removeprefix("AuthKey_")
            print(f"Using the App Store Connect key in {keys[0]}")
        else:
            print("Create a team key at https://appstoreconnect.apple.com/access/integrations/api, and keep the .p8 file private.")
            new["APP_STORE_KEY_ID"] = ask("Key ID")
    key_id = new.get("APP_STORE_KEY_ID") or value(text, "APP_STORE_KEY_ID")
    if not value(text, "APP_STORE_P8_PATH") and not (KEYS / f"AuthKey_{key_id}.p8").exists():
        new["APP_STORE_P8_PATH"] = str(pathlib.Path(ask("Path to the .p8 key file")).expanduser())
    if not value(text, "APP_STORE_ISSUER_ID"):
        new["APP_STORE_ISSUER_ID"] = ask("Issuer ID, from the same App Store Connect page")
    if fresh or not value(text, "SWITCH_API"):  # .env.example's port is only an example
        new["SWITCH_API"] = local_api() or ask("Your Switch server's address", value(text, "SWITCH_API"))
    for key, val in new.items():
        text = re.sub(rf"^{key}=.*$", lambda _: f"{key}={val}", text, flags=re.M)
    ENV.write_text(text)
    os.chmod(ENV, 0o600)


def apple_apps() -> list[dict]:
    out = subprocess.run([ROOT / "bin/asc", "apps"], capture_output=True, text=True, cwd=ROOT)
    if out.returncode:
        raise SystemExit(f"App Store Connect refused: {out.stderr.strip()[-300:]}\nCheck the key ID, issuer ID and .p8 file in .env, then run this again.")
    return [json.loads(line) for line in out.stdout.splitlines()]


def repo_report(repo: pathlib.Path) -> list[str]:
    """What the app's repo has, and what happens where it doesn't. Nothing here stops the setup."""
    locales = sorted(p.parent.name for p in repo.glob("marketing/localization/*/strings.json"))
    return [f"  {len(locales)} language files" if locales else "  No language files: @release starts them from your newest version on Apple",
            "  App Review notes" if (repo / "marketing/app-review-notes.md").exists() else "  No App Review notes file: @release offers to create one",
            "  project.yml" if (repo / "project.yml").exists() else "  No project.yml: @release can't build or upload, so upload your builds another way"]


def pick_app(apps: list[dict], done: list[dict]) -> dict | None:
    todo = [a for a in apps if a["id"] not in {d["app"] for d in done}]
    if not todo:
        return None
    print("\nYour apps:")
    for i, app in enumerate(todo, 1):
        print(f"  {i}. {app['name']}")
    answer = ask("Which one? Empty to stop adding apps" if done else "Which one?")
    if not answer:
        return None
    if not answer.isdigit() or not 1 <= int(answer) <= len(todo):
        raise SystemExit(f"Expected a number from 1 to {len(todo)}. Run this again.")
    return todo[int(answer) - 1]


def describe_app(app: dict, done: list[dict]) -> dict:
    while True:
        repo = pathlib.Path(ask(f"Path to {app['name']}'s git repo")).expanduser().resolve()
        if (repo / ".git").exists():
            break
        print(f"{repo} isn't a git repo.")
    print("\n".join(repo_report(repo)))
    short = app["name"].split(":")[0].strip()
    locales = sorted(p.parent.name for p in repo.glob("marketing/localization/*/strings.json"))
    source = "en-US" if not locales or "en-US" in locales else ask(f"Which language is the App Store text written in first? ({', '.join(locales)})")
    return {"app": app["id"], "name": ask("Name to use in the room", short),
            "slug": ask("Room prefix, lowercase, so the room is <prefix>-release", re.sub(r"[^a-z0-9-]", "", short.split()[0].lower()) or "app"),
            "repo": str(repo), "source": source,
            "checks": ask("Which language will you check translations in?", done[-1]["checks"] if done else "English")}


def room_of(entry: dict, rooms: list[dict]) -> dict | None:
    return next((r for r in rooms if r["name"] == f"{entry['slug']}-release" and not r["archived"]), None)


def connect(apps: list[dict]) -> list[dict]:
    """Points @asc at each app's room. Returns the apps that have no room yet."""
    rooms = op("list_all_rooms")
    listed = json.loads(ROOMS.read_text()) if ROOMS.exists() else []
    waiting = []
    for entry in apps:
        room = room_of(entry, rooms)
        if not room:
            waiting.append(entry)
            continue
        listed = [r for r in listed if r["app"] != entry["app"]] + [{"room_id": room["room_id"], "app": entry["app"]}]
    ROOMS.write_text(json.dumps(listed) + "\n")
    return waiting


def main() -> None:
    check_tools()
    setup_env()
    apps = json.loads(APPS.read_text()) if APPS.exists() else []
    known = apple_apps()
    if not known and not apps:
        raise SystemExit("App Store Connect lists no apps for this key. Create the app there first.")
    while app := pick_app(known, apps):
        apps.append(describe_app(app, apps))
        APPS.write_text(json.dumps(apps, indent=1, ensure_ascii=False) + "\n")
    if not apps:
        raise SystemExit("No app chosen, so nothing to set up.")
    lock([pathlib.Path(a["repo"]) for a in apps])
    register_asc()
    existing = {a["name"] for a in op("list_agents")}
    waiting = connect(apps)
    for entry in waiting:
        new_agents = [n for n in AGENTS if n not in existing]
        save(f"{entry['slug']}-release-room", f"The release room for {entry['name']}",
             fixed_template(entry["name"], entry["slug"], entry["app"], entry["repo"], entry["checks"], entry["source"], "Slack", new_agents))
        created = "It creates the agents and the room. " if new_agents else "It creates the room. "
        input(f"\nIn Switch Console open Templates, then Use on {entry['slug']}-release-room. {created}Press Return when the room exists. ")
        existing |= set(new_agents)
    waiting = connect(apps)
    if waiting:
        raise SystemExit(f"No room yet for {', '.join(e['name'] for e in waiting)}. Run make setup again once it exists.")
    print(f"""
Done. Rooms: {', '.join(e['slug'] + '-release' for e in apps)}

Two things left:
  1. Open Claude Code once in this folder and accept the trust dialog, or the agents' allow rules are ignored.
  2. Start @asc somewhere it can stay running: python3 asc_poster.py

Then, in a room: @release ship {apps[-1]['name']} <version>""")


if __name__ == "__main__":
    main()
