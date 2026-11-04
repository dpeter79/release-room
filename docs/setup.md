# Use it for your own app

This takes about an hour. It assumes Switch Console with a server, and Claude Code signed in, as in the [demo](../README.md#run-the-demo). Clone a fresh copy: the demo's `.env` points at the fake.

## 1. Add your App Store Connect key

Copy `.env.example` to `.env` and fill in `APP_STORE_KEY_ID` and `APP_STORE_ISSUER_ID`. Leave `ASC_MOCK` empty, because a value there sends everything to the fake.

Put the `.p8` key at `~/.appstoreconnect/private_keys/AuthKey_<KEY_ID>.p8`, or set `APP_STORE_P8_PATH`. Real mode runs `kit/asc.py` through [uv](https://docs.astral.sh/uv/), so install uv first; it fetches the one dependency on first run.

Set `SWITCH_API` to your server's API address. For Console's local server, the port is `api` in `~/Library/Application Support/switchdash/local-switch-server/ports.json`.

## 2. Create the agents

In Console open **Your Agents**, then the dashed card, once per agent. The names must be exactly these, and can't be changed later. Leave Auto mode on, and Who can talk to your agent on **Me and my agents**.

| Name | Directory |
| --- | --- |
| `release` | `<this repo>/agents/release` |
| `l10n` | `<this repo>/agents/l10n` |
| `stats` | `<this repo>/agents/stats` |
| `reviews` | `<this repo>/agents/reviews` |

Leave Agent instructions empty, because each agent reads the `AGENTS.md` in its folder, which Claude Code gets through a one-line `CLAUDE.md`. Then open Claude Code once in this repo and accept the trust dialog: an untrusted folder's allow rules are ignored.

## 3. Register `@asc`

Create a registration key on the Gateway's API Keys page. In Console, open the server's Home and select Open beside Full admin interface. If your local server shows no Gateway, as ours didn't, [run it yourself](troubleshooting.md#make-demo-cant-register-asc). You must create the key yourself: it makes you `@asc`'s owner, and "Me and my agents" is what lets `@asc` start your agents' turns.

```sh
pbpaste | python3 register_asc.py
```

## 4. Limit what agents can read

```sh
python3 lock_agents.py /path/to/your/app/repo
```

Name every app repo the agents should see. Run it again after adding a folder to your home folder.

## 5. Create a room

Check `room/docs/do-not-localize.md` for any other names you want kept as written, then:

```sh
python3 save_template.py
```

In Console open **Templates**, then **Use** on `app-release-room`, and fill in the app's name, room prefix, App Store Connect id, repo path, source language and the language you'll check. Repeat for each app.

The repo should have `marketing/localization/<locale>/strings.json`, with the release notes in `version.whatsNew` and the App Store description in `version.description` (a string, or a list of lines). A locale must already exist on the version in App Store Connect, or `whatsnew` skips it and says so.

### What your app needs

Paths are relative to the app's repo.

| What | Needed for | If it's missing |
| --- | --- | --- |
| `marketing/localization/<locale>/strings.json`, one folder per App Store locale | What's New and the description | `@release` runs `pull-text`, which starts them from your newest version on Apple, in every language it already has. What's New is then written from the commits |
| `marketing/app-review-notes.md` | App Review notes | `review-notes` prints the notes on Apple, and `@release` creates the file with your approval |
| `project.yml` for XcodeGen, with a top-level `name` matching the scheme | `bin/bump` and `bin/upload` | They refuse. Upload the build another way and the rest of the release still works, starting from a VALID build |
| A Mac app | `bin/upload`, which always builds for macOS | Same as above. Other platforms are untested |

A minimal `strings.json`. Other keys in the file are ignored:

```json
{
  "version": {
    "whatsNew": "What changed in this version.",
    "description": ["First line of the description.", "Second line."]
  }
}
```

`version` here is the group for text that belongs to an App Store version, not a version number, so the text can stay the same between releases. `whatsNew` and `description` can each be a string or a list of lines.

In `app-review-notes.md`, the notes go between the first two `---` lines, so you can keep your own comments above and below them. With only one `---`, the notes are everything after it:

```markdown
# My notes to myself, not sent to Apple

---

What the reviewer should know, and what's new in this version.

---

More notes to myself, not sent to Apple.
```

The source language is the locale your description is written in first. `description` refuses to send a changed description while any translation is still unchanged.

## 6. Start `@asc`

Find your room ids with `python3 switch_op.py list_all_rooms`, and list them in `rooms.json`:

```json
[{"room_id": "...", "app": "1234567890"}]
```

One room per app. Then run `python3 asc_poster.py` somewhere it can stay running, such as a terminal or a launchd service. If it stops, it reports what it missed when it starts again.

## Uploads

`@release` can make a build from the room, after an Allow for each step, if your app is a Mac app using [XcodeGen](https://github.com/yonaskolb/XcodeGen):

- `bin/bump APP_ID REPO VERSION --apply` sets the version in `project.yml` and every `Info.plist` it names, picks the next free build number, and commits those files with any new translations and App Review notes. It leaves everything else alone.
- `bin/upload APP_ID REPO --apply` generates the project, archives, exports and uploads, and can take up to 15 minutes. It refuses if the repo has uncommitted changes, so a build always matches committed code. Commit your own work first.

You need `xcodegen` installed, and your signing set up: build the app once in Xcode, so a provisioning profile is cached. The scheme must match `name:` in `project.yml`. Your API key must be in `~/.appstoreconnect/private_keys`. For anything else, upload from Xcode, and `@asc` reports the build when it's ready.

## Connect Slack

These steps follow [Switch's Slack guide](https://docs.switchagents.ai/switch-rooms/deploy/messaging-apps/slack.md).

1. At [api.slack.com/apps](https://api.slack.com/apps) choose **Create New App**, then **From an app manifest**, and paste [`docs/slack-manifest.json`](slack-manifest.json). It's Switch's manifest as of Console 0.40, with the `agent_view` block and `assistant:write` scope removed: Switch doesn't use them, and the Agent declaration can't be undone.
2. In **Basic Information**, generate an app-level token with `connections:write` (`xapp-...`).
3. Install the app, and copy the Bot User OAuth Token (`xoxb-...`).
4. Find your workspace ID: open Slack in a browser, and it's the `T...` part of the address.
5. In Console open the server's **Home**, then **Messaging apps**, **Connect**, **Slack**. Paste both tokens and the ID. Turn **Agent name autocomplete** off unless you have a paid Slack plan, because it can't be changed in Console later. Then choose **This is me**.
6. Choose Slack as the Messaging app when you use the template.

On a free workspace there's no autocomplete, so type `@release` in full.

## Sales (optional)

`@stats` answers sales questions through `bin/sales`, which calls a program you provide. Everything else works without it. Set `SALES_PROBE` to the program and `SALES_CONFIG` to anything it needs in `.env`. It's called as:

```sh
$SALES_PROBE $SALES_CONFIG --summary 2026-11-02 --currency EUR
```

It prints one JSON object for that day. A day with no report is `{"status": "missing", "day": "2026-11-02"}`. A failure exits non-zero with a `text` field. [`demo/fake_probe.py`](../demo/fake_probe.py) is a working example, and prints this plus a few fields `bin/sales` ignores:

```json
{
  "status": "report",
  "day": "2026-11-02",
  "unconverted": {},
  "products": [{"title": "DemoCam Pro", "units": 1, "proceeds": "8.40"}]
}
```

Apple's source for this is `GET /v1/salesReports`, a gzipped daily file, which your program reads and converts. `units` is net of refunds, and `proceeds` is a decimal string in EUR. `unconverted` lists any currency you couldn't convert. Titles must start with the app name the room uses.
