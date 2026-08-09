#!/usr/bin/env bash
# One command to start everything: both receivers + prevent sleep.
# Run this in the morning, Ctrl-C at end of day.
#
# What it does:
#   1. Kills any old receivers so you never end up with stale versions.
#   2. Starts WDG receiver on port 8765 in background.
#   3. Starts US Moda receiver on port 8766 in background.
#   4. Runs caffeinate -disu in the foreground: prevents display sleep,
#      idle sleep, system sleep, and disk sleep. Ctrl-C to end.
#
# When you Ctrl-C, both receivers keep running in the background so any
# already-captured data still gets pushed. To fully stop:
#   pkill -f live_receiver.py

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Killing any old receiver processes"
pkill -f live_receiver.py 2>/dev/null || true
sleep 1

echo "==> Starting WDG receiver (port 8765)"
nohup python3 tools/live_receiver.py --market wdg --port 8765 --refresh-min 5 \
    > /tmp/wdg_receiver.log 2>&1 &
echo "    PID $! → logs at /tmp/wdg_receiver.log"

echo "==> Starting US Moda receiver (port 8766)"
nohup python3 tools/live_receiver.py --market usmoda --port 8766 --refresh-min 5 \
    > /tmp/usmoda_receiver.log 2>&1 &
echo "    PID $! → logs at /tmp/usmoda_receiver.log"

echo
echo "==> Both receivers running. WhatsApp+FB tabs will now feed them."
echo "==> Now preventing sleep with caffeinate. Press Ctrl-C to release."
echo "    (Receivers keep running after Ctrl-C. Use 'pkill -f live_receiver.py' to fully stop.)"
echo
exec caffeinate -disu
