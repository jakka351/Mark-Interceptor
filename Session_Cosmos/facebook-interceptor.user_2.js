// ==UserScript==
// @name         Session Cosmos · Facebook Interceptor v2.0 (supercharged)
// @namespace    https://sessioncosmos.local/
// @version      2.0.0
// @description  Captures Facebook/Meta request telemetry + response latency + input signals. Survives relay restarts via localStorage buffer. Streams to the Session Cosmos relay.
// @author       you
// @match        https://*.facebook.com/*
// @match        https://*.messenger.com/*
// @match        https://*.instagram.com/*
// @match        https://*.threads.net/*
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════
  // CONFIG
  // ═══════════════════════════════════════════════════════════════
  const RELAY_URL        = 'http://127.0.0.1:8766/ingest';
  const HEALTH_URL       = 'http://127.0.0.1:8766/health';
  const DEDUP_WINDOW_MS  = 500;
  const BUFFER_KEY       = '__cosmos_buffer__';
  const BUFFER_MAX       = 500;          // max queued blobs when relay down
  const HEALTH_CHECK_MS  = 4000;
  const SCROLL_SAMPLE_MS = 1000;         // input sensor — scroll velocity sampler
  const VISIBILITY_EMIT  = true;         // emit visibility-change events
  const ENABLE_SW        = false;        // Service Worker variant — opt-in

  // Core blob fields (same as v1.1)
  const BLOB_FIELDS = new Set([
    '__a', '__aaid', '__ccg', '__comet_req', '__crn', '__hs', '__hsi',
    '__req', '__rev', '__s', '__spin_b', '__spin_r', '__spin_t', '__user',
    'dpr', 'fb_dtsg', 'jazoest', 'lsd', 'ph',
  ]);
  const CONTEXT_FIELDS = new Set([
    'fb_api_req_friendly_name', 'fb_api_caller_class',
    'doc_id', 'server_timestamps',
  ]);
  const MIN_FIELDS = ['__req', '__crn'];

  // ═══════════════════════════════════════════════════════════════
  // STATE
  // ═══════════════════════════════════════════════════════════════
  const TAB_ID = Math.random().toString(36).slice(2, 10);
  let captureCount = 0;
  let sendCount = 0;
  let errorCount = 0;
  let bufferedCount = 0;
  let lastFriendlyName = null;
  let lastRouteSent = null;
  let lastFriendlySent = null;
  let lastSendTime = 0;
  let relayHealthy = null; // null = unknown, true/false after first check
  let hud = null;

  // BroadcastChannel for cross-tab coordination
  let bc = null;
  if (typeof BroadcastChannel !== 'undefined') {
    try { bc = new BroadcastChannel('cosmos'); } catch (e) { bc = null; }
  }

  // ═══════════════════════════════════════════════════════════════
  // LOCAL STORAGE BUFFER — survives relay restarts
  // ═══════════════════════════════════════════════════════════════
  function loadBuffer() {
    try {
      const raw = localStorage.getItem(BUFFER_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
  }
  function saveBuffer(buf) {
    try { localStorage.setItem(BUFFER_KEY, JSON.stringify(buf.slice(-BUFFER_MAX))); }
    catch (e) { /* quota exceeded, drop */ }
  }
  function bufferPush(blob) {
    const buf = loadBuffer();
    buf.push(blob);
    saveBuffer(buf);
    bufferedCount = buf.length;
    updateStats();
  }
  function bufferDrain() {
    const buf = loadBuffer();
    if (!buf.length) return;
    // Send them in order — relay accepts out-of-sequence but logs look cleaner this way
    let idx = 0;
    function next() {
      if (idx >= buf.length) {
        saveBuffer([]);
        bufferedCount = 0;
        updateStats();
        return;
      }
      sendToRelayRaw(buf[idx], () => { idx++; next(); }, () => { /* failed — stop draining, keep remainder */
        saveBuffer(buf.slice(idx));
        bufferedCount = buf.length - idx;
        updateStats();
      });
    }
    next();
  }

  // ═══════════════════════════════════════════════════════════════
  // HUD (expanded v2.0)
  // ═══════════════════════════════════════════════════════════════
  function createHUD() {
    if (hud) return;
    hud = document.createElement('div');
    hud.id = '__cosmos_hud__';
    hud.innerHTML = `
      <div class="cosmos-title">SESSION·COSMOS</div>
      <div class="cosmos-sub">interceptor · v2.0 · tab ${TAB_ID}</div>
      <div class="cosmos-stats">
        <div class="cosmos-row"><span>captured</span><b id="cosmos-captured">0</b></div>
        <div class="cosmos-row"><span>streamed</span><b id="cosmos-streamed">0</b></div>
        <div class="cosmos-row"><span>buffered</span><b id="cosmos-buffered">0</b></div>
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
      <div class="cosmos-foot">drag · click to collapse · alt+click resets buffer</div>
    `;
    const style = document.createElement('style');
    style.textContent = `
      #__cosmos_hud__ {
        position: fixed !important; top: 16px; right: 16px;
        z-index: 2147483647 !important;
        background: rgba(5, 15, 22, 0.92) !important;
        border: 1px solid rgba(0, 255, 209, 0.4) !important;
        color: #e4f3fb !important;
        font-family: ui-monospace, 'JetBrains Mono', SFMono-Regular, Menlo, monospace !important;
        font-size: 10px !important;
        padding: 12px 14px !important; width: 240px !important;
        box-shadow: 0 0 30px rgba(0,255,209,0.15), inset 0 0 20px rgba(0,255,209,0.03) !important;
        backdrop-filter: blur(8px) !important;
        cursor: move !important; user-select: none !important;
        line-height: 1.4 !important;
      }
      #__cosmos_hud__.cosmos-hidden {
        width: 12px !important; height: 12px !important;
        padding: 0 !important; overflow: hidden !important;
        background: rgba(0,255,209,0.6) !important; border-radius: 50% !important;
        box-shadow: 0 0 14px rgba(0,255,209,0.8) !important;
        animation: cosmos-pulse 2s infinite !important;
      }
      #__cosmos_hud__ .cosmos-title { color: #00ffd1 !important; letter-spacing: 0.22em !important;
        font-weight: 700 !important; text-shadow: 0 0 10px rgba(0,255,209,0.6) !important; }
      #__cosmos_hud__ .cosmos-sub { color: #5a8ca0 !important; font-size: 8px !important;
        letter-spacing: 0.3em !important; margin: 2px 0 10px !important; }
      #__cosmos_hud__ .cosmos-stats { border-top: 1px solid rgba(0,255,209,0.15) !important; padding-top: 8px !important; }
      #__cosmos_hud__ .cosmos-row { display: flex !important; justify-content: space-between !important; padding: 2px 0 !important; }
      #__cosmos_hud__ .cosmos-row span { color: #5a8ca0 !important; letter-spacing: 0.15em !important; }
      #__cosmos_hud__ .cosmos-row b { color: #7ad7ff !important; font-weight: 500 !important; }
      #__cosmos_hud__ .cosmos-activity { border-top: 1px solid rgba(0,255,209,0.15) !important;
        margin-top: 8px !important; padding-top: 8px !important; }
      #__cosmos_hud__ .cosmos-activity-label { color: #5a8ca0 !important; font-size: 8px !important; letter-spacing: 0.25em !important; }
      #__cosmos_hud__ .cosmos-activity-value { color: #ff4fd8 !important; font-size: 10px !important;
        letter-spacing: 0.05em !important; margin-top: 3px !important;
        overflow: hidden !important; text-overflow: ellipsis !important; white-space: nowrap !important; }
      #__cosmos_hud__ .cosmos-status { display: flex !important; align-items: center !important; gap: 6px !important;
        margin-top: 10px !important; padding-top: 8px !important; border-top: 1px solid rgba(0,255,209,0.15) !important;
        font-size: 9px !important; letter-spacing: 0.2em !important; }
      #__cosmos_hud__ .cosmos-status.ok { color: #00ffd1 !important; }
      #__cosmos_hud__ .cosmos-status.warn { color: #fff275 !important; }
      #__cosmos_hud__ .cosmos-status.err { color: #ff4f4f !important; }
      #__cosmos_hud__ .cosmos-pulse { width: 6px !important; height: 6px !important; border-radius: 50% !important;
        background: currentColor !important; box-shadow: 0 0 6px currentColor !important;
        animation: cosmos-pulse 1.4s infinite !important; }
      #__cosmos_hud__ .cosmos-foot { color: #5a8ca0 !important; font-size: 8px !important;
        letter-spacing: 0.1em !important; margin-top: 8px !important; text-align: center !important; opacity: 0.6 !important; }
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

    // Click-to-collapse / alt+click to reset buffer
    let downX = 0, downY = 0, downT = 0;
    hud.addEventListener('mousedown', (e) => { downX = e.clientX; downY = e.clientY; downT = Date.now(); });
    hud.addEventListener('mouseup', (e) => {
      const dt = Date.now() - downT;
      const dist = Math.hypot(e.clientX - downX, e.clientY - downY);
      if (dt < 300 && dist < 5) {
        if (e.altKey) {
          saveBuffer([]); bufferedCount = 0; updateStats();
          setStatus('BUFFER CLEARED', 'warn');
        } else {
          hud.classList.toggle('cosmos-hidden');
        }
      }
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
    const b = hud.querySelector('#cosmos-buffered');
    const e = hud.querySelector('#cosmos-errors');
    const a = hud.querySelector('#cosmos-activity-value');
    if (c) c.textContent = captureCount;
    if (s) s.textContent = sendCount;
    if (b) b.textContent = bufferedCount;
    if (e) e.textContent = errorCount;
    if (a && lastFriendlyName) a.textContent = lastFriendlyName;
  }

  // ═══════════════════════════════════════════════════════════════
  // EXTRACTION (same as v1.1)
  // ═══════════════════════════════════════════════════════════════
  function extractBlob(bodyString, url) {
    if (!bodyString || typeof bodyString !== 'string') return null;
    if (!bodyString.includes('__req') && !bodyString.includes('__crn')) return null;
    let params;
    try { params = new URLSearchParams(bodyString); } catch (e) { return null; }
    const blob = {};
    for (const [key, value] of params.entries()) {
      if (BLOB_FIELDS.has(key) || CONTEXT_FIELDS.has(key)) {
        blob[key] = value.length > 300 ? value.slice(0, 300) : value;
      }
    }
    if (url) {
      try { blob['__url_path'] = new URL(url, location.href).pathname; }
      catch (e) { /* ignore */ }
    }
    for (const f of MIN_FIELDS) if (!blob[f]) return null;
    blob['__tab_id'] = TAB_ID;
    return blob;
  }

  function extractFromBody(body, url) {
    try {
      if (body == null) return null;
      if (typeof body === 'string') return extractBlob(body, url);
      if (body instanceof URLSearchParams) return extractBlob(body.toString(), url);
      if (body instanceof FormData) {
        const params = new URLSearchParams();
        for (const [k, v] of body.entries()) if (typeof v === 'string') params.append(k, v);
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

  // ═══════════════════════════════════════════════════════════════
  // RELAY COMMUNICATION
  // ═══════════════════════════════════════════════════════════════
  function sendToRelayRaw(payload, onSuccess, onError) {
    if (typeof GM_xmlhttpRequest === 'function') {
      GM_xmlhttpRequest({
        method: 'POST', url: RELAY_URL,
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify(payload), timeout: 3000,
        onload: onSuccess, onerror: onError, ontimeout: onError,
      });
    } else {
      fetch(RELAY_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload), mode: 'cors' })
        .then(onSuccess).catch(onError);
    }
  }

  function sendToRelay(blob) {
    const now = Date.now();
    const route = blob.__crn;
    const friendly = blob.fb_api_req_friendly_name;
    if (route === lastRouteSent && friendly === lastFriendlySent && (now - lastSendTime) < DEDUP_WINDOW_MS) return;
    lastRouteSent = route;
    lastFriendlySent = friendly;
    lastSendTime = now;
    if (friendly) lastFriendlyName = friendly.replace(/^Comet/, '').slice(0, 30);

    if (relayHealthy === false) {
      // Relay known-down — buffer immediately, skip attempt
      bufferPush(blob);
      setStatus('BUFFERING', 'warn');
      return;
    }
    sendToRelayRaw(blob,
      () => { sendCount++; updateStats(); setStatus('STREAMING', 'ok'); },
      () => { errorCount++; updateStats(); bufferPush(blob); setStatus('BUFFERING', 'warn'); relayHealthy = false; }
    );
  }

  function processBody(body, url, responseInfo) {
    const blob = extractFromBody(body, url);
    if (!blob) return;
    if (responseInfo) {
      if (responseInfo.latency_ms != null) blob['__latency_ms'] = responseInfo.latency_ms;
      if (responseInfo.response_size != null) blob['__response_size'] = responseInfo.response_size;
      if (responseInfo.status != null) blob['__http_status'] = responseInfo.status;
    }
    captureCount++;
    updateStats();
    sendToRelay(blob);
  }

  // ═══════════════════════════════════════════════════════════════
  // HOOKS — fetch + XHR + sendBeacon, with latency capture
  // ═══════════════════════════════════════════════════════════════
  const win = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;

  const origFetch = win.fetch;
  if (origFetch) {
    win.fetch = function (input, init) {
      const url = typeof input === 'string' ? input : (input && input.url);
      const t0 = performance.now();
      const body = init && init.body;
      const pending = origFetch.apply(this, arguments);
      if (body) {
        pending.then((resp) => {
          const latency = performance.now() - t0;
          // Response size guess from headers (best-effort — no body tee to avoid perf hit)
          let size = 0;
          try { size = parseInt(resp.headers.get('content-length') || '0', 10) || 0; } catch (e) {}
          processBody(body, url, { latency_ms: Math.round(latency), response_size: size, status: resp.status });
        }).catch(() => {
          processBody(body, url, { latency_ms: Math.round(performance.now() - t0), status: 0 });
        });
      }
      return pending;
    };
  }

  const OrigXHR = win.XMLHttpRequest;
  if (OrigXHR) {
    const origOpen = OrigXHR.prototype.open;
    const origSend = OrigXHR.prototype.send;
    OrigXHR.prototype.open = function (method, url) {
      try { this.__cosmos_url = url; this.__cosmos_start = performance.now(); } catch (e) {}
      return origOpen.apply(this, arguments);
    };
    OrigXHR.prototype.send = function (body) {
      const self = this;
      if (body) {
        // Attach loadend handler to capture latency when response arrives
        const capture = () => {
          try {
            const latency = performance.now() - (self.__cosmos_start || performance.now());
            let size = 0;
            try { size = (self.responseText || '').length; } catch (e) {}
            processBody(body, self.__cosmos_url, {
              latency_ms: Math.round(latency), response_size: size, status: self.status,
            });
          } catch (e) { /* ignore */ }
        };
        self.addEventListener('loadend', capture, { once: true });
      }
      return origSend.apply(this, arguments);
    };
  }

  const origBeacon = win.navigator && win.navigator.sendBeacon;
  if (origBeacon) {
    win.navigator.sendBeacon = function (url, body) {
      try { if (body) processBody(body, url, null); } catch (e) {}
      return origBeacon.apply(win.navigator, arguments);
    };
  }

  // ═══════════════════════════════════════════════════════════════
  // INPUT SENSORS — scroll velocity, tab visibility
  // Emitted as separate events with __kind='input' / 'visibility'.
  // Reflex treats __kind != 'request' as context events.
  // ═══════════════════════════════════════════════════════════════
  let scrollSamples = [];
  let lastScrollY = win.scrollY || 0;

  setInterval(() => {
    const y = win.scrollY || 0;
    const dy = Math.abs(y - lastScrollY);
    lastScrollY = y;
    if (dy > 10) {
      const ev = {
        '__kind': 'input',
        '__event': 'scroll',
        '__delta_px': dy,
        '__velocity_px_per_s': dy * (1000 / SCROLL_SAMPLE_MS),
        '__ts_wall': Math.floor(Date.now() / 1000),
        '__spin_t': Math.floor(Date.now() / 1000),
        '__crn': location.pathname,
        '__url_path': location.pathname,
        '__tab_id': TAB_ID,
      };
      sendToRelay(ev);
    }
  }, SCROLL_SAMPLE_MS);

  if (VISIBILITY_EMIT) {
    document.addEventListener('visibilitychange', () => {
      const ev = {
        '__kind': 'visibility',
        '__event': document.visibilityState,  // 'visible' | 'hidden'
        '__ts_wall': Math.floor(Date.now() / 1000),
        '__spin_t': Math.floor(Date.now() / 1000),
        '__crn': location.pathname,
        '__url_path': location.pathname,
        '__tab_id': TAB_ID,
      };
      sendToRelay(ev);
    });
  }

  // ═══════════════════════════════════════════════════════════════
  // HEALTH CHECK + BUFFER DRAIN
  // ═══════════════════════════════════════════════════════════════
  function healthCheck() {
    if (typeof GM_xmlhttpRequest === 'function') {
      GM_xmlhttpRequest({
        method: 'GET', url: HEALTH_URL, timeout: 1500,
        onload: () => { relayHealthy = true; bufferDrain(); },
        onerror: () => { relayHealthy = false; },
        ontimeout: () => { relayHealthy = false; },
      });
    } else {
      fetch(HEALTH_URL).then(() => { relayHealthy = true; bufferDrain(); })
        .catch(() => { relayHealthy = false; });
    }
  }
  setInterval(healthCheck, HEALTH_CHECK_MS);
  bufferedCount = loadBuffer().length;

  // ═══════════════════════════════════════════════════════════════
  // BOOT
  // ═══════════════════════════════════════════════════════════════
  if (document.documentElement) {
    createHUD();
  } else {
    const obs = new MutationObserver(() => {
      if (document.documentElement) { createHUD(); obs.disconnect(); }
    });
    obs.observe(document, { childList: true, subtree: true });
  }

  healthCheck();
  updateStats();

  console.log('%c[SESSION COSMOS v2.0] Interceptor armed — tab ' + TAB_ID + ' — relay: ' + RELAY_URL,
              'color: #00ffd1; font-family: monospace; font-weight: bold;');
})();
