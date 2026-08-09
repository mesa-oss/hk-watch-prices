#!/usr/bin/env bash
# One-command starter for Tier 2 live capture.
#
#   ./tools/live_start.sh
#
# Starts the local receiver server and copies the capture JS to your clipboard
# so you can paste it into Chrome DevTools with one keystroke.

set -e
cd "$(dirname "$0")/.."

# 1. Copy the capture script to clipboard
cat tools/live_capture.js | pbcopy
echo "✓ Live capture JS copied to clipboard"
echo

# 2. Print the instructions the user needs
echo "One-time setup for THIS Terminal window:"
echo "  a) Make sure Chrome has web.whatsapp.com open with the WDG chat selected."
echo "  b) In DevTools Console (⌥⌘J), type 'allow pasting' + Enter (first time only)."
echo "  c) Paste (⌘V) + Enter — a green badge will appear on the WA page."
echo
echo "Now starting the receiver server. Leave this Terminal open."
echo "(Ctrl+C here to stop.)"
echo

# 3. Run the receiver in the foreground
exec python3 tools/live_receiver.py --market wdg
