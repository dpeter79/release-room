"""Shared by the commands in bin/: the repo root, .env, and what an app's project.yml says."""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
_env_file = ROOT / ".env"
ENV = dict(line.split("=", 1) for line in (_env_file.read_text().splitlines() if _env_file.exists() else [])
           if "=" in line and not line.startswith("#"))


def only_release(command: str) -> None:
    cwd = pathlib.Path.cwd()
    if cwd.parent == ROOT / "agents" and cwd.name != "release":
        raise SystemExit(f"Only @release can run {command}.")


def spec_value(text: str, key: str) -> str:
    """The one value of a key in project.yml. More than one means targets differ, and a guess could ship the wrong number."""
    found = re.findall(rf'^\s*{key}:\s*"?([^"\s]+)"?\s*$', text, re.M)
    if len(set(found)) != 1:
        raise SystemExit(f"Expected one {key} in project.yml, found {found or 'none'}.")
    return found[0]


def read_spec(repo: pathlib.Path) -> str:
    path = repo / "project.yml"
    if not path.exists():
        raise SystemExit(f"No project.yml in {repo}. bin/bump and bin/upload work with XcodeGen projects; upload from Xcode instead.")
    return path.read_text()


def uploaded_builds(app: str) -> list[dict]:
    out = subprocess.run([ROOT / "bin/asc", "status", app], capture_output=True, text=True, cwd=ROOT)
    if out.returncode:
        raise SystemExit(f"Can't read App Store Connect: {out.stderr.strip()[-300:]}")
    return json.loads(out.stdout)["builds"]


def git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout
