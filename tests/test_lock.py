#!/usr/bin/env python3
"""lock_agents: each agent's rules close what they should and leave open what the agent needs."""
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import lock_agents as lock  # noqa: E402

base = pathlib.Path(tempfile.mkdtemp(dir=pathlib.Path.home()))
top = base / "projects"
root, app, other, far = top / "group/release-room", top / "group/app", top / "group/other", top / "far-away"
(app / "marketing/localization").mkdir(parents=True)
(app / "marketing/screenshots").mkdir()
(app / "Sources").mkdir()
root.mkdir()
other.mkdir()
far.mkdir()
lock.ROOT = root
try:
    def denied(agent):
        return set(lock.settings(agent, [app])["permissions"]["deny"])
    t = lambda p: lock.rule_path(p) + "/**"
    assert f"Read({t(other)})" in denied("stats") and f"Read({t(app)})" in denied("stats")
    assert f"Read({t(far)})" in denied("release"), "neighbours further up must close too"
    assert f"Read({t(other)})" in denied("release") and not any(lock.rule_path(app) in d for d in denied("release"))
    assert f"Read({lock.rule_path(root / '.env')})" in denied("stats")
    home_neighbour = sorted(pathlib.Path.home().iterdir())[0]
    assert any(lock.rule_path(home_neighbour) in d for d in denied("stats")), "the home folder's own contents must close"
    assert any(".claude" in d for d in denied("stats")) and any("Library" in d for d in denied("stats"))
    (root / "bin").mkdir()
    inner = root / "demo/DemoCam"
    (inner / "marketing/localization").mkdir(parents=True)
    rules = set(lock.settings("l10n", [inner])["permissions"]["deny"])
    assert f"Read({t(root / 'bin')})" not in rules, "a repo inside this one must not close it"
    assert f"Edit({t(root / 'bin')})" in rules and not any("localization" in d for d in rules)
    shutil.rmtree(root / "demo")
    shutil.rmtree(root / "bin")
    l10n = denied("l10n")
    assert f"Read({t(app / 'Sources')})" in l10n and f"Read({t(app / 'marketing/screenshots')})" in l10n
    assert not any("localization" in d for d in l10n) and f"Read({t(app)})" not in l10n
    s = lock.settings("stats", [app])["sandbox"]
    assert s["enabled"] and s["failIfUnavailable"] and not s["allowUnsandboxedCommands"] and not s["autoAllowBashIfSandboxed"]
    assert s["filesystem"]["denyRead"] == ["~/"] and s["filesystem"]["denyWrite"] == [str(app)]
    assert not any(str(root) == a for a in s["filesystem"]["allowRead"])  # the repo root holds .env
    assert lock.rule_path(pathlib.Path("/opt/x")) == "//opt/x"  # outside home still works
    assert lock.settings("l10n", [far])["permissions"]["additionalDirectories"] == [str(far / "marketing/localization")]
    print("ok: stats sees no app repo, release sees it whole, l10n only its folder, .env stays closed")
finally:
    shutil.rmtree(base)
