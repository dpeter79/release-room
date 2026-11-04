# Release checklist

Commands, run from your directory, one at a time, with nothing piped or chained:

- `../../bin/asc status <app id>`
- `../../bin/asc create-version <app id> <version>`
- `../../bin/asc attach-build <app id> <version> <build>`
- `../../bin/asc whatsnew <app id> <version> --dir <localization folder>`
- `../../bin/asc description <app id> <version> --dir <localization folder>`
- `../../bin/asc review-notes <app id> <version> --repo <repo>`
- `../../bin/asc submit <app id> <version>`
- `../../bin/asc release <app id> <version>`
- `../../bin/bump <app id> <repo> <version>`
- `../../bin/upload <app id> <repo>`

Each of these except `status` is a dry run until you add `--apply`. Post each dry run before its `--apply`. End every step with a one-line status that starts with the app and version.

1. Run `status`. `live` is the live version. Use the upload date of the newest VALID build with that version as the boundary; if more than one could be the shipped build, or none is listed, say so and ask. Read `git -C REPO log --since=<date> --oneline`, and draft What's New in en-US: what users notice, no internal names. Only committed work ships: if `git -C REPO status --short` shows uncommitted files, mention that in one line and leave them out of the notes.
2. Wait for the person to edit or approve. Save the approved text as room document `whats-new-<version>`. Then handle the two other texts, and edit their files once the person approves. Editing asks for an Allow.
   - **App Review notes:** show the part of `marketing/app-review-notes.md` that says what's new, rewritten for this version. If the repo has no such file, run `review-notes`, which prints the notes on Apple. Update those, or draft notes from the code and commits if there are none, and create the file. Put the notes between two `---` lines.
   - **Description:** compare the commits since the last version with `version.description` in `marketing/localization/en-US/strings.json`. For every new function a customer would notice that it doesn't mention, propose English wording. If there is none, say so in one line.
3. Ask @l10n to translate it, and any changed description text into every language already in the folder. Done when @l10n posts that the translations are ready.
4. Check `status` for a VALID build whose version is this version. If it's PROCESSING, wait for @asc to report VALID, then go to step 5. If there's none, run `bump` and then `upload`, each dry run first, and wait for @asc to report VALID. `bump` commits the new version and the translations together. A VALID build with another version isn't this version's build, so say so. If either refuses because of uncommitted work, stop and ask the person to deal with it: never commit, stash or discard it yourself. If an upload fails, post the error and ask the person to upload from Xcode.
5. If `status` already lists this version, skip `create-version`. Otherwise run it. Then run `attach-build` with the build number from `status`. Done when it prints `Attached build`.
6. Run `whatsnew`, then with `--apply`, then the dry run again. Done when it prints `0 locale(s) to update`. Do the same with `description`, whose dry run must show only the change the person approved, and with `review-notes`, which is done when it prints `0 to update`. A locale marked skipped isn't on the version in App Store Connect: say so and go on, and the person adds it there.
7. Run `submit`. Done when it prints `Submitted`. If no build was needed in step 4, tell the person the translations are still uncommitted.
8. Wait for @asc. On PENDING_DEVELOPER_RELEASE go to step 10. On REJECTED, METADATA_REJECTED or DEVELOPER_REJECTED go to step 9. On PROCESSING_FOR_DISTRIBUTION or READY_FOR_DISTRIBUTION, the version was set to release automatically, so skip the release in step 10.
9. Ask the person to paste Apple's message. Match it against `past-rejections`, find the cause in the code, propose a diff, and draft the Resolution Center reply. There's no command for that reply: the person pastes it into App Store Connect. The person also applies and commits the fix, or tells you to apply it, which asks for an Allow. If the fix needs a new build, continue at step 4 once it's committed. If only metadata or the reply changed, or the person says to resubmit as it is, continue at step 7 once the person says the reply is posted. The version already exists, so never run `create-version` again.
10. Run `release`, and wait. When @asc reports READY_FOR_DISTRIBUTION, say it's live and post the recap: what shipped and in how many languages, plus how long each step waited on a person and on Apple if you have the message timestamps. Otherwise say the timings aren't available.
