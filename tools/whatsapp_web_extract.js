/* ==========================================================================
   WhatsApp Web message extractor
   --------------------------------------------------------------------------
   Use when the WhatsApp "Export Chat" button is disabled but you're still a
   group member with legitimate read access.

   HOW TO USE:
     1. Open https://web.whatsapp.com in Chrome. Log in with the QR code.
     2. Open the group you want to extract.
     3. Optional: scroll UP as far as you care to go (this seeds the range).
     4. Open DevTools:  View → Developer → Developer Tools  (or ⌥⌘I).
        Click the "Console" tab.
     5. Paste this ENTIRE file. Press Enter.
     6. Wait. It scrolls upward slowly, capturing messages as they load.
        You'll see progress like "1,234 messages so far..." in the console.
     7. When it's done, a file called
             whatsapp_chat_YYYY-MM-DD.txt
        will download automatically.
     8. Move that file to
             ~/Projects/hk-watch-prices/exports/europe/YYYY-MM-DD_export.txt
        (rename with today's date). Then run:
             python3 src/refresh.py --market europe

   FORMAT: the downloaded file mimics the format of WhatsApp's official
   "Export chat" text file, so the same parser used for HK/EU works
   unchanged.
   ========================================================================== */

(async () => {
  const messages = new Map();   // key → {date, time, sender, text}

  // Extract WhatsApp meta line "[HH:MM, DD/MM/YYYY] Sender: "
  const META_RE = /^\[(\d{1,2}:\d{2}(?::\d{2})?),\s*(\d{1,2}\/\d{1,2}\/\d{4})\]\s*(.+?):\s*$/;

  const capture = (root) => {
    let added = 0;
    // WhatsApp attaches the timestamp+sender to every message bubble via
    // data-pre-plain-text. Very stable attribute across WA-Web versions.
    root.querySelectorAll('[data-pre-plain-text]').forEach(el => {
      const meta = el.getAttribute('data-pre-plain-text');
      const m = meta.match(META_RE);
      if (!m) return;
      const [, time, date, sender] = m;
      const text = el.innerText.trim();
      // dedup key — same message can render multiple times as user scrolls
      const key = `${date}|${time}|${sender}|${text.slice(0, 200)}`;
      if (!messages.has(key)) {
        messages.set(key, { date, time, sender, text });
        added++;
      }
    });
    return added;
  };

  // Catch messages as they appear (WhatsApp virtualizes; DOM nodes are
  // created on scroll). Broad subtree observer is fine here.
  const observer = new MutationObserver(muts => {
    for (const mu of muts) {
      for (const n of mu.addedNodes) {
        if (n.nodeType === 1) capture(n);
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // Initial sweep of whatever's in the DOM already
  capture(document);
  console.log(`Starting extraction, ${messages.size} messages already visible…`);

  // Locate the scrollable messages pane. WhatsApp changes selectors over
  // time, so try a few candidates.
  const findPane = () =>
    document.querySelector('[data-testid="conversation-panel-messages"]') ||
    document.querySelector('#main div[tabindex="0"][data-tab]') ||
    document.querySelector('#main [role="application"]') ||
    document.querySelector('#main .copyable-area');
  const pane = findPane();
  if (!pane) {
    observer.disconnect();
    alert(
      "Couldn't find the WhatsApp chat pane. Make sure you have a chat open, " +
      "then try again."
    );
    return;
  }

  // Scroll toward the top; declare "done" when N consecutive scrolls yield
  // no new messages. Tunables:
  const IDLE_TICKS_UNTIL_DONE = 10;
  const SCROLL_WAIT_MS = 1300;    // give lazy-load time to run

  let idleTicks = 0;
  let lastCount = messages.size;
  while (idleTicks < IDLE_TICKS_UNTIL_DONE) {
    pane.scrollTop = 0;
    await new Promise(r => setTimeout(r, SCROLL_WAIT_MS));
    if (messages.size === lastCount) {
      idleTicks++;
    } else {
      idleTicks = 0;
      lastCount = messages.size;
      console.log(`… ${messages.size.toLocaleString()} messages so far`);
    }
  }
  observer.disconnect();
  console.log(`Done. Captured ${messages.size.toLocaleString()} messages.`);

  // Sort chronologically. Time may have seconds or not.
  const toDate = (d, t) => {
    const [dd, mm, yyyy] = d.split('/');
    const [hh, mi, se = '0'] = t.split(':');
    return new Date(+yyyy, +mm - 1, +dd, +hh, +mi, +se);
  };
  const rows = [...messages.values()].sort(
    (a, b) => toDate(a.date, a.time) - toDate(b.date, b.time)
  );

  // Format like WhatsApp's own export: [DD/MM/YYYY HH:MM:SS] Sender: text
  const lines = rows.map(r => {
    const time = r.time.split(':').length === 2 ? `${r.time}:00` : r.time;
    // Multi-line messages: keep newlines inside the message; the HK/EU
    // parser already handles multi-line bodies.
    return `[${r.date} ${time}] ${r.sender}: ${r.text}`;
  });
  const content = lines.join('\n');

  // Download as .txt
  const today = new Date().toISOString().slice(0, 10);
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `whatsapp_chat_${today}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  console.log(`Downloaded whatsapp_chat_${today}.txt — move it to exports/europe/`);
})();
