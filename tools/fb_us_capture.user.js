// ==UserScript==
// @name         US Moda Facebook Group Live Capture
// @namespace    hk-watch-prices
// @version      2.5
// @description  Live-captures posts from a Facebook group and POSTs to the local receiver. v2 uses author-profile-link detection since FB stopped using role='article' for posts, and strips invisible-character anti-bot obfuscation.
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
   SETUP (once):
     1. Tampermonkey icon → Create new script → paste this file → save (⌘S).
     2. In another Terminal:
          cd ~/Projects/hk-watch-prices
          ./tools/live_start_usmoda.sh
     3. Open the FB group in Chrome — badge appears bottom-right, capture is
        automatic. Auto-reloads every 10 min to keep the feed fresh (FB
        doesn't push new posts like WhatsApp does).
*/

(function () {
  "use strict";

  console.log("[US Moda] userscript v2.5 starting");
  const SERVER = "http://127.0.0.1:8766";
  const RELOAD_EVERY_MS = 4 * 60 * 1000;  // reload every 4 min for freshness

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

  // ---- FB text cleaning ----
  // Facebook inserts U+034F (Combining Grapheme Joiner) and other invisible
  // chars into text as anti-bot obfuscation. We truncate at the first
  // invisible char (everything after is garbage) and strip any strays.
  // Using explicit \uXXXX escapes — inline invisible chars can be parsed
  // ambiguously in a regex character class and silently break the script.
  const INVISIBLE_RE = /[\u034F\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/;
  const INVISIBLE_STRIP = /[\u034F\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/g;
  const cleanText = (s) => {
    if (!s) return "";
    const cutIdx = s.search(INVISIBLE_RE);
    const truncated = cutIdx >= 0 ? s.slice(0, cutIdx) : s;
    return truncated.replace(INVISIBLE_STRIP, "").trim();
  };

  // ---- Post extraction via author-link anchoring ----
  //
  // Each post has an author profile link `/groups/{GID}/user/{UID}/`. We
  // walk UP from that anchor to find the post container (a div that also
  // holds the post's body text and timestamp link). Much more robust than
  // relying on role="article" or randomized class names.
  const AUTHOR_LINK_SEL = 'a[href*="/groups/"][href*="/user/"]';

  const findPostContainer = (authorLink) => {
    // Pass 1: look for FB's real post markers. These are the correct
    // boundary of a post; text-based heuristics can overshoot into the
    // page shell (left sidebar → "Facebook" repeats + huge innerText).
    let node = authorLink.parentElement;
    for (let i = 0; i < 12 && node && node !== document.body; i++) {
      const role = node.getAttribute?.("role");
      const pagelet = node.getAttribute?.("data-pagelet") || "";
      if (
        role === "article" ||
        pagelet.startsWith("FeedUnit") ||
        pagelet.startsWith("GroupFeed") ||
        pagelet.startsWith("Feed")
      ) {
        return node;
      }
      node = node.parentElement;
    }
    // Pass 2: text-heuristic fallback with a HARD upper bound on both
    // depth and text length — otherwise we grab the whole page including
    // sidebar chrome (which has plenty of text + timestamp links elsewhere).
    node = authorLink.parentElement;
    for (let i = 0; i < 8 && node && node !== document.body; i++) {
      const t = node.innerText || "";
      const hasTs = node.querySelector(
        'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"], a[aria-label*="ago"]'
      );
      if (t.length > 60 && t.length < 4000 && hasTs) return node;
      node = node.parentElement;
    }
    return null;
  };

  // Detect "this is page chrome, not a post" — the FB left sidebar has
  // 15+ repetitions of "Facebook" as accessibility labels for recent
  // groups. A real dealer post never has that pattern.
  const looksLikePageChrome = (text) => {
    const lines = text.split(/\n+/).slice(0, 30);
    let fbCount = 0;
    for (const l of lines) if (l.trim() === "Facebook") fbCount++;
    return fbCount >= 3;
  };

  const extractTimestamp = (container) => {
    // Try multiple approaches — FB uses different formats in different contexts
    for (const a of container.querySelectorAll(
      'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]'
    )) {
      const label = a.getAttribute("aria-label");
      if (label) {
        const d = new Date(label);
        if (!isNaN(d)) return d;
      }
      const abbr = a.querySelector("abbr");
      const title = abbr?.getAttribute("title");
      if (title) {
        const d = new Date(title);
        if (!isNaN(d)) return d;
      }
    }
    // Last resort: relative-time text like "5 min", "2 hr", "3d"
    const rel = container.querySelector('a[role="link"] span, span[dir="auto"]');
    // Just fall back to now — better than dropping the post
    return new Date();
  };

  const two = (n) => String(n).padStart(2, "0");
  const captured = new WeakSet();  // successfully-sent posts: never retry
  // Cache last-seen text length per author-link. If length grows (e.g. after
  // "See more" expansion), re-attempt the capture. Skips re-scanning stable
  // posts on every MutationObserver tick.
  const lastLen = new WeakMap();

  // Click "See more" buttons to expand truncated post text. FB truncates
  // long posts and hides the rest behind a button — the ref number and
  // price are often *inside* the hidden portion, so container.innerText
  // returns a useless preview and looksLikeListing() rejects it. We click
  // aggressively (every 3s) so posts self-expand as they scroll into view.
  const SEE_MORE_TEXTS = new Set([
    "see more", "…see more", "see more…", "... see more", "see more...",
    "voir plus", "…voir plus", "voir plus…",  // French
    "mehr anzeigen",                            // German
    "ver más",                                  // Spanish
    "altro",                                    // Italian
  ]);
  const expandAllSeeMore = () => {
    let n = 0;
    for (const el of document.querySelectorAll(
      'div[role="button"], span[role="button"]'
    )) {
      if (!el.offsetParent) continue;  // must be visible
      const t = (el.textContent || "").trim().toLowerCase();
      if (SEE_MORE_TEXTS.has(t)) {
        try { el.click(); n++; } catch (_) {}
      }
    }
    if (n) dbg(`expanded ${n} "See more"`);
  };

  // Skip these "authors" — either FB itself, generic system pages, or noise.
  const AUTHOR_BLOCKLIST = new Set([
    "facebook", "facebook groups", "meta", "instagram", "admin",
    "moderator", "group admin", "anonymous participant",
  ]);

  // A post is worth capturing only if it has REAL trading content.
  // Comments like "beautiful watch, glws" or "still available?" don't.
  // Requires ONE strong signal (price with $ or €) plus ANY hint of
  // watch content (ref-number pattern OR brand keyword).
  const looksLikeListing = (text) => {
    if (text.length < 60) return false;
    // Explicit dealer-price signal: dollar/euro amount, or "USD 5000",
    // or numeric+k/m (e.g. "17k"). Bare 4-6 digit numbers don't count
    // (too many false positives — year, quantity, etc.).
    const hasPrice =
      /\$\s?\d{2,}|\€\s?\d{2,}|\bUSD\s?\d|\bEUR\s?\d|\d+\s?[kKmM]\b/i.test(text);
    // Any of: 5-6 digit Rolex-shape ref, W-prefixed Cartier ref, 4-digit
    // Patek/AP ref with letter suffix.
    const hasRef =
      /\b(?:1[12]\d{4}|[23]\d{5}|5\d{3}[A-Z]|W[A-Z0-9]{5,7})\b/.test(text);
    // Watch keyword = a brand OR a well-known model (Daytona is a Rolex
    // model, Nautilus is Patek, Royal Oak is AP, etc.). Either signals
    // that the post is about a watch. Brand inference happens later in
    // the Python parser based on the reference number's shape.
    const hasWatchKeyword =
      /\b(?:Rolex|RLX|Patek|Audemars\s?Piguet|AP|Cartier|Hublot|Omega|Tudor|Panerai|Vacheron|Richard\s?Mille|RM|PP|VC|Bvlgari|Breguet|IWC|Lange|Daytona|Datejust|Submariner|GMT[- ]Master|Sky[- ]Dweller|Yacht[- ]Master|Explorer|Nautilus|Aquanaut|Calatrava|Royal\s?Oak|Offshore|Perpetual|Constellation|Speedmaster|Seamaster|Santos|Tank|Ballon|Panthere)\b/i.test(
        text
      );
    return hasPrice && (hasRef || hasWatchKeyword);
  };

  // Is this author link inside a comments section? Walk up looking for
  // comment-container markers.
  const isInsideComments = (el) => {
    let node = el;
    for (let i = 0; i < 15 && node && node !== document.body; i++) {
      const aria = (node.getAttribute("aria-label") || "").toLowerCase();
      if (aria.includes("comment")) return true;
      if (node.tagName === "UL") return true;   // FB renders comments as list items
      node = node.parentElement;
    }
    return false;
  };

  // Toggle DEBUG=true to log every decision to console. Helps see WHY
  // real posts are being rejected. Turn off once filter is tuned.
  const DEBUG = true;
  const dbg = (...args) => { if (DEBUG) console.log("[US Moda]", ...args); };

  const captureFrom = (root) => {
    const authors = (root || document).querySelectorAll(AUTHOR_LINK_SEL);
    authors.forEach((authorLink) => {
      if (captured.has(authorLink)) return;

      const author = cleanText(authorLink.textContent).slice(0, 100);
      if (!author) return;
      if (AUTHOR_BLOCKLIST.has(author.toLowerCase())) {
        captured.add(authorLink);  // permanent: name never changes
        return;
      }

      if (isInsideComments(authorLink)) {
        captured.add(authorLink);  // permanent: structural
        return;
      }

      const container = findPostContainer(authorLink);
      if (!container) {
        // Don't add to captured — container may appear as page loads more
        return;
      }

      const rawText = container.innerText || "";
      // Sidebar chrome sanity check: if we grabbed page shell, drop it
      // permanently for this authorLink so we don't spam retries.
      if (looksLikePageChrome(rawText)) {
        dbg("skip page-chrome (wrong container):", author);
        captured.add(authorLink);
        return;
      }

      // Skip re-scanning identical content. Recheck when text length grows
      // (e.g. after "See more" expands the post).
      const len = rawText.length;
      if (lastLen.get(authorLink) === len) return;
      lastLen.set(authorLink, len);

      const text = cleanText(rawText).slice(0, 3000);
      if (!looksLikeListing(text)) {
        dbg("skip not-a-listing:", author, "len=" + len,
            "clean-len=" + text.length,
            "text:", text.slice(0, 200));
        // Don't add to captured — text may expand and pass later
        return;
      }

      const ts = extractTimestamp(container);
      const date = `${two(ts.getDate())}/${two(ts.getMonth() + 1)}/${ts.getFullYear()}`;
      const time = `${two(ts.getHours())}:${two(ts.getMinutes())}`;

      const key = `${date}|${time}|${author}|${text.slice(0, 200)}`;
      if (seen.has(key)) {
        captured.add(authorLink);  // done — no need to rescan
        return;
      }
      seen.add(key);
      captured.add(authorLink);
      dbg("✅ CAPTURED:", author, "→", text.slice(0, 80));
      buffer.push({ date, time, sender: author, text });
      scheduleFlush();
    });
  };

  // ---- Auto-click "N new posts" buttons ----
  const clickNewPostsButtons = () => {
    for (const el of document.querySelectorAll(
      'div[role="button"], span[role="button"], button'
    )) {
      const t = (el.textContent || "").toLowerCase();
      if (
        (t.includes("new post") ||
          t.includes("new activit") ||
          t.match(/^see \d+ new/) ||
          t === "new posts") &&
        el.offsetParent !== null
      ) {
        el.click();
        return true;
      }
    }
    return false;
  };

  // ---- Bootstrap ----
  const bootstrap = () => {
    // Force CHRONOLOGICAL sort on initial load so FB doesn't show algorithmic feed
    const url0 = new URL(location.href);
    if (
      url0.searchParams.get("sorting_setting") !== "CHRONOLOGICAL" &&
      /\/groups\/[^/]+\/?$/.test(url0.pathname)
    ) {
      url0.searchParams.set("sorting_setting", "CHRONOLOGICAL");
      console.log("US Moda: redirecting to CHRONOLOGICAL sort");
      location.replace(url0.toString());
      return;
    }

    captureFrom(null);

    const observer = new MutationObserver((muts) => {
      for (const mu of muts) {
        for (const n of mu.addedNodes) {
          if (n.nodeType === 1) captureFrom(n);
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Retry stuck items every 30s
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

    // Auto-expand truncated posts every 3s — the ref/price are almost
    // always inside the "See more" portion of long dealer posts.
    setInterval(expandAllSeeMore, 3_000);
    // Also do a first-pass expansion right at bootstrap
    setTimeout(expandAllSeeMore, 1_500);

    // Periodic full-page reload as fallback for stale feed
    setInterval(() => {
      if (Date.now() - lastReloadAt >= RELOAD_EVERY_MS && buffer.length === 0) {
        const url = new URL(location.href);
        url.searchParams.set("sorting_setting", "CHRONOLOGICAL");
        location.replace(url.toString());
      }
      updateBadge();
    }, 30_000);

    // Initial server ping
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
