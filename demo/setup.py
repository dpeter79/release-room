#!/usr/bin/env python3
"""Sets up the demo: a fictional app, a fake App Store Connect and invented sales, on your local Switch server.

    python3 demo/setup.py             # .env, fake state, demo repo, lock, @asc, the demo template. Safe to re-run.
    python3 demo/setup.py --connect   # after running the template: points @asc at democam-release
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lock_agents import lock  # noqa: E402
from save_template import AGENTS, fixed_template, save  # noqa: E402
from switch_op import op  # noqa: E402

ENV = ROOT / ".env"
STATE = ROOT / "state"
REPO = ROOT / "demo/DemoCam"
# Where Electron keeps Console's data on each system. Not checked on a real Linux Console: if it's wrong, make demo falls back to a key you create.
APP_DATA = pathlib.Path.home() / "Library/Application Support" if sys.platform == "darwin" else pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home() / ".config")
LOCAL_SERVER = APP_DATA / "switchdash/local-switch-server"
TEMPLATE = "democam-demo"
REGISTER_BY_HAND = """Couldn't register @asc automatically: {}
Create a registration key instead (docs/troubleshooting.md explains how), then run:
    python3 register_asc.py < file-with-the-key
Then run the same make command again."""


def local_api() -> str | None:
    """Console picks the local server's port."""
    ports = LOCAL_SERVER / "ports.json"
    return f"http://127.0.0.1:{json.loads(ports.read_text())['api']}" if ports.exists() else None


def write_env() -> None:
    if ENV.exists():
        if not re.search(r"^ASC_MOCK=.+$", ENV.read_text(), re.M):
            raise SystemExit("This clone's .env is set up for a real app, so the demo won't touch it. Clone again for the demo.")
        return
    text = (ROOT / ".env.example").read_text()
    text = re.sub(r"^ASC_MOCK=.*$", f"ASC_MOCK={STATE / 'demo-asc.json'}", text, flags=re.M)
    text = re.sub(r"^SALES_PROBE=.*$", f"SALES_PROBE={ROOT / 'demo/fake_probe.py'}", text, flags=re.M)
    if api := local_api():
        text = re.sub(r"^SWITCH_API=.*$", f"SWITCH_API={api}", text, flags=re.M)
    ENV.write_text(text)
    os.chmod(ENV, 0o600)


def write_fixtures() -> None:
    STATE.mkdir(exist_ok=True)
    if not (STATE / "demo-asc.json").exists():
        state = json.loads((ROOT / "kit/fixtures/demo-state.json").read_text())
        for build in state["builds"]:  # uploaded just now, so it doesn't look stuck
            if build["state"] == "PROCESSING":
                build["uploaded"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(timespec="seconds")
        (STATE / "demo-asc.json").write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n")
    if not (REPO / "marketing/localization").exists():
        shutil.rmtree(REPO, ignore_errors=True)
        subprocess.run(["sh", ROOT / "kit/fixtures/make-demo-repo.sh", REPO], check=True)
        shutil.copytree(ROOT / "kit/fixtures/demo-locales", REPO / "marketing/localization")
        for path in (REPO / "marketing/localization").glob("*/strings.json"):  # @l10n writes this during the demo
            strings = json.loads(path.read_text())
            strings["version"]["whatsNew"] = ""
            path.write_text(json.dumps(strings, ensure_ascii=False, indent=2) + "\n")
        shutil.copy(ROOT / "kit/fixtures/demo-review-notes.md", REPO / "marketing/app-review-notes.md")
        subprocess.run(["git", "-C", REPO, "add", "marketing"], check=True)
        subprocess.run(["git", "-C", REPO, "-c", "user.name=Demo", "-c", "user.email=demo@example.com", "commit", "-q", "-m", "Internal: add the App Store text"], check=True)


def register_asc() -> None:
    """Makes a registration key through the local server's Gateway API, then deletes it. The API isn't documented; checked on Switch 0.31."""
    if re.search(r"^SWITCH_ASC_KEY=.+$", ENV.read_text(), re.M):
        return
    secrets = LOCAL_SERVER / "native/run/switch-core.env"
    if not secrets.exists():
        raise SystemExit(REGISTER_BY_HAND.format("no local server found. In Switch Console choose Run a server on this computer."))
    cfg = dict(l.split("=", 1) for l in secrets.read_text().splitlines() if "=" in l and not l.startswith("#"))
    api = re.search(r"^SWITCH_API=(.*)$", ENV.read_text(), re.M).group(1)
    web = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(path: str, body: dict | None = None, method: str = "POST"):
        req = urllib.request.Request(api + "/gateway" + path, method=method, headers={"Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode())
        return json.load(web.open(req, timeout=30))

    try:
        call("/auth/login", {"email": cfg["GATEWAY_ADMIN_EMAIL"].strip("\"'"), "password": cfg["GATEWAY_ADMIN_PASSWORD"].strip("\"'")})
        key = call("/api-keys", {"label": "release-room demo"})
        try:
            subprocess.run([sys.executable, ROOT / "register_asc.py"], input=key["key"], text=True, check=True)
        finally:
            call(f"/api-keys/{key['id']}", method="DELETE")
    except urllib.error.HTTPError as e:
        raise SystemExit(REGISTER_BY_HAND.format(e))
    except urllib.error.URLError as e:
        raise SystemExit(f"Can't reach your Switch server: {e.reason}. Is it running in Switch Console? "
                         "If its port changed since .env was written, update SWITCH_API in .env, or delete a demo's .env and run make demo again.")
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as e:
        raise SystemExit(REGISTER_BY_HAND.format(e))


def template_yaml() -> str:
    return fixed_template("DemoCam", "democam", "1000000001", REPO, "Hungarian", "en-US", "Mattermost", list(AGENTS), prefix="demo-",
                          instructions="Follow AGENTS.md in your directory. In the demo room you go by @{name}.")


def connect() -> None:
    rooms = [r for r in op("list_all_rooms") if r["name"] == "democam-release" and not r["archived"]]
    if not rooms:
        raise SystemExit(f"No democam-release room yet. In Switch Console open Templates, then Use on {TEMPLATE}.")
    path = ROOT / "rooms.json"
    listed = json.loads(path.read_text()) if path.exists() else []
    listed = [r for r in listed if r["app"] != "1000000001"]
    listed.append({"room_id": rooms[0]["room_id"], "app": "1000000001", "release": "demo-release", "reviews": "demo-reviews"})
    path.write_text(json.dumps(listed) + "\n")
    print("@asc now reports into democam-release. Leave this running; Ctrl-C stops it.")


if __name__ == "__main__":
    if "--connect" in sys.argv:
        connect()
    else:
        write_env()
        write_fixtures()
        lock([REPO])
        register_asc()
        save(TEMPLATE, "The Release Room demo: a fictional app with its agents", template_yaml())
        print(f"Ready. In Switch Console open Templates, then Use on {TEMPLATE}. Then run: make poster")
