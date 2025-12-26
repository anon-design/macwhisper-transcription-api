#!/bin/bash
# MacWhisper Transcription API - Test Script
# Performs end-to-end test of transcription

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
API_URL="http://localhost:3001"

echo "========================================"
echo "MacWhisper Transcription API Test"
echo "========================================"
echo ""

# Check if server is running
echo "[1/4] Checking server health..."
HEALTH_RESPONSE=$(curl -s "$API_URL/health" 2>&1) || {
    echo "ERROR: Server is not responding at $API_URL"
    echo "Start the server first: python3 src/server.py"
    exit 1
}

echo "  Server Status:"
echo "$HEALTH_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$HEALTH_RESPONSE"

# Check MacWhisper
echo ""
echo "[2/4] Checking MacWhisper status..."
if pgrep -x "MacWhisper" > /dev/null; then
    echo "  MacWhisper is running"
else
    echo "  WARNING: MacWhisper is not running!"
    echo "  Please start MacWhisper before testing"
    read -p "Continue anyway? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create test audio file using say command
echo ""
echo "[3/4] Creating test audio..."
TEST_AUDIO="/tmp/test_transcription_$(date +%s).m4a"
say -o "$TEST_AUDIO" --data-format=alac "Hello, this is a test of the MacWhisper transcription API. This audio was generated automatically to verify the system is working correctly."
echo "  Created: $TEST_AUDIO"
echo "  Size: $(ls -lh "$TEST_AUDIO" | awk '{print $5}')"

# Submit for transcription (synchronous mode)
echo ""
echo "[4/4] Submitting for transcription (wait mode)..."
echo "  This may take 10-30 seconds..."
echo ""

START_TIME=$(date +%s)

RESPONSE=$(curl -s -X POST "$API_URL/transcribe?wait=true" \
    -F "file=@$TEST_AUDIO" \
    --max-time 120) || {
    echo "ERROR: Transcription request failed"
    rm -f "$TEST_AUDIO"
    exit 1
}

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

# Clean up test file
rm -f "$TEST_AUDIO"

# Parse and display results
echo "========================================"
echo "TEST RESULTS"
echo "========================================"
echo ""

# Check if successful
SUCCESS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('success', False))" 2>/dev/null || echo "false")

if [[ "$SUCCESS" == "True" ]] || [[ "$SUCCESS" == "true" ]]; then
    echo "STATUS: SUCCESS"
    echo ""

    # Extract key info
    TEXT=$(echo "$RESPONSE" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('result', {}).get('text', 'N/A')[:200] + '...' if len(r.get('result', {}).get('text', '')) > 200 else r.get('result', {}).get('text', 'N/A'))" 2>/dev/null || echo "N/A")
    WORDS=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('result', {}).get('words', 'N/A'))" 2>/dev/null || echo "N/A")
    PROC_TIME=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('processing_time', 'N/A'))" 2>/dev/null || echo "N/A")

    echo "Transcription: $TEXT"
    echo ""
    echo "Stats:"
    echo "  - Words: $WORDS"
    echo "  - Processing Time: ${PROC_TIME}s"
    echo "  - Total Request Time: ${ELAPSED}s"
    echo ""
    echo "========================================"
    echo "ALL TESTS PASSED"
    echo "========================================"
else
    echo "STATUS: FAILED"
    echo ""
    echo "Response:"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    echo ""
    echo "========================================"
    echo "TESTS FAILED"
    echo "========================================"
    exit 1
fi
