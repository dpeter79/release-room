#!/usr/bin/env python3
"""bin/sales with a fake probe: keeps one app's titles, sums money exactly, caches only finished days."""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

SOURCE = pathlib.Path(__file__).resolve().parent
tmp = pathlib.Path(tempfile.mkdtemp())
shutil.copytree(SOURCE / "bin", tmp / "bin")
probe = tmp / "probe"
probe.write_text(f"""#!{sys.executable}
import datetime, json, pathlib, sys
log = pathlib.Path({str(tmp)!r}) / "calls"
log.write_text(log.read_text() + "x" if log.exists() else "x")
day = sys.argv[3]
if datetime.date.fromisoformat(day).toordinal() % 2:
    print(json.dumps({{"status": "missing", "day": day}})); raise SystemExit
print(json.dumps({{"status": "report", "day": day, "unconverted": {{}}, "products": [
  {{"title": "DemoCam Pro", "units": 1, "proceeds": "0.10"}},
  {{"title": "DemoCam: Virtual Camera", "units": 3, "proceeds": "0.20"}},
  {{"title": "DemoCamera Plus", "units": 9, "proceeds": "5"}}]}}))
""")
probe.chmod(0o755)
(tmp / ".env").write_text(f"SALES_PROBE={probe}\nSALES_CONFIG=unused\n")


def run(*args):
    return subprocess.run([tmp / "bin/sales", *args], capture_output=True, text=True)


first = json.loads(run("democam", "4").stdout)
reports = [d for d in first["days"] if d["status"] == "report"]
missing = [d for d in first["days"] if d["status"] == "missing"]
assert len(reports) == len(missing) == 2, first["days"]
assert reports[0]["proceeds_eur"] == "0.30"  # exact, not 0.30000000000000004
assert {p["title"] for p in reports[0]["products"]} == {"DemoCam Pro", "DemoCam: Virtual Camera"}
assert first["totals"]["DemoCam Pro"] == {"units": 2, "proceeds": "0.20"}
calls = len((tmp / "calls").read_text())
assert json.loads(run("democam", "4").stdout)["totals"] == first["totals"]
assert len((tmp / "calls").read_text()) == calls + 2  # only the 2 missing days are asked again

shutil.rmtree(tmp / "state")
(tmp / ".env").write_text("SALES_PROBE=/nonexistent/probe\n")
broken = run("democam", "1")
assert broken.returncode and "Can't run the sales probe" in broken.stderr and "Traceback" not in broken.stderr, broken.stderr
print("ok: one app's titles, exact money, finished days cached, a missing probe is explained")
shutil.rmtree(tmp)
