#!/bin/bash
# MacWhisper Transcription API - Update Script
# Pulls latest changes from git and restarts the service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DAEMON_PLIST="/Library/LaunchDaemons/com.transcriptionserver.macwhisper-api.plist"

echo "========================================"
echo "MacWhisper Transcription API Updater"
echo "========================================"
echo ""

cd "$PROJECT_DIR"

# Check for uncommitted changes
echo "[1/4] Checking for local changes..."
if [[ -n $(git status --porcelain) ]]; then
    echo "  WARNING: You have uncommitted changes"
    git status --short
    echo ""
    read -p "Stash changes and continue? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git stash
        echo "  Changes stashed"
    else
        echo "  Aborted"
        exit 1
    fi
fi

# Pull latest changes
echo ""
echo "[2/4] Pulling latest changes..."
git pull origin master
echo "  Updated to latest version"

# Update dependencies if requirements changed
echo ""
echo "[3/4] Updating dependencies..."
pip3 install --user -r requirements.txt --quiet
echo "  Dependencies updated"

# Restart service
echo ""
echo "[4/4] Restarting service..."

if [[ -f "$DAEMON_PLIST" ]]; then
    echo "  Restarting via launchctl..."
    sudo launchctl unload "$DAEMON_PLIST" 2>/dev/null || true
    sleep 2
    sudo launchctl load "$DAEMON_PLIST"
    echo "  Service restarted"
else
    echo "  No daemon installed, checking for running process..."
    if pgrep -f "python.*server.py" > /dev/null; then
        echo "  Killing existing server process..."
        pkill -f "python.*server.py" || true
        sleep 2
    fi
    echo "  Starting server in background..."
    nohup python3 "$PROJECT_DIR/src/server.py" > /tmp/server.log 2>&1 &
    echo "  Server started (PID: $!)"
fi

# Wait for server to start
echo ""
echo "Waiting for server to start..."
sleep 3

# Verify server is running
if curl -s http://localhost:3001/health > /dev/null 2>&1; then
    echo "Server is running!"
    curl -s http://localhost:3001/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:3001/health
else
    echo "WARNING: Server may not have started correctly"
    echo "Check logs: tail -f $PROJECT_DIR/logs/api.log"
fi

echo ""
echo "========================================"
echo "Update Complete!"
echo "========================================"
