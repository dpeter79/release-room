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

    with tempfile.TemporaryDirectory() as stale:
        copy = pathlib.Path(stale) / "locales"
        shutil.copytree(locales, copy)
        old = {x["locale"]: x["whatsNew"] for x in json.loads(pathlib.Path(state).read_text())["localizations"]}
        strings = json.loads((copy / "hu/strings.json").read_text())
        strings["version"]["whatsNew"] = old["hu"]
        (copy / "hu/strings.json").write_text(json.dumps(strings))
        try:  # Apple copied last release's text, so a missed language looks unchanged
            run(state, "whatsnew", APP, "1.1.0", "--dir", str(copy), "--apply")
            raise AssertionError("a language still on last release's What's New wasn't refused")
        except SystemExit as e:
            assert "translations didn't" in str(e) and "hu" in str(e), e
        data = json.loads(pathlib.Path(state).read_text())
        kept = json.dumps(data)
        new_id = next(v["id"] for v in data["versions"] if v["version"] == "1.1.0")
        for loc in data["localizations"]:
            if loc["version"] == new_id:
                loc["whatsNew"] = ""
        pathlib.Path(state).write_text(json.dumps(data))
        try:  # the same mistake if Apple leaves the new version empty
            run(state, "whatsnew", APP, "1.1.0", "--dir", str(copy), "--apply")
            raise AssertionError("a stale language wasn't refused when Apple copied nothing")
        except SystemExit as e:
            assert "translations didn't" in str(e) and "hu" in str(e), e
        pathlib.Path(state).write_text(kept)
        for loc in ("en-US", "de-DE", "ja"):
            strings = json.loads((copy / loc / "strings.json").read_text())
            strings["version"]["whatsNew"] = old[loc]
            (copy / loc / "strings.json").write_text(json.dumps(strings))
        try:
            run(state, "whatsnew", APP, "1.1.0", "--dir", str(copy))
            raise AssertionError("last release's What's New wasn't refused")
        except SystemExit as e:
            assert "still the text of version" in str(e), e

    out = run(state, "whatsnew", APP, "1.1.0", "--dir", locales, "--apply")
    assert "4 locale(s) updated" in out, out
    assert "unchanged" in run(state, "whatsnew", APP, "1.1.0", "hu", "--dir", locales)
    assert "0 locale(s) to update" in run(state, "description", APP, "1.1.0", "--dir", locales), "Apple copied the old description"

    # no language files or notes yet: refused with directions, then started from Apple
    with tempfile.TemporaryDirectory() as bare:
        folder = pathlib.Path(bare) / "marketing/localization"
        for cmd in ("whatsnew", "description"):
            try:
                run(state, cmd, APP, "1.1.0", "--dir", str(folder), "--apply")
                raise AssertionError(f"{cmd} with no language files wasn't refused")
            except SystemExit as e:
                assert "pull-text" in str(e), e
        assert "4 language file(s) to write" in run(state, "pull-text", APP, "--repo", bare)
        assert not folder.exists(), "a dry run must not write"
        run(state, "pull-text", APP, "--repo", bare, "--apply")
        pulled = json.loads((folder / "en-US/strings.json").read_text())["version"]
        assert pulled == {"description": "DemoCam is a fictional Mac virtual camera.", "whatsNew": ""}, pulled
        try:
            run(state, "whatsnew", APP, "1.1.0", "--dir", str(folder))
            raise AssertionError("a language with no What's New wasn't refused")
        except SystemExit as e:
            assert "whatsNew is empty" in str(e), e
        assert "0 locale(s) to update" in run(state, "description", APP, "1.1.0", "--dir", str(folder))
        (folder / "hu/strings.json").write_text('{"version": {"whatsNew": "mine", "description": "mine"}}')
        assert "already there" in run(state, "pull-text", APP, "--repo", bare, "--apply")
        assert "mine" in (folder / "hu/strings.json").read_text(), "pull-text must not overwrite"
        saved = pathlib.Path(state).read_text()
        odd = json.loads(saved)
        for loc in odd["localizations"]:
            loc["locale"] = "../evil"
        pathlib.Path(state).write_text(json.dumps(odd))
        try:
            run(state, "pull-text", APP, "--repo", bare, "--apply")
            raise AssertionError("an odd locale name wasn't refused")
        except SystemExit as e:
            assert "odd locale" in str(e), e
        for loc in odd["localizations"]:
            loc["locale"], loc["whatsNew"] = "hu", ""
        pathlib.Path(state).write_text(json.dumps(odd))
        try:
            run(state, "submit", APP, "1.1.0", "--apply")
            raise AssertionError("a version with no What's New was submitted")
        except SystemExit as e:
            assert "no What's New" in str(e), e
        pathlib.Path(state).write_text(saved)

    with tempfile.TemporaryDirectory() as partial:
        copy = pathlib.Path(partial) / "locales"
        shutil.copytree(locales, copy)
        english = json.loads((copy / "en-US/strings.json").read_text())
        english["version"]["description"] = ["A new function."]
        (copy / "en-US/strings.json").write_text(json.dumps(english))
        try:
            run(state, "description", APP, "1.1.0", "--dir", str(copy), "--apply")
            raise AssertionError("a description missing its translations wasn't refused")
        except SystemExit as e:
            assert "translations didn't" in str(e) and "hu" in str(e), e
        try:
            run(state, "description", APP, "1.1.0", "en-US", "--dir", str(copy), "--apply")
            raise AssertionError("naming one language got past the translation check")
        except SystemExit as e:
            assert "translations didn't" in str(e), e
        hungarian = json.loads((copy / "hu/strings.json").read_text())
        hungarian["version"]["description"] = ["Uj funkcio."]
        (copy / "hu/strings.json").write_text(json.dumps(hungarian))
        (copy / "en-US/strings.json").write_text((pathlib.Path(locales) / "en-US/strings.json").read_text())
        try:
            run(state, "description", APP, "1.1.0", "--dir", str(copy), "--source", "hu", "--apply")
            raise AssertionError("another source language wasn't checked")
        except SystemExit as e:
            assert "The hu text" in str(e) and "en-US" in str(e), e
        try:
            run(state, "description", APP, "1.1.0", "--dir", str(copy), "--source", "fr-FR")
            raise AssertionError("a missing source language wasn't refused")
        except SystemExit as e:
            assert "isn't in" in str(e), e

    with tempfile.TemporaryDirectory() as notes_repo:
        assert "no notes on Apple" in run(state, "review-notes", APP, "1.1.0", "--repo", notes_repo)
        assert "no notes on Apple" in run(state, "review-notes", APP, "1.0.0", "--repo", notes_repo), "the live version must be readable"
        try:
            run(state, "review-notes", APP, "1.1.0", "--repo", notes_repo, "--apply")
            raise AssertionError("--apply with no notes file wasn't refused")
        except SystemExit as e:
            assert "Nothing changed" in str(e), e
        notes = pathlib.Path(notes_repo) / "marketing/app-review-notes.md"
        notes.parent.mkdir()
        notes.write_text("# Heading\n\n---\n\nThe notes.\n\n---\n\nOur own changelog.\n")
        assert "Review notes to update:" in run(state, "review-notes", APP, "1.1.0", "--repo", notes_repo)
        assert not json.loads(pathlib.Path(state).read_text()).get("review_details"), "a dry run must not write"
        run(state, "review-notes", APP, "1.1.0", "--repo", notes_repo, "--apply")
        assert [d["notes"] for d in json.loads(pathlib.Path(state).read_text())["review_details"]] == ["The notes."]
        assert "0 to update" in run(state, "review-notes", APP, "1.1.0", "--repo", notes_repo)
        notes.write_text("No rule in this file.")
        try:
            run(state, "review-notes", APP, "1.1.0", "--repo", notes_repo)
            raise AssertionError("notes with no --- line weren't refused")
        except SystemExit as e:
            assert "no --- line" in str(e), e
        notes.write_text("---\n" + "x" * 4001)
        try:
            run(state, "review-notes", APP, "1.1.0", "--repo", notes_repo)
            raise AssertionError("over-long notes weren't refused")
        except SystemExit as e:
            assert "limit" in str(e), e
        notes.write_text("---\nChanged.\n---\n")
        run(state, "review-notes", APP, "1.1.0", "--repo", notes_repo, "--apply")
        assert [d["notes"] for d in json.loads(pathlib.Path(state).read_text())["review_details"]] == ["Changed."]
        notes.unlink()
        assert "Changed." in run(state, "review-notes", APP, "1.1.0", "--repo", notes_repo)

    # Apple's 500 on adding the version to a new submission is retried, not left for a person.
    real_call, failed = Fake.call, []

    def flaky(self, method, path, body=None):
        if method == "POST" and path == "/v1/reviewSubmissionItems" and not failed:
            failed.append(path)
            raise SystemExit("POST /v1/reviewSubmissionItems -> 500\nUNEXPECTED_ERROR")
        return real_call(self, method, path, body)
    Fake.call, asc.RETRY_WAIT = flaky, 0
    try:
        out = run(state, "submit", APP, "1.1.0", "--apply")
    finally:
        Fake.call = real_call
    assert failed and "Trying again" in out and "Submitted" in out, out
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

    # The fixture's new reviews wait until the version is live; only they are new.
    assert run(state, "customer-reviews", APP, "--state", seen) == ""
    Fake(state).advance()
    Fake(state).advance()
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
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                run(state, "release", APP, "1.1.0", short)
            except SystemExit as e:
                assert e.code == 2, e
            else:
                raise AssertionError(f"{short} was accepted")
    print("ok: full release with one rejection, then a new review and its reply, against the fake")


if __name__ == "__main__":
    main()
