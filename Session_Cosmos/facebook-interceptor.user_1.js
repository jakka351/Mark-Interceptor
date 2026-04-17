// ==UserScript==
// @name         Session Cosmos · Facebook Interceptor
// @namespace    https://sessioncosmos.local/
// @version      1.1.0
// @description  Captures Facebook/Meta request telemetry with activity context (friendly operation names) and streams to the Session Cosmos relay.
// @author       you
// @match        https://*.facebook.com/*
// @match        https://*.messenger.com/*
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
  'use strict';

  const RELAY_URL = 'http://127.0.0.1:8766/ingest';

  // Core blob fields
  const BLOB_FIELDS = new Set([
    '__a', '__aaid', '__ccg', '__comet_req', '__crn', '__hs', '__hsi',
    '__req', '__rev', '__s', '__spin_b', '__spin_r', '__spin_t', '__user',
    'dpr', 'fb_dtsg', 'jazoest', 'lsd', 'ph',
  ]);

  // Activity-context fields (v1.1 — what IS the user actually doing?)
  const CONTEXT_FIELDS = new Set([
    'fb_api_req_friendly_name',  // e.g. "CometUFIFeedbackLikeMutation" — the key field
    'fb_api_caller_class',        // context about caller
    'doc_id',                     // persisted GraphQL query ID
    'server_timestamps',          // if present
  ]);

  const MIN_FIELDS = ['__req', '__crn'];

  let captureCount = 0;
  let sendCount = 0;
  let errorCount = 0;
  let lastFriendlyName = null;
  let lastRouteSent = null;
  let lastFriendlySent = null;
  let lastSendTime = 0;

  let hud = null;

  function createHUD() {
    if (hud) return;
    hud = document.createElement('div');
    hud.id = '__cosmos_hud__';
    hud.innerHTML = `
      <div class="cosmos-title">SESSION·COSMOS</div>
      <div class="cosmos-sub">interceptor · v1.1</div>
      <div class="cosmos-stats">
        <div class="cosmos-row"><span>captured</span><b id="cosmos-captured">0</b></div>
        <div class="cosmos-row"><span>streamed</span><b id="cosmos-streamed">0</b></div>
        <div class="cosmos-row"><span>errors</span><b id="cosmos-errors">0</b></div>
      </div>
      <div class="cosmos-activity" id="cosmos-activity">
        <div class="cosmos-activity-label">last activity</div>
        <div class="cosmos-activity-value" id="cosmos-activity-value">—</div>
      </div>
      <div class="cosmos-status" id="cosmos-status">
        <span class="cosmos-pulse"></span>
        <span id="cosmos-status-text">INITIALIZING</span>
      </div>
      <div class="cosmos-foot">drag to move · click to hide</div>
    `;
    const style = document.createElement('style');
    style.textContent = `
      #__cosmos_hud__ {
        position: fixed !important;
        top: 16px; right: 16px;
        z-index: 2147483647 !important;
        background: rgba(5, 15, 22, 0.92) !important;
        border: 1px solid rgba(0, 255, 209, 0.4) !important;
        color: #e4f3fb !important;
        font-family: ui-monospace, 'JetBrains Mono', SFMono-Regular, Menlo, monospace !important;
        font-size: 10px !important;
        padding: 12px 14px !important;
        width: 220px !important;
        box-shadow: 0 0 30px rgba(0,255,209,0.15), inset 0 0 20px rgba(0,255,209,0.03) !important;
        backdrop-filter: blur(8px) !important;
        cursor: move !important;
        user-select: none !important;
        line-height: 1.4 !important;
      }
      #__cosmos_hud__.cosmos-hidden {
        width: 12px !important; height: 12px !important;
        padding: 0 !important; overflow: hidden !important;
        background: rgba(0,255,209,0.6) !important;
        border-radius: 50% !important;
        box-shadow: 0 0 14px rgba(0,255,209,0.8) !important;
        animation: cosmos-pulse 2s infinite !important;
      }
      #__cosmos_hud__ .cosmos-title {
        color: #00ffd1 !important;
        letter-spacing: 0.22em !important;
        font-weight: 700 !important;
        text-shadow: 0 0 10px rgba(0,255,209,0.6) !important;
      }
      #__cosmos_hud__ .cosmos-sub {
        color: #5a8ca0 !important; font-size: 8px !important;
        letter-spacing: 0.3em !important; margin: 2px 0 10px !important;
      }
      #__cosmos_hud__ .cosmos-stats {
        border-top: 1px solid rgba(0,255,209,0.15) !important;
        padding-top: 8px !important;
      }
      #__cosmos_hud__ .cosmos-row {
        display: flex !important; justify-content: space-between !important;
        padding: 2px 0 !important;
      }
      #__cosmos_hud__ .cosmos-row span { color: #5a8ca0 !important; letter-spacing: 0.15em !important; }
      #__cosmos_hud__ .cosmos-row b { color: #7ad7ff !important; font-weight: 500 !important; }
      #__cosmos_hud__ .cosmos-activity {
        border-top: 1px solid rgba(0,255,209,0.15) !important;
        margin-top: 8px !important; padding-top: 8px !important;
      }
      #__cosmos_hud__ .cosmos-activity-label {
        color: #5a8ca0 !important; font-size: 8px !important;
        letter-spacing: 0.25em !important;
      }
      #__cosmos_hud__ .cosmos-activity-value {
        color: #ff4fd8 !important; font-size: 10px !important;
        letter-spacing: 0.05em !important;
        margin-top: 3px !important;
        overflow: hidden !important; text-overflow: ellipsis !important;
        white-space: nowrap !important;
      }
      #__cosmos_hud__ .cosmos-status {
        display: flex !important; align-items: center !important; gap: 6px !important;
        margin-top: 10px !important; padding-top: 8px !important;
        border-top: 1px solid rgba(0,255,209,0.15) !important;
        font-size: 9px !important; letter-spacing: 0.2em !important;
      }
      #__cosmos_hud__ .cosmos-status.ok { color: #00ffd1 !important; }
      #__cosmos_hud__ .cosmos-status.warn { color: #fff275 !important; }
      #__cosmos_hud__ .cosmos-status.err { color: #ff4f4f !important; }
      #__cosmos_hud__ .cosmos-pulse {
        width: 6px !important; height: 6px !important; border-radius: 50% !important;
        background: currentColor !important;
        box-shadow: 0 0 6px currentColor !important;
        animation: cosmos-pulse 1.4s infinite !important;
      }
      #__cosmos_hud__ .cosmos-foot {
        color: #5a8ca0 !important; font-size: 8px !important;
        letter-spacing: 0.15em !important; margin-top: 8px !important;
        text-align: center !important; opacity: 0.6 !important;
      }
      @keyframes cosmos-pulse {
        0%, 100% { opacity: 0.4; transform: scale(1); }
        50% { opacity: 1; transform: scale(1.3); }
      }
    `;
    document.documentElement.appendChild(style);
    document.documentElement.appendChild(hud);

    // Drag
    let dragging = false, dx = 0, dy = 0;
    hud.addEventListener('mousedown', (e) => {
      if (hud.classList.contains('cosmos-hidden')) return;
      dragging = true;
      dx = e.clientX - hud.getBoundingClientRect().left;
      dy = e.clientY - hud.getBoundingClientRect().top;
      e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      hud.style.left = (e.clientX - dx) + 'px';
      hud.style.top = (e.clientY - dy) + 'px';
      hud.style.right = 'auto';
    });
    document.addEventListener('mouseup', () => { dragging = false; });

    // Click-to-collapse
    let downX = 0, downY = 0, downT = 0;
    hud.addEventListener('mousedown', (e) => { downX = e.clientX; downY = e.clientY; downT = Date.now(); });
    hud.addEventListener('mouseup', (e) => {
      const dt = Date.now() - downT;
      const dist = Math.hypot(e.clientX - downX, e.clientY - downY);
      if (dt < 300 && dist < 5) hud.classList.toggle('cosmos-hidden');
    });

    setStatus('ARMED', 'ok');
  }

  function setStatus(text, kind = 'ok') {
    if (!hud) return;
    const status = hud.querySelector('#cosmos-status');
    const label = hud.querySelector('#cosmos-status-text');
    if (status) status.className = 'cosmos-status ' + kind;
    if (label) label.textContent = text;
  }

  function updateStats() {
    if (!hud) return;
    const c = hud.querySelector('#cosmos-captured');
    const s = hud.querySelector('#cosmos-streamed');
    const e = hud.querySelector('#cosmos-errors');
    const a = hud.querySelector('#cosmos-activity-value');
    if (c) c.textContent = captureCount;
    if (s) s.textContent = sendCount;
    if (e) e.textContent = errorCount;
    if (a && lastFriendlyName) a.textContent = lastFriendlyName;
  }

  // ========== EXTRACTION ==========

  function extractBlob(bodyString, url) {
    if (!bodyString || typeof bodyString !== 'string') return null;
    if (!bodyString.includes('__req') && !bodyString.includes('__crn')) return null;

    let params;
    try {
      params = new URLSearchParams(bodyString);
    } catch (e) { return null; }

    const blob = {};
    for (const [key, value] of params.entries()) {
      if (BLOB_FIELDS.has(key) || CONTEXT_FIELDS.has(key)) {
        // Truncate long values (variables can be huge)
        blob[key] = value.length > 300 ? value.slice(0, 300) : value;
      }
    }

    // Attach URL pathname as hint (sanitized — no query string)
    if (url) {
      try {
        const u = new URL(url, 'https://facebook.com');
        blob['__url_path'] = u.pathname;
      } catch (e) { /* ignore */ }
    }

    for (const f of MIN_FIELDS) {
      if (!blob[f]) return null;
    }
    return blob;
  }

  function extractFromBody(body, url) {
    try {
      if (body == null) return null;
      if (typeof body === 'string') return extractBlob(body, url);
      if (body instanceof URLSearchParams) return extractBlob(body.toString(), url);
      if (body instanceof FormData) {
        const params = new URLSearchParams();
        for (const [k, v] of body.entries()) {
          if (typeof v === 'string') params.append(k, v);
        }
        return extractBlob(params.toString(), url);
      }
      if (body instanceof Blob) return null;
      if (body instanceof ArrayBuffer) {
        try { return extractBlob(new TextDecoder().decode(body), url); }
        catch (e) { return null; }
      }
    } catch (e) { /* ignore */ }
    return null;
  }

  function sendToRelay(blob) {
    const now = Date.now();
    const route = blob.__crn;
    const friendly = blob.fb_api_req_friendly_name;
    // Dedupe: same route AND same friendly_name within 500ms = skip
    // (but DIFFERENT friendly names on the same route should go through, those are different actions)
    if (route === lastRouteSent && friendly === lastFriendlySent && (now - lastSendTime) < 500) return;
    lastRouteSent = route;
    lastFriendlySent = friendly;
    lastSendTime = now;
    if (friendly) lastFriendlyName = friendly.replace(/^Comet/, '').slice(0, 30);

    if (typeof GM_xmlhttpRequest === 'function') {
      GM_xmlhttpRequest({
        method: 'POST',
        url: RELAY_URL,
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify(blob),
        timeout: 3000,
        onload: () => { sendCount++; updateStats(); setStatus('STREAMING', 'ok'); },
        onerror: () => { errorCount++; updateStats(); setStatus('RELAY UNREACHABLE', 'err'); },
        ontimeout: () => { errorCount++; updateStats(); setStatus('RELAY TIMEOUT', 'warn'); },
      });
    } else {
      fetch(RELAY_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(blob),
        mode: 'cors',
      }).then(() => {
        sendCount++; updateStats(); setStatus('STREAMING', 'ok');
      }).catch(() => {
        errorCount++; updateStats(); setStatus('RELAY UNREACHABLE', 'err');
      });
    }
  }

  function processBody(body, url) {
    const blob = extractFromBody(body, url);
    if (blob) {
      captureCount++;
      updateStats();
      sendToRelay(blob);
    }
  }

  // ========== HOOKS ==========

  const win = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;

  const origFetch = win.fetch;
  if (origFetch) {
    win.fetch = function (input, init) {
      try {
        const url = typeof input === 'string' ? input : (input && input.url);
        if (init && init.body) processBody(init.body, url);
      } catch (e) { /* swallow */ }
      return origFetch.apply(this, arguments);
    };
  }

  const OrigXHR = win.XMLHttpRequest;
  if (OrigXHR) {
    const origOpen = OrigXHR.prototype.open;
    const origSend = OrigXHR.prototype.send;
    OrigXHR.prototype.open = function (method, url) {
      try { this.__cosmos_url = url; } catch (e) {}
      return origOpen.apply(this, arguments);
    };
    OrigXHR.prototype.send = function (body) {
      try {
        if (body) processBody(body, this.__cosmos_url);
      } catch (e) {}
      return origSend.apply(this, arguments);
    };
  }

  const origBeacon = win.navigator && win.navigator.sendBeacon;
  if (origBeacon) {
    win.navigator.sendBeacon = function (url, body) {
      try {
        if (body) processBody(body, url);
      } catch (e) {}
      return origBeacon.apply(win.navigator, arguments);
    };
  }

  if (document.documentElement) {
    createHUD();
  } else {
    const obs = new MutationObserver(() => {
      if (document.documentElement) {
        createHUD();
        obs.disconnect();
      }
    });
    obs.observe(document, { childList: true, subtree: true });
  }

  setInterval(() => {
    if (captureCount > 0 && sendCount === 0 && errorCount > 0) {
      setStatus('RELAY OFFLINE', 'err');
    }
  }, 4000);

  console.log('%c[SESSION COSMOS v1.1] Interceptor armed — relay: ' + RELAY_URL,
              'color: #00ffd1; font-family: monospace; font-weight: bold;');
})();
