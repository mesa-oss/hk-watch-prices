// ==UserScript==
// @name         US Moda Facebook Group Live Capture
// @namespace    hk-watch-prices
// @version      1.0
// @description  Streams new posts from the US Moda Facebook group to the local receiver. Auto-clicks 'new posts' buttons and reloads the page periodically to work around FB's non-push feed.
// @author       hk-watch-prices
// @match        https://www.facebook.com/groups/*
// @match        https://m.facebook.com/groups/*
// @grant        GM_xmlhttpRequest
// @grant        GM.xmlHttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==

/*
   HOW TO INSTALL
   --------------
   1. Install Tampermonkey (already done if the WDG script works).
   2. Tampermonkey icon → 'Create a new script…' → paste this whole file →
      save (⌘S).
   3. Make sure the US receiver is running on your Mac:
        cd ~/Projects/hk-watch-prices
        python3 tools/live_receiver.py --market usmoda --port 8766 --refresh-min 5
      (Different port from WDG — 8766 vs 8765.)
   4. Open the US Moda Facebook group in Chrome and leave the tab open.
      A green badge will appear in the bottom-right and every new post
      that comes in gets POSTed to your receiver.

   FACEBOOK QUIRKS THIS SCRIPT HANDLES
   -----------------------------------
   - FB doesn't auto-push new posts. The script watches for the
     "N new activity" / "new posts" button and auto-clicks it every ~30s.
   - The feed virtualizes: old posts drop out of DOM. Capture is
     immediate on first render — later scrolls only find newly-created
     posts.
   - Facebook DOM classnames randomize on every release, so we rely on
     stable role/aria attributes.
   - Auto-reloads the page every 10 minutes as a fallback in case FB's
     WebSocket lags or the new-posts button doesn't appear.
*/

(function () {
  "use strict";

  const SERVER = "http://127.0.0.1:8766";
  const RELOAD_EVERY_MS = 10 * 60 * 1000;

  const gmRequest = (opts) =>
    new Promise((resolve, reject) => {
      const fn =
        typeof GM_xmlhttpRequest !== "undefined"
          ? GM_xmlhttpRequest
          : GM && GM.xmlHttpRequest;
      if (!fn) return reject(new Error("no GM_xmlhttpRequest"));
      fn(
        Object.assign({}, opts, {
          onload: (r) =>
            r.status >= 200 && r.status < 300
              ? resolve(r)
              : reject(new Error(`HTTP ${r.status}`)),
          onerror: () => reject(new Error("network")),
          ontimeout: () => reject(new Error("timeout")),
        })
      );
    });

  if (window.__usmoda_capture_active) return;
  window.__usmoda_capture_active = true;

  const seen = new Set();
  const buffer = [];
  let flushTimer = null;
  let sent = 0;
  let failed = 0;
  let serverAlive = false;
  let lastReloadAt = Date.now();

  // ---- Badge ----
  const badge = document.createElement("div");
  badge.style.cssText = `
    position:fixed; bottom:12px; right:12px; z-index:2147483647;
    background:#111; color:#fff; padding:8px 12px; border-radius:8px;
    font:12px/1.4 -apple-system,BlinkMacSystemFont,sans-serif;
    box-shadow:0 4px 12px rgba(0,0,0,.3); user-select:none;
    transition:background .3s;
  `;
  badge.textContent = "🟡 US Moda starting…";
  const attach = () => {
    if (document.body && !badge.isConnected) document.body.appendChild(badge);
  };
  attach();
  const updateBadge = () => {
    attach();
    const dot = serverAlive ? "🟢" : "🔴";
    const status = serverAlive ? "Live" : "Server offline";
    const nextReloadMin = Math.max(
      0,
      Math.round((RELOAD_EVERY_MS - (Date.now() - lastReloadAt)) / 60000)
    );
    badge.textContent = `${dot} US Moda · ${status} · ${sent.toLocaleString()} sent · reload in ${nextReloadMin}m`;
    if (failed) badge.textContent += ` · ${failed} failed`;
    badge.style.background = serverAlive ? "#0a3" : "#a00";
  };

  // ---- POST batching ----
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
      buffer.unshift(...batch);
      updateBadge();
    }
  };
  const scheduleFlush = () => {
    if (!flushTimer) flushTimer = setTimeout(flush, 800);
  };

  // ---- FB post extraction ----
  // Post = <div role="article"> containing an author link and body text.
  // Timestamp is the abbr/a element whose href includes /posts/ or /permalink/.
  const now = () => new Date();
  const two = (n) => String(n).padStart(2, "0");

  const extractPostData = (article) => {
    // Try to find the timestamp link
    let ts = null;
    for (const a of article.querySelectorAll('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]')) {
      const abbr = a.querySelector("abbr");
      const title = abbr?.getAttribute("title") || a.getAttribute("aria-label");
      if (title && /\d/.test(title)) {
        ts = new Date(title);
        if (!isNaN(ts)) break;
      }
      if (a.textContent && a.textContent.match(/^(just now|\d+\s?(s|m|h|d|w|mo|y))/i)) {
        ts = now();  // relative — approximate with now
        break;
      }
    }
    if (!ts) ts = now();

    // Author: the first link/strong inside the article's header area
    let author = "Unknown";
    const authorEl =
      article.querySelector('h3 a, h2 a, strong a, a[role="link"] strong');
    if (authorEl && authorEl.textContent.trim()) {
      author = authorEl.textContent.trim().slice(0, 100);
    }

    // Body text — collapse the article's visible text but drop the
    // author/timestamp header. Cheap heuristic: use innerText, remove
    // duplicate lines, cap length.
    const text = (article.innerText || "")
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s && s.length > 1)
      .filter((s) => s !== author)
      .filter((s) => !/^\d+\s?(s|m|h|d|w|mo|y)$/i.test(s))
      .filter((s) => !/^(like|comment|share|see more|see less)$/i.test(s))
      .join(" ")
      .slice(0, 2000);

    if (!text) return null;

    const date = `${two(ts.getDate())}/${two(ts.getMonth() + 1)}/${ts.getFullYear()}`;
    const time = `${two(ts.getHours())}:${two(ts.getMinutes())}`;
    const key = `${date}|${time}|${author}|${text.slice(0, 200)}`;
    if (seen.has(key)) return null;
    seen.add(key);
    return { date, time, sender: author, text };
  };

  const capture = (root) => {
    root.querySelectorAll('div[role="article"]').forEach((art) => {
      const data = extractPostData(art);
      if (data) {
        buffer.push(data);
        scheduleFlush();
      }
    });
  };

  // ---- Auto-click "N new posts" buttons ----
  const clickNewPostsButtons = () => {
    for (const el of document.querySelectorAll('div[role="button"], span[role="button"], button')) {
      const t = (el.textContent || "").toLowerCase();
      if (
        (t.includes("new post") || t.includes("new activit") ||
         t.match(/^see \d+ new/) || t === "new posts") &&
        el.offsetParent !== null  // visible
      ) {
        el.click();
        return true;
      }
    }
    return false;
  };

  // ---- Bootstrap ----
  const bootstrap = () => {
    capture(document);
    // Watch for new posts appearing in DOM
    const observer = new MutationObserver((muts) => {
      for (const mu of muts)
        for (const n of mu.addedNodes)
          if (n.nodeType === 1) capture(n);
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Retry queued items every 30s
    setInterval(() => { if (buffer.length) flush(); }, 30_000);

    // Health-check server every 60s
    setInterval(async () => {
      try {
        await gmRequest({ method: "GET", url: `${SERVER}/status`, timeout: 5000 });
        serverAlive = true;
      } catch { serverAlive = false; }
      updateBadge();
    }, 60_000);

    // Auto-click "new posts" every 30s
    setInterval(() => { clickNewPostsButtons(); }, 30_000);

    // Periodic page reload — FB fallback when the feed goes stale.
    // Preserves CHRONOLOGICAL sort so we don't fall back to FB's
    // algorithmic 'Top Posts' order (which would hide fresh listings).
    setInterval(() => {
      if (Date.now() - lastReloadAt >= RELOAD_EVERY_MS) {
        if (buffer.length === 0) {
          const url = new URL(location.href);
          if (url.searchParams.get("sorting_setting") !== "CHRONOLOGICAL") {
            url.searchParams.set("sorting_setting", "CHRONOLOGICAL");
          }
          location.replace(url.toString());
        }
      }
      updateBadge();
    }, 30_000);

    // On first load, force chronological sort if the user landed without it
    if (new URL(location.href).searchParams.get("sorting_setting") !== "CHRONOLOGICAL") {
      const url = new URL(location.href);
      url.searchParams.set("sorting_setting", "CHRONOLOGICAL");
      // Only redirect if we're on the group root (avoid post-detail pages)
      if (/\/groups\/[^/]+\/?$/.test(url.pathname)) {
        console.log("US Moda capture: redirecting to CHRONOLOGICAL sort");
        location.replace(url.toString());
        return;
      }
    }

    // Initial server check
    (async () => {
      try {
        await gmRequest({ method: "GET", url: `${SERVER}/status`, timeout: 3000 });
        serverAlive = true;
      } catch { serverAlive = false; }
      updateBadge();
    })();
  };

  if (document.body) bootstrap();
  else window.addEventListener("DOMContentLoaded", bootstrap);
})();
