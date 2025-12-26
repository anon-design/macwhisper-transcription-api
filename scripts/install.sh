#!/bin/bash
# MacWhisper Transcription API - Installation Script
# This script installs dependencies, creates folders, and optionally sets up the daemon

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
USER_HOME="/Users/transcriptionserver"

echo "========================================"
echo "MacWhisper Transcription API Installer"
echo "========================================"
echo ""

# Check if running on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "ERROR: This script only works on macOS"
    exit 1
fi

# Check Python version
echo "[1/5] Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is required but not installed"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Found Python $PYTHON_VERSION"

# Install dependencies
echo ""
echo "[2/5] Installing Python dependencies..."
pip3 install --user -r "$PROJECT_DIR/requirements.txt"
echo "  Dependencies installed"

# Create required directories
echo ""
echo "[3/5] Creating directories..."

mkdir -p "$USER_HOME/MacwhisperWatched"
echo "  Created: $USER_HOME/MacwhisperWatched"

mkdir -p "$PROJECT_DIR/logs"
echo "  Created: $PROJECT_DIR/logs"

mkdir -p "$PROJECT_DIR/audio_archive"
echo "  Created: $PROJECT_DIR/audio_archive"

# Check MacWhisper
echo ""
echo "[4/5] Checking MacWhisper..."
if pgrep -x "MacWhisper" > /dev/null; then
    echo "  MacWhisper is running"
else
    echo "  WARNING: MacWhisper is not running"
    echo "  Please start MacWhisper and configure Watch Folders:"
    echo "    - Watch Folder: $USER_HOME/MacwhisperWatched"
    echo "    - Output Format: Plain Text (.txt)"
    echo "    - Output Location: Same as source"
    echo "    - Auto-Transcribe: Enabled"
fi

# Ask about daemon installation
echo ""
echo "[5/5] LaunchDaemon setup..."
read -p "Install LaunchDaemon for auto-start? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    "$SCRIPT_DIR/install-daemon.sh"
else
    echo "  Skipped daemon installation"
    echo "  You can run the server manually with: python3 src/server.py"
fi

echo ""
echo "========================================"
echo "Installation Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Ensure MacWhisper is running with Watch Folders configured"
echo "2. Test the installation: ./scripts/test.sh"
echo "3. Server runs on: http://localhost:3001"
echo ""
