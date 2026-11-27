#!/usr/bin/env bash
# Install or uninstall the macOS LaunchAgent that keeps TwinScan Overwatch
# (4K USB Webcam + Built-in MacBook Pro Camera) streaming automatically in the
# background at login — zero terminal windows or manual CLI commands required.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_LABEL="com.eigenia.twinscan.camera-bridge"
PLIST_PATH="${HOME}/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_PATH="${HOME}/Library/Logs/eigenia-camera-bridge.log"
PYTHON_BIN="${REPO_DIR}/.venv/bin/python"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)" "${PLIST_PATH}" 2>/dev/null || launchctl unload "${PLIST_PATH}" 2>/dev/null || true
  rm -f "${PLIST_PATH}"
  echo "Removed ${PLIST_LABEL} LaunchAgent."
  exit 0
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/Library/Logs"

cat > "${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${REPO_DIR}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>-m</string>
    <string>src.bridge.mac_camera_bridge</string>
    <string>--all-cameras</string>
    <string>--width</string>
    <string>1920</string>
    <string>--height</string>
    <string>1080</string>
    <string>--fps</string>
    <string>10</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>5</integer>
  <key>StandardOutPath</key>
  <string>${LOG_PATH}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_PATH}</string>
</dict>
</plist>
EOF

# Stop any prior instance cleanly before reloading
launchctl bootout "gui/$(id -u)" "${PLIST_PATH}" 2>/dev/null || launchctl unload "${PLIST_PATH}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}" 2>/dev/null || launchctl load -w "${PLIST_PATH}"

echo "Installed & started ${PLIST_LABEL}!"
echo "Plist: ${PLIST_PATH}"
echo "Logs:  ${LOG_PATH}"
