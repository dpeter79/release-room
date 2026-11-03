# Troubleshooting

## The server isn't running

`Can't reach Switch at http://127.0.0.1:...`, or agents stay silent after a restart. In our testing the local server didn't come back by itself after a restart of the Mac. Open it in Switch Console and start it, and make sure Docker Desktop is running for Mattermost. Agents answer only while their machine's agent controller is running, which on a local setup means Switch Console on this Mac.

## `make demo` can't register `@asc`

`make demo` uses the local server's Gateway API with the admin login Console generated. If that fails, create the key yourself on the Gateway's API Keys page: in Console, open the server's Home and select Open beside Full admin interface. If there's no Gateway, as on the local server we tested, run it yourself. You need Node.js. In a folder of your choice:

```sh
git clone --depth 1 https://github.com/sandbox-quantum/switch && cd switch/gateway
```

In `vite.config.ts`, point the proxy target at your API port (the `api` value in `~/Library/Application Support/switchdash/local-switch-server/ports.json`). Then:

```sh
npm install --ignore-scripts
node_modules/.bin/vite --port 5199 --host 127.0.0.1
```

Open http://127.0.0.1:5199/ and sign in with `GATEWAY_ADMIN_EMAIL` and `GATEWAY_ADMIN_PASSWORD` from `~/Library/Application Support/switchdash/local-switch-server/native/run/switch-core.env`. Under **API Keys**, create a registration key, copy it, and run:

```sh
pbpaste | python3 register_asc.py
make demo
```

## An agent doesn't answer

- Spell the name exactly, and don't end the sentence with it: `@release.` doesn't match.
- Mention the agent, unless follow-ups are on: then a thread reply reaches the agent that last spoke, and a channel message reaches it within 5 minutes of its last answer.
- It may still be working. Messages queue until its current turn ends, so a reply can take a while.
- `!agents-status` shows who's busy. A hand means a request is waiting for you, often in an older thread.
- "I only take instructions from my owner" means your chat account isn't linked to your Switch user. Link it in Console.
- See Switch's [When an agent doesn't answer](https://docs.switchagents.ai/switch-rooms/using/agent-not-answering.md).

## `@asc` looks offline

That's expected. It posts over HTTP and has no session, so Switch shows it as awaiting a manual poll. To check it, look at the `make poster` terminal.

## `make advance` changed something, but nothing appears

- `make poster` must be running before the first `make advance`, because its first poll only records.
- It polls every 20 seconds in the demo, and every 2 minutes by default.
- `post failed, will retry` means Switch was unreachable. The post is safe in `state/outbox.jsonl`.
- `asc failed` means a command failed: try `bin/asc status 1000000001` by hand.
- `make advance` printing `nothing to advance` is normal when Apple is waiting on you.

## A warning says an agent "isn't in this room"

In the demo the agents are named `demo-release` and so on, with room aliases like `@release`. In testing, on a server that also had an agent named `release`, typing `@release` got this warning. The message still reaches the demo agent. `@asc` uses the full names, so it doesn't trigger it.

## The template stops with a name that's taken

Agent names are unique on a server, so running `democam-demo` a second time stops. Delete the `demo-*` agents under **Your Agents**, or carry on in the existing room. A template also needs the Console machine online, with Claude Code signed in.

## `@release` refuses something `@asc` asked for

That's by design. Only people can give instructions; `@asc`'s posts are data. Send the request yourself.

## Start the demo over

`make reset` recreates the fake and the demo repo, and keeps `@asc`'s registration. Then send `!reset @release` in the room, so it forgets the old run. To remove everything, archive the room and delete the `demo-*` agents in Console.

## A shell command says `Operation not permitted`

That's the sandbox from `lock_agents.py`, stopping an agent from reading outside its folders. If the agent needs that folder, name it when you run `lock_agents.py`. A `bin/` command piped into something else stays in the sandbox and can't reach its keys, so run it by itself. If the sandbox can't start at all, Claude Code exits instead of running unprotected (`failIfUnavailable`).

## An Allow never appears

Keep Auto mode on for the agent. If a write runs with no Allow, stop the agent and check its `.claude/settings.json`.

## `whatsnew` says a locale was skipped

The locale isn't on the version in App Store Connect yet. Add it there first.

## `bin/upload` or `bin/bump` refuses

- `uncommitted changes`: a build must match committed code, so commit or stash your work. The agent can't do that for you.
- `isn't on a branch`: check out a branch first, because a commit here would get lost.
- `already uploaded`: that version and build are on App Store Connect, so run `bin/bump` first.
- `Expected one MARKETING_VERSION`: your targets have different versions in `project.yml`, so set the version by hand and upload from Xcode.

## An upload fails

The error and the path of the full log (`state/upload/<app>/upload.log`) are posted in the room. Build the app once in Xcode if signing complains about missing profiles or accounts. Xcode can also ask for its Metal toolchain: `xcodebuild -downloadComponent MetalToolchain`. If only the Uploading step failed, wait a minute and check `bin/asc status`: Apple accepts a version and build only once, so if the build is there, don't upload it again. You can always upload from Xcode instead, and `@asc` reports the build the same way.

## Sales questions fail

`Sales aren't set up` means `SALES_PROBE` is empty in `.env`. See [Sales](setup.md#sales-optional). `missing` days are normal: Apple doesn't say whether the report isn't ready or there were no sales.
