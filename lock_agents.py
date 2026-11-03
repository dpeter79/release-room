#!/usr/bin/env python3
"""Writes each agent's git-ignored settings.local.json, limiting what it can read and change on this machine.

    python3 lock_agents.py ~/code/my-app ~/code/other-app   # the app repos the agents may read

Two layers, because neither covers both: the sandbox stops shell commands, and deny rules stop the Read and Edit
tools. Your whole home folder is closed apart from the named repos, and shell commands can't change those repos. The
commands in bin/ run outside the sandbox, since they need the keys and the network; each agent's writes still need an
Allow, and those commands limit each agent to its own. Run it again after adding a folder to your home folder.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home()
PRIVATE = [HOME / p for p in (".ssh", ".aws", ".appstoreconnect", ".claude", ".claude.json", ".config", ".gnupg", "Library", "Documents", "Desktop", "Downloads")]
# What each agent reads of an app repo: all of it, one folder, or none.
REPOS = {"release": "", "reviews": "", "l10n": "marketing/localization", "stats": None}
OPEN = ["agents", "bin", "room", "kit", "demo"]


def rule_path(path: pathlib.Path) -> str:
    """How a path is written in a permission rule: ~/x from home, //x from the filesystem root."""
    return "~/" + str(path.relative_to(HOME)) if path.is_relative_to(HOME) else "/" + str(path)


def rule(tool: str, path: pathlib.Path) -> str:
    return f"{tool}({rule_path(path)}{'/**' if path.is_dir() else ''})"


def beside(keep: list[pathlib.Path]) -> list[pathlib.Path]:
    """Every neighbour of the kept folders, at each level up to and including the home folder."""
    around, on_the_way = set(), set(keep)
    for path in keep:
        for parent in path.parents:
            if not parent.is_relative_to(HOME) or any(parent.is_relative_to(k) for k in keep):
                continue
            on_the_way.add(parent)
            around |= set(parent.iterdir())
    return sorted(around - on_the_way)


def outside(repo: pathlib.Path, sub: str | None) -> list[pathlib.Path]:
    """The parts of an app repo this agent must not read. A deny rule beats any allow, so walk down to the open part."""
    if sub is None:
        return [repo]
    closed, here = [], repo
    for part in pathlib.PurePath(sub).parts:
        if not here.is_dir():
            break
        closed += [c for c in here.iterdir() if c.name != part]
        here /= part
    return closed


def settings(agent: str, repos: list[pathlib.Path]) -> dict:
    sub = REPOS[agent]
    readable = [] if sub is None else [r / sub for r in repos]
    closed = sorted(set(beside([ROOT, *repos]) + PRIVATE)) + [p for r in repos for p in outside(r, sub)]
    deny = [rule(tool, p) for p in closed for tool in ("Read", "Edit")]
    # This repo: nothing here is an agent's to change, except a demo app that lives inside it.
    inside = [p for p in ROOT.iterdir() if p.name not in (".git",) and not any(r.is_relative_to(p) for r in repos)]
    deny += [rule("Edit", p) for p in inside] + [rule("Read", ROOT / "state"), f"Read({rule_path(ROOT / '.env')})", rule("Read", ROOT / ".git")]
    allow = []
    if agent == "l10n":
        allow = [f"Read({rule_path(p)}/**)" for p in readable] + [f"Edit({rule_path(p)}/*/strings.json)" for p in readable]
    excluded = ["../../bin/asc *", "../../bin/sales *"]
    if agent == "release":
        excluded += ["../../bin/bump *", "../../bin/upload *"]
    return {
        "permissions": {
            "additionalDirectories": [str(p) for p in readable],
            "allow": allow,
            "deny": deny,
        },
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "autoAllowBashIfSandboxed": False,
            "excludedCommands": excluded,
            "filesystem": {
                "denyRead": ["~/"],
                # Claude Code's shell setup and git's config: a sandboxed shell and git can't start without them.
                "allowRead": [str(ROOT / d) for d in OPEN] + [str(p) for p in readable] + ["~/.claude/shell-snapshots", "~/.gitconfig"],
                "denyWrite": [str(r) for r in repos],
            },
        },
    }


def lock(repos: list[pathlib.Path]) -> None:
    for agent in REPOS:
        path = ROOT / "agents" / agent / ".claude/settings.local.json"
        path.write_text(json.dumps(settings(agent, repos), indent=2) + "\n")
    print("locked", ", ".join(REPOS), "to", ", ".join(p.name for p in repos) or "this repo")


if __name__ == "__main__":
    lock([pathlib.Path(a).expanduser().resolve() for a in sys.argv[1:]])
