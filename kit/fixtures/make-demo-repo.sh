#!/bin/sh
# Creates a small DemoCam repo whose history since the 1.0.0 release is what
# a release agent turns into What's New. Usage: make-demo-repo.sh DIR
set -eu
dir=${1:?usage: make-demo-repo.sh DIR}
[ -e "$dir" ] && { echo "$dir already exists" >&2; exit 1; }
mkdir -p "$dir" && cd "$dir"
git init -q
c() { GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" git -c user.name=Demo -c user.email=demo@example.com commit -q --allow-empty -m "$2"; }

printf '# DemoCam plan\n\n## 1.0.0 released (2026-09-01)\n\n- [x] Virtual camera with one filter\n' > PLAN.md
git add PLAN.md && c 2026-09-01T10:00:00 "Release 1.0.0 (5)"
c 2026-10-20T09:12:00 "Refresh the camera list when a webcam is plugged in"
c 2026-10-21T16:40:00 "Switch back to the saved camera after a fallback"
c 2026-10-22T11:05:00 "Internal: rename CameraWatcher to DeviceMonitor"
printf '\n## 1.1.0 (7): camera hotplug (2026-10-27)\n\n- [x] Plugging a webcam in refreshes the camera list\n- [x] Switches back to the saved camera if DemoCam had fallen back\n- [x] Uploaded 2026-10-27\n' >> PLAN.md
git add PLAN.md && c 2026-10-27T09:00:00 "Bump to 1.1.0 (7)"
echo "DemoCam repo at $(pwd): $(git rev-list --count HEAD) commits"
