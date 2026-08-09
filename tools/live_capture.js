/* ==========================================================================
   WhatsApp Web LIVE capture  (Tier 2)
   --------------------------------------------------------------------------
   Paste this ONCE into DevTools Console for a WhatsApp Web tab that has
   the target chat (WDG) open. From that moment on, every new message that
   lands in the chat is POSTed to your local receiver, which appends it to
   the export file and auto-runs refresh.py every 15 min.

   Prereqs:
     1. `python3 tools/live_receiver.py` running in a Terminal
     2. Chrome tab open on https://web.whatsapp.com with the group selected

   HOW TO USE (one-time):
     1. In DevTools console, type:  allow pasting  ↵
     2. Paste this whole file, press Enter.
     3. A small badge appears in the bottom-right of the WA page showing
        capture status ("🟢 Live · 34 sent").
     4. Leave the tab open. That's it. You never have to touch it again.

   To stop: reload the tab (⌘R). To restart: paste this again.
   ========================================================================== */

(() => {
  const SERVER = "http://127.0.0.1:8765";
  const META_RE = /^\[(\d{1,2}:\d{2}(?::\d{2})?),\s*(\d{1,2}\/\d{1,2}\/\d{4})\]\s*(.+?):\s*$/;

  // Avoid multiple listeners if pasted twice
  if (window.__wa_live_capture_active) {
    console.log("Live capture already running — skipping duplicate install.");
    return;
  }
  window.__wa_live_capture_active = true;

  // Dedupe: don't POST the same message twice even if DOM re-renders
  const seen = new Set();

  // Buffer + flush pattern: batch outbound POSTs so we don't slam the server
  // on bulk backfills
  const buffer = [];
  let flushTimer = null;
  let sent = 0;
  let failed = 0;
  let serverAlive = true;

  const badge = (() => {
    const el = document.createElement("div");
    el.style.cssText = `
      position:fixed; bottom:12px; right:12px; z-index:2147483647;
      background:#111; color:#fff; padding:8px 12px; border-radius:8px;
      font:12px/1.4 -apple-system,BlinkMacSystemFont,sans-serif;
      box-shadow:0 4px 12px rgba(0,0,0,.3); user-select:none;
      transition:background .3s;
    `;
    el.textContent = "🟡 Starting capture…";
    document.body.appendChild(el);
    return el;
  })();
  const updateBadge = () => {
    const dot = serverAlive ? "🟢" : "🔴";
    const status = serverAlive ? "Live" : "Server offline";
    badge.textContent = `${dot} ${status} · ${sent.toLocaleString()} sent`;
    if (failed) badge.textContent += ` · ${failed} failed`;
    badge.style.background = serverAlive ? "#0a3" : "#a00";
  };

  const flush = async () => {
    flushTimer = null;
    if (!buffer.length) return;
    const batch = buffer.splice(0);
    try {
      const res = await fetch(`${SERVER}/msg`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(batch),
      });
      if (res.ok) {
        const j = await res.json();
        sent += batch.length;
        serverAlive = true;
        updateBadge();
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (e) {
      failed += batch.length;
      serverAlive = false;
      // Re-queue for retry on next flush
      buffer.unshift(...batch);
      updateBadge();
    }
  };

  const scheduleFlush = () => {
    if (flushTimer) return;
    flushTimer = setTimeout(flush, 800);   // batch messages within 800ms
  };

  const capture = (root) => {
    root.querySelectorAll?.("[data-pre-plain-text]").forEach(el => {
      const meta = el.getAttribute("data-pre-plain-text");
      const m = meta.match(META_RE);
      if (!m) return;
      const [, time, date, sender] = m;
      const text = el.innerText.trim();
      const key = `${date}|${time}|${sender}|${text.slice(0, 200)}`;
      if (seen.has(key)) return;
      seen.add(key);
      buffer.push({date, time, sender, text});
      scheduleFlush();
    });
  };

  // Initial sweep of anything already in the DOM
  capture(document);

  // Watch for future additions (new incoming messages OR user scrolling
  // through history — both get captured)
  const observer = new MutationObserver(muts => {
    for (const mu of muts) {
      for (const n of mu.addedNodes) {
        if (n.nodeType === 1) capture(n);
      }
    }
  });
  observer.observe(document.body, {childList: true, subtree: true});

  // Retry any queued items every 30s in case server was offline
  setInterval(() => {
    if (buffer.length) flush();
  }, 30_000);

  // Health-check the server every minute so the badge reflects reality
  setInterval(async () => {
    try {
      const r = await fetch(`${SERVER}/status`);
      if (r.ok) { serverAlive = true; updateBadge(); }
    } catch {
      serverAlive = false;
      updateBadge();
    }
  }, 60_000);

  console.log("✅ Live capture installed. Look for the badge in the bottom-right corner.");
  updateBadge();
})();
