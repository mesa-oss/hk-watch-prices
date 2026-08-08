/* ==========================================================================
   WhatsApp Web message extractor  (v2 — more aggressive scroll triggers)
   --------------------------------------------------------------------------
   HOW TO USE:
     1. Open https://web.whatsapp.com in Chrome and log in.
     2. Click into the target group chat.
     3. Open DevTools (⌥⌘J → Console tab).
     4. Type:  allow pasting  ↵   (only needed the first time)
     5. Paste this entire file, press Enter.
     6. Wait. Progress lines appear like "… 1,234 messages so far".
     7. When it finishes, `whatsapp_chat_YYYY-MM-DD.txt` downloads.
     8. Move it to  exports/wdg/YYYY-MM-DD_export.txt  and run
             python3 src/refresh.py --market wdg
   ========================================================================== */

(async () => {
  const messages = new Map();
  const META_RE = /^\[(\d{1,2}:\d{2}(?::\d{2})?),\s*(\d{1,2}\/\d{1,2}\/\d{4})\]\s*(.+?):\s*$/;

  const capture = (root) => {
    let added = 0;
    root.querySelectorAll('[data-pre-plain-text]').forEach(el => {
      const meta = el.getAttribute('data-pre-plain-text');
      const m = meta.match(META_RE);
      if (!m) return;
      const [, time, date, sender] = m;
      const text = el.innerText.trim();
      const key = `${date}|${time}|${sender}|${text.slice(0, 200)}`;
      if (!messages.has(key)) {
        messages.set(key, { date, time, sender, text });
        added++;
      }
    });
    return added;
  };

  // Watch the whole document — messages come in via various mount points.
  const observer = new MutationObserver(muts => {
    for (const mu of muts) {
      for (const n of mu.addedNodes) {
        if (n.nodeType === 1) capture(n);
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  capture(document);
  console.log(`Starting extraction. ${messages.size} messages already visible.`);

  // Locate the scrollable pane by walking up from an existing message bubble
  // to the nearest ancestor with vertical scrolling. Much more reliable than
  // guessing CSS class names (WhatsApp scrambles those regularly).
  const findScrollableAncestor = (el) => {
    let node = el;
    while (node && node !== document.body) {
      const s = getComputedStyle(node);
      if ((s.overflowY === 'auto' || s.overflowY === 'scroll') &&
          node.scrollHeight > node.clientHeight + 10) {
        return node;
      }
      node = node.parentElement;
    }
    return null;
  };

  let pane = null;
  const sampleMsg = document.querySelector('[data-pre-plain-text]');
  if (sampleMsg) pane = findScrollableAncestor(sampleMsg);
  if (!pane) {
    // Fallback: scan candidates
    pane = document.querySelector('#main [role="application"]') ||
           document.querySelector('#main');
  }
  if (!pane) {
    observer.disconnect();
    alert("Couldn't find the chat pane. Open a chat and try again.");
    return;
  }
  console.log('Scroll target:', pane, `scrollHeight=${pane.scrollHeight}`);

  // Fire ALL of these on each iteration — WhatsApp's virtualized list responds
  // to different triggers depending on version. Belt and suspenders.
  const scrollUp = () => {
    // 1) Direct scrollTop reset
    pane.scrollTop = 0;
    // 2) Wheel event with big negative delta (simulates fast wheel-up)
    pane.dispatchEvent(new WheelEvent('wheel', {
      deltaY: -3000, deltaMode: 0,
      bubbles: true, cancelable: true, view: window,
    }));
    // 3) Focus + Home key (WhatsApp binds Home to jump-to-top)
    pane.focus?.();
    for (const target of [pane, document.activeElement, document.body]) {
      if (!target) continue;
      target.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Home', code: 'Home', keyCode: 36, which: 36,
        bubbles: true, cancelable: true,
      }));
      target.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'PageUp', code: 'PageUp', keyCode: 33, which: 33,
        bubbles: true, cancelable: true,
      }));
    }
  };

  // Bigger idle budget so slow servers don't cause premature stop.
  const IDLE_TICKS_UNTIL_DONE = 25;
  const SCROLL_WAIT_MS = 1500;
  let idleTicks = 0;
  let lastCount = messages.size;
  let iter = 0;

  while (idleTicks < IDLE_TICKS_UNTIL_DONE) {
    scrollUp();
    await new Promise(r => setTimeout(r, SCROLL_WAIT_MS));
    iter++;
    if (messages.size === lastCount) {
      idleTicks++;
      // Every 5 idle ticks, log so user knows we're still trying
      if (idleTicks % 5 === 0) {
        console.log(`  (waiting — ${idleTicks}/${IDLE_TICKS_UNTIL_DONE} idle, `
                    + `scrollHeight=${pane.scrollHeight}, scrollTop=${pane.scrollTop})`);
      }
    } else {
      idleTicks = 0;
      const delta = messages.size - lastCount;
      lastCount = messages.size;
      console.log(`… ${messages.size.toLocaleString()} messages (+${delta})`);
    }
  }

  observer.disconnect();
  console.log(`Done. Captured ${messages.size.toLocaleString()} messages after ${iter} scroll cycles.`);

  if (messages.size < 100) {
    console.warn(
      '⚠️  Very few messages captured. Common causes:\n' +
      '   • Group has "Disappearing messages" enabled → old ones gone.\n' +
      '   • WhatsApp Web hasn\'t cached older history from your phone.\n' +
      '     Open the chat on your PHONE, scroll back manually, then reload\n' +
      '     web.whatsapp.com and re-run this script.\n' +
      '   • This is a fresh group without much history.'
    );
  }

  // Sort chronologically, format as WhatsApp export, download.
  const toDate = (d, t) => {
    const [dd, mm, yyyy] = d.split('/');
    const [hh, mi, se = '0'] = t.split(':');
    return new Date(+yyyy, +mm - 1, +dd, +hh, +mi, +se);
  };
  const rows = [...messages.values()].sort(
    (a, b) => toDate(a.date, a.time) - toDate(b.date, b.time)
  );
  const lines = rows.map(r => {
    const time = r.time.split(':').length === 2 ? `${r.time}:00` : r.time;
    return `[${r.date} ${time}] ${r.sender}: ${r.text}`;
  });
  const content = lines.join('\n');
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
  console.log(`Downloaded whatsapp_chat_${today}.txt`);
})();
