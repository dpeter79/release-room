#!/usr/bin/env python3
"""bin/bump and bin/upload against the fake, a temp git repo and stub build tools. Nothing here touches Apple."""
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

SOURCE = pathlib.Path(__file__).resolve().parent.parent
tmp = pathlib.Path(tempfile.mkdtemp())
root = tmp / "room"
shutil.copytree(SOURCE / "bin", root / "bin")
shutil.copytree(SOURCE / "kit", root / "kit")
fake = tmp / "asc.json"
shutil.copy(SOURCE / "kit/fixtures/demo-state.json", fake)
(root / ".env").write_text(f"ASC_MOCK={fake}\nAPP_STORE_KEY_ID=KEY\nAPP_STORE_ISSUER_ID=ISSUER\n")
(root / "agents/stats").mkdir(parents=True)
(root / "agents/release").mkdir(parents=True)
APP = "1000000001"

repo = tmp / "app"
repo.mkdir()
(repo / "project.yml").write_text('name: DemoCam\nsettings:\n  DEVELOPMENT_TEAM: TEAM\ntargets:\n  DemoCam:\n    settings:\n      INFOPLIST_FILE: App/Info.plist\n  Ext:\n    settings:\n      INFOPLIST_FILE: Ext/Info.plist\n      MARKETING_VERSION: "1.1.0"\n      CURRENT_PROJECT_VERSION: "7"\n')
for folder in ("App", "Ext"):
    (repo / folder).mkdir()
    (repo / folder / "Info.plist").write_text("<dict>\n<key>CFBundleShortVersionString</key>\n<string>1.1.0</string>\n<key>CFBundleVersion</key>\n<string>7</string>\n</dict>\n")
(repo / "marketing/localization/hu").mkdir(parents=True)
(repo / "marketing/localization/hu/strings.json").write_text("{}\n")


def git(*args):
    return subprocess.run(["git", "-C", repo, "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
                          check=True, capture_output=True, text=True).stdout


git("init", "-q")
git("config", "user.name", "T")
git("config", "user.email", "t@example.com")
git("add", ".")
git("commit", "-qm", "start")


def run(tool, *args, cwd=None):
    return subprocess.run([root / "bin" / tool, *map(str, args)], capture_output=True, text=True, cwd=cwd or root)


try:
    # Only @release can run them, and abbreviated flags are refused.
    assert "Only @release" in run("bump", APP, repo, "1.2.0", "--apply", cwd=root / "agents/stats").stderr
    assert "Only @release" in run("upload", APP, repo, "--apply", cwd=root / "agents/stats").stderr
    assert run("bump", APP, repo, "1.2.0", "--app").returncode == 2

    # The dry run changes nothing.
    out = run("bump", APP, repo, "1.2.0", cwd=root / "agents/release")
    assert "Would bump 1.1.0 (7) to 1.2.0 (8)" in out.stdout, out.stdout + out.stderr
    assert '"1.1.0"' in (repo / "project.yml").read_text() and len(git("log", "--oneline").splitlines()) == 1
    assert "isn't a version" in run("bump", APP, repo, "soon").stderr

    # A build already on App Store Connect can't be uploaded again.
    out = run("upload", APP, repo)
    assert "already uploaded" in out.stderr, out.stdout + out.stderr

    # Translations waiting to be committed go in with the bump, and the dry run says so.
    (repo / "marketing/localization/hu/strings.json").write_text('{"version": {"whatsNew": "Javitas"}}\n')
    assert "marketing/localization/hu/strings.json" in run("bump", APP, repo, "1.2.0").stdout

    # An app with several targets gets the new number in every Info.plist, and other work is left alone.
    (repo / "note.txt").write_text("someone's unfinished work")
    git("add", "note.txt")
    (repo / "note.txt").write_text("someone's unfinished work, edited")
    out = run("bump", APP, repo, "1.2.0", "--apply")
    assert "Committed" in out.stdout, out.stdout + out.stderr
    assert '"1.2.0"' in (repo / "project.yml").read_text() and '"8"' in (repo / "project.yml").read_text()
    assert set(git("show", "--name-only", "--format=", "HEAD").split()) == {"project.yml", "App/Info.plist", "Ext/Info.plist", "marketing/localization/hu/strings.json"}
    for folder in ("App", "Ext"):
        assert "<string>1.2.0</string>" in (repo / folder / "Info.plist").read_text() and "<string>8</string>" in (repo / folder / "Info.plist").read_text()
    assert "Nothing to do" in run("bump", APP, repo, "1.2.0").stdout

    # A version can't go backwards, and a failed commit puts the files back.
    assert "older" in run("bump", APP, repo, "1.0.0").stderr
    (repo / ".git/hooks/pre-commit").write_text("#!/bin/sh\nexit 1\n")
    (repo / ".git/hooks/pre-commit").chmod(0o755)
    out = run("bump", APP, repo, "1.3.0", "--apply")
    assert "Nothing to do" in out.stdout or "put back" in out.stderr, out.stdout + out.stderr
    data = json.loads(fake.read_text())
    before = fake.read_text()
    data["builds"].append({**data["builds"][0], "id": "b-8", "build": "8", "version": "1.2.0", "state": "VALID"})
    fake.write_text(json.dumps(data))
    out = run("bump", APP, repo, "1.3.0", "--apply")
    assert "put back" in out.stderr and '"1.2.0"' in (repo / "project.yml").read_text(), out.stdout + out.stderr
    (repo / ".git/hooks/pre-commit").unlink()
    fake.write_text(before)

    # Unfinished work blocks an upload, so a build always matches committed code.
    out = run("upload", APP, repo)
    assert "uncommitted" in out.stderr and "1 uncommitted" not in out.stdout, out.stdout + out.stderr
    git("reset", "-q", "--", "note.txt")
    (repo / "note.txt").unlink()
    out = run("upload", APP, repo)
    assert "Would archive and upload DemoCam 1.2.0 (8)" in out.stdout, out.stdout + out.stderr
    assert "fake App Store Connect" in run("upload", APP, repo, "--apply").stderr

    # The real steps run in order, with the key from .env, against stub tools.
    stubs, calls = tmp / "stubs", tmp / "calls.jsonl"
    stubs.mkdir()
    for tool in ("xcodegen", "xcodebuild", "xcrun"):
        (stubs / tool).write_text(f"""#!{sys.executable}
import json, os, pathlib, sys
args = sys.argv[1:]
with open({str(calls)!r}, "a") as f:
    f.write(json.dumps({{"tool": {tool!r}, "args": args, "keys": os.environ.get("API_PRIVATE_KEYS_DIR")}}) + "\\n")
if "-exportPath" in args:
    export = pathlib.Path(args[args.index("-exportPath") + 1])
    export.mkdir(parents=True)
    (export / "DemoCam.pkg").write_text("pkg")
if "--upload-app" in args:
    print(pathlib.Path({str(tmp / "altool-says")!r}).read_text())
""")
        (stubs / tool).chmod(0o755)
    home = tmp / "home"
    (home / ".appstoreconnect/private_keys").mkdir(parents=True)
    (home / ".appstoreconnect/private_keys/AuthKey_KEY.p8").write_text("not a real key")
    os.environ["PATH"], os.environ["HOME"] = f"{stubs}:{os.environ['PATH']}", str(home)
    sys.path.insert(0, str(root / "bin"))
    loader = importlib.machinery.SourceFileLoader("upload", str(root / "bin/upload"))
    spec = importlib.util.spec_from_loader("upload", loader)
    upload = importlib.util.module_from_spec(spec)
    loader.exec_module(upload)
    (tmp / "altool-says").write_text("ERROR: something went wrong, KEY")
    try:
        upload.run_upload(repo, "DemoCam", "TEAM", tmp / "work")
    except SystemExit as e:  # altool can exit 0 after a failure
        assert "Uploading failed" in str(e) and "<key>" in str(e) and ", KEY" not in str(e), e
    else:
        raise AssertionError("a failed upload was reported as a success")
    calls.unlink()
    (tmp / "altool-says").write_text("UPLOAD SUCCEEDED with no errors")
    upload.run_upload(repo, "DemoCam", "TEAM", tmp / "work")
    steps = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [s["tool"] for s in steps] == ["xcodegen", "xcodebuild", "xcodebuild", "xcrun"]
    assert steps[1]["args"][0] == "archive" and "CODE_SIGN_IDENTITY=Apple Development" in steps[1]["args"]
    assert "--upload-app" in steps[3]["args"] and "KEY" in steps[3]["args"] and steps[3]["keys"].endswith("private_keys")
    print("ok: bump and upload are @release's only, dry runs change nothing, unfinished work is safe, steps run in order")
finally:
    shutil.rmtree(tmp)
