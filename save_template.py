#!/usr/bin/env python3
"""Saves room/template.yaml in Switch as app-release-room, with room/docs/*.md embedded as room documents.

Then in Switch Console: Templates, Use on app-release-room, and fill in the app's name, id and repo.
The template operations aren't in Switch's documented catalog; checked on Switch 0.31.
"""
from __future__ import annotations

import pathlib

from switch_op import op

ROOT = pathlib.Path(__file__).resolve().parent


def with_docs(yaml: str) -> str:
    block = "    docs:\n"
    for path in sorted((ROOT / "room/docs").glob("*.md")):
        title = path.read_text().splitlines()[0].lstrip("# ")
        content = "".join(f"          {line}\n" if line else "\n" for line in path.read_text().splitlines())
        block += (f"      - name: {path.stem}\n        description: \"{title}\"\n"
                  f"        instructions: \"Use it as the room instructions say.\"\n        content: |\n{content}")
    assert yaml.count("    instructions: |\n") == 1
    return yaml.replace("    instructions: |\n", block + "    instructions: |\n")


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
