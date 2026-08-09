// ==UserScript==
// @name         US Moda Facebook Group Live Capture
// @namespace    hk-watch-prices
// @version      3.2
// @description  Intercepts Facebook's GraphQL responses to capture Watchtrading posts. Injects hook code into the page's real context (bypasses Tampermonkey sandbox) and forwards captured posts to the local receiver.
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
   v3.1 CHANGES vs v3.0
   =====================

   v3.0 failed because Tampermonkey isolates userscripts in a sandbox
   where `window.fetch` is a wrapper — patching it only affects the
   userscript's own fetch calls, not the page's. FB's own code uses
   page-window's real fetch, which our v3.0 monkey-patch never touched.
   Badge showed 0 intercepted requests forever.

   v3.1 injects the hook code as a <script> tag directly into the page.
   That runs in the real page context alongside FB's own code, so our
   patched fetch/XHR IS the one FB uses. Captured posts are handed
   back to the userscript via window.postMessage.
*/

(function () {
  "use strict";

  console.log("[US Moda] v3.2 (page-context inject + URL diagnostics) starting");
  const SERVER = "http://127.0.0.1:8766";

  // ---------- The injected hook code ----------
  //
  // This runs as a <script> tag in the PAGE's context, not Tampermonkey's
  // sandbox. It patches the REAL window.fetch and window.XMLHttpRequest,
  // walks GraphQL responses for post-shaped objects, and posts each
  // extracted {author, text, time, id} back to the userscript via
  // window.postMessage.
  const injectedCode = function () {
    console.log("[US Moda inject] hooking fetch + XHR in page context");

    const shouldIntercept = (url) => {
      if (!url || typeof url !== "string") return false;
      return (
        url.includes("/api/graphql/") ||
        url.includes("/graphql/") ||
        url.includes("bulk-route-definitions") ||
        url.includes("/comet/") ||
        url.includes("/ajax/route-definitions") ||
        url.includes("/ajax/pagelet") ||
        url.includes("/ajax/bootloader") ||
        url.includes("/api/graphqlbatch")
      );
    };

    // TEMP DIAGNOSTIC: log every fetch/XHR URL so we can see what FB
    // actually calls. Remove once we've confirmed the pattern is right.
    // Buffered so we don't spam the console — logs a batch every 3s.
    const urlLog = [];
    const noteUrl = (kind, url) => {
      if (!url) return;
      urlLog.push(`${kind} ${url.slice(0, 200)}`);
      if (urlLog.length === 1) {
        setTimeout(() => {
          console.log("[US Moda inject] URLs seen (last 3s):\n" + urlLog.join("\n"));
          urlLog.length = 0;
        }, 3000);
      }
    };

    const seenIds = new Set();
    let interceptedCount = 0;
    let extractedCount = 0;

    const send = (payload) => {
      window.postMessage({ __usmoda: true, ...payload }, "*");
    };

    const emit = (author, text, timeSec, id) => {
      if (!author || !text) return;
      text = String(text).trim();
      if (text.length < 20) return;
      author = String(author).trim().slice(0, 100);
      if (!author) return;

      const key = id || `${author}|${text.slice(0, 120)}`;
      if (seenIds.has(key)) return;
      seenIds.add(key);
      extractedCount++;
      send({ type: "post", author, text, timeSec, id });
      console.log("[US Moda inject] ✅", author, "→", text.slice(0, 60));
    };

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
          node?.post_id ||
          node?.id ||
          node?.story_bucket_id ||
          null;

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

    // Hook fetch
    const origFetch = window.fetch;
    window.fetch = function (input, init) {
      const url =
        typeof input === "string" ? input :
        (input && input.url) ? input.url : "";
      const p = origFetch.apply(this, arguments);
      noteUrl("FETCH", url);
      if (shouldIntercept(url)) {
        interceptedCount++;
        send({ type: "req", url: url.slice(0, 100), count: interceptedCount });
        p.then((resp) => {
          resp.clone().text().then(parseBody).catch(() => {});
        }).catch(() => {});
      }
      return p;
    };

    // Hook XHR
    const OrigXHR = window.XMLHttpRequest;
    function PatchedXHR() {
      const xhr = new OrigXHR();
      let intercept = false;
      const origOpen = xhr.open;
      xhr.open = function (method, url) {
        noteUrl("XHR", url);
        intercept = shouldIntercept(url);
        if (intercept) {
          interceptedCount++;
          send({ type: "req", url: url.slice(0, 100), count: interceptedCount });
        }
        return origOpen.apply(xhr, arguments);
      };
      xhr.addEventListener("load", () => {
        if (intercept) {
          try { parseBody(xhr.responseText); } catch (_) {}
        }
      });
      return xhr;
    }
    PatchedXHR.prototype = OrigXHR.prototype;
    Object.setPrototypeOf(PatchedXHR, OrigXHR);
    window.XMLHttpRequest = PatchedXHR;

    send({ type: "ready" });
    console.log("[US Moda inject] hooks installed. Scroll to load feed.");
  };

  // Inject the code as a page-context script
  const injectHook = () => {
    const s = document.createElement("script");
    s.textContent = "(" + injectedCode.toString() + ")();";
    (document.head || document.documentElement).appendChild(s);
    s.remove();
  };

  // Inject as early as possible — before FB's own scripts load
  if (document.documentElement) {
    injectHook();
  } else {
    new MutationObserver((_, obs) => {
      if (document.documentElement) {
        obs.disconnect();
        injectHook();
      }
    }).observe(document, { childList: true, subtree: true });
  }

  // ---------- Receive events from injected code ----------
  let interceptedRequests = 0;
  let extractedPosts = 0;
  let hookReady = false;
  const buffer = [];
  const seenKeys = new Set();
  let flushTimer = null;
  let sent = 0;
  let failed = 0;
  let serverAlive = false;

  window.addEventListener("message", (evt) => {
    const d = evt.data;
    if (!d || !d.__usmoda) return;
    if (d.type === "ready") {
      hookReady = true;
      updateBadge();
    } else if (d.type === "req") {
      interceptedRequests = d.count;
      updateBadge();
    } else if (d.type === "post") {
      const key = d.id || `${d.author}|${(d.text || "").slice(0, 120)}`;
      if (seenKeys.has(key)) return;
      seenKeys.add(key);
      extractedPosts++;
      const date = new Date(d.timeSec ? d.timeSec * 1000 : Date.now());
      const two = (n) => String(n).padStart(2, "0");
      buffer.push({
        date: `${two(date.getDate())}/${two(date.getMonth() + 1)}/${date.getFullYear()}`,
        time: `${two(date.getHours())}:${two(date.getMinutes())}`,
        sender: d.author,
        text: d.text,
      });
      scheduleFlush();
      updateBadge();
    }
  });

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
    if (document.body) document.body.appendChild(badge);
  };
  const updateBadge = () => {
    if (!badge) return;
    const dot = serverAlive ? "🟢" : "🔴";
    const hookDot = hookReady ? "🔧" : "⏳";
    badge.textContent =
      `${dot}${hookDot} v3.1 · ${sent} sent · ${extractedPosts} found · ${interceptedRequests} req`;
    if (failed) badge.textContent += ` · ${failed} failed`;
    badge.style.background = serverAlive
      ? (interceptedRequests > 0 ? "#0a3" : "#c60")
      : "#a00";
  };
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
      buffer.unshift(...batch);
    }
    updateBadge();
  };
  const scheduleFlush = () => {
    if (!flushTimer) flushTimer = setTimeout(flush, 1000);
  };

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
})();
