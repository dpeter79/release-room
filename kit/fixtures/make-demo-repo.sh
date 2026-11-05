#!/bin/sh
# Creates a small DemoCam repo whose history since the 1.0.0 release is what
# a release agent turns into What's New. Usage: make-demo-repo.sh DIR
set -eu
dir=${1:?usage: make-demo-repo.sh DIR}
[ -e "$dir" ] && { echo "$dir already exists" >&2; exit 1; }
mkdir -p "$dir" && cd "$dir"
git init -q
c() { GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" git -c user.name=Demo -c user.email=demo@example.com commit -q -m "$2"; }

printf '# DemoCam plan\n\n## 1.0.0 released (2026-09-01)\n\n- [x] Virtual camera with one filter\n' > PLAN.md
mkdir Sources
cat > Sources/ExtensionInstaller.swift <<'SWIFT'
import SystemExtensions

/// Installs the virtual camera. The app shows a spinner while isInstalling is true.
final class ExtensionInstaller: NSObject, ObservableObject, OSSystemExtensionRequestDelegate {
    @Published var isInstalling = false

    func install() {
        isInstalling = true
        let request = OSSystemExtensionRequest.activationRequest(forExtensionWithIdentifier: "com.example.democam.camera", queue: .main)
        request.delegate = self
        OSSystemExtensionManager.shared.submitRequest(request)
    }

    func request(_ request: OSSystemExtensionRequest, didFinishWithResult result: OSSystemExtensionRequest.Result) { isInstalling = false }
    func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) { isInstalling = false }
    func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {}
    func request(_ request: OSSystemExtensionRequest, actionForReplacingExtension existing: OSSystemExtensionProperties, withExtension ext: OSSystemExtensionProperties) -> OSSystemExtensionRequest.ReplacementAction { .replace }
}
SWIFT
cat > Sources/CameraWatcher.swift <<'SWIFT'
import AVFoundation

/// The cameras DemoCam can use. Read once at launch.
final class CameraWatcher: ObservableObject {
    @Published var cameras = AVCaptureDevice.DiscoverySession(deviceTypes: [.external, .builtInWideAngleCamera], mediaType: .video, position: .unspecified).devices
}
SWIFT
git add PLAN.md Sources && c 2026-09-01T10:00:00 "Release 1.0.0 (5)"
cat > Sources/CameraWatcher.swift <<'SWIFT'
import AVFoundation

/// The cameras DemoCam can use, kept current as cameras are connected.
final class CameraWatcher: ObservableObject {
    @Published var cameras: [AVCaptureDevice] = []
    private var observer: NSObjectProtocol?

    init() {
        refresh()
        observer = NotificationCenter.default.addObserver(forName: AVCaptureDevice.wasConnectedNotification, object: nil, queue: .main) { [weak self] _ in self?.refresh() }
    }

    func refresh() {
        cameras = AVCaptureDevice.DiscoverySession(deviceTypes: [.external, .builtInWideAngleCamera], mediaType: .video, position: .unspecified).devices
    }
}
SWIFT
git add Sources && c 2026-10-20T09:12:00 "Refresh the camera list when a webcam is plugged in"
cat > Sources/CameraWatcher.swift <<'SWIFT'
import AVFoundation

/// The cameras DemoCam can use, kept current as cameras are connected.
final class CameraWatcher: ObservableObject {
    @Published var cameras: [AVCaptureDevice] = []
    @Published var current: AVCaptureDevice?
    var savedCameraID: String?
    private var observer: NSObjectProtocol?

    init() {
        refresh()
        observer = NotificationCenter.default.addObserver(forName: AVCaptureDevice.wasConnectedNotification, object: nil, queue: .main) { [weak self] _ in self?.refresh() }
    }

    func refresh() {
        cameras = AVCaptureDevice.DiscoverySession(deviceTypes: [.external, .builtInWideAngleCamera], mediaType: .video, position: .unspecified).devices
        if let saved = cameras.first(where: { $0.uniqueID == savedCameraID }) { current = saved }  // back from a fallback
    }
}
SWIFT
git add Sources && c 2026-10-21T16:40:00 "Switch back to the saved camera after a fallback"
git mv Sources/CameraWatcher.swift Sources/DeviceMonitor.swift
sed -i.bak 's/CameraWatcher/DeviceMonitor/' Sources/DeviceMonitor.swift && rm Sources/DeviceMonitor.swift.bak
git add Sources && c 2026-10-22T11:05:00 "Internal: rename CameraWatcher to DeviceMonitor"
printf '\n## 1.1.0 (7): camera hotplug\n\n- [x] Plugging a webcam in refreshes the camera list\n- [x] Switches back to the saved camera if DemoCam had fallen back\n- [x] Uploaded\n' >> PLAN.md
git add PLAN.md && c 2026-10-27T09:00:00 "Bump to 1.1.0 (7)"
echo "DemoCam repo at $(pwd): $(git rev-list --count HEAD) commits"
