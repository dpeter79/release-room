#!/usr/bin/env python3
"""make setup: .env holds what was found and asked for, the template fits who exists, and @asc finds the rooms."""
import builtins
import io
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import setup_app as s  # noqa: E402

tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
real_stdout, sys.stdout = sys.stdout, io.StringIO()  # the setup talks to the person running it
s.ENV, s.APPS, s.ROOMS, s.KEYS = tmp / ".env", tmp / "apps.json", tmp / "rooms.json", tmp / "keys"
s.KEYS.mkdir()
s.local_api = lambda: "http://127.0.0.1:1234"

# One key on disk: its id is taken from the file name, and only the issuer is asked for.
(s.KEYS / "AuthKey_ABC123.p8").write_text("not a real key")
asked = []
builtins.input = lambda q: (asked.append(q), "issuer-1")[1]
s.setup_env()
text = s.ENV.read_text()
assert "APP_STORE_KEY_ID=ABC123\n" in text and "APP_STORE_ISSUER_ID=issuer-1\n" in text, text
assert "SWITCH_API=http://127.0.0.1:1234\n" in text and "APP_STORE_P8_PATH=\n" in text, text
assert len(asked) == 1 and oct(s.ENV.stat().st_mode)[-3:] == "600", (asked, oct(s.ENV.stat().st_mode))

# A second run asks nothing.
asked.clear()
s.setup_env()
assert asked == [] and s.ENV.read_text() == text

# The demo's .env is never taken over.
s.ENV.write_text("ASC_MOCK=/x\n")
try:
    s.setup_env()
    raise AssertionError("took over the demo's .env")
except SystemExit as e:
    assert "fake" in str(e)

# The repo check says what's there and what's missing.
repo = tmp / "app"
(repo / "marketing/localization/hu").mkdir(parents=True)
(repo / "marketing/localization/hu/strings.json").write_text("{}")
report = "\n".join(s.repo_report(repo))
assert "1 language files" in report and "No App Review notes" in report and "No project.yml" in report, report
assert "No language files" in "\n".join(s.repo_report(tmp))

# Choosing an app: ones already set up aren't offered, and a wrong number stops.
apps = [{"id": "1", "name": "One"}, {"id": "2", "name": "Two"}]
builtins.input = lambda q: "1"
assert s.pick_app(apps, [{"app": "1", "checks": "English"}])["id"] == "2"
assert s.pick_app(apps[:1], [{"app": "1", "checks": "English"}]) is None
builtins.input = lambda q: "9"
try:
    s.pick_app(apps, [])
    raise AssertionError("accepted a wrong number")
except SystemExit as e:
    assert "1 to 2" in str(e)

# Describing an app: a wrong path asks again, and the defaults come from the name.
git_repo = tmp / "real"
(git_repo / ".git").mkdir(parents=True)
answers = iter([str(tmp / "nope"), str(git_repo), "", "", "Hungarian"])
builtins.input = lambda q: next(answers)
entry = s.describe_app({"id": "7", "name": "FrostCam: Freeze Your Webcam"}, [])
assert entry == {"app": "7", "name": "FrostCam", "slug": "frostcam", "repo": str(git_repo), "source": "en-US", "checks": "Hungarian"}, entry

# The template creates only the agents that don't exist, and asks where to run them only if there are any.
first = s.fixed_template("A", "a", "1", repo, "Hungarian", "en-US", "Slack", list(s.AGENTS))
assert "agents: [asc, release_agent, l10n_agent, stats_agent, reviews_agent]" in first and "type: machine" in first, first[:400]
assert f'directory: "{ROOT}/agents/release"' in first and "name: release\n" in first and "aliases" not in first
later = s.fixed_template("B: x", "b", "2", repo, "Hungarian", "en-US", "Slack", [])
assert "agents: [asc, release, l10n, stats, reviews]" in later and "type: agent" not in later and "type: machine" not in later
assert 'default: "B: x"' in later, "a name with a colon must stay one value"

# Rooms: found by name, archived ones ignored, other rows kept, and a missing room reported.
s.ROOMS.write_text(json.dumps([{"room_id": "old", "app": "9"}, {"room_id": "stale", "app": "1"}]))
s.op = lambda name: [{"name": "a-release", "room_id": "new", "archived": False}, {"name": "b-release", "room_id": "gone", "archived": True}]
waiting = s.connect([{"app": "1", "slug": "a"}, {"app": "2", "slug": "b"}])
assert [w["app"] for w in waiting] == ["2"], waiting
assert json.loads(s.ROOMS.read_text()) == [{"room_id": "old", "app": "9"}, {"room_id": "new", "app": "1"}]

# bin/asc apps lists the fake's apps, and an agent can't run it.
state = tmp / "fake.json"
state.write_text((ROOT / "kit/fixtures/demo-state.json").read_text())
out = subprocess.run([sys.executable, ROOT / "kit/asc.py", "--mock", state, "apps"], capture_output=True, text=True, check=True).stdout
assert json.loads(out) == {"id": "1000000001", "name": "DemoCam"}, out
blocked = subprocess.run([ROOT / "bin/asc", "apps"], capture_output=True, text=True, cwd=ROOT / "agents/release")
assert blocked.returncode and "only run" in blocked.stderr, blocked.stderr

sys.stdout = real_stdout
print("ok: .env asks only what it must, wrong answers are caught, the template fits who exists, rooms are found by name")
