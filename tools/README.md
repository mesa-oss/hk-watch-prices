# tools/

Extra scripts that aren't part of the core parsing pipeline.

## `whatsapp_web_extract.js`

Pulls messages from a WhatsApp group directly via **WhatsApp Web**, for
groups where the "Export chat" button has been disabled but you're still a
member. Downloads a text file in the same format as an official export, so
the same parser handles it.

### Weekly workflow

1. Open <https://web.whatsapp.com> in Chrome, log in via QR code.
2. Open the target group.
3. Scroll up as far back as you want to capture (optional — the script also
   scrolls itself, but starting further back speeds things up).
4. Open **DevTools** (⌥⌘I) → **Console** tab.
5. Open [`whatsapp_web_extract.js`](whatsapp_web_extract.js), copy the whole
   file, paste it into the Console, press Enter.
6. Watch the console for progress (`… 1,234 messages so far`). When it
   finishes, a `whatsapp_chat_YYYY-MM-DD.txt` file downloads.
7. Move that file into the right market's exports folder, renamed with the
   date, e.g.:

   ```bash
   mv ~/Downloads/whatsapp_chat_2026-08-10.txt \
      ~/Projects/hk-watch-prices/exports/wdg/2026-08-10_export.txt
   ```

8. Run the refresh:

   ```bash
   cd ~/Projects/hk-watch-prices
   python3 src/refresh.py --market wdg
   ```

Same dedup / vacuum happens automatically; the Streamlit UI's Market
toggle picks up the new database on next reload.

### Troubleshooting

- **"Couldn't find the WhatsApp chat pane"** — you don't have a chat open,
  or WhatsApp has changed its selectors. Refresh the page, click into the
  target chat first, then run the script.
- **Scrolls forever without stopping** — you're in a very large group. Let
  it run; it'll converge once it reaches the top of loaded history.
- **Nothing downloads** — Chrome blocked the download. Look at the address
  bar for a blocked-download indicator and allow it.
- **Missing messages** — messages inside "Disappearing" retention windows
  or older than the WhatsApp Web cache aren't visible to anyone (not
  even you). Nothing to be done about those.

### On ethics / ToS

You're a group member with legitimate read access. The export button is a
UX toggle, not a permission — every message this script captures is one
that WhatsApp Web is already showing you in your browser. Don't use this
to redistribute private conversations; personal-use price tracking is the
intended use case here.
