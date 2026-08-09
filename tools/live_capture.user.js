// ==UserScript==
// @name         WDG WhatsApp Live Capture
// @namespace    hk-watch-prices
// @version      1.0
// @description  Streams every WhatsApp Web message to the local receiver so the WDG price DB stays current in real-time. Runs automatically on every WA Web page load — no DevTools paste needed after installation.
// @author       hk-watch-prices
// @match        https://web.whatsapp.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM.xmlHttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==

/*
   HOW TO INSTALL
   --------------
   1. Install Tampermonkey from the Chrome Web Store (free, one-time):
        https://chromewebstore.google.com/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobfkfo
   2. Click the Tampermonkey icon in Chrome → "Create a new script…"
   3. Delete the template code, paste THIS entire file, and press ⌘S to save.
   4. Make sure the receiver server is running on your Mac:
        cd ~/Projects/hk-watch-prices
        python3 tools/live_receiver.py --market wdg
   5. Reload web.whatsapp.com. A green badge appears bottom-right of the WA page.
   That's the setup done. From now on the badge appears on every WA Web page
   and every message is captured automatically. Chrome tab must stay open.
*/

(function () {
  "use strict";

  const SERVER = "http://127.0.0.1:8765";
  const META_RE = /^\[(\d{1,2}:\d{2}(?::\d{2})?),\s*(\d{1,2}\/\d{1,2}\/\d{4})\]\s*(.+?):\s*$/;

  // Tampermonkey may expose either the old GM_ prefix or the new promise-based
  // GM.* API depending on version. Normalize to a single request() function.
  const gmRequest = (opts) => {
    return new Promise((resolve, reject) => {
      const fn = (typeof GM_xmlhttpRequest !== "undefined")
        ? GM_xmlhttpRequest
        : (GM && GM.xmlHttpRequest);
      if (!fn) return reject(new Error("Tampermonkey GM_xmlhttpRequest not available"));
      fn(Object.assign({}, opts, {
        onload: (r) => (r.status >= 200 && r.status < 300)
          ? resolve(r)
          : reject(new Error(`HTTP ${r.status}`)),
        onerror: () => reject(new Error("network")),
        ontimeout: () => reject(new Error("timeout")),
      }));
    });
  };

  // Guard against duplicate install (Tampermonkey usually only runs once per
  // page but reload cycles can double-invoke).
  if (window.__wdg_live_capture_active) return;
  window.__wdg_live_capture_active = true;

  const seen = new Set();
  const buffer = [];
  let flushTimer = null;
  let sent = 0;
  let failed = 0;
  let serverAlive = false;

  const badge = document.createElement("div");
  badge.style.cssText = `
    position:fixed; bottom:12px; right:12px; z-index:2147483647;
    background:#111; color:#fff; padding:8px 12px; border-radius:8px;
    font:12px/1.4 -apple-system,BlinkMacSystemFont,sans-serif;
    box-shadow:0 4px 12px rgba(0,0,0,.3); user-select:none;
    transition:background .3s;
  `;
  badge.textContent = "🟡 Starting…";
  const attachBadge = () => {
    if (document.body && !badge.isConnected) document.body.appendChild(badge);
  };
  attachBadge();

  const updateBadge = () => {
    attachBadge();
    const dot = serverAlive ? "🟢" : "🔴";
    const status = serverAlive ? "Live" : "Server offline";
    badge.textContent = `${dot} WDG · ${status} · ${sent.toLocaleString()} sent`;
    if (failed) badge.textContent += ` · ${failed} failed`;
    badge.style.background = serverAlive ? "#0a3" : "#a00";
  };

  const flush = async () => {
    flushTimer = null;
    if (!buffer.length) return;
    const batch = buffer.splice(0);
    try {
      await gmRequest({
        method: "POST",
        url: `${SERVER}/msg`,
        headers: { "Content-Type": "application/json" },
        data: JSON.stringify(batch),
        timeout: 8000,
      });
      sent += batch.length;
      serverAlive = true;
      updateBadge();
    } catch (e) {
      failed += batch.length;
      serverAlive = false;
      buffer.unshift(...batch);  // retry next flush
      updateBadge();
    }
  };

  const scheduleFlush = () => {
    if (flushTimer) return;
    flushTimer = setTimeout(flush, 800);
  };

  const capture = (root) => {
    root.querySelectorAll?.("[data-pre-plain-text]").forEach((el) => {
      const meta = el.getAttribute("data-pre-plain-text");
      const m = meta.match(META_RE);
      if (!m) return;
      const [, time, date, sender] = m;
      const text = (el.innerText || "").trim();
      const key = `${date}|${time}|${sender}|${text.slice(0, 200)}`;
      if (seen.has(key)) return;
      seen.add(key);
      buffer.push({ date, time, sender, text });
      scheduleFlush();
    });
  };

  // Wait until WA has rendered its main pane, then start observing.
  const bootstrap = () => {
    capture(document);
    const observer = new MutationObserver((muts) => {
      for (const mu of muts) {
        for (const n of mu.addedNodes) {
          if (n.nodeType === 1) capture(n);
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Retry queued items every 30s if server was momentarily down
    setInterval(() => { if (buffer.length) flush(); }, 30_000);
    // Health-check every 60s so badge reflects reality
    setInterval(async () => {
      try {
        await gmRequest({ method: "GET", url: `${SERVER}/status`, timeout: 5000 });
        serverAlive = true; updateBadge();
      } catch {
        serverAlive = false; updateBadge();
      }
    }, 60_000);
    // Initial health-check right away
    (async () => {
      try {
        await gmRequest({ method: "GET", url: `${SERVER}/status`, timeout: 3000 });
        serverAlive = true;
      } catch { serverAlive = false; }
      updateBadge();
    })();
  };

  // WA renders progressively — wait for body then start
  if (document.body) bootstrap();
  else window.addEventListener("DOMContentLoaded", bootstrap);
})();
