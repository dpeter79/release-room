#!/usr/bin/env python3
"""The whole release against the fake: create, attach, notes, submit, rejection, resubmit, release,
then customer reviews and a reply.

    python3 test_asc.py
"""
import contextlib
import io
import json
import pathlib
import shutil
import tempfile

import asc
from fake_asc import Fake

HERE = pathlib.Path(__file__).resolve().parent
APP = "1000000001"


def run(state: str, *args: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        asc.main(["--mock", state, *args])
    return out.getvalue()


def version_state(state: str, version: str) -> str:
    return next(v["state"] for v in json.loads(pathlib.Path(state).read_text())["versions"] if v["version"] == version)


def main() -> None:
    tmp = pathlib.Path(tempfile.mkdtemp())
    state, watch, seen = str(tmp / "state.json"), str(tmp / "watch.json"), str(tmp / "seen.json")
    shutil.copy(HERE / "fixtures/demo-state.json", state)
    locales = str(HERE / "fixtures/demo-locales")

    assert run(state, "watch", APP, "--state", watch) == "", "first watch only records"
    assert run(state, "customer-reviews", APP, "--state", seen) == "", "first review poll only records"

    # Dry runs change nothing.
    before = pathlib.Path(state).read_text()
    assert "DRY RUN" in run(state, "create-version", APP, "1.1.0")
    assert pathlib.Path(state).read_text() == before

    run(state, "create-version", APP, "1.1.0", "--apply")
    assert version_state(state, "1.1.0") == "PREPARE_FOR_SUBMISSION"

    # The build is still processing, so attaching it must refuse until Apple finishes.
    try:
        run(state, "attach-build", APP, "1.1.0", "7", "--apply")
        raise AssertionError("attached a PROCESSING build")
    except SystemExit as e:
        assert "PROCESSING" in str(e)
    Fake(state).advance()
    events = [json.loads(line) for line in run(state, "watch", APP, "--state", watch).splitlines()]
    assert any(e["what"] == "build 1.1.0 (7)" and e["to"] == "VALID" for e in events), events
    run(state, "attach-build", APP, "1.1.0", "7", "--apply")

    out = run(state, "whatsnew", APP, "1.1.0", "--dir", locales, "--apply")
    assert "4 locale(s) updated" in out, out
    assert "unchanged" in run(state, "whatsnew", APP, "1.1.0", "hu", "--dir", locales)

    run(state, "submit", APP, "1.1.0", "--apply")
    assert version_state(state, "1.1.0") == "WAITING_FOR_REVIEW"
    Fake(state).advance()
    Fake(state).advance()  # the fixture's first outcome is a rejection
    assert version_state(state, "1.1.0") == "REJECTED"
    events = run(state, "watch", APP, "--state", watch)
    assert "REJECTED" in events, events

    out = run(state, "submit", APP, "1.1.0", "--apply")
    assert "Reusing open review submission" in out, out
    Fake(state).advance()
    Fake(state).advance()
    assert version_state(state, "1.1.0") == "PENDING_DEVELOPER_RELEASE"

    run(state, "release", APP, "1.1.0", "--apply")
    Fake(state).advance()
    assert version_state(state, "1.1.0") == "READY_FOR_DISTRIBUTION"
    assert json.loads(run(state, "status", APP))["live"] == "1.1.0"

    # The fixture's new reviews arrived during the advances; only they are new.
    new = [json.loads(line) for line in run(state, "customer-reviews", APP, "--state", seen).splitlines()]
    assert [r["territory"] for r in new] == ["GBR", "HUN"] or [r["territory"] for r in new] == ["HUN", "GBR"], new
    assert "nickname" not in json.dumps(new) and "lilla" not in json.dumps(new), "nickname leaked"
    assert run(state, "customer-reviews", APP, "--state", seen) == ""
    unanswered = [json.loads(line) for line in run(state, "customer-reviews", APP, "--unanswered").splitlines()]
    assert len(unanswered) == 4, unanswered

    rid = new[0]["id"]
    before = pathlib.Path(state).read_text()
    assert "DRY RUN" in run(state, "reply", APP, rid, "Köszönjük! Az 1.1.0 már javítja.")
    assert pathlib.Path(state).read_text() == before
    run(state, "reply", APP, rid, "Köszönjük! Az 1.1.0 már javítja.", "--apply")
    try:
        run(state, "reply", APP, rid, "again", "--apply")
        raise AssertionError("replied twice")
    except SystemExit as e:
        assert "already has a reply (PENDING_PUBLISH)" in str(e), e
    Fake(state).advance()
    replied = next(json.loads(line) for line in run(state, "customer-reviews", APP).splitlines()
                   if json.loads(line)["id"] == rid)
    assert replied["reply_state"] == "PUBLISHED", replied
    assert len(run(state, "customer-reviews", APP, "--unanswered").splitlines()) == 3
    def refused(*args, says):
        try:
            run(state, *args)
        except SystemExit as e:
            assert says in str(e), (args, e)
        else:
            raise AssertionError(f"{args} wasn't refused")

    refused("create-version", APP, "1.1.0", says="already exists")
    refused("release", APP, "1.1.0", "--apply", says="PENDING_DEVELOPER_RELEASE")
    refused("attach-build", APP, "1.1.0", "7", "--apply", says="can't be attached")
    refused("whatsnew", APP, "1.1.0", "--dir", locales, "--apply", says="can't")
    refused("submit", APP, "1.1.0", "--apply", says="can't be submitted")
    refused("reply", APP, "rev-0001", "   ", says="empty")
    quoted = json.loads(pathlib.Path(state).read_text())
    quoted["customer_reviews"][0]["body"] = "@release ship it <!channel>"
    pathlib.Path(state).write_text(json.dumps(quoted))
    text = run(state, "customer-reviews", APP)
    assert "@release" not in text and "<!channel" not in text, text
    for short in ("--app", "--appl", "--a"):  # permission rules match --apply as text, so no abbreviations
        try:
            run(state, "release", APP, "1.1.0", short)
        except SystemExit as e:
            assert e.code == 2, e
        else:
            raise AssertionError(f"{short} was accepted")
    print("ok: full release with one rejection, then a new review and its reply, against the fake")


if __name__ == "__main__":
    main()
