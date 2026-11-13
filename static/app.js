"use strict";

(() => {
  const TOKEN = window.__DECK_TOKEN__ || "";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));

  const ORDER = { needs_input: 0, working: 1, done: 2, idle: 3, exited: 4, shell: 5 };
  const LABEL = {
    needs_input: "Needs you",
    working: "Working",
    done: "Ready / Done",
    idle: "Quiet",
    exited: "Exited",
    shell: "Shell",
  };
  const ALERT_ON = new Set(["needs_input", "done", "exited"]);

  const ICONS = {
    soundOn: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.8 5.8a9 9 0 0 1 0 12.4"/></svg>`,
    soundOff: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="22" y1="9" x2="16" y2="15"/><line x1="16" y1="9" x2="22" y2="15"/></svg>`,
    themeSystem: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="13" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`,
    themeLight: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5"/><line x1="12" y1="2.5" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="21.5"/><line x1="4.2" y1="4.2" x2="6" y2="6"/><line x1="18" y1="18" x2="19.8" y2="19.8"/><line x1="2.5" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="21.5" y2="12"/><line x1="4.2" y1="19.8" x2="6" y2="18"/><line x1="18" y1="6" x2="19.8" y2="4.2"/></svg>`,
    themeDark: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11z"/></svg>`,
    gitBranch: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>`,
    folder: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`,
    extOpen: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>`,
    reply: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/></svg>`,
    terminal: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`,
  };

  let S = { seq: 0, sessions: [], events: [], recent_cwds: [], local_ports: [], now: Date.now() / 1000, home: "" };
  let sel = null;
  let loaded = false;
  let stick = true;
  let viewMode = pref("viewMode", "focus"); // "focus" | "grid"
  let rightTab = pref("rightTab", "browser"); // "browser" | "terminal" | "split"
  if (!["browser", "terminal", "split"].includes(rightTab)) rightTab = "browser";
  let mobilePreview = pref("mobilePreview", false);
  let agentFilter = pref("agentFilter", "both"); // "both" | "agy" | "claude"
  if (!["both", "agy", "claude"].includes(agentFilter)) agentFilter = "both";
  let statusFilter = "all";
  let searchFilter = "";
  let termQuery = "";
  let activePreset = "agy";

  // Output & browser frame caches keyed by session id
  const paneOutputs = {}; // pane -> { hash, ansi, plain }
  const browserFramePool = new Map(); // sid -> { el, url, touched }
  const startingServers = new Set(); // sid currently booting dev server
  const openReplyCards = new Set(); // sid with inline sidebar reply box open
  const cardDrafts = {}; // sid -> unsent inline reply text
  let lastPortSelectSig = "";
  const prevStatus = {};
  const flashUntil = {};
  const history = [];
  let hIdx = -1;

  function pref(k, d) {
    try {
      const v = localStorage.getItem("deck." + k);
      return v === null ? d : JSON.parse(v);
    } catch {
      return d;
    }
  }
  function setPref(k, v) {
    try {
      localStorage.setItem("deck." + k, JSON.stringify(v));
    } catch {}
  }

  let sound = pref("sound", true);
  let theme = pref("theme", "system"); // "system" | "light" | "dark"
  let useAnsi = pref("ansi", true);
  let wrapLines = pref("wrap", true);

  const DEFAULT_SIDEBAR_W = 440;
  const MIN_SIDEBAR_W = 280;
  const MAX_SIDEBAR_W = 880;
  let sidebarWidth = Number(pref("sidebarWidth", DEFAULT_SIDEBAR_W)) || DEFAULT_SIDEBAR_W;

  function clampSidebarWidth(w) {
    const viewportCap = Math.max(MIN_SIDEBAR_W, Math.floor(window.innerWidth * 0.68));
    return Math.round(Math.min(Math.min(MAX_SIDEBAR_W, viewportCap), Math.max(MIN_SIDEBAR_W, w)));
  }

  function applySidebarWidth(w, persist = false) {
    sidebarWidth = clampSidebarWidth(w);
    $("#workspace").style.setProperty("--sidebar-w", `${sidebarWidth}px`);
    if (persist) setPref("sidebarWidth", sidebarWidth);
  }
  applySidebarWidth(sidebarWidth, false);

  (() => {
    const resizer = $("#sidebarResizer");
    if (!resizer) return;
    let dragging = false;

    resizer.addEventListener("pointerdown", e => {
      if (e.button !== 0) return;
      dragging = true;
      document.body.classList.add("is-resizing");
      resizer.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    resizer.addEventListener("pointermove", e => {
      if (!dragging) return;
      const rect = $("#workspace").getBoundingClientRect();
      applySidebarWidth(e.clientX - rect.left, false);
    });

    const stopDrag = e => {
      if (!dragging) return;
      dragging = false;
      document.body.classList.remove("is-resizing");
      try { resizer.releasePointerCapture(e.pointerId); } catch {}
      setPref("sidebarWidth", sidebarWidth);
    };
    resizer.addEventListener("pointerup", stopDrag);
    resizer.addEventListener("pointercancel", stopDrag);

    resizer.addEventListener("dblclick", () => {
      applySidebarWidth(DEFAULT_SIDEBAR_W, true);
      toast("Sidebar width reset");
    });

    resizer.addEventListener("keydown", e => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        applySidebarWidth(sidebarWidth - 24, true);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        applySidebarWidth(sidebarWidth + 24, true);
      }
    });

    window.addEventListener("resize", () => applySidebarWidth(sidebarWidth, false));
  })();

  const DEFAULT_SPLIT_PCT = 54;
  let splitTopPct = Number(pref("splitTopPct", DEFAULT_SPLIT_PCT)) || DEFAULT_SPLIT_PCT;
  function applySplitPct(pct, persist = false) {
    splitTopPct = Math.round(Math.min(78, Math.max(22, pct)));
    $("#pane")?.style.setProperty("--split-top", `${splitTopPct}%`);
    if (persist) setPref("splitTopPct", splitTopPct);
  }
  applySplitPct(splitTopPct, false);

  (() => {
    const sResizer = $("#splitResizer");
    if (!sResizer) return;
    let dragging = false;

    sResizer.addEventListener("pointerdown", e => {
      if (e.button !== 0) return;
      dragging = true;
      sResizer.classList.add("dragging");
      document.body.classList.add("is-resizing");
      sResizer.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    sResizer.addEventListener("pointermove", e => {
      if (!dragging) return;
      const paneEl = $("#pane");
      const barH = $("#workspaceModeBar")?.offsetHeight || 0;
      const rect = paneEl.getBoundingClientRect();
      const avail = Math.max(240, rect.height - barH);
      const relY = e.clientY - rect.top - barH;
      applySplitPct((relY / avail) * 100, false);
    });

    const stopSplitDrag = e => {
      if (!dragging) return;
      dragging = false;
      sResizer.classList.remove("dragging");
      document.body.classList.remove("is-resizing");
      try { sResizer.releasePointerCapture(e.pointerId); } catch {}
      setPref("splitTopPct", splitTopPct);
    };
    sResizer.addEventListener("pointerup", stopSplitDrag);
    sResizer.addEventListener("pointercancel", stopSplitDrag);

    sResizer.addEventListener("dblclick", () => {
      applySplitPct(DEFAULT_SPLIT_PCT, true);
      toast("Split height reset");
    });
  })();

  $("#showExternal").checked = pref("external", true);
  $("#showShells").checked = pref("shells", false);
  $("#ansiToggle").checked = useAnsi;
  $("#wrapToggle").checked = wrapLines;

  /* ---------- Utilities ---------- */

  function api(path, body) {
    const opts = { headers: { "X-Deck-Token": TOKEN } };
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(r => r.json());
  }

  const esc = s =>
    String(s ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));

  const shortPath = p =>
    S.home && p && p.startsWith(S.home) ? "~" + p.slice(S.home.length) : (p || "");

  function dur(sec) {
    sec = Math.max(0, Math.floor(sec));
    if (sec < 60) return sec + "s";
    const m = Math.floor(sec / 60);
    if (m < 60) return m + "m " + (sec % 60) + "s";
    const h = Math.floor(m / 60);
    if (h < 24) return h + "h " + (m % 60) + "m";
    return Math.floor(h / 24) + "d " + (h % 24) + "h";
  }

  const ago = t => (t ? (S.now - t < 3 ? "just now" : dur(S.now - t) + " ago") : "unknown");

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => t.classList.remove("show"), 2200);
  }

  /* ---------- Fast, XSS-safe SGR ANSI-to-HTML Renderer ---------- */

  function xterm256ToCss(n) {
    if (n < 16) return `var(--ansi-${n})`;
    if (n < 232) {
      const idx = n - 16;
      const levels = [0, 95, 135, 175, 215, 255];
      const r = levels[Math.floor(idx / 36) % 6];
      const g = levels[Math.floor(idx / 6) % 6];
      const b = levels[idx % 6];
      return `rgb(${r},${g},${b})`;
    }
    const gray = 8 + (n - 232) * 10;
    return `rgb(${gray},${gray},${gray})`;
  }

  function escapeWithSearch(text, needleLower, counter) {
    if (!needleLower) return esc(text);
    const lower = text.toLowerCase();
    let pos = 0;
    let idx = lower.indexOf(needleLower, pos);
    if (idx === -1) return esc(text);
    let out = "";
    while (idx !== -1) {
      out += esc(text.slice(pos, idx));
      out += `<mark class="search-hit">${esc(text.slice(idx, idx + needleLower.length))}</mark>`;
      counter.hits++;
      pos = idx + needleLower.length;
      idx = lower.indexOf(needleLower, pos);
    }
    out += esc(text.slice(pos));
    return out;
  }

  function ansiToHtml(raw, query = "", allowColors = true) {
    const counter = { hits: 0 };
    const needleLower = query ? query.toLowerCase() : "";
    if (!raw) return { html: "", hits: 0 };

    if (!allowColors) {
      const stripped = raw.replace(/\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]/g, "");
      return { html: escapeWithSearch(stripped, needleLower, counter), hits: counter.hits };
    }

    // Normalize non-SGR escapes first, keeping only \x1b[...m
    const cleaned = raw.replace(
      /\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[A-ln-z@-~]|\x1b[@-Z\\-_]/g,
      ""
    );

    const st = { b: false, d: false, i: false, u: false, s: false, inv: false, fg: null, bg: null };
    let openSpan = false;
    let html = "";

    function emitSpanOpen() {
      const classes = [];
      const styles = [];
      if (st.b) classes.push("a-b");
      if (st.d) classes.push("a-d");
      if (st.i) classes.push("a-i");
      if (st.u) classes.push("a-u");
      if (st.s) classes.push("a-s");
      if (st.inv) classes.push("a-inv");

      if (st.fg !== null) {
        if (typeof st.fg === "number") classes.push(`fg-${st.fg}`);
        else styles.push(`color:${st.fg}`);
      }
      if (st.bg !== null) {
        styles.push(`background-color:${st.bg}`);
      }
      if (!classes.length && !styles.length) return false;
      const clsAttr = classes.length ? ` class="${classes.join(" ")}"` : "";
      const styAttr = styles.length ? ` style="${styles.join(";")}"` : "";
      html += `<span${clsAttr}${styAttr}>`;
      return true;
    }

    function applyCodes(codes) {
      for (let i = 0; i < codes.length; i++) {
        const c = codes[i];
        if (c === 0) {
          st.b = st.d = st.i = st.u = st.s = st.inv = false;
          st.fg = st.bg = null;
        } else if (c === 1) st.b = true;
        else if (c === 2) st.d = true;
        else if (c === 3) st.i = true;
        else if (c === 4) st.u = true;
        else if (c === 7) st.inv = true;
        else if (c === 9) st.s = true;
        else if (c === 22) { st.b = false; st.d = false; }
        else if (c === 23) st.i = false;
        else if (c === 24) st.u = false;
        else if (c === 27) st.inv = false;
        else if (c === 29) st.s = false;
        else if (c >= 30 && c <= 37) st.fg = c - 30;
        else if (c === 39) st.fg = null;
        else if (c >= 90 && c <= 97) st.fg = c - 90 + 8;
        else if (c >= 40 && c <= 47) st.bg = xterm256ToCss(c - 40);
        else if (c === 49) st.bg = null;
        else if (c >= 100 && c <= 107) st.bg = xterm256ToCss(c - 100 + 8);
        else if (c === 38 || c === 48) {
          const isFg = c === 38;
          const mode = codes[i + 1];
          if (mode === 5 && i + 2 < codes.length) {
            const n = Math.max(0, Math.min(255, codes[i + 2]));
            if (isFg && n < 16) st.fg = n;
            else if (isFg) st.fg = xterm256ToCss(n);
            else st.bg = xterm256ToCss(n);
            i += 2;
          } else if (mode === 2 && i + 4 < codes.length) {
            const r = Math.max(0, Math.min(255, codes[i + 2]));
            const g = Math.max(0, Math.min(255, codes[i + 3]));
            const b = Math.max(0, Math.min(255, codes[i + 4]));
            const rgb = `rgb(${r},${g},${b})`;
            if (isFg) st.fg = rgb;
            else st.bg = rgb;
            i += 4;
          }
        }
      }
    }

    const sgrRe = /\x1b\[([0-9;]*)m/g;
    let lastIdx = 0;
    let match;
    while ((match = sgrRe.exec(cleaned)) !== null) {
      if (match.index > lastIdx) {
        html += escapeWithSearch(cleaned.slice(lastIdx, match.index), needleLower, counter);
      }
      if (openSpan) {
        html += "</span>";
        openSpan = false;
      }
      const rawParams = match[1];
      const codes = rawParams === "" ? [0] : rawParams.split(";").map(x => (x === "" ? 0 : parseInt(x, 10) || 0));
      applyCodes(codes);
      openSpan = emitSpanOpen();
      lastIdx = sgrRe.lastIndex;
    }

    if (lastIdx < cleaned.length) {
      html += escapeWithSearch(cleaned.slice(lastIdx), needleLower, counter);
    }
    if (openSpan) html += "</span>";
    return { html, hits: counter.hits };
  }

  /* ---------- Filtering & Selection ---------- */

  function passesBaseToggleFilter(s) {
    const shells = $("#showShells").checked;
    const showExt = $("#showExternal").checked;
    const isExt = (s.backend || "tmux") !== "tmux";
    if (isExt && !showExt && !s.pinned) return false;
    if (!shells && s.status === "shell" && !s.pinned) return false;
    return true;
  }

  function matchesAgentTab(s, tab = agentFilter) {
    if (tab === "agy") return s.agent_kind === "agy";
    if (tab === "claude") return s.agent_kind === "claude";
    return true;
  }

  function visibleSessions() {
    const q = searchFilter.trim().toLowerCase();
    return S.sessions
      .filter(s => {
        if (!passesBaseToggleFilter(s)) return false;
        if (!matchesAgentTab(s, agentFilter)) return false;
        if (statusFilter !== "all" && s.status !== statusFilter) return false;
        if (q) {
          const hay = [
            s.terminal_name,
            s.conversation_title,
            s.folder_name,
            s.dev_server,
            s.browser_url,
            s.tty_short,
            s.session,
            s.current_task,
            s.window_name,
            s.host_app,
            s.label,
            s.cwd,
            s.agent_kind,
            s.git?.branch,
            s.ticket,
          ].filter(Boolean).join(" ").toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      })
      .sort((a, b) => {
        if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
        if (ORDER[a.status] !== ORDER[b.status]) return ORDER[a.status] - ORDER[b.status];
        return a.target.localeCompare(b.target, undefined, { numeric: true });
      });
  }

  const current = () => S.sessions.find(s => s.id === sel && matchesAgentTab(s, agentFilter));

  /* ---------- Alerts & Sound ---------- */

  let audioCtx = null;
  function beep(status) {
    if (!sound) return;
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const notes = status === "needs_input" ? [880, 660] : status === "done" ? [660, 990] : [330, 250];
      notes.forEach((f, i) => {
        const o = audioCtx.createOscillator();
        const g = audioCtx.createGain();
        o.frequency.value = f;
        o.type = "sine";
        const t0 = audioCtx.currentTime + i * 0.15;
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.exponentialRampToValueAtTime(0.16, t0 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.14);
        o.connect(g).connect(audioCtx.destination);
        o.start(t0);
        o.stop(t0 + 0.15);
      });
    } catch {}
  }

  function notifyTransition(s) {
    flashUntil[s.id] = Date.now() + 1200;
    beep(s.status);
    if (document.hidden && "Notification" in window && Notification.permission === "granted") {
      const what =
        s.status === "needs_input"
          ? "needs your response"
          : s.status === "done"
            ? "finished its turn"
            : "exited";
      const n = new Notification(`${s.session} ${what}`, {
        body: s.label || (s.preview || []).slice(-1)[0] || shortPath(s.cwd),
        tag: s.id,
      });
      n.onclick = () => {
        window.focus();
        selectSession(s.id);
        n.close();
      };
    }
  }

  function detectTransitions() {
    for (const s of S.sessions) {
      if (loaded && prevStatus[s.id] && prevStatus[s.id] !== s.status && ALERT_ON.has(s.status)) {
        notifyTransition(s);
      }
      prevStatus[s.id] = s.status;
    }
    loaded = true;
  }

  /* ---------- Rendering ---------- */

  function formatAgentSummary(s) {
    const kind = s.agent_kind;
    if (!kind || kind === "program") return null;
    const parts = [kind.toUpperCase()];
    const m = s.agent_meta || {};
    if (m.model) parts.push(m.model);
    if (m.mode) parts.push(m.mode);
    if (m.effort) parts.push(m.effort);
    if (m.sandbox) parts.push("sandbox");
    if (m.skip_perms) parts.push("skip-perms");
    return parts.join(" · ");
  }

  function renderAgentTabs() {
    let bothCount = 0;
    let agyCount = 0;
    let claudeCount = 0;
    let bothNeeds = false;
    let agyNeeds = false;
    let claudeNeeds = false;

    S.sessions.forEach(s => {
      if (!passesBaseToggleFilter(s)) return;
      bothCount++;
      if (s.status === "needs_input") bothNeeds = true;
      if (s.agent_kind === "agy") {
        agyCount++;
        if (s.status === "needs_input") agyNeeds = true;
      } else if (s.agent_kind === "claude") {
        claudeCount++;
        if (s.status === "needs_input") claudeNeeds = true;
      }
    });

    $("#agentCountBoth").textContent = String(bothCount);
    $("#agentCountAgy").textContent = String(agyCount);
    $("#agentCountClaude").textContent = String(claudeCount);

    $$("button[data-agent-tab]").forEach(btn => {
      const key = btn.dataset.agentTab;
      const isAct = key === agentFilter;
      const needs = key === "both" ? bothNeeds : key === "agy" ? agyNeeds : claudeNeeds;
      btn.classList.toggle("active", isAct);
      btn.classList.toggle("has-needs", needs);
      btn.setAttribute("aria-selected", isAct ? "true" : "false");
    });
  }

  function renderCounts() {
    const c = { all: 0, needs_input: 0, working: 0, done: 0, idle: 0, exited: 0 };
    let totalNeedsAcrossAll = 0;
    S.sessions.forEach(s => {
      if (!passesBaseToggleFilter(s)) return;
      if (s.status === "needs_input") totalNeedsAcrossAll++;
      if (!matchesAgentTab(s, agentFilter)) return;
      c.all++;
      if (s.status in c) c[s.status]++;
    });

    const pills = [
      { key: "all", label: "All", count: c.all },
      { key: "needs_input", label: "Needs you", count: c.needs_input, hot: c.needs_input > 0 },
      { key: "working", label: "Working", count: c.working },
      { key: "done", label: "Ready", count: c.done },
      { key: "idle", label: "Quiet", count: c.idle },
    ];
    if (c.exited > 0 || statusFilter === "exited") {
      pills.push({ key: "exited", label: "Exited", count: c.exited });
    }

    $("#counts").innerHTML = pills
      .map(p => {
        const cls = [
          "count-pill",
          statusFilter === p.key ? "active-filter" : "",
          p.hot ? "needs-hot" : "",
        ].filter(Boolean).join(" ");
        return `<button type="button" class="${cls}" data-filter="${p.key}">${esc(p.label)} <b>${p.count}</b></button>`;
      })
      .join("");

    document.title = (totalNeedsAcrossAll ? `(${totalNeedsAcrossAll}) ` : "") + "Agent Deck";
  }

  function progressText(p) {
    return p ? `${p.done} of ${p.total} ${p.source === "checklist" ? "items" : "steps"}` : "";
  }

  function formatSessionTime(s) {
    const uptime =
      s.agent_since && !s.agent_ended
        ? (s.agent_since_exact ? "" : "≥ ") + dur(S.now - s.agent_since)
        : null;

    if (s.status === "working") {
      const start = s.turn_since || (s.last_change_exact ? s.last_change : s.agent_since);
      if (start) {
        const text = `running ${dur(S.now - start)}`;
        const tip = uptime ? `Current turn running ${dur(S.now - start)} · Open ${uptime}` : `Current turn running ${dur(S.now - start)}`;
        return { text, tip };
      }
    }

    if (s.last_change_exact && s.last_change) {
      const rel = ago(s.last_change);
      const tip = uptime ? `Last active ${rel} · Open ${uptime}` : `Last active ${rel}`;
      return { text: rel, tip };
    }

    if (uptime) {
      return { text: `up ${uptime}`, tip: `Open ${uptime}` };
    }
    return null;
  }

  function canSessionSend(s) {
    if (!s) return false;
    if (typeof s.can_send === "boolean") return s.can_send;
    return ["tmux", "ghostty", "iterm2", "terminal_app"].includes(s.backend || "tmux");
  }

  function canSessionKeys(s) {
    if (!s) return false;
    if (typeof s.can_keys === "boolean") return s.can_keys;
    return ["tmux", "ghostty", "iterm2", "terminal_app"].includes(s.backend || "tmux");
  }

  function effectiveChoices(s) {
    if (s?.pending_action?.choices?.length) return s.pending_action.choices;
    if (s?.choices?.length) return s.choices;
    return [
      { keys: ["1"], label: "1. Allow once", style: "primary" },
      { keys: ["2"], label: "2. Always allow", style: "" },
      { keys: ["y", "Enter"], label: "Yes (y)", style: "" },
      { keys: ["Escape"], label: "Cancel (Esc)", style: "danger" },
    ];
  }

  function renderChoiceButtons(choices, keyAttr = "data-keys", extraAttrs = "") {
    return choices
      .map(ch => {
        const stCls = ch.style === "primary"
          ? " choice-primary"
          : ch.style === "danger"
            ? " choice-danger"
            : "";
        const tip = ch.tooltip || ch.label;
        const extra = extraAttrs ? ` ${extraAttrs}` : "";
        return `<button type="button" class="btn compact choice-btn${stCls}"${extra} ${keyAttr}='${esc(JSON.stringify(ch.keys))}' title="${esc(tip)}">${esc(ch.label)}</button>`;
      })
      .join("");
  }

  function renderSidebar(list) {
    const nowMs = Date.now();
    const shellCount = S.sessions.filter(s => s.status === "shell").length;
    $("#emptyShowShellsBtn").hidden = shellCount === 0 || $("#showShells").checked;

    const listEl = $("#list");
    const focusedCardInput = document.activeElement?.dataset?.cardReplyInput || null;
    $$("input[data-card-reply-input]", listEl).forEach(inp => {
      cardDrafts[inp.dataset.cardReplyInput] = inp.value;
    });

    if (!list.length) {
      let msg = "No active agent sessions yet.";
      if (statusFilter !== "all" || searchFilter) {
        msg = "No sessions match your current filter.";
      } else if (agentFilter === "claude") {
        msg = "No Claude Code sessions running right now.";
      } else if (agentFilter === "agy") {
        msg = "No Antigravity (agy) sessions running right now.";
      } else if (shellCount > 0 && !$("#showShells").checked) {
        msg = `Only ${shellCount} plain shell${shellCount === 1 ? "" : "s"} open. Enable “Plain shells” above to view.`;
      }
      listEl.innerHTML = `<li class="row-meta" style="padding:12px 10px">${esc(msg)}</li>`;
      return;
    }

    listEl.innerHTML = list
      .map((s, i) => {
        const pct = s.progress ? Math.round((100 * s.progress.done) / s.progress.total) : null;
        const timeInfo = formatSessionTime(s);
        const last = (s.preview || []).slice(-1)[0] || "";
        const pulse = s.status === "working" || s.status === "needs_input" ? " pulse" : "";
        const kindBadge = s.agent_kind && s.agent_kind !== "program"
          ? `<span class="row-badge kind-${esc(s.agent_kind)}">${esc(s.agent_kind)}</span>`
          : "";
        const isExt = (s.backend || "tmux") !== "tmux";
        const hostLabel = s.backend === "agy_live"
          ? "IDE / live"
          : isExt
            ? `${s.host_app || "Terminal"}${s.tty_short ? ` · ${s.tty_short}` : ""}`
            : `tmux · ${s.session}:${s.window}`;
        const hostBadge = `<span class="row-badge ext-badge" title="Terminal location">${esc(hostLabel)}</span>`;
        const webLabel = s.dev_server || shortBrowserBadge(s.custom_url);
        const devBadge = webLabel
          ? `<button type="button" class="row-badge dev-badge" data-card-view="browser" data-card-id="${esc(s.id)}" title="Show live browser (${esc(s.browser_url || webLabel)})">${esc(webLabel)}</button>`
          : "";
        const termTitle = s.terminal_name || s.session;
        const taskText = s.current_task || s.label || "Idle";
        const folderLabel = s.folder_name || (shortPath(s.cwd).split("/").filter(Boolean).pop() || shortPath(s.cwd));
        const folderPill = `<span class="card-where-pill" title="${esc(shortPath(s.cwd))}">${ICONS.folder}${esc(folderLabel)}</span>`;
        const branchPill = s.git?.branch
          ? `<span class="card-branch-pill" title="Git branch">${ICONS.gitBranch}${esc(s.git.branch)}${s.git.dirty ? ` *${s.git.dirty}` : ""}</span>`
          : `<span class="card-branch-pill" title="No git repository">${ICONS.gitBranch}no-branch</span>`;

        const canSend = canSessionSend(s);
        const canKeys = canSessionKeys(s);
        const replyOpen = canSend && openReplyCards.has(s.id);
        const replyToggleBtn = canSend
          ? `<button type="button" class="card-open-btn card-reply-toggle${replyOpen ? " active" : ""}" data-toggle-reply="${esc(s.id)}" title="Reply directly to ${esc(termTitle)}">${ICONS.reply}Reply</button>`
          : "";
        const isTermShown = s.id === sel && (rightTab === "terminal" || rightTab === "split");
        const termViewBtn = `<button type="button" class="card-open-btn${isTermShown ? " is-active-mode" : ""}" data-card-view="terminal" data-card-id="${esc(s.id)}" title="${isTermShown ? "Switch back to Browser view" : "Show terminal text & code right here"}">${ICONS.terminal}Code</button>`;

        let actionBoxHtml = "";
        if (s.status === "needs_input") {
          const actTitle = s.pending_action?.title || "Waiting for your confirmation";
          const actDetail = s.pending_action?.detail || "";
          const choicesHtml = canKeys
            ? renderChoiceButtons(effectiveChoices(s), "data-card-keys", `data-card-pane="${esc(s.id)}"`) +
              (canSend && !replyOpen
                ? `<button type="button" class="btn compact choice-btn" data-toggle-reply="${esc(s.id)}" title="Type a custom reply">Reply…</button>`
                : "")
            : `<button type="button" class="btn compact choice-btn choice-primary" data-open-term="${esc(s.id)}">Open terminal</button>` +
              `<button type="button" class="btn compact choice-btn" data-card-adopt="${esc(s.id)}">Resume in tmux</button>`;
          actionBoxHtml = `<div class="card-action-box">
            <div class="card-action-title">${esc(actTitle)}</div>
            ${actDetail ? `<code class="card-action-detail" title="${esc(actDetail)}">${esc(actDetail)}</code>` : ""}
            <div class="card-action-choices">${choicesHtml}</div>
          </div>`;
        }

        const inlineReplyHtml = replyOpen
          ? `<form class="card-reply-form" data-card-reply-form="${esc(s.id)}" autocomplete="off">
               <input type="text" data-card-reply-input="${esc(s.id)}" placeholder="Reply to ${esc(termTitle)}…" value="${esc(cardDrafts[s.id] || "")}" aria-label="Reply to ${esc(termTitle)}">
               <button type="submit" class="btn compact primary">Send</button>
             </form>`
          : "";

        return `<li class="session-row s-${s.status}${s.id === sel ? " sel" : ""}${flashUntil[s.id] > nowMs ? " flash" : ""}" data-id="${esc(s.id)}" tabindex="-1">
          <div class="row-top">
            <span class="dot${pulse}"></span>
            <span class="row-name" title="${esc(termTitle)}">${s.pinned ? "★ " : ""}${esc(termTitle)}</span>
            <div class="card-top-actions">
              ${termViewBtn}
              ${replyToggleBtn}
              <button type="button" class="card-open-btn" data-open-term="${esc(s.id)}" title="Focus window in ${esc(s.host_app || "macOS Terminal")}">${ICONS.extOpen}App</button>
            </div>
          </div>
          <div class="card-branch-row">
            <span class="row-status">${esc(LABEL[s.status])}</span>
            ${kindBadge}
            ${hostBadge}
            ${devBadge}
            ${timeInfo ? `<span class="card-dur" title="${esc(timeInfo.tip)}">· ${esc(timeInfo.text)}</span>` : ""}
            ${s.error_hint ? `<span class="row-warn">· Error</span>` : ""}
          </div>
          <div class="card-where-row">
            ${folderPill}
            ${branchPill}
          </div>
          <div class="card-task" title="${esc(taskText)}"><span class="task-lbl">Task:</span>${esc(taskText)}</div>
          ${actionBoxHtml}
          ${inlineReplyHtml}
          ${pct !== null ? `<div class="prog-track" title="${esc(progressText(s.progress))}"><span style="width:${pct}%"></span></div>` : ""}
          ${last ? `<div class="row-preview">${esc(last)}</div>` : ""}
          ${i < 9 ? `<span class="row-key">${i + 1}</span>` : ""}
        </li>`;
      })
      .join("");

    if (focusedCardInput) {
      const inp = $(`input[data-card-reply-input="${CSS.escape(focusedCardInput)}"]`, listEl);
      if (inp) {
        inp.focus();
        const len = inp.value.length;
        try { inp.setSelectionRange(len, len); } catch {}
      }
    }
  }

  function renderEvents() {
    const ev = S.events.slice(-40).reverse();
    $("#eventCount").textContent = String(ev.length);
    $("#events").innerHTML = ev.length
      ? ev.map(e =>
          `<li class="s-${e.to}">
            <span class="ev-time">${esc(ago(e.t).replace(" ago", ""))}</span>
            <span class="ev-sess">${esc(e.session)}</span>
            <span class="ev-to">${esc(LABEL[e.to])}</span>
          </li>`
        ).join("")
      : `<li class="ev-time">Transitions appear here as agents work.</li>`;
  }

  function renderTerminalContent() {
    const s = current();
    if (!s) return;
    const entry = paneOutputs[s.id];
    const outEl = $("#out");
    outEl.className = `term-out ${wrapLines ? "wrap" : "nowrap"}`;

    if (!entry) {
      outEl.textContent = "Loading session output…";
      $("#termMatchCount").textContent = "";
      return;
    }

    const raw = entry.ansi || entry.plain || "";
    if (!raw) {
      outEl.textContent = "(empty screen)";
      $("#termMatchCount").textContent = "";
      return;
    }

    const rendered = ansiToHtml(raw, termQuery, useAnsi);
    outEl.innerHTML = rendered.html;
    $("#termMatchCount").textContent = termQuery ? `${rendered.hits} match${rendered.hits === 1 ? "" : "es"}` : "";
    if (stick) {
      outEl.scrollTop = outEl.scrollHeight;
    }
  }

  function shortBrowserBadge(urlStr) {
    if (!urlStr) return "";
    try {
      const u = new URL(urlStr);
      if (u.port && (u.hostname === "localhost" || u.hostname === "127.0.0.1")) {
        return `web :${u.port}`;
      }
      return `web ${u.host.slice(0, 18)}`;
    } catch {
      return "";
    }
  }

  function resolveUrlInput(raw, s) {
    const val = String(raw || "").trim();
    if (!val) return "";
    if (val.startsWith("/")) {
      const base = s?.browser_url || s?.auto_url || "http://localhost:3000";
      try {
        const u = new URL(base);
        return `${u.origin}${val}`;
      } catch {
        return `http://localhost:3000${val}`;
      }
    }
    if (val.startsWith(":")) return `http://localhost${val}`;
    if (/^\d{2,5}(\/.*)?$/.test(val)) return `http://localhost:${val}`;
    if (/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(\/.*)?$/i.test(val)) return `http://${val}`;
    if (/^https?:\/\//i.test(val)) return val;
    return `https://${val}`;
  }

  function syncBrowserFrames(activeSess) {
    const aliveIds = new Set(S.sessions.map(x => x.id));
    for (const [sid, entry] of browserFramePool) {
      if (!aliveIds.has(sid)) {
        entry.el.remove();
        browserFramePool.delete(sid);
      }
    }

    const framesWrap = $("#browserFrames");
    const emptyWrap = $("#browserEmpty");
    const url = activeSess?.browser_url || "";

    if (!activeSess || !url) {
      framesWrap.hidden = true;
      emptyWrap.hidden = !activeSess;
      for (const [, entry] of browserFramePool) entry.el.hidden = true;
      return;
    }

    framesWrap.hidden = false;
    emptyWrap.hidden = true;

    let entry = browserFramePool.get(activeSess.id);
    if (!entry) {
      if (browserFramePool.size >= 8) {
        let oldestId = null;
        let oldestTs = Infinity;
        for (const [sid, cand] of browserFramePool) {
          if (sid !== activeSess.id && cand.touched < oldestTs) {
            oldestTs = cand.touched;
            oldestId = sid;
          }
        }
        if (oldestId) {
          browserFramePool.get(oldestId)?.el.remove();
          browserFramePool.delete(oldestId);
        }
      }
      const frame = document.createElement("iframe");
      frame.className = "browser-frame";
      frame.dataset.sid = activeSess.id;
      frame.setAttribute("allow", "clipboard-read; clipboard-write; microphone; camera; fullscreen");
      frame.src = url;
      framesWrap.appendChild(frame);
      entry = { el: frame, url, touched: Date.now() };
      browserFramePool.set(activeSess.id, entry);
    } else {
      entry.touched = Date.now();
      if (entry.url !== url) {
        entry.url = url;
        entry.el.src = url;
      }
    }

    for (const [sid, item] of browserFramePool) {
      item.el.hidden = sid !== activeSess.id;
    }
  }

  function reloadBrowserFrame(sid) {
    const entry = browserFramePool.get(sid);
    if (!entry) return;
    try {
      entry.el.contentWindow.location.reload();
    } catch {
      const u = entry.url;
      entry.el.src = u;
    }
  }

  function renderBrowserView(s) {
    const pulse = s.status === "working" || s.status === "needs_input" ? " pulse" : "";
    const dot = $("#bDot");
    dot.className = `dot s-${s.status}${pulse}`;
    $("#bName").textContent = s.terminal_name || s.session;
    $("#bName").title = `${s.terminal_name || s.session} · ${shortPath(s.cwd)}`;

    const bBranch = $("#bBranch");
    bBranch.hidden = !s.git?.branch;
    if (s.git?.branch) {
      bBranch.textContent = s.git.branch;
      bBranch.title = `${shortPath(s.cwd)} (${s.git.branch})`;
    }

    const wAgentBadge = $("#wAgentBadge");
    const wSummary = formatAgentSummary(s);
    if (wAgentBadge) {
      wAgentBadge.hidden = !wSummary;
      if (wSummary) {
        const wKindCls = s.agent_kind === "agy" ? "is-agy" : s.agent_kind === "claude" ? "is-claude" : "";
        wAgentBadge.className = `agent-chip ${wKindCls}`.trim();
        wAgentBadge.textContent = wSummary;
      }
    }

    const wPortBadge = $("#wPortBadge");
    if (wPortBadge) {
      const portLbl = s.dev_port ? `:${s.dev_port}` : (s.custom_url ? shortBrowserBadge(s.custom_url).replace(/^web\s+/, "") : "");
      wPortBadge.hidden = !portLbl;
      if (portLbl) wPortBadge.textContent = portLbl;
    }

    const wOpenLbl = $("#wOpenAppLabel");
    if (wOpenLbl) {
      const appName = s.host_app && s.host_app !== "tmux" && s.host_app !== "Antigravity"
        ? s.host_app
        : "Terminal App";
      wOpenLbl.textContent = `Open ${appName}`;
    }

    const urlInput = $("#bUrlInput");
    if (document.activeElement !== urlInput) {
      urlInput.value = s.browser_url || "";
    }

    const resetBtn = $("#bUrlResetBtn");
    resetBtn.hidden = !s.custom_url;
    if (s.custom_url) {
      resetBtn.textContent = s.dev_port ? `Auto :${s.dev_port}` : "Clear";
      resetBtn.title = s.auto_url
        ? `Revert to auto-detected ${s.auto_url}`
        : "Clear custom URL";
    }

    $("#bReloadBtn").disabled = !s.browser_url;
    $("#bPopOutBtn").disabled = !s.browser_url;
    $("#bMobileBtn").classList.toggle("active", mobilePreview);
    $("#browserStage").classList.toggle("is-mobile", mobilePreview);

    const ports = S.local_ports || [];
    const portSel = $("#bPortSelect");
    portSel.hidden = ports.length === 0;
    if (ports.length && document.activeElement !== portSel) {
      const sig = `${s.id}|${s.browser_url || ""}|${ports.map(p => `${p.port}:${p.folder}`).join(",")}`;
      if (sig !== lastPortSelectSig) {
        lastPortSelectSig = sig;
        let curOrigin = "";
        try {
          if (s.browser_url) curOrigin = new URL(s.browser_url).origin;
        } catch {}
        const opts = [`<option value="">Switch port…</option>`];
        for (const p of ports) {
          const selAttr = curOrigin === p.url ? " selected" : "";
          const suffix = p.folder ? ` · ${p.folder}` : "";
          opts.push(`<option value="${esc(p.url)}"${selAttr}>:${p.port}${esc(suffix)}</option>`);
        }
        portSel.innerHTML = opts.join("");
      }
    }

    const srvBtn = $("#bServerBtn");
    const isBooting = startingServers.has(s.id);
    if (isBooting) {
      srvBtn.hidden = false;
      srvBtn.disabled = true;
      srvBtn.textContent = "Starting…";
    } else if (s.managed_dev) {
      srvBtn.hidden = false;
      srvBtn.disabled = false;
      srvBtn.textContent = `Stop :${s.dev_port || "dev"}`;
    } else if (!s.dev_port && s.can_start_dev) {
      srvBtn.hidden = false;
      srvBtn.disabled = false;
      srvBtn.textContent = "Start server";
    } else {
      srvBtn.hidden = true;
    }

    const canSend = canSessionSend(s);
    const canKeys = canSessionKeys(s);
    const actBanner = $("#bActionBanner");
    actBanner.hidden = s.status !== "needs_input";
    if (s.status === "needs_input") {
      $("#bActionTitle").textContent = s.pending_action?.title || "Waiting for your response";
      const detEl = $("#bActionDetail");
      const detText = s.pending_action?.detail || "";
      detEl.hidden = !detText;
      if (detText) {
        detEl.textContent = detText;
        detEl.title = detText;
      }
      $("#bActionChoices").innerHTML = canKeys
        ? renderChoiceButtons(effectiveChoices(s), "data-keys")
        : `<button type="button" class="btn compact choice-btn choice-primary" data-b-open="1">Open terminal</button>` +
          `<button type="button" class="btn compact choice-btn" data-b-adopt="1">Resume in tmux</button>`;
    }

    const bReplyForm = $("#bReplyForm");
    const bReplyReadonly = $("#bReplyReadonly");
    bReplyForm.hidden = !canSend;
    bReplyReadonly.hidden = canSend;
    if (canSend) {
      const hostDesc = s.backend === "tmux"
        ? `tmux · ${s.session}:${s.window}`
        : `${s.host_app || s.backend}${s.tty_short ? ` · ${s.tty_short}` : ""}`;
      $("#bReplyInput").placeholder = `Reply directly to ${s.terminal_name || s.session} (${hostDesc})… (i)`;
      $("#bReplyQuick").hidden = !canKeys;
    } else {
      $("#bReplyReadonlyText").textContent = s.backend === "agy_live"
        ? "Live Antigravity IDE transcript. Resume in tmux to send prompts & keys here."
        : `Running in ${s.host_app || "external terminal"}. Open terminal or resume in tmux to reply here.`;
      $("#bReplyAdoptBtn").textContent = s.adopt_cmd ? "Resume in tmux" : "Open folder in tmux";
    }

    syncBrowserFrames(s);

    if (!s.browser_url) {
      $("#bEmptyTitle").textContent = `No local web server linked to ${s.terminal_name || s.session}`;
      $("#bEmptyMeta").textContent = `${shortPath(s.cwd)}${s.git?.branch ? ` · ${s.git.branch}` : ""}`;
      $("#bEmptyTask").textContent = `Task: ${s.current_task || s.label || "Idle"}`;

      const startBtn = $("#bEmptyStartBtn");
      startBtn.hidden = !s.can_start_dev;
      startBtn.disabled = isBooting;
      startBtn.textContent = isBooting
        ? "Starting dev server…"
        : `Start dev server (${s.dev_cmd_preview || "dev"})`;

      const pickerWrap = $("#bEmptyPortsWrap");
      pickerWrap.hidden = ports.length === 0;
      if (ports.length) {
        $("#bEmptyPorts").innerHTML = ports
          .map(p => {
            const same = p.cwd && p.cwd === s.cwd ? " same-cwd" : "";
            const folderHtml = p.folder ? `<span class="port-folder">${esc(p.folder)}</span>` : "";
            return `<button type="button" class="port-pick-btn${same}" data-pick-url="${esc(p.url)}">localhost:${p.port} ${folderHtml}</button>`;
          })
          .join("");
      }
    }
  }

  function renderEmptyState() {
    const anyBaseSessions = S.sessions.some(passesBaseToggleFilter);
    if (agentFilter === "claude") {
      $("#emptyTitle").textContent = "No Claude Code sessions running yet";
      $("#emptyDesc").innerHTML = "Start a Claude Code (<code>claude</code>) session directly from here, or launch one in any terminal:";
      $("#emptyCode").textContent = "tmux new -s feature-work\nclaude";
      $("#emptyNewBtn").textContent = "Start a Claude session";
      $("#emptyShowBothBtn").hidden = !anyBaseSessions;
    } else if (agentFilter === "agy") {
      $("#emptyTitle").textContent = "No Antigravity (agy) sessions running yet";
      $("#emptyDesc").innerHTML = "Start an Antigravity (<code>agy</code>) session directly from here, or launch one in any terminal:";
      $("#emptyCode").textContent = "tmux new -s feature-work\nagy --mode auto";
      $("#emptyNewBtn").textContent = "Start an agy session";
      $("#emptyShowBothBtn").hidden = !anyBaseSessions;
    } else {
      $("#emptyTitle").textContent = "No agent sessions running yet";
      $("#emptyDesc").innerHTML = "Start an Antigravity (<code>agy</code>) or Claude Code (<code>claude</code>) session directly from here, or launch one in any terminal:";
      $("#emptyCode").textContent = "tmux new -s feature-work\nagy --mode auto   # or: claude";
      $("#emptyNewBtn").textContent = "Start a session";
      $("#emptyShowBothBtn").hidden = true;
    }
  }

  function renderInspector() {
    const s = current();
    $("#empty").hidden = !!s;
    $("#pane").hidden = !s;
    if (!s) {
      renderEmptyState();
      syncBrowserFrames(null);
      return;
    }

    $$("[data-right-tab]").forEach(btn => {
      const isAct = btn.dataset.rightTab === rightTab;
      btn.classList.toggle("active", isAct);
      if (btn.getAttribute("role") === "tab") {
        btn.setAttribute("aria-selected", isAct ? "true" : "false");
      }
    });
    const isSplit = rightTab === "split";
    $("#pane").classList.toggle("is-split", isSplit);
    $("#browserView").hidden = rightTab === "terminal";
    $("#splitResizer").hidden = !isSplit;
    $("#termView").hidden = rightTab === "browser";

    renderBrowserView(s);

    const backend = s.backend || "tmux";
    const isExt = backend !== "tmux";
    $("#pName").textContent = s.terminal_name || s.session;

    const pill = $("#pStatus");
    const pulse = s.status === "working" || s.status === "needs_input" ? " pulse" : "";
    pill.className = `status-pill s-${s.status}`;
    pill.innerHTML = `<span class="dot${pulse}"></span>${esc(LABEL[s.status])}`;

    const srcChip = $("#pSourceChip");
    srcChip.hidden = !isExt;
    if (isExt) {
      srcChip.textContent = backend === "agy_live"
        ? "Antigravity live"
        : `${s.host_app || "External TTY"}${s.tty_short ? ` · ${s.tty_short}` : ""}`;
    }

    const agentSummary = formatAgentSummary(s);
    const agentChip = $("#pAgentChip");
    agentChip.hidden = !agentSummary;
    if (agentSummary) {
      const chipKindCls = s.agent_kind === "agy" ? "is-agy" : s.agent_kind === "claude" ? "is-claude" : "";
      agentChip.className = `agent-chip ${chipKindCls}`.trim();
      agentChip.textContent = agentSummary;
    }

    const gitChip = $("#pGitChip");
    gitChip.hidden = false;
    gitChip.textContent = s.git?.branch
      ? `branch: ${s.git.branch}${s.git.dirty ? ` (*${s.git.dirty})` : ""}`
      : "branch: none";

    const ticketChip = $("#pTicketChip");
    ticketChip.hidden = !s.ticket;
    if (s.ticket) {
      ticketChip.textContent = `Ticket: ${s.ticket.slice(0, 12)}`;
      ticketChip.title = `Ticket: ${s.ticket}`;
    }

    const taskText = s.current_task || s.label || "Idle";
    $("#pTaskLine").innerHTML = `<span class="task-lbl">Current task:</span>${esc(taskText)}`;

    const adoptLabel = s.adopt_cmd ? "Resume in tmux" : "Open folder in tmux";
    $("#adoptBtn").hidden = !isExt;
    $("#adoptBtn").textContent = adoptLabel;
    $("#adoptBtn").title = s.adopt_cmd ? `Start tmux session running: ${s.adopt_cmd}` : "Open this working directory in tmux";

    $("#ackBtn").hidden = isExt || s.status !== "done";
    $("#respawnBtn").hidden = isExt || s.status !== "exited";
    $("#copyAttach").hidden = isExt;
    $("#killBtn").hidden = isExt;
    $("#dismissBtn").hidden = !isExt;
    $("#pinBtn").textContent = s.pinned ? "Unpin" : "Pin";

    if (document.activeElement !== $("#pLabel")) {
      $("#pLabel").value = s.label || "";
    }

    const running =
      s.agent_since && !s.agent_ended
        ? (s.agent_since_exact ? "" : "≥ ") + dur(S.now - s.agent_since)
        : null;
    const ended = s.agent_ended ? ago(s.agent_ended) : null;
    const progDisplay =
      s.status === "shell" || (s.status === "done" && s.agent_ended)
        ? s.cmd
        : s.subtool
          ? `${s.agent_cmd} → ${s.subtool}`
          : s.agent_cmd;

    $("#pMeta").innerHTML =
      `<span>Worktree <b class="mono-val">${esc(shortPath(s.cwd))}</b></span>` +
      `<span>Process <b class="mono-val">${esc(progDisplay)}</b></span>` +
      (s.dev_server ? `<span>Server <b class="mono-val">${esc(s.dev_server)}</b></span>` : "") +
      (running ? `<span>Open <b>${esc(running)}</b></span>` : "") +
      (ended ? `<span>Exited <b>${esc(ended)}</b></span>` : "") +
      (s.last_change_exact !== false && s.last_change ? `<span>Last active <b>${esc(ago(s.last_change))}</b></span>` : "") +
      (s.status === "exited" && s.dead_status ? `<span class="warn">Exit code ${esc(s.dead_status)}</span>` : "") +
      (s.error_hint ? `<span class="warn">Error detected in output</span>` : "");

    const p = s.progress;
    $("#pProg").hidden = !p;
    $("#pProg").className = `pane-progress s-${s.status}`;
    if (p) {
      $("#pBar").style.width = `${Math.round((100 * p.done) / p.total)}%`;
      $("#pProgText").textContent = progressText(p);
    }

    // Prompt banner with detected interactive options
    const canSend = canSessionSend(s);
    const canKeys = canSessionKeys(s);
    const readOnlyExt = !canSend;
    const banner = $("#promptBanner");
    const showPrompt = s.status === "needs_input" && canKeys;
    banner.hidden = !showPrompt;
    if (showPrompt) {
      $("#promptTitle").textContent = s.pending_action?.title || "Waiting for your response";
      const pDet = $("#promptDetail");
      const detTxt = s.pending_action?.detail || "";
      pDet.hidden = !detTxt;
      if (detTxt) {
        pDet.textContent = detTxt;
        pDet.title = detTxt;
      }
      $("#promptChoices").innerHTML = renderChoiceButtons(effectiveChoices(s), "data-keys");
    }

    // Show interactive controls vs read-only Adopt banner
    $("#quick").hidden = !canKeys;
    $("#agySlashBar").hidden = s.agent_kind !== "agy" || !canKeys;
    $("#claudeSlashBar").hidden = s.agent_kind !== "claude" || !canKeys;
    $("#cmdForm").hidden = readOnlyExt;
    $("#adoptBanner").hidden = !readOnlyExt;
    if (readOnlyExt) {
      $("#adoptBannerBtn").textContent = adoptLabel;
      $("#adoptBannerText").textContent = backend === "agy_live"
        ? "Live Antigravity transcript stream. Resume in tmux (close the original tab first if active) for full TUI & keystroke control."
        : s.conversation_id
          ? `Live Antigravity transcript from ${s.host_app || "Terminal"}${s.tty_short ? ` (${s.tty_short})` : ""}. Click 'Open terminal' to jump there, or 'Resume in tmux' for keystroke control here.`
          : `Running outside tmux in ${s.host_app || "an external terminal"}. Move into tmux for live output & keystroke control.`;
    }
  }

  function renderGrid(list) {
    const wall = $("#gridWall");
    if (viewMode !== "grid") {
      wall.hidden = true;
      return;
    }
    wall.hidden = false;
    if (!list.length) {
      wall.innerHTML = `<div class="empty-state"><h2>No sessions to display in grid</h2><p>Start a session or adjust your status filter above.</p></div>`;
      return;
    }

    // Preserve focused tile inputs across re-renders
    const focusedInputPane = document.activeElement?.dataset?.tileInput;
    const drafts = {};
    $$("input[data-tile-input]", wall).forEach(inp => {
      drafts[inp.dataset.tileInput] = inp.value;
    });

    wall.innerHTML = list
      .map(s => {
        const entry = paneOutputs[s.id];
        const rendered = entry ? ansiToHtml(entry.ansi || entry.plain || "", "", useAnsi).html : "Loading…";
        const pulse = s.status === "working" || s.status === "needs_input" ? " pulse" : "";
        const canSend = canSessionSend(s);
        const canKeys = canSessionKeys(s);
        const quickChoices = (s.status === "needs_input" && canKeys)
          ? renderChoiceButtons(effectiveChoices(s).slice(0, 3), "data-tile-keys", `data-tile-pane="${esc(s.id)}"`)
          : "";
        const readOnlyExt = !canSend;
        const footHtml = readOnlyExt
          ? `<div class="tile-foot">
               <span class="tile-meta" style="flex:1">${esc(s.host_app || "External")} (read-only)</span>
               <button class="btn compact primary" type="button" data-tile-adopt="${esc(s.id)}">${esc(s.adopt_cmd ? "Resume in tmux" : "Open in tmux")}</button>
             </div>`
          : `<form class="tile-foot" data-tile-form="${esc(s.id)}" autocomplete="off">
               ${quickChoices}
               <input type="text" data-tile-input="${esc(s.id)}" placeholder="Reply to ${esc(s.terminal_name || s.session)}…" value="${esc(drafts[s.id] || "")}">
               <button class="btn compact primary" type="submit">Send</button>
             </form>`;
        const termTitle = s.terminal_name || s.session;
        const taskText = s.current_task || s.label || "Idle";
        const branchPill = s.git?.branch
          ? `<span class="card-branch-pill">${ICONS.gitBranch}${esc(s.git.branch)}${s.git.dirty ? ` *${s.git.dirty}` : ""}</span>`
          : `<span class="card-branch-pill">${ICONS.gitBranch}no-branch</span>`;

        return `<article class="grid-tile s-${s.status}" data-tile="${esc(s.id)}">
          <div class="tile-head s-${s.status}">
            <div class="tile-head-top">
              <span class="dot${pulse}"></span>
              <span class="tile-title" data-focus-pane="${esc(s.id)}" title="${esc(termTitle)}">${esc(termTitle)}</span>
              <span class="spacer" style="flex:1"></span>
              <button type="button" class="card-open-btn" data-open-term="${esc(s.id)}" title="Open in macOS Terminal">${ICONS.extOpen}Open terminal</button>
              <span class="status-pill s-${s.status}">${esc(LABEL[s.status])}</span>
            </div>
            <div class="card-branch-row">
              ${branchPill}
              <span class="tile-meta">${esc(shortPath(s.cwd))}</span>
            </div>
            <div class="card-task" title="${esc(taskText)}"><span class="task-lbl">Task:</span>${esc(taskText)}</div>
          </div>
          <pre class="tile-term" data-tile-term="${esc(s.id)}">${rendered || "(empty)"}</pre>
          ${footHtml}
        </article>`;
      })
      .join("");

    $$(".tile-term", wall).forEach(el => {
      el.scrollTop = el.scrollHeight;
    });
    if (focusedInputPane) {
      const inp = $(`input[data-tile-input="${CSS.escape(focusedInputPane)}"]`, wall);
      if (inp) inp.focus();
    }
  }

  function render() {
    $("#workspace").classList.toggle("mode-grid", viewMode === "grid");
    $("#viewFocusBtn").classList.toggle("active", viewMode === "focus");
    $("#viewGridBtn").classList.toggle("active", viewMode === "grid");

    const list = visibleSessions();
    const scopedSessions = S.sessions.filter(s => passesBaseToggleFilter(s) && matchesAgentTab(s, agentFilter));
    if (!sel || !scopedSessions.some(s => s.id === sel)) {
      sel = list[0]?.id ?? scopedSessions[0]?.id ?? null;
      stick = true;
    }
    renderAgentTabs();
    renderCounts();
    renderSidebar(list);
    renderEvents();
    if (viewMode === "focus") {
      renderInspector();
      if (rightTab === "terminal" || rightTab === "split") renderTerminalContent();
    } else {
      renderGrid(list);
    }
  }

  /* ---------- Output Fetching & SSE Live Stream ---------- */

  async function fetchPaneOutput(paneId, lines = 800) {
    const existing = paneOutputs[paneId];
    const hashParam = existing?.hash ? `&hash=${encodeURIComponent(existing.hash)}` : "";
    try {
      const r = await api(`/api/output?pane=${encodeURIComponent(paneId)}&lines=${lines}${hashParam}`);
      if (r.ok && !r.unchanged) {
        paneOutputs[paneId] = { hash: r.hash, ansi: r.ansi || "", plain: r.text || "" };
        return true;
      }
    } catch {}
    return false;
  }

  async function syncNeededOutputs() {
    if (viewMode === "focus") {
      if (rightTab !== "terminal" && rightTab !== "split") return;
      const s = current();
      if (!s) return;
      const cached = paneOutputs[s.id];
      if (!cached || cached.hash !== s.output_hash) {
        if (await fetchPaneOutput(s.id, 900)) renderTerminalContent();
      }
    } else {
      const list = visibleSessions().slice(0, 12);
      let anyUpdated = false;
      await Promise.all(
        list.map(async s => {
          const cached = paneOutputs[s.id];
          if (!cached || cached.hash !== s.output_hash) {
            if (await fetchPaneOutput(s.id, 240)) anyUpdated = true;
          }
        })
      );
      if (anyUpdated) renderGrid(list);
    }
  }

  function handleStateUpdate(nextState) {
    S = nextState;
    const b = $("#banner");
    b.hidden = !S.error;
    b.textContent = S.error || "";
    detectTransitions();
    render();
    syncNeededOutputs();
  }

  let sseActive = false;
  function connectStream() {
    if (!("EventSource" in window)) {
      fallbackPoll();
      return;
    }
    const es = new EventSource(`/api/stream?token=${encodeURIComponent(TOKEN)}`);
    es.onopen = () => {
      sseActive = true;
      $("#banner").hidden = !S.error;
    };
    es.onmessage = ev => {
      try {
        handleStateUpdate(JSON.parse(ev.data));
      } catch {}
    };
    es.onerror = () => {
      sseActive = false;
      es.close();
      $("#banner").hidden = false;
      $("#banner").textContent = "Reconnecting to Agent Deck…";
      setTimeout(connectStream, 2000);
    };
  }

  async function fallbackPoll() {
    if (!sseActive) {
      try {
        const st = await api("/api/state");
        if (st && Array.isArray(st.sessions)) handleStateUpdate(st);
      } catch {
        const b = $("#banner");
        b.hidden = false;
        b.textContent = "Cannot reach Agent Deck server. Check that agent_deck.py is running.";
      }
    }
    setTimeout(fallbackPoll, 1500);
  }

  /* ---------- Actions & Event Handlers ---------- */

  function selectSession(id) {
    if (!id) return;
    const targetSess = S.sessions.find(x => x.id === id);
    if (targetSess && !matchesAgentTab(targetSess, agentFilter)) {
      agentFilter = "both";
      setPref("agentFilter", agentFilter);
    }
    sel = id;
    stick = true;
    if (viewMode === "grid") {
      viewMode = "focus";
      setPref("viewMode", viewMode);
    }
    render();
    syncNeededOutputs();
    $(`.session-row[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" });
  }

  async function sendAction(paneId, body, okMsg) {
    try {
      const r = await api("/api/action", Object.assign({ pane: paneId }, body));
      if (!r.ok) toast(r.error || "Action failed");
      else if (okMsg) toast(okMsg);
      setTimeout(() => fetchPaneOutput(paneId, 900).then(ch => { if (ch) render(); }), 140);
      return r.ok;
    } catch {
      toast("Cannot reach Agent Deck.");
      return false;
    }
  }

  // Topbar filters & view switches
  function setAgentFilter(nextTab) {
    if (!["both", "agy", "claude"].includes(nextTab)) return;
    agentFilter = nextTab;
    setPref("agentFilter", agentFilter);
    if (statusFilter !== "all") {
      const hasStatusMatch = S.sessions.some(
        s => passesBaseToggleFilter(s) && matchesAgentTab(s, agentFilter) && s.status === statusFilter
      );
      if (!hasStatusMatch) statusFilter = "all";
    }
    render();
    syncNeededOutputs();
  }

  $("#agentTabs").addEventListener("click", e => {
    const btn = e.target.closest("button[data-agent-tab]");
    if (!btn) return;
    setAgentFilter(btn.dataset.agentTab);
  });

  $("#emptyShowBothBtn").onclick = () => setAgentFilter("both");

  $("#counts").addEventListener("click", e => {
    const btn = e.target.closest("button[data-filter]");
    if (!btn) return;
    statusFilter = btn.dataset.filter;
    render();
  });

  $("#viewFocusBtn").onclick = () => { viewMode = "focus"; setPref("viewMode", "focus"); render(); syncNeededOutputs(); };
  $("#viewGridBtn").onclick = () => { viewMode = "grid"; setPref("viewMode", "grid"); render(); syncNeededOutputs(); };

  $("#filterInput").addEventListener("input", e => {
    searchFilter = e.target.value;
    render();
  });

  async function openInTerminal(sid) {
    if (sid) {
      await sendAction(sid, { action: "open_terminal" }, "Opened in macOS Terminal");
      return;
    }
    const s = current();
    if (s) {
      await sendAction(s.id, { action: "open_terminal" }, "Opened in macOS Terminal");
      return;
    }
    try {
      const r = await api("/api/action", { action: "open_new_terminal", cwd: S.recent_cwds[0] || "~" });
      toast(r.ok ? "Opened macOS Terminal" : (r.error || "Could not open Terminal"));
    } catch {
      toast("Cannot reach Agent Deck.");
    }
  }

  $("#list").addEventListener("click", e => {
    const viewBtn = e.target.closest("[data-card-view]");
    if (viewBtn) {
      e.stopPropagation();
      const sid = viewBtn.dataset.cardId;
      const desired = viewBtn.dataset.cardView;
      if (desired === "terminal") {
        const nextMode = (sid === sel && (rightTab === "terminal" || rightTab === "split")) ? "browser" : "terminal";
        rightTab = nextMode;
        setPref("rightTab", rightTab);
        selectSession(sid);
      } else {
        rightTab = "browser";
        setPref("rightTab", rightTab);
        selectSession(sid);
      }
      return;
    }
    const openBtn = e.target.closest("button[data-open-term]");
    if (openBtn) {
      e.stopPropagation();
      openInTerminal(openBtn.dataset.openTerm);
      return;
    }
    const toggleBtn = e.target.closest("button[data-toggle-reply]");
    if (toggleBtn) {
      e.stopPropagation();
      const sid = toggleBtn.dataset.toggleReply;
      if (openReplyCards.has(sid)) {
        openReplyCards.delete(sid);
        renderSidebar(visibleSessions());
      } else {
        openReplyCards.add(sid);
        renderSidebar(visibleSessions());
        const inp = $(`input[data-card-reply-input="${CSS.escape(sid)}"]`, $("#list"));
        if (inp) inp.focus();
      }
      return;
    }
    const choiceBtn = e.target.closest("button[data-card-keys]");
    if (choiceBtn) {
      e.stopPropagation();
      const sid = choiceBtn.dataset.cardPane;
      sendAction(sid, { action: "keys", keys: JSON.parse(choiceBtn.dataset.cardKeys) }, `Sent ${choiceBtn.textContent.trim()}`);
      return;
    }
    const adoptCardBtn = e.target.closest("button[data-card-adopt]");
    if (adoptCardBtn) {
      e.stopPropagation();
      adoptSession(adoptCardBtn.dataset.cardAdopt);
      return;
    }
    if (e.target.closest("form[data-card-reply-form]")) {
      e.stopPropagation();
      return;
    }
    const r = e.target.closest(".session-row");
    if (r) selectSession(r.dataset.id);
  });

  $("#list").addEventListener("input", e => {
    const inp = e.target.closest("input[data-card-reply-input]");
    if (inp) cardDrafts[inp.dataset.cardReplyInput] = inp.value;
  });

  $("#list").addEventListener("keydown", e => {
    const inp = e.target.closest("input[data-card-reply-input]");
    if (inp && e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      openReplyCards.delete(inp.dataset.cardReplyInput);
      renderSidebar(visibleSessions());
    }
  });

  $("#list").addEventListener("submit", async e => {
    const form = e.target.closest("form[data-card-reply-form]");
    if (!form) return;
    e.preventDefault();
    e.stopPropagation();
    const sid = form.dataset.cardReplyForm;
    const inp = $(`input[data-card-reply-input="${CSS.escape(sid)}"]`, form);
    const text = inp ? inp.value : "";
    if (!text.trim()) return;
    if (await sendAction(sid, { action: "send", text, enter: true }, "Sent reply")) {
      history.push(text);
      if (history.length > 60) history.shift();
      hIdx = -1;
      cardDrafts[sid] = "";
      if (inp) inp.value = "";
    }
  });

  $("#emptyShowShellsBtn").onclick = () => {
    $("#showShells").checked = true;
    setPref("shells", true);
    render();
  };

  // Terminal scroll & search
  const outEl = $("#out");
  outEl.addEventListener("scroll", () => {
    stick = outEl.scrollHeight - outEl.scrollTop - outEl.clientHeight < 42;
    $("#jump").classList.toggle("show", !stick);
  });
  $("#jump").onclick = () => {
    outEl.scrollTop = outEl.scrollHeight;
    stick = true;
    $("#jump").classList.remove("show");
  };

  $("#termSearch").addEventListener("input", e => {
    termQuery = e.target.value;
    renderTerminalContent();
  });
  $("#ansiToggle").onchange = e => {
    useAnsi = e.target.checked;
    setPref("ansi", useAnsi);
    render();
  };
  $("#wrapToggle").onchange = e => {
    wrapLines = e.target.checked;
    setPref("wrap", wrapLines);
    renderTerminalContent();
  };
  $("#copyOutBtn").onclick = async () => {
    const s = current();
    const plain = s && paneOutputs[s.id]?.plain;
    if (!plain) return toast("Nothing to copy");
    try {
      await navigator.clipboard.writeText(plain);
      toast("Copied clean terminal output");
    } catch {
      toast("Clipboard unavailable");
    }
  };

  // Quick keys, prompt choices, and agy slash commands
  function handleKeyClick(e) {
    const kb = e.target.closest("button[data-keys]");
    if (kb && sel) {
      sendAction(sel, { action: "keys", keys: JSON.parse(kb.dataset.keys) }, `Sent ${kb.textContent.trim()}`);
      return;
    }
    const sb = e.target.closest("button[data-slash]");
    if (sb && sel) {
      const cmdInput = $("#cmd");
      const slash = sb.dataset.slash;
      if (["/compact", "/learn", "/clear", "/cost", "/init", "/review"].includes(slash)) {
        sendAction(sel, { action: "send", text: slash, enter: true }, `Sent ${slash}`);
      } else {
        cmdInput.value = slash + " ";
        cmdInput.focus();
      }
    }
  }
  $("#quick").addEventListener("click", handleKeyClick);
  $("#promptChoices").addEventListener("click", handleKeyClick);
  $("#bReplyQuick").addEventListener("click", handleKeyClick);
  $("#bActionChoices").addEventListener("click", e => {
    if (e.target.closest("button[data-b-open]")) {
      openInTerminal(sel);
      return;
    }
    if (e.target.closest("button[data-b-adopt]")) {
      if (sel) adoptSession(sel);
      return;
    }
    handleKeyClick(e);
  });

  const bReplyInput = $("#bReplyInput");
  $("#bReplyForm").addEventListener("submit", async e => {
    e.preventDefault();
    if (!sel) return;
    const text = bReplyInput.value;
    if (!text.trim()) return;
    if (await sendAction(sel, { action: "send", text, enter: true }, "Sent reply")) {
      history.push(text);
      if (history.length > 60) history.shift();
      hIdx = -1;
      bReplyInput.value = "";
    }
  });
  bReplyInput.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      bReplyInput.blur();
      return;
    }
    if (history.length && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      e.preventDefault();
      hIdx = e.key === "ArrowUp"
        ? (hIdx < 0 ? history.length - 1 : Math.max(0, hIdx - 1))
        : (hIdx < 0 ? -1 : hIdx + 1);
      if (hIdx >= history.length) hIdx = -1;
      bReplyInput.value = hIdx < 0 ? "" : history[hIdx];
    }
  });

  // Composer form (supports multi-line Shift+Enter)
  const cmdEl = $("#cmd");
  function autoSizeCmd() {
    cmdEl.style.height = "auto";
    cmdEl.style.height = Math.min(150, cmdEl.scrollHeight) + "px";
  }
  cmdEl.addEventListener("input", autoSizeCmd);

  async function submitComposer() {
    if (!sel) return;
    const text = cmdEl.value;
    const enter = $("#withEnter").checked;
    if (!text && !enter) return;
    if (await sendAction(sel, { action: "send", text, enter })) {
      if (text.trim()) {
        history.push(text);
        if (history.length > 60) history.shift();
      }
      hIdx = -1;
      cmdEl.value = "";
      autoSizeCmd();
      stick = true;
    }
  }

  $("#cmdForm").addEventListener("submit", e => {
    e.preventDefault();
    submitComposer();
  });

  cmdEl.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      e.target.blur();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitComposer();
      return;
    }
    if (!cmdEl.value.includes("\n") && history.length && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      e.preventDefault();
      hIdx = e.key === "ArrowUp"
        ? (hIdx < 0 ? history.length - 1 : Math.max(0, hIdx - 1))
        : (hIdx < 0 ? -1 : hIdx + 1);
      if (hIdx >= history.length) hIdx = -1;
      cmdEl.value = hIdx < 0 ? "" : history[hIdx];
      autoSizeCmd();
    }
  });

  // Session header controls
  $("#pLabel").addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === "Escape") e.target.blur();
  });
  $("#pLabel").addEventListener("change", async e => {
    const s = current();
    if (!s) return;
    const r = await api("/api/label", { target: s.target, label: e.target.value });
    toast(r.ok ? "Note saved" : (r.error || "Couldn't save note"));
  });

  $("#pinBtn").onclick = async () => {
    const s = current();
    if (!s) return;
    const next = !s.pinned;
    await api("/api/label", { target: s.target, pinned: next });
    s.pinned = next;
    render();
    toast(next ? "Pinned session to top" : "Unpinned session");
  };

  async function adoptSession(sid) {
    try {
      const r = await api("/api/action", { pane: sid, action: "adopt" });
      if (!r.ok) return toast(r.error || "Could not resume in tmux");
      toast(`Started tmux session: ${r.session}`);
      if (r.pane) setTimeout(() => selectSession(r.pane), 260);
    } catch {
      toast("Cannot reach Agent Deck.");
    }
  }

  $("#adoptBtn").onclick = () => { if (sel) adoptSession(sel); };
  $("#adoptBannerBtn").onclick = () => { if (sel) adoptSession(sel); };
  $("#bReplyAdoptBtn").onclick = () => { if (sel) adoptSession(sel); };
  $("#openTermBtn").onclick = () => openInTerminal(sel);
  $("#topOpenTermBtn").onclick = () => openInTerminal(sel);
  $("#adoptFocusBtn").onclick = () => openInTerminal(sel);
  $("#bOpenTermBtn").onclick = () => openInTerminal(sel);
  $("#bEmptyTermBtn").onclick = () => openInTerminal(sel);
  $("#bReplyOpenBtn").onclick = () => openInTerminal(sel);

  // Right panel mode switch (Browser | Terminal | Split)
  function setRightTab(tab) {
    rightTab = ["browser", "terminal", "split"].includes(tab) ? tab : "browser";
    setPref("rightTab", rightTab);
    render();
    syncNeededOutputs();
  }

  $("#detail").addEventListener("click", e => {
    const tabBtn = e.target.closest("button[data-right-tab]");
    if (tabBtn) {
      setRightTab(tabBtn.dataset.rightTab);
      return;
    }
    const pickBtn = e.target.closest("button[data-pick-url]");
    if (pickBtn) {
      saveSessionBrowserUrl(pickBtn.dataset.pickUrl);
    }
  });

  async function saveSessionBrowserUrl(rawInput) {
    const s = current();
    if (!s) return;
    const resolved = rawInput ? resolveUrlInput(rawInput, s) : "";
    // If resolved equals auto_url, clear custom override so it stays dynamically linked
    const toStore = resolved && resolved === s.auto_url ? "" : resolved;
    try {
      const r = await api("/api/label", { target: s.target, browser_url: toStore });
      if (!r.ok) {
        toast(r.error || "Invalid URL");
        return;
      }
      s.custom_url = r.browser_url || "";
      s.browser_url = s.custom_url || s.auto_url || "";
      // Force immediate navigation if user explicitly submitted the same URL
      if (resolved && browserFramePool.has(s.id)) {
        const entry = browserFramePool.get(s.id);
        entry.url = resolved;
        entry.el.src = resolved;
      }
      render();
    } catch {
      toast("Cannot reach Agent Deck.");
    }
  }

  $("#bUrlForm").addEventListener("submit", e => {
    e.preventDefault();
    const val = $("#bUrlInput").value.trim();
    $("#bUrlInput").blur();
    saveSessionBrowserUrl(val);
  });

  $("#bEmptyUrlForm").addEventListener("submit", e => {
    e.preventDefault();
    const val = $("#bEmptyUrlInput").value.trim();
    if (!val) return;
    $("#bEmptyUrlInput").value = "";
    saveSessionBrowserUrl(val);
  });

  $("#bUrlResetBtn").onclick = () => saveSessionBrowserUrl("");

  $("#bPortSelect").addEventListener("change", e => {
    const val = e.target.value;
    if (val) saveSessionBrowserUrl(val);
  });

  $("#bReloadBtn").onclick = () => {
    if (sel) {
      reloadBrowserFrame(sel);
      toast("Reloaded browser view");
    }
  };

  $("#bMobileBtn").onclick = () => {
    mobilePreview = !mobilePreview;
    setPref("mobilePreview", mobilePreview);
    render();
    toast(mobilePreview ? "Mobile viewport (393px)" : "Desktop viewport (100%)");
  };

  $("#bPopOutBtn").onclick = () => {
    const s = current();
    if (s?.browser_url) window.open(s.browser_url, "_blank", "noopener");
  };

  async function toggleManagedDevServer() {
    const s = current();
    if (!s || startingServers.has(s.id)) return;
    if (s.managed_dev) {
      const r = await api("/api/action", { pane: s.id, action: "stop_dev_server" });
      toast(r.ok ? "Stopped dev server" : (r.error || "Could not stop server"));
      return;
    }
    startingServers.add(s.id);
    render();
    try {
      const r = await api("/api/action", { pane: s.id, action: "start_dev_server" });
      startingServers.delete(s.id);
      if (!r.ok) {
        render();
        toast(r.error || "Failed to start dev server");
        return;
      }
      s.dev_port = r.port;
      s.auto_url = r.url;
      s.browser_url = s.custom_url || r.url;
      s.managed_dev = true;
      render();
      toast(`Dev server live at localhost:${r.port}`);
    } catch {
      startingServers.delete(s.id);
      render();
      toast("Cannot reach Agent Deck.");
    }
  }

  $("#bServerBtn").onclick = toggleManagedDevServer;
  $("#bEmptyStartBtn").onclick = toggleManagedDevServer;
  $("#dismissBtn").onclick = () => {
    if (sel) sendAction(sel, { action: "dismiss" }, "Hidden external session");
  };

  $("#ackBtn").onclick = () => {
    if (sel) sendAction(sel, { action: "ack" }, "Marked reviewed");
  };

  $("#respawnBtn").onclick = () => {
    if (sel) sendAction(sel, { action: "respawn" }, "Pane restarted");
  };

  $("#copyAttach").onclick = async () => {
    const s = current();
    if (!s) return;
    const cmd = `tmux attach -t ${s.session}`;
    try {
      await navigator.clipboard.writeText(cmd);
      toast("Copied: " + cmd);
    } catch {
      toast(cmd);
    }
  };

  $("#killBtn").onclick = () => {
    const s = current();
    if (!s) return;
    if (confirm(`Close ${s.session} (${s.window}.${s.pane})? Any running process inside it will terminate.`)) {
      sendAction(s.id, { action: "kill" }, "Session closed");
    }
  };

  // Grid Wall interactions
  $("#gridWall").addEventListener("click", e => {
    const openEl = e.target.closest("button[data-open-term]");
    if (openEl) {
      openInTerminal(openEl.dataset.openTerm);
      return;
    }
    const focusEl = e.target.closest("[data-focus-pane]");
    if (focusEl) {
      selectSession(focusEl.dataset.focusPane);
      return;
    }
    const adoptEl = e.target.closest("button[data-tile-adopt]");
    if (adoptEl) {
      adoptSession(adoptEl.dataset.tileAdopt);
      return;
    }
    const keyBtn = e.target.closest("button[data-tile-keys]");
    if (keyBtn) {
      sendAction(keyBtn.dataset.tilePane, { action: "keys", keys: JSON.parse(keyBtn.dataset.tileKeys) }, "Sent");
    }
  });

  $("#gridWall").addEventListener("submit", async e => {
    const form = e.target.closest("form[data-tile-form]");
    if (!form) return;
    e.preventDefault();
    const paneId = form.dataset.tileForm;
    const inp = $(`input[data-tile-input="${CSS.escape(paneId)}"]`, form);
    const text = inp ? inp.value : "";
    if (!text) return;
    if (await sendAction(paneId, { action: "send", text, enter: true }, "Sent")) {
      inp.value = "";
    }
  });

  // Theme, sound, notifications, shells
  $("#showExternal").onchange = e => {
    setPref("external", e.target.checked);
    render();
  };
  $("#showShells").onchange = e => {
    setPref("shells", e.target.checked);
    render();
  };

  function applyTheme() {
    document.documentElement.setAttribute("data-theme", theme);
    const btn = $("#themeBtn");
    btn.innerHTML = theme === "light" ? ICONS.themeLight : theme === "dark" ? ICONS.themeDark : ICONS.themeSystem;
    btn.title = `Theme: ${theme} (click to cycle)`;
  }
  $("#themeBtn").onclick = () => {
    theme = theme === "system" ? "dark" : theme === "dark" ? "light" : "system";
    setPref("theme", theme);
    applyTheme();
    toast(`Theme: ${theme}`);
  };
  applyTheme();

  function paintSound() {
    const b = $("#soundBtn");
    b.innerHTML = sound ? ICONS.soundOn : ICONS.soundOff;
    b.title = sound ? "Sound alerts on" : "Sound alerts muted";
  }
  $("#soundBtn").onclick = () => {
    sound = !sound;
    setPref("sound", sound);
    paintSound();
    if (sound) beep("done");
  };
  paintSound();

  function paintNotify() {
    const b = $("#notifyBtn");
    if (!("Notification" in window)) { b.hidden = true; return; }
    b.hidden = Notification.permission === "granted";
    b.textContent = Notification.permission === "denied" ? "Browser alerts blocked" : "Enable alerts";
  }
  $("#notifyBtn").onclick = async () => {
    try { await Notification.requestPermission(); } catch {}
    paintNotify();
  };
  paintNotify();

  /* ---------- New Session Dialog & agy Command Builder ---------- */

  const dlg = $("#newDlg");

  function syncPresetCommand() {
    if (activePreset === "agy") {
      const parts = ["agy"];
      const mode = $("#agyMode").value;
      const effort = $("#agyEffort").value;
      if (mode) parts.push(`--mode ${mode}`);
      if (effort) parts.push(`--effort ${effort}`);
      if ($("#agyContinue").checked) parts.push("--continue");
      if ($("#agySandbox").checked) parts.push("--sandbox");
      $("#nCmd").value = parts.join(" ");
    } else if (activePreset === "claude") {
      const parts = ["claude"];
      const pmode = $("#claudePermMode").value;
      if (pmode === "skip") parts.push("--dangerously-skip-permissions");
      else if (pmode) parts.push(`--permission-mode ${pmode}`);
      if ($("#claudeContinue").checked) parts.push("--continue");
      $("#nCmd").value = parts.join(" ");
    }
  }

  function applyPresetTab(preset) {
    activePreset = preset;
    $$(".preset-tab").forEach(t => t.classList.toggle("active", t.dataset.preset === preset));
    $("#agyBuilder").hidden = preset !== "agy";
    $("#claudeBuilder").hidden = preset !== "claude";
    if (preset === "custom") $("#nCmd").value = "";
    else syncPresetCommand();
  }

  $$(".preset-tab").forEach(tab => {
    tab.onclick = () => applyPresetTab(tab.dataset.preset);
  });

  ["#agyMode", "#agyEffort", "#agyContinue", "#agySandbox", "#claudePermMode", "#claudeContinue"].forEach(selStr => {
    $(selStr).addEventListener("change", syncPresetCommand);
  });

  function openNewDialog() {
    $("#nErr").textContent = "";
    if (agentFilter === "claude" && activePreset !== "claude") applyPresetTab("claude");
    else if (agentFilter === "agy" && activePreset !== "agy") applyPresetTab("agy");
    const s = current();
    if (!$("#nCwd").value) {
      $("#nCwd").value = s ? shortPath(s.cwd) : (S.recent_cwds[0] ? shortPath(S.recent_cwds[0]) : "~");
    }
    $("#cwdChips").innerHTML = (S.recent_cwds || [])
      .slice(0, 5)
      .map(p => `<button type="button" class="cwd-chip" data-cwd="${esc(shortPath(p))}">${esc(shortPath(p))}</button>`)
      .join("");
    dlg.showModal();
    $("#nName").focus();
  }

  $("#cwdChips").addEventListener("click", e => {
    const chip = e.target.closest("button[data-cwd]");
    if (chip) $("#nCwd").value = chip.dataset.cwd;
  });

  $("#newBtn").onclick = openNewDialog;
  $("#emptyNewBtn").onclick = openNewDialog;
  $("#nCancel").onclick = () => dlg.close();
  $("#nCloseX").onclick = () => dlg.close();

  $("#newForm").addEventListener("submit", async e => {
    e.preventDefault();
    const r = await api("/api/new", {
      name: $("#nName").value.trim(),
      cwd: $("#nCwd").value.trim(),
      command: $("#nCmd").value.trim(),
      prompt: $("#nPrompt").value.trim(),
      label: $("#nLabel").value.trim(),
    });
    if (!r.ok) {
      $("#nErr").textContent = r.error || "Could not start session.";
      return;
    }
    dlg.close();
    $("#nName").value = "";
    $("#nPrompt").value = "";
    $("#nLabel").value = "";
    toast("Session started");
    setTimeout(() => selectSession(r.pane), 260);
  });

  /* ---------- Global Keyboard Shortcuts ---------- */

  document.addEventListener("keydown", e => {
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || dlg.open || e.metaKey || e.ctrlKey || e.altKey) {
      return;
    }
    const list = visibleSessions();
    const idx = list.findIndex(s => s.id === sel);

    if (e.key === "ArrowDown" || e.key === "j") {
      e.preventDefault();
      if (list[idx + 1]) selectSession(list[idx + 1].id);
    } else if (e.key === "ArrowUp" || e.key === "k") {
      e.preventDefault();
      if (idx > 0) selectSession(list[idx - 1].id);
    } else if (/^[1-9]$/.test(e.key)) {
      const target = list[Number(e.key) - 1];
      if (target) selectSession(target.id);
    } else if (e.key === "i") {
      const s = current();
      if (viewMode === "focus" && s) {
        e.preventDefault();
        if (rightTab === "browser") {
          if (canSessionSend(s)) $("#bReplyInput").focus();
          else $("#bUrlInput").focus();
        } else {
          cmdEl.focus();
        }
      }
    } else if (e.key === "/") {
      if (viewMode === "focus" && current()) {
        e.preventDefault();
        if (rightTab === "browser") {
          $("#bUrlInput").focus();
          $("#bUrlInput").select();
        } else {
          $("#termSearch").focus();
        }
      }
    } else if (e.key === "b") {
      if (viewMode === "focus" && current()) {
        e.preventDefault();
        setRightTab(rightTab === "terminal" ? "browser" : "terminal");
      }
    } else if (e.key === "t") {
      if (viewMode === "focus" && current()) {
        e.preventDefault();
        setRightTab(rightTab === "split" ? "browser" : "split");
      }
    } else if (e.key === "r") {
      if (viewMode === "focus" && rightTab !== "terminal" && sel && current()?.browser_url) {
        e.preventDefault();
        reloadBrowserFrame(sel);
        toast("Reloaded browser view");
      }
    } else if (e.key === "v") {
      e.preventDefault();
      viewMode = viewMode === "focus" ? "grid" : "focus";
      setPref("viewMode", viewMode);
      render();
      syncNeededOutputs();
    } else if (e.key === "n") {
      e.preventDefault();
      openNewDialog();
    }
  });

  connectStream();
  fallbackPoll();
})();
