#!/usr/bin/env bash
# Start the US Moda receiver on port 8766 (WDG uses 8765).
#
#   ./tools/live_start_usmoda.sh
#
# Run this in a separate Terminal window from the WDG receiver.
# Copies the FB userscript to clipboard for the first-time install.

set -e
cd "$(dirname "$0")/.."

cat tools/fb_us_capture.user.js | pbcopy

cat <<'EOF'
────────────────────────────────────────────────────────────────
US Moda live capture
────────────────────────────────────────────────────────────────

First time only:
  1. Tampermonkey icon → 'Create a new script…'
  2. Paste (⌘V) → save (⌘S).
  3. Open the US Moda Facebook group in Chrome and leave the tab open.

Every session:
  Just run this command (which is what you're doing now).
  Leave THIS Terminal window open — receiver runs in the foreground.

Ctrl+C to stop.
────────────────────────────────────────────────────────────────

EOF

exec python3 tools/live_receiver.py --market usmoda --port 8766 --refresh-min 5
