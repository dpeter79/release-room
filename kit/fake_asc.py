#!/usr/bin/env python3
"""A local fake of the App Store Connect endpoints asc.py uses, kept in one JSON file.

It lets the release flow run with no Apple account: asc.py --mock STATE talks to it,
and `fake_asc.py advance STATE` plays App Review one step forward:

    builds      PROCESSING -> VALID
    review      WAITING_FOR_REVIEW -> IN_REVIEW -> the next outcome in "review_outcomes"
                ("reject" -> REJECTED, "approve" -> PENDING_DEVELOPER_RELEASE or straight
                to READY_FOR_DISTRIBUTION for an AFTER_APPROVAL version)
    release     PROCESSING_FOR_DISTRIBUTION -> READY_FOR_DISTRIBUTION; older released versions
                stay READY_FOR_DISTRIBUTION, as Apple's do
    customers   the next review in "incoming_reviews" is posted; replies PENDING_PUBLISH -> PUBLISHED

Only the requests asc.py sends are understood; anything else is an error, so a new
call in asc.py has to be added here too.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone

LIVE = "READY_FOR_DISTRIBUTION"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Fake:
    def __init__(self, path: str) -> None:
        self.path = pathlib.Path(path)
        if not self.path.exists():
            raise SystemExit(f"No fake state at {path}. Run make demo first.")
        self.s = json.loads(self.path.read_text())

    def save(self) -> None:
        self.path.write_text(json.dumps(self.s, indent=1))

    def _version(self, vid: str) -> dict:
        return next(v for v in self.s["versions"] if v["id"] == vid)

    @staticmethod
    def _v(v: dict) -> dict:
        return {"type": "appStoreVersions", "id": v["id"], "attributes": {
            "versionString": v["version"], "platform": v["platform"], "appVersionState": v["state"],
            "releaseType": v["release_type"], "createdDate": v["created"]}}

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        url = urllib.parse.urlparse(path)
        p, qs = url.path, dict(urllib.parse.parse_qsl(url.query))
        data = (body or {}).get("data", {})

        if method == "GET" and (m := re.fullmatch(r"/v1/apps/(\w+)", p)):
            return {"data": {"type": "apps", "id": m[1], "attributes": {"name": self.s["apps"][m[1]]["name"]}}}

        if method == "GET" and (m := re.fullmatch(r"/v1/apps/(\w+)/appStoreVersions", p)):
            vs = [v for v in self.s["versions"] if v["app"] == m[1] and v["platform"] == qs.get("filter[platform]")]
            return {"data": [self._v(v) for v in sorted(vs, key=lambda v: v["created"], reverse=True)]}

        if method == "GET" and p == "/v1/builds":
            bs = [b for b in self.s["builds"] if b["app"] == qs["filter[app]"]
                  and b["platform"] == qs["filter[preReleaseVersion.platform]"]
                  and qs.get("filter[version]", b["build"]) == b["build"]
                  and qs.get("filter[preReleaseVersion.version]", b["version"]) == b["version"]]
            bs.sort(key=lambda b: b["uploaded"], reverse=True)
            return {"data": [{"type": "builds", "id": b["id"],
                              "attributes": {"version": b["build"], "processingState": b["state"],
                                             "uploadedDate": b["uploaded"]},
                              "relationships": {"preReleaseVersion": {"data": {"type": "preReleaseVersions",
                                                                               "id": "pre-" + b["version"]}}}}
                             for b in bs],
                    "included": [{"type": "preReleaseVersions", "id": "pre-" + b["version"],
                                  "attributes": {"version": b["version"]}} for b in bs]}

        if method == "GET" and (m := re.fullmatch(r"/v1/apps/(\w+)/reviewSubmissions", p)):
            rs = [r for r in self.s["reviews"] if r["app"] == m[1] and r["platform"] == qs.get("filter[platform]")]
            return {"data": [{"type": "reviewSubmissions", "id": r["id"],
                              "attributes": {"state": r["state"], "submittedDate": r["submitted"]}} for r in rs]}

        if method == "GET" and (m := re.fullmatch(r"/v1/appStoreVersions/([\w-]+)/build", p)):
            bid = self._version(m[1])["build"]
            return {"data": {"type": "builds", "id": bid} if bid else None}

        if method == "GET" and (m := re.fullmatch(r"/v1/appStoreVersions/([\w-]+)/appStoreVersionLocalizations", p)):
            return {"data": [{"type": "appStoreVersionLocalizations", "id": loc["id"],
                              "attributes": {"locale": loc["locale"], "whatsNew": loc["whatsNew"], "description": loc.get("description")}}
                             for loc in self.s["localizations"] if loc["version"] == m[1]]}

        if method == "GET" and (m := re.fullmatch(r"/v1/apps/(\w+)/customerReviews", p)):
            rs = sorted((r for r in self.s["customer_reviews"] if r["app"] == m[1]), key=lambda r: r["created"], reverse=True)
            replies = {x["review"]: x for x in self.s["review_responses"]}
            return {"data": [{"type": "customerReviews", "id": r["id"],
                              "attributes": {k: r[k] for k in ("rating", "title", "body", "territory")}
                              | {"createdDate": r["created"], "reviewerNickname": r["nickname"]},
                              "relationships": {"response": {"data": {"type": "customerReviewResponses",
                                                                      "id": replies[r["id"]]["id"]}
                                                             if r["id"] in replies else None}}} for r in rs],
                    "included": [{"type": "customerReviewResponses", "id": x["id"],
                                  "attributes": {"responseBody": x["body"], "state": x["state"]}}
                                 for x in replies.values()]}

        if method == "POST" and p == "/v1/customerReviewResponses":
            rid = data["relationships"]["review"]["data"]["id"]
            if any(x["review"] == rid for x in self.s["review_responses"]):
                raise SystemExit("fake_asc: 409, the review already has a response")
            self.s["review_responses"].append({"id": str(uuid.uuid4()), "review": rid,
                                               "body": data["attributes"]["responseBody"], "state": "PENDING_PUBLISH"})
            self.save()
            return {}

        if method == "POST" and p == "/v1/appStoreVersions":
            at = data["attributes"]
            app = data["relationships"]["app"]["data"]["id"]
            v = {"id": str(uuid.uuid4()), "app": app, "platform": at["platform"], "version": at["versionString"],
                 "state": "PREPARE_FOR_SUBMISSION", "release_type": at.get("releaseType", "AFTER_APPROVAL"),
                 "created": now(), "build": None}
            # Apple copies the localizations of the latest version into a new one.
            prev = [x for x in self.s["versions"] if x["app"] == app and x["platform"] == at["platform"]]
            if prev:
                last = max(prev, key=lambda x: x["created"])["id"]
                self.s["localizations"] += [{"id": str(uuid.uuid4()), "version": v["id"], "locale": loc["locale"],
                                             "whatsNew": loc["whatsNew"], "description": loc.get("description")}
                                            for loc in self.s["localizations"] if loc["version"] == last]
                self.s.setdefault("review_details", []).extend(
                    [{"id": str(uuid.uuid4()), "version": v["id"], "notes": d["notes"]}
                     for d in self.s.get("review_details", []) if d["version"] == last])
            self.s["versions"].append(v)
            self.save()
            return {"data": self._v(v)}

        if method == "PATCH" and (m := re.fullmatch(r"/v1/appStoreVersions/([\w-]+)/relationships/build", p)):
            self._version(m[1])["build"] = data["id"]
            self.save()
            return {}

        if method == "PATCH" and (m := re.fullmatch(r"/v1/appStoreVersionLocalizations/([\w-]+)", p)):
            next(loc for loc in self.s["localizations"] if loc["id"] == m[1]).update(data["attributes"])
            self.save()
            return {}

        if method == "GET" and (m := re.fullmatch(r"/v1/appStoreVersions/([\w-]+)/appStoreReviewDetail", p)):
            d = next((x for x in self.s.get("review_details", []) if x["version"] == m[1]), None)
            if not d:  # as Apple does
                raise SystemExit(f"GET {p} -> 404\nResource not found")
            return {"data": {"type": "appStoreReviewDetails", "id": d["id"], "attributes": {"notes": d["notes"]}}}

        if method == "POST" and p == "/v1/appStoreReviewDetails":
            vid = data["relationships"]["appStoreVersion"]["data"]["id"]
            self.s.setdefault("review_details", []).append({"id": str(uuid.uuid4()), "version": vid, "notes": data["attributes"]["notes"]})
            self.save()
            return {}

        if method == "PATCH" and (m := re.fullmatch(r"/v1/appStoreReviewDetails/([\w-]+)", p)):
            next(d for d in self.s["review_details"] if d["id"] == m[1])["notes"] = data["attributes"]["notes"]
            self.save()
            return {}

        if method == "POST" and p == "/v1/reviewSubmissions":
            r = {"id": str(uuid.uuid4()), "app": data["relationships"]["app"]["data"]["id"],
                 "platform": data["attributes"]["platform"], "state": "READY_FOR_REVIEW", "submitted": None,
                 "items": []}
            self.s["reviews"].append(r)
            self.save()
            return {"data": {"type": "reviewSubmissions", "id": r["id"]}}

        if method == "POST" and p == "/v1/reviewSubmissionItems":
            rid = data["relationships"]["reviewSubmission"]["data"]["id"]
            next(r for r in self.s["reviews"] if r["id"] == rid)["items"].append(
                data["relationships"]["appStoreVersion"]["data"]["id"])
            self.save()
            return {}

        if method == "PATCH" and (m := re.fullmatch(r"/v1/reviewSubmissions/([\w-]+)", p)):
            r = next(r for r in self.s["reviews"] if r["id"] == m[1])
            if data["attributes"].get("submitted"):
                r["state"], r["submitted"] = "WAITING_FOR_REVIEW", now()
                for vid in r["items"]:
                    self._version(vid)["state"] = "WAITING_FOR_REVIEW"
            self.save()
            return {}

        if method == "POST" and p == "/v1/appStoreVersionReleaseRequests":
            self._version(data["relationships"]["appStoreVersion"]["data"]["id"])["state"] = "PROCESSING_FOR_DISTRIBUTION"
            self.save()
            return {}

        raise SystemExit(f"fake_asc: unsupported request {method} {path}")

    def advance(self) -> list[str]:
        """One step of Apple's side. Returns what changed, for the demo's log."""
        changed = []
        for b in self.s["builds"]:
            if b["state"] == "PROCESSING":
                b["state"] = "VALID"
                changed.append(f"build {b['version']} ({b['build']}) VALID")
        for r in self.s["reviews"]:
            vs = [self._version(vid) for vid in r["items"]]
            if r["state"] == "WAITING_FOR_REVIEW":
                r["state"] = "IN_REVIEW"
                for v in vs:
                    v["state"] = "IN_REVIEW"
                changed.append("review IN_REVIEW")
            elif r["state"] == "IN_REVIEW":
                outcome = self.s["review_outcomes"].pop(0) if self.s["review_outcomes"] else "approve"
                if outcome == "reject":
                    r["state"] = "UNRESOLVED_ISSUES"
                    for v in vs:
                        v["state"] = "REJECTED"
                else:
                    r["state"] = "COMPLETE"
                    for v in vs:
                        v["state"] = "PENDING_DEVELOPER_RELEASE" if v["release_type"] == "MANUAL" else "PROCESSING_FOR_DISTRIBUTION"
                changed.append(f"review {outcome}")
        for v in self.s["versions"]:
            if v["state"] == "PROCESSING_FOR_DISTRIBUTION":
                v["state"] = LIVE
                changed.append(f"version {v['version']} live")
        for x in self.s["review_responses"]:
            if x["state"] == "PENDING_PUBLISH":
                x["state"] = "PUBLISHED"
                changed.append("review reply published")
        if self.s["incoming_reviews"]:
            r = self.s["incoming_reviews"].pop(0) | {"created": now()}
            self.s["customer_reviews"].append(r)
            changed.append(f"new {r['rating']}-star review from {r['territory']}")
        self.save()
        return changed


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "advance":
        raise SystemExit("usage: fake_asc.py advance STATE")
    print("\n".join(Fake(sys.argv[2]).advance()) or "nothing to advance")
