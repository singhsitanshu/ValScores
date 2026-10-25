#!/usr/bin/env bash
# Run the ValScoresTests XCTest target through the shared `valoreal` scheme.
#
# Usage: scripts/ios-test.sh [extra xcodebuild arguments]
#   IOS_SIMULATOR="iPhone 16e"  pick a specific simulator (default: first available iPhone)
#   DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer  use Xcode when
#     xcode-select points at the Command Line Tools
set -euo pipefail

cd "$(dirname "$0")/.."

if ! xcodebuild -version >/dev/null 2>&1; then
  echo "xcodebuild is unavailable. Install Xcode, then run:" >&2
  echo "  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" >&2
  echo "or prefix this script with DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer" >&2
  exit 1
fi

simulator_id="$(
  xcrun simctl list devices available -j | IOS_SIMULATOR="${IOS_SIMULATOR:-}" python3 -c '
import json, os, sys
wanted = os.environ["IOS_SIMULATOR"]
runtimes = json.load(sys.stdin)["devices"]
for runtime in sorted(runtimes, reverse=True):
    if ".iOS-" not in runtime:
        continue
    for device in runtimes[runtime]:
        name = device["name"]
        if (wanted and name == wanted) or (not wanted and name.startswith("iPhone")):
            print(device["udid"])
            sys.exit(0)
sys.exit(1)
'
)" || {
  echo "No available iOS simulator matched '${IOS_SIMULATOR:-iPhone*}'." >&2
  echo "Install one from Xcode > Settings > Components." >&2
  exit 1
}

xcodebuild -version
echo "Testing on simulator ${simulator_id}"
xcodebuild \
  -project valoreal.xcodeproj \
  -scheme valoreal \
  -destination "id=${simulator_id}" \
  "$@" \
  test
