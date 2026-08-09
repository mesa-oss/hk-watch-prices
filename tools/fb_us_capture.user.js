// ==UserScript==
// @name         US Moda Facebook Group Live Capture
// @namespace    hk-watch-prices
// @version      3.0
// @description  Intercepts Facebook's GraphQL responses (the same JSON their own UI reads) to capture Watchtrading posts, then POSTs to the local receiver. No DOM parsing — hooks fetch/XHR at document-start.
// @author       hk-watch-prices
// @match        https://www.facebook.com/groups/*
// @match        https://m.facebook.com/groups/*
// @grant        GM_xmlhttpRequest
// @grant        GM.xmlHttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-start
// ==/UserScript==

/*
   HOW THIS WORKS (v3.0 — total rewrite)
   =====================================

   The DOM-based approach (v2.x) failed because FB obfuscates class names,
   removes role="article" markers, hides text behind "See more", and
   nests posts inside indistinguishable divs. Every version we patched,
   FB's chrome would leak in.

   v3.0 skips the DOM entirely. FB's own React UI reads posts by calling
   /api/graphql/ endpoints — those responses contain the full post as
   structured JSON: author name, message text, creation time. We
   monkey-patch window.fetch and XMLHttpRequest to intercept the raw
   responses BEFORE FB's UI code sees them, walk the JSON tree for
   post-shaped objects, and forward them to the local receiver.

   This is how commercial FB scrapers work. It's resistant to:
   - HTML class-name obfuscation (we never look at HTML)
   - "See more" truncation (JSON always has full text)
   - Invisible-char anti-bot (that's DOM-only obfuscation)
   - Layout changes (as long as the GraphQL shape stays roughly similar)

   Setup:
     1. Tampermonkey icon → Create new script → paste this file → save (⌘S).
     2. Terminal:
          cd ~/Projects/hk-watch-prices
          ./tools/live_start_usmoda.sh
     3. Reload the FB group tab (⌘⇧R). Badge appears bottom-right.
        Scroll to load posts; each new response is intercepted and sent.
*/

(function () {
  "use strict";

  console.log("[US Moda] v3.0 (GraphQL intercept) starting");
  const SERVER = "http://127.0.0.1:8766";

  // ---------- GraphQL interception ----------
  //
  // FB's UI fetches feed data via /api/graphql/ (also /ajax/bulk-route-definitions/
  // and similar). Responses are usually multi-line: each line is one JSON
  // "payload chunk" (FB uses HTTP streaming for progressive feed load).
  // Some responses start with `for (;;);` as a CSRF anti-hijack prefix
  // that must be stripped.

  const seen = new Set();       // dedup by post-id or (author|text-hash)
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
      transition:background .3s;
    `;
    badge.textContent = "🟡 US Moda v3 starting…";
    if (document.body) document.body.appendChild(badge);
  };
  const updateBadge = () => {
    if (!badge) return;
    const dot = serverAlive ? "🟢" : "🔴";
    badge.textContent =
      `${dot} US Moda v3 · ${sent} sent · ${extractedPosts} found · ${interceptedRequests} req`;
    if (failed) badge.textContent += ` · ${failed} failed`;
    badge.style.background = serverAlive ? "#0a3" : (interceptedRequests > 0 ? "#c60" : "#a00");
  };
  // Attach badge as soon as body exists
  const attachBadgeWhenReady = () => {
    if (document.body) { buildBadge(); updateBadge(); return; }
    setTimeout(attachBadgeWhenReady, 100);
  };
  attachBadgeWhenReady();

  // ---------- Sender ----------
  const gmRequest = (opts) =>
    new Promise((resolve, reject) => {
      const fn =
        typeof GM_xmlhttpRequest !== "undefined"
          ? GM_xmlhttpRequest
          : (typeof GM !== "undefined" && GM.xmlHttpRequest);
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
    } catch (e) {
      failed += batch.length;
      serverAlive = false;
      // Put back at front so we retry on next flush
      buffer.unshift(...batch);
    }
    updateBadge();
  };
  const scheduleFlush = () => {
    if (!flushTimer) flushTimer = setTimeout(flush, 1000);
  };

  // ---------- Post extraction ----------
  //
  // FB's GraphQL objects for feed stories vary but share consistent
  // fields. We walk the JSON tree and pick out anything that looks like
  // a story with an author name and message text.
  const emit = (author, text, tsSec, postId) => {
    if (!author || !text) return;
    text = String(text).trim();
    if (text.length < 20) return;                  // too short to be a listing
    author = String(author).trim().slice(0, 100);
    if (!author) return;

    const key = postId || `${author}|${text.slice(0, 120)}`;
    if (seen.has(key)) return;
    seen.add(key);
    extractedPosts++;

    const d = tsSec ? new Date(tsSec * 1000) : new Date();
    const two = (n) => String(n).padStart(2, "0");
    const date = `${two(d.getDate())}/${two(d.getMonth() + 1)}/${d.getFullYear()}`;
    const time = `${two(d.getHours())}:${two(d.getMinutes())}`;

    buffer.push({ date, time, sender: author, text });
    scheduleFlush();
    console.log("[US Moda] ✅ extracted:", author, "→", text.slice(0, 80));
  };

  // Recursively walk an object looking for post-shaped nodes.
  //
  // FB feed stories typically have SOME combination of these fields
  // (the shape varies by response type — comet_sections vs actors vs
  // owning_profile — so we accept any that carries a message + name):
  //
  //   creation_time (unix seconds)
  //   id | post_id | story_bucket_id (post identifier)
  //   message: { text: string }              — the post body
  //   message_preferred_body: { text: ... }  — sometimes here instead
  //   actors: [{ name: string }]             — the author
  //   comet_sections: { context_layout: { story: { actors: [{name}] } } }
  //   comet_sections: { content: { story: { message: { text } } } }
  //
  // We look at every object in the tree, extract whatever we can find,
  // and if we get both an author name AND message text, we emit.
  const walkForPosts = (obj) => {
    const stack = [obj];
    let depth = 0;
    while (stack.length && depth < 5000) {
      depth++;
      const node = stack.pop();
      if (!node || typeof node !== "object") continue;

      // Try to extract post fields from this node
      const author =
        node?.actors?.[0]?.name ||
        node?.owning_profile?.name ||
        node?.author?.name ||
        node?.from?.name ||
        node?.comet_sections?.context_layout?.story?.actors?.[0]?.name ||
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
        node?.post_id ||
        node?.id ||
        node?.story_bucket_id ||
        null;

      if (author && text) {
        emit(author, text, time, id);
      }

      // Recurse into children (arrays and object values)
      if (Array.isArray(node)) {
        for (const item of node) stack.push(item);
      } else {
        for (const val of Object.values(node)) {
          if (val && typeof val === "object") stack.push(val);
        }
      }
    }
  };

  // Parse a raw GraphQL response body. FB sends multi-line JSON,
  // sometimes with a `for (;;);` CSRF prefix.
  const parseResponseBody = (body) => {
    if (!body || typeof body !== "string") return;
    // Strip CSRF prefix if present
    if (body.startsWith("for (;;);")) body = body.slice(9);
    if (body.startsWith(")]}'")) body = body.slice(4);

    // Multi-line JSON: try each line
    for (const line of body.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("{")) continue;
      try {
        const obj = JSON.parse(trimmed);
        walkForPosts(obj);
      } catch (_) {
        // Not JSON — skip
      }
    }
    // Also try parsing whole body as one JSON (some responses are single-payload)
    try {
      const obj = JSON.parse(body);
      walkForPosts(obj);
    } catch (_) {}
  };

  const shouldIntercept = (url) => {
    if (!url || typeof url !== "string") return false;
    return (
      url.includes("/api/graphql/") ||
      url.includes("/graphql/") ||
      url.includes("bulk-route-definitions")
    );
  };

  // ---------- Monkey-patch fetch ----------
  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    const url =
      typeof input === "string" ? input :
      (input && input.url) ? input.url : "";
    const promise = origFetch.apply(this, arguments);
    if (shouldIntercept(url)) {
      interceptedRequests++;
      promise
        .then((response) => {
          response.clone().text()
            .then(parseResponseBody)
            .catch(() => {});
        })
        .catch(() => {});
      updateBadge();
    }
    return promise;
  };

  // ---------- Monkey-patch XMLHttpRequest ----------
  const OrigXHR = window.XMLHttpRequest;
  function PatchedXHR() {
    const xhr = new OrigXHR();
    let interceptThis = false;
    const origOpen = xhr.open;
    xhr.open = function (method, url) {
      interceptThis = shouldIntercept(url);
      return origOpen.apply(xhr, arguments);
    };
    xhr.addEventListener("load", () => {
      if (interceptThis) {
        interceptedRequests++;
        try {
          parseResponseBody(xhr.responseText);
        } catch (_) {}
        updateBadge();
      }
    });
    return xhr;
  }
  PatchedXHR.prototype = OrigXHR.prototype;
  window.XMLHttpRequest = PatchedXHR;

  // ---------- Server health check ----------
  const pingServer = async () => {
    try {
      await gmRequest({ method: "GET", url: `${SERVER}/status`, timeout: 3000 });
      serverAlive = true;
    } catch { serverAlive = false; }
    updateBadge();
  };
  setInterval(pingServer, 30_000);
  setTimeout(pingServer, 500);

  // Retry stuck buffer items every 30s
  setInterval(() => { if (buffer.length) flush(); }, 30_000);
  setInterval(updateBadge, 5_000);

  console.log("[US Moda] fetch + XHR hooks installed. Scroll the group to load posts.");
})();
