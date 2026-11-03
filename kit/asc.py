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
    asc.py whatsnew APP 1.0.9 [locale ...] --dir marketing/localization [--apply]
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
WHATS_NEW_MAX = 4000
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
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{method} {path} -> {e.code}\n{e.read().decode()[:800]}")


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
        print(f"DRY RUN, would {method} {path}\n  {json.dumps(body)}")
        return {}
    return api.call(method, path, body)


def live_version(vs: list[dict]) -> str | None:
    # Apple leaves every released version at READY_FOR_DISTRIBUTION (appStoreState
    # READY_FOR_SALE), never REPLACED_WITH_NEW_VERSION (measured 29 Oct 2026), so the
    # live one is the newest of them.
    released = [v for v in vs if v["state"] == "READY_FOR_DISTRIBUTION"]
    return max(released, key=lambda v: v["created"])["version"] if released else None


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


def load_whats_new(folder: pathlib.Path, locales: list[str]) -> dict[str, str]:
    """<folder>/<locale>/strings.json, one file per App Store locale."""
    locales = locales or sorted(p.parent.name for p in folder.glob("*/strings.json"))
    out = {}
    for loc in locales:
        wn = json.loads((folder / loc / "strings.json").read_text())["version"]["whatsNew"]
        text = "\n".join(wn) if isinstance(wn, list) else wn
        if not text.strip():
            raise SystemExit(f"{loc}: whatsNew is empty.")
        if len(text) > WHATS_NEW_MAX:
            raise SystemExit(f"{loc}: whatsNew is {len(text)} characters, Apple's limit is {WHATS_NEW_MAX}.")
        out[loc] = text
    return out


def cmd_whatsnew(api, a) -> None:
    v = find_version(api, a.app, a.platform, a.version)
    if v["state"] not in EDITABLE:
        raise SystemExit(f"Version {a.version} is {v['state']}; its metadata can't change now.")
    new = load_whats_new(pathlib.Path(a.dir), a.locales)
    current = {loc["attributes"]["locale"]: loc for loc in api.call(
        "GET", q(f"/v1/appStoreVersions/{v['id']}/appStoreVersionLocalizations", limit=200))["data"]}
    changed = skipped = 0
    for loc, text in new.items():
        if loc not in current:
            print(f"{loc:<8} not on this version, skipped (add the locale in App Store Connect first)")
            skipped += 1
            continue
        if (current[loc]["attributes"].get("whatsNew") or "") == text:
            print(f"{loc:<8} unchanged")
            continue
        print(f"{loc:<8} {len(text):>4} chars  {text.splitlines()[0][:60]}")
        write(api, a.apply, "PATCH", f"/v1/appStoreVersionLocalizations/{current[loc]['id']}", {"data": {
            "type": "appStoreVersionLocalizations", "id": current[loc]["id"], "attributes": {"whatsNew": text}}})
        changed += 1
    print(f"\n{changed} locale(s) {'updated' if a.apply else 'to update'}, {skipped} skipped, "
          f"{len(current)} on the version.")


def cmd_submit(api, a) -> None:
    v = find_version(api, a.app, a.platform, a.version)
    if v["state"] not in EDITABLE:
        raise SystemExit(f"Version {a.version} is {v['state']}; it can't be submitted now.")
    if not api.call("GET", f"/v1/appStoreVersions/{v['id']}/build").get("data"):
        raise SystemExit(f"Version {a.version} has no build attached. Run attach-build first.")
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

    add("status", cmd_status, apply=False)
    add("watch", cmd_watch, apply=False).add_argument("--state", required=True)
    add("create-version", cmd_create_version, "version").add_argument("--release-type", default="MANUAL",
                                                                      choices=["MANUAL", "AFTER_APPROVAL"])
    add("attach-build", cmd_attach_build, "version", "build")
    p = add("whatsnew", cmd_whatsnew, "version")
    p.add_argument("--dir", required=True, help="folder with <locale>/strings.json")
    p.add_argument("locales", nargs="*")
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
