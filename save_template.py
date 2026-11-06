#!/usr/bin/env python3
"""Saves room/template.yaml in Switch as app-release-room, with room/docs/*.md embedded as room documents.

Then in Switch Console: Templates, Use on app-release-room, and fill in the app's name, id and repo.
The template operations aren't in Switch's documented catalog; checked on Switch 0.31.
"""
from __future__ import annotations

import json
import pathlib
import re

from switch_op import op

ROOT = pathlib.Path(__file__).resolve().parent
AGENTS = {"release": "Runs the App Store release", "l10n": "Translates release notes",
          "stats": "Answers questions about sales, downloads and submission status",
          "reviews": "Shows customer reviews and drafts replies for approval"}


def with_docs(yaml: str) -> str:
    block = "    docs:\n"
    for path in sorted((ROOT / "room/docs").glob("*.md")):
        title = path.read_text().splitlines()[0].lstrip("# ")
        content = "".join(f"          {line}\n" if line else "\n" for line in path.read_text().splitlines())
        block += (f"      - name: {path.stem}\n        description: \"{title}\"\n"
                  f"        instructions: \"Use it as the room instructions say.\"\n        content: |\n{content}")
    assert yaml.count("    instructions: |\n") == 1
    return yaml.replace("    instructions: |\n", block + "    instructions: |\n")


def fixed_template(app: str, slug: str, app_id: str, repo, checks: str, source: str, chat: str, new_agents: list[str], prefix: str = "",
                   instructions: str = "Follow AGENTS.md in your directory.") -> str:
    """The room template with one app's answers filled in, so Use only asks where to run it. Creates the agents in new_agents."""
    y = with_docs((ROOT / "room/template.yaml").read_text())
    q = json.dumps
    params = f"""params:
  app: {{type: string, default: {q(app)}, input: fixed}}
  slug: {{type: string, default: {q(slug)}, input: fixed}}
  app_id: {{type: string, default: {q(app_id)}, input: fixed}}
  repo: {{type: string, default: {q(str(repo))}, input: fixed}}
  checks: {{type: string, default: {q(checks)}, input: fixed}}
  source: {{type: string, default: {q(source)}, input: fixed}}
  chat: {{type: bridge, label: Messaging app, default: [{chat}, $first]}}
"""
    if new_agents:
        params += """  machine: {type: machine, label: Machine, default: [$first]}
  provider: {type: provider, description: "The first one ready is chosen. Only Claude Code has the Allow step and the folder lockdown.", default: [claude, codex, opencode, cursor, antigravity], input: advanced}
"""
    y = re.sub(r"^params:\n(?:  .*\n)+", params, y, flags=re.M)
    agents = "".join(f"""  {name}_agent:
    type: agent
    name: {prefix}{name}
    description: "{AGENTS[name]}"
    instructions: "{instructions.replace('{name}', name)}"
    provider: "{{provider}}"
    machine: "{{machine}}"
    directory: "{ROOT / 'agents' / name}"
""" for name in new_agents)
    y = y.replace("resources:\n", "resources:\n" + agents, 1)
    keys = ", ".join(f"{n}_agent" if n in new_agents else n for n in AGENTS)
    line = f"agents: [asc, {keys}]"
    if prefix:
        line += "\n    aliases: {" + ", ".join(f"{n}_agent: {n}" for n in AGENTS) + "}"
    y, count = re.subn(r"agents: \[.*\]", line, y)
    assert count == 1
    return y


def save(name: str, description: str, yaml: str) -> None:
    saved = [t for t in op("list_templates") if t["name"] == name]
    if saved:
        op("update_template", {"template_id": saved[0]["id"], "yaml": yaml})
    else:
        op("save_template", {"name": name, "description": description, "yaml": yaml})


if __name__ == "__main__":
    save("app-release-room", "One release room for one app: agents, instructions and documents",
         with_docs((ROOT / "room/template.yaml").read_text()))
    print("Saved app-release-room. In Switch Console open Templates, then Use.")
