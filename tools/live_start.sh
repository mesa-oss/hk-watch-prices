#!/usr/bin/env bash
# One-command starter for Tier 2 live capture.
#
#   ./tools/live_start.sh
#
# Starts the local receiver. The capture happens via a Tampermonkey userscript
# in Chrome — see tools/live_capture.user.js for setup (once). After the
# userscript is installed, this command is all you need to run day-to-day.

set -e
cd "$(dirname "$0")/.."

cat <<'EOF'
────────────────────────────────────────────────────────────────
First time only:
  1. Install Tampermonkey from the Chrome Web Store:
       https://chromewebstore.google.com/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobfkfo
  2. Open tools/live_capture.user.js in an editor, copy its contents.
  3. Click the Tampermonkey icon in Chrome → "Create a new script…"
  4. Paste, save (⌘S).
  5. Reload web.whatsapp.com.

Every time:
  * Just run this command (which is what you're doing now).
  * Leave web.whatsapp.com open in Chrome with the WDG chat selected.
  * A green badge in the bottom-right of the WA page shows live status.

Ctrl+C to stop the receiver.
────────────────────────────────────────────────────────────────

EOF

exec python3 tools/live_receiver.py --market wdg
