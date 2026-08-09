/* ==========================================================================
   WhatsApp Web message extractor  (v3 — incremental scroll)
   --------------------------------------------------------------------------
   Fix vs v2: v2 scrolled to top on every iteration, which caused WhatsApp
   to fast-forward past middle date ranges. Result: only bookend dates
   were captured (e.g. Jul 13-14 + Aug 8-9, missing the 3 weeks between).

   v3 scrolls UPWARD in small steps and captures messages explicitly at
   each step. Every batch passes through the viewport and gets picked up.

   HOW TO USE:
     1. Open https://web.whatsapp.com in Chrome and log in.
     2. Click into the target group chat.
     3. Open DevTools (⌥⌘J → Console tab).
     4. Type:  allow pasting  ↵   (only needed the first time)
     5. Paste this entire file, press Enter.
     6. Watch progress: "… 1,234 msgs [DD/MM/YYYY]" as it walks upward.
     7. When it finishes, `whatsapp_chat_YYYY-MM-DD.txt` downloads.
     8. Move it to  exports/wdg/YYYY-MM-DD_export.txt  and run
             python3 src/refresh.py --market wdg
   ========================================================================== */

(async () => {
  const messages = new Map();
  const META_RE = /^\[(\d{1,2}:\d{2}(?::\d{2})?),\s*(\d{1,2}\/\d{1,2}\/\d{4})\]\s*(.+?):\s*$/;

  const capture = () => {
    let added = 0;
    document.querySelectorAll('[data-pre-plain-text]').forEach(el => {
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

  // Locate the scrollable messages pane.
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

  const sampleMsg = document.querySelector('[data-pre-plain-text]');
  const pane = sampleMsg ? findScrollableAncestor(sampleMsg) : null;
  if (!pane) {
    alert("Couldn't find the WhatsApp chat pane. Open a chat and try again.");
    return;
  }

  console.log(`Scroll pane found. Starting incremental extraction…`);
  console.log(`Initial DOM messages: ${document.querySelectorAll('[data-pre-plain-text]').length}`);

  // Initial capture of whatever's currently in view
  capture();
  console.log(`Captured initial batch: ${messages.size}`);

  // Show progress with the OLDEST date we've reached so user knows where we are
  const oldestDate = () => {
    let oldest = null;
    for (const v of messages.values()) {
      const [dd, mm, yyyy] = v.date.split('/');
      const d = new Date(+yyyy, +mm - 1, +dd);
      if (!oldest || d < oldest) oldest = d;
    }
    return oldest ? oldest.toISOString().slice(0, 10) : '?';
  };

  // Incremental scroll parameters
  const SCROLL_STEP_PX = 800;      // ~1 screenful of messages per step
  const STEP_WAIT_MS = 1200;       // let batch settle after each step
  const MAX_STALE_STEPS = 20;      // stop when scrollHeight stops growing

  let staleSteps = 0;
  let lastScrollHeight = pane.scrollHeight;
  let iter = 0;

  while (staleSteps < MAX_STALE_STEPS) {
    iter++;

    // Scroll UP by SCROLL_STEP_PX. If we're already near the top, scrollTop
    // clamps to 0 and WhatsApp will request the next older batch.
    const before = pane.scrollTop;
    pane.scrollTop = Math.max(0, before - SCROLL_STEP_PX);

    // Also poke keyboard events some WhatsApp Web builds bind (PageUp/Home).
    pane.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'PageUp', code: 'PageUp', keyCode: 33, bubbles: true,
    }));

    await new Promise(r => setTimeout(r, STEP_WAIT_MS));

    // Capture after every step — don't rely on MutationObserver alone.
    const added = capture();

    // Progress heuristic: growing scrollHeight = older batch loaded.
    const grew = pane.scrollHeight > lastScrollHeight + 50;
    if (added > 0 || grew) {
      staleSteps = 0;
      lastScrollHeight = pane.scrollHeight;
      if (iter % 3 === 0 || added > 5) {
        console.log(`  step ${iter}: ${messages.size.toLocaleString()} msgs, oldest=${oldestDate()}, scrollH=${pane.scrollHeight.toLocaleString()}`);
      }
    } else {
      staleSteps++;
      // When we've clamped at scrollTop=0 for a while and nothing new is
      // loading, try more aggressive triggers before giving up.
      if (pane.scrollTop === 0 && staleSteps % 5 === 0) {
        pane.dispatchEvent(new KeyboardEvent('keydown', {
          key: 'Home', code: 'Home', keyCode: 36, bubbles: true,
        }));
        pane.dispatchEvent(new WheelEvent('wheel', {
          deltaY: -3000, deltaMode: 0, bubbles: true, cancelable: true,
        }));
        console.log(`  step ${iter}: at top, waiting for lazy-load (${staleSteps}/${MAX_STALE_STEPS} idle)`);
      }
    }
  }

  console.log(`\nDone. ${messages.size.toLocaleString()} messages captured in ${iter} steps.`);

  if (messages.size < 200) {
    console.warn(
      "\n⚠️  Fewer than 200 messages captured. Your phone likely hasn't\n" +
      "   cached deep history. Fix by:\n" +
      "   1. Open WhatsApp on your PHONE\n" +
      "   2. Open the group and scroll UP slowly (pause 5s every few scrolls)\n" +
      "   3. Reload web.whatsapp.com (⌘R) and re-run this script"
    );
  }

  // Sort chronologically, format as WhatsApp export, download
  const toDate = (d, t) => {
    const [dd, mm, yyyy] = d.split('/');
    const [hh, mi, se = '0'] = t.split(':');
    return new Date(+yyyy, +mm - 1, +dd, +hh, +mi, +se);
  };
  const rows = [...messages.values()].sort(
    (a, b) => toDate(a.date, a.time) - toDate(b.date, b.time)
  );

  // Report date coverage so user can see gaps
  const byDate = {};
  rows.forEach(r => { byDate[r.date] = (byDate[r.date] || 0) + 1; });
  console.log('\n📅 Messages per date:');
  Object.entries(byDate).sort((a, b) => {
    const pa = a[0].split('/').reverse().join('');
    const pb = b[0].split('/').reverse().join('');
    return pa.localeCompare(pb);
  }).forEach(([d, n]) => console.log(`  ${d}: ${n}`));

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
  console.log(`\nDownloaded whatsapp_chat_${today}.txt`);
})();
