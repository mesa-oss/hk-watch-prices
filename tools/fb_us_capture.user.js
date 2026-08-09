// ==UserScript==
// @name         US Moda Facebook Group Live Capture
// @namespace    hk-watch-prices
// @version      3.9
// @description  Intercepts Facebook's GraphQL responses via unsafeWindow (bypasses TM sandbox AND FB's CSP). No inline injection, no DOM parsing.
// @author       hk-watch-prices
// @match        https://www.facebook.com/groups/*
// @match        https://m.facebook.com/groups/*
// @grant        GM_xmlhttpRequest
// @grant        GM.xmlHttpRequest
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-start
// ==/UserScript==

/*
   v3.3 CHANGES vs v3.2
   =====================
   v3.2 injected a <script> tag into FB's document to escape Tampermonkey's
   sandbox. FB's CSP blocked it: "Executing inline script violates the
   following Content Security Policy directive". Dead end.

   v3.3 uses `unsafeWindow`, Tampermonkey's granted handle to the page's
   REAL window object. Assigning unsafeWindow.fetch = ... patches the
   fetch that FB's own code calls — no <script> tag, no CSP check.

   The @grant unsafeWindow line in the header is what makes this work.
*/

(function () {
  "use strict";

  console.log("[US Moda] v3.9 (deeper cycles for busy days) starting");
  const SERVER = "http://127.0.0.1:8766";

  // Force chronological sort so we see the newest listings first.
  // FB's default is algorithmic; that means we could miss brand-new posts.
  try {
    const u = new URL(location.href);
    if (
      u.pathname.startsWith("/groups/") &&
      !u.pathname.includes("/user/") &&
      u.searchParams.get("sorting_setting") !== "CHRONOLOGICAL"
    ) {
      u.searchParams.set("sorting_setting", "CHRONOLOGICAL");
      console.log("[US Moda] redirecting to chronological sort");
      location.replace(u.toString());
      return;
    }
  } catch (_) {}

  // Fall back to window if unsafeWindow isn't granted (shouldn't happen with our header)
  const W = (typeof unsafeWindow !== "undefined") ? unsafeWindow : window;
  console.log("[US Moda] using", W === window ? "window (sandbox)" : "unsafeWindow (page)");

  // ---------- State ----------
  const seenKeys = new Set();
  const buffer = [];
  let flushTimer = null;
  let sent = 0;
  let failed = 0;
  let serverAlive = false;
  let interceptedRequests = 0;
  let extractedPosts = 0;

  // ---------- Badge ----------
  let badge;
  const buildBadge = () => {
    if (badge) return;
    badge = document.createElement("div");
    badge.style.cssText = `
      position:fixed; bottom:12px; right:12px; z-index:2147483647;
      background:#111; color:#fff; padding:8px 12px; border-radius:8px;
      font:12px/1.4 -apple-system,BlinkMacSystemFont,sans-serif;
      box-shadow:0 4px 12px rgba(0,0,0,.3); user-select:none;
    `;
    if (document.body) document.body.appendChild(badge);
  };
  const updateBadge = () => {
    if (!badge) return;
    const dot = serverAlive ? "🟢" : "🔴";
    badge.textContent =
      `${dot} v3.3 · ${sent} sent · ${extractedPosts} found · ${interceptedRequests} req`;
    if (failed) badge.textContent += ` · ${failed} failed`;
    badge.style.background = serverAlive
      ? (interceptedRequests > 0 ? "#0a3" : "#c60")
      : "#a00";
  };
  const attachBadge = () => {
    if (document.body) { buildBadge(); updateBadge(); }
    else setTimeout(attachBadge, 100);
  };
  attachBadge();

  // ---------- Sender ----------
  const gmRequest = (opts) =>
    new Promise((resolve, reject) => {
      const fn =
        typeof GM_xmlhttpRequest !== "undefined"
          ? GM_xmlhttpRequest
          : (typeof GM !== "undefined" && GM.xmlHttpRequest);
      if (!fn) return reject(new Error("no GM_xmlhttpRequest"));
      fn(Object.assign({}, opts, {
        onload: (r) => (r.status >= 200 && r.status < 300)
          ? resolve(r) : reject(new Error(`HTTP ${r.status}`)),
        onerror: () => reject(new Error("network")),
        ontimeout: () => reject(new Error("timeout")),
      }));
    });

  const flush = async () => {
    flushTimer = null;
    if (!buffer.length) return;
    const batch = buffer.splice(0);
    try {
      await gmRequest({
        method: "POST", url: `${SERVER}/msg`,
        headers: { "Content-Type": "application/json" },
        data: JSON.stringify(batch), timeout: 8000,
      });
      sent += batch.length;
      serverAlive = true;
    } catch (e) {
      failed += batch.length;
      serverAlive = false;
      buffer.unshift(...batch);
    }
    updateBadge();
  };
  const scheduleFlush = () => {
    if (!flushTimer) flushTimer = setTimeout(flush, 1000);
  };

  // ---------- Post extraction ----------
  // FB dealers use Unicode Bold ("𝐑𝐋𝐗 𝟏𝟐𝟔𝟕𝟏𝟗") to stand out. Those are
  // Mathematical Alphanumeric Symbols — different codepoints from plain
  // ASCII, so the Python parser's regexes won't match them. NFKC
  // normalization folds those styled characters back to ASCII equivalents.
  const normalize = (s) => {
    if (!s) return s;
    try { return s.normalize("NFKC"); }
    catch (_) { return s; }
  };

  const emit = (author, text, timeSec, id) => {
    if (!author || !text) return;
    text = normalize(String(text)).trim();
    if (text.length < 20) return;
    author = normalize(String(author)).trim().slice(0, 100);
    if (!author) return;

    const key = id || `${author}|${text.slice(0, 120)}`;
    if (seenKeys.has(key)) return;
    seenKeys.add(key);
    extractedPosts++;

    const d = timeSec ? new Date(timeSec * 1000) : new Date();
    const two = (n) => String(n).padStart(2, "0");
    buffer.push({
      date: `${two(d.getDate())}/${two(d.getMonth() + 1)}/${d.getFullYear()}`,
      time: `${two(d.getHours())}:${two(d.getMinutes())}`,
      sender: author,
      text,
    });
    scheduleFlush();
    updateBadge();
    console.log("[US Moda] ✅", author, "→", text.slice(0, 60));
  };

  // Walk any JSON tree for post-shaped objects (see v3.1 comments for field list).
  const walkForPosts = (root) => {
    const stack = [root];
    let count = 0;
    while (stack.length && count < 10000) {
      count++;
      const node = stack.pop();
      if (!node || typeof node !== "object") continue;

      const author =
        node?.actors?.[0]?.name ||
        node?.owning_profile?.name ||
        node?.author?.name ||
        node?.from?.name ||
        node?.comet_sections?.context_layout?.story?.actors?.[0]?.name ||
        node?.comet_sections?.actor_photo?.story?.actors?.[0]?.name ||
        null;

      const text =
        node?.message?.text ||
        node?.message_preferred_body?.text ||
        node?.body?.text ||
        node?.comet_sections?.content?.story?.message?.text ||
        node?.comet_sections?.message?.story?.message?.text ||
        null;

      const time =
        node?.creation_time ||
        node?.created_time ||
        node?.comet_sections?.context_layout?.story?.creation_time ||
        null;

      const id =
        node?.post_id || node?.id || node?.story_bucket_id || null;

      if (author && text) emit(author, text, time, id);

      if (Array.isArray(node)) {
        for (const v of node) stack.push(v);
      } else {
        for (const v of Object.values(node)) {
          if (v && typeof v === "object") stack.push(v);
        }
      }
    }
  };

  const parseBody = (body) => {
    if (!body || typeof body !== "string") return;
    if (body.startsWith("for (;;);")) body = body.slice(9);
    if (body.startsWith(")]}'")) body = body.slice(4);
    for (const line of body.split("\n")) {
      const t = line.trim();
      if (!t.startsWith("{")) continue;
      try { walkForPosts(JSON.parse(t)); } catch (_) {}
    }
    try { walkForPosts(JSON.parse(body)); } catch (_) {}
  };

  const shouldIntercept = (url) => {
    if (!url || typeof url !== "string") return false;
    return (
      url.includes("/api/graphql/") ||
      url.includes("/graphql/") ||
      url.includes("bulk-route-definitions") ||
      url.includes("/comet/") ||
      url.includes("/ajax/route-definitions") ||
      url.includes("/ajax/pagelet") ||
      url.includes("/api/graphqlbatch")
    );
  };

  // URL noise diagnostics — kept as no-op in prod. Uncomment the body
  // and toggle DEBUG at top if you need to inspect which endpoints FB
  // is calling on a page you haven't seen before.
  const noteUrl = (_kind, _url) => {};

  // ---------- Hook fetch on the REAL page window ----------
  const origFetch = W.fetch;
  if (!origFetch) {
    console.warn("[US Moda] W.fetch is undefined — hook cannot install");
  } else {
    W.fetch = function (input, init) {
      const url =
        typeof input === "string" ? input :
        (input && input.url) ? input.url : "";
      const p = origFetch.apply(this, arguments);
      noteUrl("FETCH", url);
      if (shouldIntercept(url)) {
        interceptedRequests++;
        updateBadge();
        p.then((resp) => {
          resp.clone().text().then((body) => parseBody(body, url)).catch(() => {});
        }).catch(() => {});
      }
      return p;
    };
    console.log("[US Moda] fetch hook installed on", W === window ? "sandbox" : "page");
  }

  // ---------- Hook XMLHttpRequest ----------
  const OrigXHR = W.XMLHttpRequest;
  if (!OrigXHR) {
    console.warn("[US Moda] W.XMLHttpRequest is undefined — XHR hook skipped");
  } else {
    function PatchedXHR() {
      const xhr = new OrigXHR();
      let intercept = false;
      let capturedUrl = "";
      const origOpen = xhr.open;
      xhr.open = function (method, url) {
        capturedUrl = url;
        noteUrl("XHR", url);
        intercept = shouldIntercept(url);
        if (intercept) {
          interceptedRequests++;
          updateBadge();
        }
        return origOpen.apply(xhr, arguments);
      };
      xhr.addEventListener("load", () => {
        if (!intercept) return;
        // Try responseText first; if responseType is 'json' or 'arraybuffer',
        // responseText throws — fall back to xhr.response.
        let body = null;
        try { body = xhr.responseText; }
        catch (_) {
          try {
            const r = xhr.response;
            body = (typeof r === "string") ? r : JSON.stringify(r);
          } catch (_) {}
        }
        parseBody(body, capturedUrl);
      });
      return xhr;
    }
    PatchedXHR.prototype = OrigXHR.prototype;
    Object.setPrototypeOf(PatchedXHR, OrigXHR);
    W.XMLHttpRequest = PatchedXHR;
    console.log("[US Moda] XHR hook installed");
  }

  // ---------- Server health ----------
  const pingServer = async () => {
    try {
      await gmRequest({ method: "GET", url: `${SERVER}/status`, timeout: 3000 });
      serverAlive = true;
    } catch { serverAlive = false; }
    updateBadge();
  };
  setInterval(pingServer, 30_000);
  setTimeout(pingServer, 500);
  setInterval(() => { if (buffer.length) flush(); }, 30_000);
  setInterval(updateBadge, 5_000);

  // ---------- Auto-scroll strategy ----------
  //
  // Chronological FB feed: newest post is at the TOP. Old posts load as
  // you scroll down. So the wrong thing to do is scroll down forever —
  // you just wander further into old listings and never see anything new.
  //
  // Correct pattern for capturing new listings:
  //   1. On page load: burst-scroll DOWN a few times to load ~40 posts of
  //      historical baseline (each scroll = one /api/graphql/ request).
  //   2. Then wait, and reload to top every RELOAD_EVERY_MS. Each reload
  //      returns us to the top with any brand-new posts included.
  //   3. Between reloads, also click any "N new posts" button FB shows
  //      when new content appears above the fold — that jumps to the top
  //      without a full reload.
  // 12 scrolls × 5s = 60s of scrolling, then 30s idle before the 90s reload.
  // Each scroll loads ~8 posts, so we capture ~100 posts per cycle. Busy
  // dealer days rarely see more than a few posts per minute, so this gives
  // us ~10-20x headroom before anything slides past our capture window.
  const INITIAL_SCROLLS = 12;
  const INITIAL_SCROLL_GAP_MS = 5_000;
  const RELOAD_EVERY_MS = 90 * 1000;
  const startTime = Date.now();
  let doneInitialScrolls = 0;

  const scrollDown = () => {
    try { W.scrollBy(0, W.innerHeight * 0.9); } catch (_) {}
    try {
      const main = document.querySelector('div[role="main"]');
      if (main && main.scrollBy) main.scrollBy(0, W.innerHeight * 0.9);
    } catch (_) {}
  };

  const clickNewPostsBanner = () => {
    // FB shows a "N new posts" banner at the top when new content arrives.
    // Clicking it jumps to top and loads the new posts.
    for (const el of document.querySelectorAll(
      'div[role="button"], span[role="button"], button'
    )) {
      if (!el.offsetParent) continue;
      const t = (el.textContent || "").toLowerCase().trim();
      if (
        /^see \d+ new/.test(t) ||
        t === "new posts" ||
        t.includes("new post") ||
        t.includes("new activit")
      ) {
        try { el.click(); return true; } catch (_) {}
      }
    }
    return false;
  };

  const doReload = () => {
    const url = new URL(W.location.href);
    url.searchParams.set("sorting_setting", "CHRONOLOGICAL");
    console.log("[US Moda] auto-reload → top of feed");
    W.location.replace(url.toString());
  };

  // Phase 1: burst-scroll for baseline
  const initialScrollTick = () => {
    if (doneInitialScrolls >= INITIAL_SCROLLS) return;
    doneInitialScrolls++;
    console.log(`[US Moda] initial scroll ${doneInitialScrolls}/${INITIAL_SCROLLS}`);
    scrollDown();
    setTimeout(initialScrollTick, INITIAL_SCROLL_GAP_MS);
  };
  setTimeout(initialScrollTick, 5_000);

  // Phase 2: keep clicking "new posts" banner + eventually reload
  setInterval(() => {
    if (Date.now() - startTime >= RELOAD_EVERY_MS) {
      doReload();
      return;
    }
    // Between reloads, try to catch newly-arrived posts without reloading
    if (clickNewPostsBanner()) {
      console.log("[US Moda] clicked 'new posts' banner");
    }
  }, 15_000);

  console.log("[US Moda] setup done — auto-scroll running (top-of-feed strategy)");
})();
