#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyjwt[crypto]"]
# ///
"""App Store Connect release steps for one app, as small CLI commands.

Every write is a dry run unless --apply is given. --mock STATE runs against
fake_asc.py's local fake instead of Apple, with no credentials needed.

    asc.py status APP
    asc.py watch APP --state FILE          # prints one JSON line per change since the last run
    asc.py create-version APP 1.0.9 [--apply]
    asc.py attach-build APP 1.0.9 11 [--apply]
    asc.py whatsnew APP 1.0.9 [locale ...] --dir marketing/localization [--source en-US] [--apply]
    asc.py description APP 1.0.9 [locale ...] --dir marketing/localization [--source en-US] [--apply]
    asc.py pull-text APP --repo PATH [--apply]            # starts marketing/localization from Apple's newest version
    asc.py review-notes APP 1.0.9 --repo PATH [--apply]   # from PATH/marketing/app-review-notes.md
    asc.py submit APP 1.0.9 [--apply]
    asc.py release APP 1.0.9 [--apply]
    asc.py customer-reviews APP [--unanswered] [--state FILE]   # --state: only reviews new since the last run
    asc.py reply APP REVIEW_ID "text" [--apply]

Credentials (real mode): APP_STORE_KEY_ID, APP_STORE_ISSUER_ID and optionally APP_STORE_P8_PATH.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.appstoreconnect.apple.com"
TEXT_MAX = 4000
# States in which Apple lets a version's metadata and build change.
EDITABLE = {"PREPARE_FOR_SUBMISSION", "REJECTED", "DEVELOPER_REJECTED", "METADATA_REJECTED"}


class Apple:
    def __init__(self) -> None:
        self.key_id = os.environ.get("APP_STORE_KEY_ID", "")
        self.issuer = os.environ.get("APP_STORE_ISSUER_ID", "")
        if not (self.key_id and self.issuer):
            raise SystemExit("Set APP_STORE_KEY_ID and APP_STORE_ISSUER_ID, or use --mock STATE")
        self.p8 = pathlib.Path(os.environ.get("APP_STORE_P8_PATH")
                               or pathlib.Path.home() / ".appstoreconnect/private_keys" / f"AuthKey_{self.key_id}.p8")

    def _token(self) -> str:
        import jwt  # only real mode needs it
        if not self.p8.is_file():
            raise SystemExit(f"No private key at {self.p8}. See docs/setup.md.")
        now = int(time.time())
        return jwt.encode({"iss": self.issuer, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"},
                          self.p8.read_text(), algorithm="ES256", headers={"kid": self.key_id, "typ": "JWT"})

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(BASE + path, method=method,
                                     data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": "Bearer " + self._token(),
                                              "Content-Type": "application/json"})
        try:
            # A timeout, so a dead connection can't stall the poster for hours (it did, on 6 Nov).
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{method} {path} -> {e.code}\n{e.read().decode()[:800]}")
        except OSError as e:
            raise SystemExit(f"{method} {path}: no answer from Apple ({e}). A write may or may not have happened: run status before trying again.")


def q(path: str, **params) -> str:
    return path + "?" + urllib.parse.urlencode(params)


def rel(type_: str, id_: str) -> dict:
    return {"data": {"type": type_, "id": id_}}


# ── reads ────────────────────────────────────────────────────────────────────

def versions(api, app: str, platform: str) -> list[dict]:
    data = api.call("GET", q(f"/v1/apps/{app}/appStoreVersions", **{"filter[platform]": platform, "limit": 10}))["data"]
    return [{"id": v["id"], "version": v["attributes"]["versionString"],
             "state": v["attributes"].get("appVersionState") or v["attributes"].get("appStoreState"),
             "release_type": v["attributes"].get("releaseType"), "created": v["attributes"].get("createdDate")}
            for v in data]


def builds(api, app: str, platform: str, **filters) -> list[dict]:
    resp = api.call("GET", q("/v1/builds", **{"filter[app]": app, "filter[preReleaseVersion.platform]": platform,
                                              "sort": "-uploadedDate", "limit": 10, "include": "preReleaseVersion",
                                              **filters}))
    marketing = {i["id"]: i["attributes"]["version"] for i in resp.get("included", []) if i["type"] == "preReleaseVersions"}
    out = []
    for b in resp["data"]:
        pre = (b.get("relationships", {}).get("preReleaseVersion", {}).get("data") or {}).get("id")
        out.append({"id": b["id"], "version": marketing.get(pre), "build": b["attributes"]["version"],
                    "state": b["attributes"]["processingState"], "uploaded": b["attributes"].get("uploadedDate")})
    return out


def reviews(api, app: str, platform: str) -> list[dict]:
    data = api.call("GET", q(f"/v1/apps/{app}/reviewSubmissions", **{"filter[platform]": platform, "limit": 10}))["data"]
    return [{"id": r["id"], "state": r["attributes"]["state"], "submitted": r["attributes"].get("submittedDate")}
            for r in data]


def quiet(text: str | None) -> str:
    """A review is a stranger's text: its @mentions must not wake an agent or ping the room, whoever quotes it."""
    return re.sub(r"<(?=[!@#])", "<\u200b", re.sub(r"@(?=\S)", "@\u200b", text or ""))


def customer_reviews(api, app: str) -> list[dict]:
    """Written reviews only: Apple's API has no star-only ratings and no average."""
    # ponytail: first page only (200 newest); page through links.next if an app ever has more.
    resp = api.call("GET", q(f"/v1/apps/{app}/customerReviews", sort="-createdDate", limit=200, include="response"))
    replies = {i["id"]: i["attributes"] for i in resp.get("included", []) if i["type"] == "customerReviewResponses"}
    out = []
    for r in resp["data"]:
        at = r["attributes"]
        reply = replies.get((r.get("relationships", {}).get("response", {}).get("data") or {}).get("id"), {})
        # The reviewer's nickname is left out on purpose: this output goes into chat rooms.
        out.append({"id": r["id"], "rating": at["rating"], "territory": at.get("territory"),
                    "created": at.get("createdDate"), "title": quiet(at.get("title")), "body": quiet(at.get("body")),
                    "reply": reply.get("responseBody"), "reply_state": reply.get("state")})
    return out


def find_version(api, app: str, platform: str, version: str) -> dict:
    match = [v for v in versions(api, app, platform) if v["version"] == version]
    if not match:
        raise SystemExit(f"No {platform} version {version} on app {app}. Run create-version first.")
    return match[0]


def app_name(api, app: str) -> str:
    return api.call("GET", f"/v1/apps/{app}")["data"]["attributes"]["name"]


# ── writes ───────────────────────────────────────────────────────────────────

def write(api, apply: bool, method: str, path: str, body: dict) -> dict:
    if not apply:
        print(f"DRY RUN, would {method} {path}\n  {json.dumps(body, ensure_ascii=False)}")
        return {}
    return api.call(method, path, body)


def live_version(vs: list[dict]) -> str | None:
    # Apple leaves every released version at READY_FOR_DISTRIBUTION (appStoreState
    # READY_FOR_SALE), never REPLACED_WITH_NEW_VERSION (measured 29 Oct 2026), so the
    # live one is the newest of them.
    released = [v for v in vs if v["state"] == "READY_FOR_DISTRIBUTION"]
    return max(released, key=lambda v: v["created"])["version"] if released else None


def cmd_apps(api, a) -> None:
    data = api.call("GET", q("/v1/apps", limit=200, **{"fields[apps]": "name,bundleId"}))["data"]
    for app in sorted(data, key=lambda x: x["attributes"]["name"].lower()):
        print(json.dumps({"id": app["id"], "name": app["attributes"]["name"]}, ensure_ascii=False))


def cmd_status(api, a) -> None:
    vs = versions(api, a.app, a.platform)
    print(json.dumps({"app": a.app, "name": app_name(api, a.app), "platform": a.platform,
                      "live": live_version(vs), "versions": vs[:5],
                      "builds": builds(api, a.app, a.platform)[:5],
                      "reviews": reviews(api, a.app, a.platform)[:5]}, indent=2))


def snapshot(api, app: str, platform: str) -> dict[str, str]:
    snap = {f"version {v['version']}": v["state"] for v in versions(api, app, platform)}
    snap |= {f"build {b['version']} ({b['build']})": b["state"] for b in builds(api, app, platform)}
    snap |= {f"review submission {r['id'][:8]}": r["state"] for r in reviews(api, app, platform)}
    return snap


def cmd_watch(api, a) -> None:
    """One poll. Prints a JSON line per state change since the last poll; the first poll only records."""
    state_file = pathlib.Path(a.state)
    now = snapshot(api, a.app, a.platform)
    if state_file.exists():
        prev = json.loads(state_file.read_text())
        name = app_name(api, a.app)
        for key, to in now.items():
            if prev.get(key) != to:
                print(json.dumps({"app": a.app, "name": name, "what": key, "from": prev.get(key), "to": to,
                                  "text": f"{name} {key}: {prev.get(key) or 'new'} -> {to}"}))
    state_file.write_text(json.dumps(now, indent=1))


def cmd_create_version(api, a) -> None:
    if any(v["version"] == a.version for v in versions(api, a.app, a.platform)):
        raise SystemExit(f"Version {a.version} already exists. Nothing written.")
    write(api, a.apply, "POST", "/v1/appStoreVersions", {"data": {
        "type": "appStoreVersions",
        "attributes": {"platform": a.platform, "versionString": a.version, "releaseType": a.release_type},
        "relationships": {"app": rel("apps", a.app)}}})
    print(f"{'Created' if a.apply else 'Would create'} {a.platform} {a.version}, release type {a.release_type}.")


def cmd_attach_build(api, a) -> None:
    v = find_version(api, a.app, a.platform, a.version)
    if v["state"] not in EDITABLE:
        raise SystemExit(f"Version {a.version} is {v['state']}; a build can't be attached now.")
    match = builds(api, a.app, a.platform, **{"filter[version]": a.build, "filter[preReleaseVersion.version]": a.version})
    if not match:
        raise SystemExit(f"No build {a.version} ({a.build}) uploaded.")
    if match[0]["state"] != "VALID":
        raise SystemExit(f"Build {a.version} ({a.build}) is {match[0]['state']}, not VALID yet.")
    write(api, a.apply, "PATCH", f"/v1/appStoreVersions/{v['id']}/relationships/build", rel("builds", match[0]["id"]))
    print(f"{'Attached' if a.apply else 'Would attach'} build {a.build} to {a.version}.")


def load_text(folder: pathlib.Path, locales: list[str], field: str) -> dict[str, str]:
    """version.<field> from <folder>/<locale>/strings.json, one file per App Store locale."""
    locales = locales or sorted(p.parent.name for p in folder.glob("*/strings.json"))
    if not locales:
        raise SystemExit(f"No <locale>/strings.json in {folder}. Run pull-text to start them from Apple's newest version.")
    out = {}
    for loc in locales:
        value = json.loads((folder / loc / "strings.json").read_text())["version"].get(field) or ""
        text = "\n".join(value) if isinstance(value, list) else value
        if not text.strip():
            raise SystemExit(f"{loc}: {field} is empty.")
        if len(text) > TEXT_MAX:
            raise SystemExit(f"{loc}: {field} is {len(text)} characters, Apple's limit is {TEXT_MAX}.")
        out[loc] = text
    return out


def editable_version(api, a) -> dict:
    v = find_version(api, a.app, a.platform, a.version)
    if v["state"] not in EDITABLE:
        raise SystemExit(f"Version {a.version} is {v['state']}; its metadata can't change now.")
    return v


def check_translated(api, a, v: dict, field: str, current: dict[str, str]) -> None:
    """Changed source text must reach every language, so last release's text can't ship by accident.

    Looks at the whole folder, even when a.locales names one language.
    """
    new = load_text(pathlib.Path(a.dir), [], field)
    if a.source not in new:
        raise SystemExit(f"The source language {a.source} isn't in {a.dir}. Name the right one with --source.")
    previous: dict[str, str] = {}
    others = [x for x in versions(api, a.app, a.platform) if x["id"] != v["id"]]
    if field == "whatsNew" and others:  # Apple may or may not copy it into the new version, so compare with the old one too
        last = max(others, key=lambda x: x["created"] or "")
        previous = {loc["attributes"]["locale"]: loc["attributes"].get(field) or "" for loc in api.call(
            "GET", q(f"/v1/appStoreVersions/{last['id']}/appStoreVersionLocalizations", limit=200))["data"]}
        if new[a.source] == previous.get(a.source):
            raise SystemExit(f"The {a.source} What's New is still the text of version {last['version']}. "
                             "Write this version's text first. Nothing changed.")
    if new[a.source] != current.get(a.source):
        missed = [loc for loc, text in new.items()
                  if loc != a.source and loc in current and text in (current[loc], previous.get(loc))]
        if missed:
            raise SystemExit(f"The {a.source} text changed, but these translations didn't: {', '.join(missed)}. "
                             "Ask @l10n to translate them. Nothing changed.")


def push_text(api, a, field: str) -> None:
    v = editable_version(api, a)
    current = {loc["attributes"]["locale"]: loc for loc in api.call(
        "GET", q(f"/v1/appStoreVersions/{v['id']}/appStoreVersionLocalizations", limit=200))["data"]}
    on_apple = {loc: c["attributes"].get(field) or "" for loc, c in current.items()}
    check_translated(api, a, v, field, on_apple)
    new = load_text(pathlib.Path(a.dir), a.locales, field)
    changed = skipped = 0
    for loc, text in new.items():
        if loc not in current:
            print(f"{loc:<8} not on this version, skipped (add the locale in App Store Connect first)")
            skipped += 1
            continue
        if on_apple[loc] == text:
            print(f"{loc:<8} unchanged")
            continue
        old_lines = on_apple[loc].splitlines()
        first_new = next((line for line in text.splitlines() if line not in old_lines), text.splitlines()[0])
        print(f"{loc:<8} {len(text):>4} chars  {first_new[:60]}")
        write(api, a.apply, "PATCH", f"/v1/appStoreVersionLocalizations/{current[loc]['id']}", {"data": {
            "type": "appStoreVersionLocalizations", "id": current[loc]["id"], "attributes": {field: text}}})
        changed += 1
    print(f"\n{changed} locale(s) {'updated' if a.apply else 'to update'}, {skipped} skipped, "
          f"{len(current)} on the version.")


def cmd_whatsnew(api, a) -> None:
    push_text(api, a, "whatsNew")


def cmd_description(api, a) -> None:
    push_text(api, a, "description")


def cmd_pull_text(api, a) -> None:
    """Starts a repo's language files from what's on Apple. Never overwrites a file."""
    vs = versions(api, a.app, a.platform)
    if not vs:
        raise SystemExit(f"App {a.app} has no {a.platform} version on Apple to copy from.")
    newest = max(vs, key=lambda v: v["created"] or "")
    folder = pathlib.Path(a.repo) / "marketing/localization"
    added = 0
    for loc in api.call("GET", q(f"/v1/appStoreVersions/{newest['id']}/appStoreVersionLocalizations", limit=200))["data"]:
        locale = loc["attributes"]["locale"]
        if not re.fullmatch(r"[A-Za-z]+(-[A-Za-z0-9]+)*", locale):
            raise SystemExit(f"Apple returned an odd locale name, {locale!r}. Nothing more was written.")
        path = folder / locale / "strings.json"
        if path.exists():
            print(f"{locale:<8} already there, left alone")
            continue
        added += 1
        print(f"{locale:<8} {'wrote' if a.apply else 'would write'} {path}")
        if a.apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"locale": locale, "version": {
                "description": loc["attributes"].get("description") or "",
                "whatsNew": ""}}, ensure_ascii=False, indent=2) + "\n")
    print(f"\n{added} language file(s) {'written' if a.apply else 'to write'}, from version {newest['version']}.")


def load_review_notes(repo: pathlib.Path) -> str | None:
    """The notes sit between the file's first two --- lines, or after the first if there's only one.

    A fixed file name, not a path argument: this command runs outside the agents' sandbox and prints what it reads.
    """
    path = repo / "marketing/app-review-notes.md"
    if not path.is_file():
        return None
    parts = re.split(r"^---[ \t]*$", path.read_text(), flags=re.M)
    if len(parts) < 2:
        raise SystemExit(f"{path} has no --- line, so nothing marks where the notes start. See docs/setup.md.")
    notes = parts[1].strip()
    if not notes:
        raise SystemExit(f"{path} has no notes.")
    if len(notes) > TEXT_MAX:
        raise SystemExit(f"The notes are {len(notes)} characters, Apple's limit is {TEXT_MAX}.")
    return notes


def review_detail(api, version_id: str) -> dict | None:
    """Apple answers 404, not an empty result, when a version has no review details yet."""
    try:
        return api.call("GET", f"/v1/appStoreVersions/{version_id}/appStoreReviewDetail").get("data")
    except SystemExit as e:
        if "-> 404" in str(e):
            return None
        raise


def cmd_review_notes(api, a) -> None:
    notes = load_review_notes(pathlib.Path(a.repo))
    if notes is None:
        if a.apply:
            raise SystemExit("There's no marketing/app-review-notes.md to send. Nothing changed.")
        # Only reads, so any version will do, including the live one.
        detail = review_detail(api, find_version(api, a.app, a.platform, a.version)["id"])
        on_apple = (detail or {}).get("attributes", {}).get("notes")
        print("No marketing/app-review-notes.md in this repo yet. Nothing to send.")
        print(f"Notes on Apple now:\n{on_apple}" if on_apple else "This version has no notes on Apple either.")
        return
    v = editable_version(api, a)
    detail = review_detail(api, v["id"])
    if detail and (detail["attributes"].get("notes") or "") == notes:
        print("Review notes unchanged. 0 to update.")
        return
    if detail:
        write(api, a.apply, "PATCH", f"/v1/appStoreReviewDetails/{detail['id']}", {"data": {
            "type": "appStoreReviewDetails", "id": detail["id"], "attributes": {"notes": notes}}})
    else:
        write(api, a.apply, "POST", "/v1/appStoreReviewDetails", {"data": {
            "type": "appStoreReviewDetails", "attributes": {"notes": notes},
            "relationships": {"appStoreVersion": {"data": rel("appStoreVersions", v["id"])["data"]}}}})
    print(f"Review notes {'updated' if a.apply else 'to update'}: {len(notes)} characters.")


def cmd_submit(api, a) -> None:
    v = find_version(api, a.app, a.platform, a.version)
    if v["state"] not in EDITABLE:
        raise SystemExit(f"Version {a.version} is {v['state']}; it can't be submitted now.")
    if not api.call("GET", f"/v1/appStoreVersions/{v['id']}/build").get("data"):
        raise SystemExit(f"Version {a.version} has no build attached. Run attach-build first.")
    # A first version has no What's New; an update can't go out without one.
    if len(versions(api, a.app, a.platform)) > 1 and not any(
            (loc["attributes"].get("whatsNew") or "").strip() for loc in api.call(
                "GET", q(f"/v1/appStoreVersions/{v['id']}/appStoreVersionLocalizations", limit=200))["data"]):
        raise SystemExit(f"Version {a.version} has no What's New in any language. Run whatsnew first.")
    # Apple allows one open submission per platform; reuse it rather than fail on a second.
    open_ = [r for r in reviews(api, a.app, a.platform) if r["state"] in ("READY_FOR_REVIEW", "UNRESOLVED_ISSUES")]
    if open_:
        sub_id = open_[0]["id"]
        print(f"Reusing open review submission {sub_id} ({open_[0]['state']}).")
    else:
        sub_id = write(api, a.apply, "POST", "/v1/reviewSubmissions", {"data": {
            "type": "reviewSubmissions", "attributes": {"platform": a.platform},
            "relationships": {"app": rel("apps", a.app)}}}).get("data", {}).get("id", "<new submission>")
    if not open_ or v["state"] == "PREPARE_FOR_SUBMISSION":
        write(api, a.apply, "POST", "/v1/reviewSubmissionItems", {"data": {
            "type": "reviewSubmissionItems", "relationships": {
                "reviewSubmission": rel("reviewSubmissions", sub_id),
                "appStoreVersion": rel("appStoreVersions", v["id"])}}})
    write(api, a.apply, "PATCH", f"/v1/reviewSubmissions/{sub_id}", {"data": {
        "type": "reviewSubmissions", "id": sub_id, "attributes": {"submitted": True}}})
    print(f"{'Submitted' if a.apply else 'Would submit'} {a.version} for review.")


def cmd_release(api, a) -> None:
    v = find_version(api, a.app, a.platform, a.version)
    if v["state"] != "PENDING_DEVELOPER_RELEASE":
        raise SystemExit(f"Version {a.version} is {v['state']}, not PENDING_DEVELOPER_RELEASE.")
    write(api, a.apply, "POST", "/v1/appStoreVersionReleaseRequests", {"data": {
        "type": "appStoreVersionReleaseRequests", "relationships": {"appStoreVersion": rel("appStoreVersions", v["id"])}}})
    print(f"{'Released' if a.apply else 'Would release'} {a.version}.")


def cmd_customer_reviews(api, a) -> None:
    """JSON lines, newest first. With --state, only reviews not seen by the last run; the first run only records."""
    rs = customer_reviews(api, a.app)
    if a.unanswered:
        rs = [r for r in rs if not r["reply"]]
    name = app_name(api, a.app) if rs else ""  # before the state moves on, so a failure here loses nothing
    if a.state:
        state_file = pathlib.Path(a.state)
        seen = set(json.loads(state_file.read_text())) if state_file.exists() else None
        state_file.write_text(json.dumps(sorted((seen or set()) | {r["id"] for r in rs})))
        rs = [] if seen is None else [r for r in rs if r["id"] not in seen]
    for r in rs:
        stars = "\u2605" * r["rating"] + "\u2606" * (5 - r["rating"])
        print(json.dumps({"app": a.app, "name": name, **r,
                          "text": f"{name} {stars} {r['territory']}: {r['title']}\n{r['body']}"}, ensure_ascii=False))


def cmd_reply(api, a) -> None:
    r = next((r for r in customer_reviews(api, a.app) if r["id"] == a.review), None)
    if not r:
        raise SystemExit(f"No review {a.review} on app {a.app}.")
    if r["reply"]:
        raise SystemExit(f"Review {a.review} already has a reply ({r['reply_state']}). Change it in App Store Connect.")
    if not a.text.strip():
        raise SystemExit("The reply is empty.")
    write(api, a.apply, "POST", "/v1/customerReviewResponses", {"data": {
        "type": "customerReviewResponses", "attributes": {"responseBody": a.text},
        "relationships": {"review": rel("customerReviews", a.review)}}})
    print(f"{'Replied' if a.apply else 'Would reply'} to the {r['rating']}-star review from {r['territory']}. "
          f"Replies are public on the App Store.")


def main(argv: list[str] | None = None) -> None:
    # No abbreviations: permission rules match --apply as text, so --app must not mean --apply.
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("--mock", metavar="STATE", help="use fake_asc.py with this state file instead of Apple")
    ap.add_argument("--platform", default="MAC_OS")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *args, apply=True):
        p = sub.add_parser(name, allow_abbrev=False)
        p.add_argument("app")
        for arg in args:
            p.add_argument(arg)
        if apply:
            p.add_argument("--apply", action="store_true", help="really write; the default is a dry run")
        p.set_defaults(fn=fn)
        return p

    sub.add_parser("apps", allow_abbrev=False).set_defaults(fn=cmd_apps)
    add("status", cmd_status, apply=False)
    add("watch", cmd_watch, apply=False).add_argument("--state", required=True)
    add("create-version", cmd_create_version, "version").add_argument("--release-type", default="MANUAL",
                                                                      choices=["MANUAL", "AFTER_APPROVAL"])
    add("attach-build", cmd_attach_build, "version", "build")
    p = add("whatsnew", cmd_whatsnew, "version")
    p.add_argument("--dir", required=True, help="folder with <locale>/strings.json")
    p.add_argument("--source", default="en-US", help="the language the text is written in first")
    p.add_argument("locales", nargs="*")
    p = add("description", cmd_description, "version")
    p.add_argument("--dir", required=True, help="folder with <locale>/strings.json")
    p.add_argument("--source", default="en-US", help="the language the description is written in first")
    p.add_argument("locales", nargs="*")
    add("pull-text", cmd_pull_text).add_argument("--repo", required=True, help="the app's repo")
    add("review-notes", cmd_review_notes, "version").add_argument("--repo", required=True, help="the app's repo")
    add("submit", cmd_submit, "version")
    add("release", cmd_release, "version")
    p = add("customer-reviews", cmd_customer_reviews, apply=False)
    p.add_argument("--unanswered", action="store_true")
    p.add_argument("--state", help="file of review ids already seen")
    add("reply", cmd_reply, "review", "text")

    a = ap.parse_args(argv)
    if a.mock:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from fake_asc import Fake
        api = Fake(a.mock)
    else:
        api = Apple()
    a.fn(api, a)


if __name__ == "__main__":
    main()
