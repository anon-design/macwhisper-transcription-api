#!/bin/bash
# MacWhisper Transcription API - LaunchDaemon Installer
# Installs the service to auto-start on boot

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DAEMON_NAME="com.transcriptionserver.macwhisper-api"
DAEMON_PLIST="/Library/LaunchDaemons/$DAEMON_NAME.plist"
USER_HOME="/Users/transcriptionserver"

echo "========================================"
echo "LaunchDaemon Installer"
echo "========================================"
echo ""

# Check for sudo
if [[ $EUID -ne 0 ]]; then
    echo "This script requires sudo privileges"
    echo "Re-running with sudo..."
    exec sudo "$0" "$@"
fi

# Stop existing daemon if running
if launchctl list | grep -q "$DAEMON_NAME"; then
    echo "Stopping existing daemon..."
    launchctl unload "$DAEMON_PLIST" 2>/dev/null || true
    sleep 2
fi

# Create plist file
echo "Creating LaunchDaemon plist..."
cat > "$DAEMON_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$DAEMON_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$PROJECT_DIR/src/server.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>

    <key>UserName</key>
    <string>transcriptionserver</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/daemon-stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/daemon-stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>$USER_HOME</string>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

# Set permissions
echo "Setting permissions..."
chown root:wheel "$DAEMON_PLIST"
chmod 644 "$DAEMON_PLIST"

# Ensure log directory exists
mkdir -p "$PROJECT_DIR/logs"
chown -R transcriptionserver:staff "$PROJECT_DIR/logs"

# Load daemon
echo "Loading daemon..."
launchctl load "$DAEMON_PLIST"

# Wait for startup
sleep 3

# Verify
echo ""
if launchctl list | grep -q "$DAEMON_NAME"; then
    echo "Daemon installed and running!"
    echo ""
    echo "Useful commands:"
    echo "  - Status: sudo launchctl list | grep macwhisper"
    echo "  - Stop:   sudo launchctl unload $DAEMON_PLIST"
    echo "  - Start:  sudo launchctl load $DAEMON_PLIST"
    echo "  - Logs:   tail -f $PROJECT_DIR/logs/api.log"
else
    echo "WARNING: Daemon may not have started correctly"
    echo "Check logs: tail -f $PROJECT_DIR/logs/daemon-stderr.log"
fi

echo ""
echo "========================================"
echo "Installation Complete!"
echo "========================================"
