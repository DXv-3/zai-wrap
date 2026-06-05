/**
 * Build Watch Hub — preview-first, hardened client
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const PREVIEWABLE = /\.(html?|htm|tsx?|jsx?|vue|svg)$/i;
  const POLL_FAST_MS = 1000;
  const POLL_SLOW_MS = 5000;

  let state = null;
  let settings = {};
  let mode = "preview";
  let termMode = "mirror";
  let pollTimer = null;
  let pollMs = POLL_FAST_MS;
  let primarySet = false;
  let userPreviewLocked = false;
  let currentPath = "";
  let buildDirty = false;
  let lastPreviewBase = "";
  let lastFeedSig = "";
  let lastRailSig = "";
  let lastGrokSig = "";
  let tickInFlight = false;
  let tickAbort = null;
  let fileAbort = null;
  let toastTimer = null;
  let grokActsCache = [];

  function toast(msg, kind = "info", ms = 3200) {
    const el = $("toast");
    if (!el) return;
    el.textContent = msg;
    el.className = "toast show " + kind;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.classList.remove("show");
      el.hidden = true;
    }, ms);
  }

  async function api(path, opts = {}) {
    const ctrl = opts.signal ? null : new AbortController();
    const signal = opts.signal || ctrl?.signal;
    const r = await fetch(path, { ...opts, signal });
    if (!r.ok && opts.expectOk !== false) {
      let detail = "";
      try {
        const j = await r.clone().json();
        detail = j.error || j.detail || "";
      } catch {
        /* ignore */
      }
      throw new Error(detail || String(r.status));
    }
    return r.json().catch(() => ({}));
  }

  function relPath(path) {
    if (!path || !state?.project) return (path || "").replace(/^\//, "");
    const root = state.project;
    return path.startsWith(root) ? path.slice(root.length).replace(/^\//, "") : path.replace(/^\//, "");
  }

  function normalizePreviewInput(raw) {
    const u = (raw || "").trim();
    if (!u) return "";
    if (/^https?:\/\//i.test(u)) {
      try {
        const parsed = new URL(u);
        if (!["http:", "https:"].includes(parsed.protocol)) return "";
        if (parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost") return u;
        return u;
      } catch {
        return "";
      }
    }
    if (u.startsWith("/api/")) return u;
    const clean = u.replace(/^\//, "").replace(/\\/g, "/");
    if (!clean || clean.includes("..")) return "";
    return "/api/raw?path=" + encodeURIComponent(clean);
  }

  function previewOrigin(url) {
    if (!url) return "";
    if (url.startsWith("http")) return url.split("?")[0];
    const full = url.startsWith("/") ? location.origin + url : location.origin + "/" + url;
    return full.split("?")[0];
  }

  function setMode(m) {
    if (m !== mode && buildDirty && mode === "build") {
      if (!confirm("Discard unsaved edits?")) return false;
      buildDirty = false;
    }
    mode = m;
    document.querySelectorAll(".canvas-tabs .tab").forEach((b) => {
      const on = b.dataset.mode === m;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    ["preview", "code", "build"].forEach((name) => {
      const pane = $("pane" + name.charAt(0).toUpperCase() + name.slice(1));
      const on = name === m;
      pane.classList.toggle("active", on);
      pane.hidden = !on;
    });
    if (m === "build" && $("buildPath").value.trim()) refreshBuildPreview();
    return true;
  }

  function syncPreview(force, { switchTab = false } = {}) {
    const raw = $("previewUrl").value.trim() || (!userPreviewLocked ? state?.primary_preview : "") || "";
    const url = normalizePreviewInput(raw) || raw;
    if (!url || (!url.startsWith("http") && !url.startsWith("/"))) {
      $("previewEmpty").hidden = false;
      $("previewLoading").hidden = true;
      $("previewFrame").removeAttribute("src");
      lastPreviewBase = "";
      return;
    }
    const base = previewOrigin(url);
    if (!force && base === lastPreviewBase && $("previewFrame").getAttribute("src")) return;

    lastPreviewBase = base;
    if (!userPreviewLocked || force) {
      $("previewUrl").value = raw || url;
    }
    $("previewEmpty").hidden = true;
    $("previewLoading").hidden = false;

    const full = url.startsWith("http") ? url : location.origin + (url.startsWith("/") ? url : "/" + url);
    const sep = full.includes("?") ? "&" : "?";
    $("previewFrame").onload = () => {
      $("previewLoading").hidden = true;
    };
    $("previewFrame").onerror = () => {
      $("previewLoading").hidden = true;
      toast("Preview failed to load", "error");
    };
    $("previewFrame").src = full + sep + "_bw=" + Date.now();
    if (switchTab) setMode("preview");
  }

  function openPreview(url, path, type) {
    if (!url && path) {
      const rel = relPath(path);
      if (/\.md$/i.test(rel)) {
        openFile(rel, "code");
        return;
      }
      if (PREVIEWABLE.test(rel)) {
        url = "/api/raw?path=" + encodeURIComponent(rel);
      } else {
        openFile(rel, "code");
        return;
      }
    }
    if (url) {
      userPreviewLocked = true;
      $("previewUrl").value = url.startsWith("http") ? url : url;
      if (path) currentPath = relPath(path);
      syncPreview(true, { switchTab: true });
      highlightRail(url, path);
    }
    if (type === "code" && path) openFile(relPath(path), "code");
  }

  function highlightRail(url, path) {
    const rp = path ? relPath(path) : "";
    document.querySelectorAll(".rail-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.url === url || relPath(el.dataset.path || "") === rp);
    });
  }

  async function openFile(path, targetMode) {
    const rel = relPath(path);
    if (!rel) return;
    if (fileAbort) fileAbort.abort();
    fileAbort = new AbortController();
    $("codePathLabel").textContent = "Loading…";
    try {
      const d = await api("/api/file?path=" + encodeURIComponent(rel), { signal: fileAbort.signal });
      if (d.error) throw new Error(d.error);
      currentPath = rel;
      const text = d.content ?? "";
      $("codePathLabel").textContent = rel;
      $("codeView").textContent = text;
      $("buildPath").value = rel;
      $("buildEditor").value = text;
      buildDirty = false;
      setMode(targetMode || "code");
      if (PREVIEWABLE.test(rel)) refreshBuildPreview();
    } catch (err) {
      if (err.name === "AbortError") return;
      $("codePathLabel").textContent = "Error";
      toast("Could not open file: " + (err.message || rel), "error");
    }
  }

  function refreshBuildPreview() {
    const path = $("buildPath").value.trim();
    if (!path || !PREVIEWABLE.test(path)) return;
    const url = location.origin + "/api/raw?path=" + encodeURIComponent(relPath(path)) + "&_bw=" + Date.now();
    $("buildFrame").src = url;
  }

  async function saveBuild() {
    const path = $("buildPath").value.trim();
    if (!path) {
      toast("Enter a file path to save", "warn");
      return;
    }
    const btn = $("btnBuildSave");
    btn.disabled = true;
    try {
      const r = await fetch("/api/file/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: relPath(path), content: $("buildEditor").value }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.error || String(r.status));
      buildDirty = false;
      currentPath = d.path || relPath(path);
      $("codeView").textContent = $("buildEditor").value;
      refreshBuildPreview();
      if (PREVIEWABLE.test(currentPath)) {
        $("previewUrl").value = "/api/raw?path=" + encodeURIComponent(currentPath);
        syncPreview(true, { switchTab: false });
      }
      toast("Saved " + currentPath, "ok");
    } catch (err) {
      toast("Save failed: " + (err.message || "error"), "error");
    } finally {
      btn.disabled = false;
    }
  }

  function feedSignature(events, grokActs) {
    const g = grokActs || [];
    const last = g[g.length - 1];
    return [(events || []).length, g.length, last?.path, last?.status, last?.ts].join("|");
  }

  function renderFeed(events, grokActs) {
    grokActsCache = grokActs || [];
    const sig = feedSignature(events, grokActs);
    if (sig === lastFeedSig) return;
    lastFeedSig = sig;

    const merged = [];
    grokActsCache.forEach((a, i) => merged.push({ grok: true, idx: i, ...a }));
    (events || []).forEach((e) => merged.push({ grok: false, ...e }));
    merged.sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));

    const el = $("feedList");
    const scrollTop = el.scrollTop;
    if (!merged.length) {
      el.innerHTML = '<p class="empty">Run Grok Build — edits appear here and refresh preview.</p>';
      return;
    }

    el.innerHTML = merged
      .slice(0, 60)
      .map((item) => {
        if (item.grok) {
          const running = item.status === "running" ? " running" : "";
          const body =
            item.type === "shell"
              ? esc(item.command || "") + (item.output ? "\n" + esc(String(item.output).slice(0, 400)) : "")
              : esc(item.text || item.command || "");
          const rp = item.path ? relPath(item.path) : "";
          const file = rp
            ? `<div class="file-link" data-path="${esc(rp)}">${esc(rp)}</div>`
            : "";
          return `<article class="bubble grok${running}" data-grok-idx="${item.idx}">
            <div class="meta">Grok · ${esc(item.title || item.type || "edit")} · ${esc(item.status || "")}</div>
            ${body}${file}</article>`;
        }
        const time = (item.ts || "").slice(11, 19);
        const files = (item.files || [])
          .map((f) => `<div class="file-link" data-path="${esc(relPath(f))}">${esc(relPath(f))}</div>`)
          .join("");
        return `<article class="bubble">
          <div class="meta">${esc(item.kind || "event")} · ${esc(time)}</div>
          ${esc(item.msg || "")}${files}</article>`;
      })
      .join("");
    el.scrollTop = Math.min(scrollTop, el.scrollHeight);
  }

  function onFeedClick(ev) {
    const link = ev.target.closest(".file-link");
    if (link) {
      ev.stopPropagation();
      openPathFromStream(link.dataset.path);
      return;
    }
    const bubble = ev.target.closest("[data-grok-idx]");
    if (bubble) {
      const act = grokActsCache[Number(bubble.dataset.grokIdx)];
      if (!act) return;
      if (act.path) openPathFromStream(relPath(act.path), act);
      else if (act.code || act.output) {
        currentPath = "";
        $("buildEditor").value = act.code || act.output || "";
        buildDirty = true;
        setMode("build");
      }
    }
  }

  function openPathFromStream(p, act) {
    if (!p) return;
    if (PREVIEWABLE.test(p)) {
      openPreview("/api/raw?path=" + encodeURIComponent(p), p, "html");
    } else {
      openFile(p, act?.code || act?.output ? "build" : "code");
    }
  }

  function railSignature(previews) {
    return (previews || []).map((p) => p.url + ":" + p.path).join("|");
  }

  function renderRail(previews) {
    const sig = railSignature(previews);
    if (sig === lastRailSig) return;
    lastRailSig = sig;

    const list = $("filesList");
    const items = previews || [];
    if (!items.length) {
      list.innerHTML = '<p class="empty">No previews yet</p>';
      return;
    }
    list.innerHTML = items
      .map((p) => {
        const tag = p.type === "server" ? '<span class="tag live">live</span>' : '<span class="tag">file</span>';
        return `<div class="rail-item" data-url="${esc(p.url || "")}" data-path="${esc(p.path || "")}" data-type="${esc(p.type || "")}">
          ${tag}<strong>${esc(p.label || "Preview")}</strong>
          <span>${esc(p.path || p.url || "")}</span></div>`;
      })
      .join("");
  }

  function onRailClick(ev) {
    const item = ev.target.closest(".rail-item");
    if (!item) return;
    openPreview(item.dataset.url, item.dataset.path, item.dataset.type);
  }

  async function refreshMirror() {
    const pin = $("termPick")?.value;
    const q = pin ? "?pin=" + encodeURIComponent(pin) : "";
    try {
      const d = await api("/api/terminal/mirror" + q, { expectOk: false });
      $("termOutput").textContent =
        (d.command ? "$ " + d.command + "\n\n" : "") + (d.output_tail || d.error || "Waiting for Grok terminal…");
    } catch {
      /* keep last output */
    }
  }

  async function loadTermList() {
    try {
      const d = await api("/api/terminal/list");
      const sel = $("termPick");
      const prev = sel.value;
      sel.innerHTML = (d.terminals || [])
        .map((t) => `<option value="${esc(t.path)}">${esc(t.name)}</option>`)
        .join("");
      if (prev) sel.value = prev;
    } catch {
      /* ignore */
    }
  }

  function setTermMode(m) {
    termMode = m;
    const mirror = m === "mirror";
    $("btnMirror").classList.toggle("active", mirror);
    $("btnShell").classList.toggle("active", !mirror);
    $("termInput").disabled = mirror;
    if (mirror) refreshMirror();
  }

  function maybeAutoPreview(grokActs) {
    const sig = (grokActs || []).length + ":" + ((grokActs || []).slice(-1)[0]?.path || "");
    if (sig === lastGrokSig) return;
    lastGrokSig = sig;

    if (mode !== "preview" || userPreviewLocked) return;
    const latest = [...(grokActs || [])].reverse().find((a) => a.path && /\.html?$/i.test(a.path));
    if (!latest?.path) return;
    const p = relPath(latest.path);
    const url = "/api/raw?path=" + encodeURIComponent(p);
    if (previewOrigin($("previewUrl").value) !== previewOrigin(url)) {
      $("previewUrl").value = url;
      syncPreview(true);
    }
  }

  async function tick() {
    if (tickInFlight) return;
    tickInFlight = true;
    if (tickAbort) tickAbort.abort();
    tickAbort = new AbortController();
    try {
      state = await api("/api/canvas", { signal: tickAbort.signal });
      const pill = $("livePill");
      pill.classList.add("ok");
      pill.innerHTML = '<span class="dot"></span> Live';

      const name = state.project_name || "—";
      $("projectName").textContent = name;
      $("projectName").title = state.project || name;

      const g = state.grok || {};
      $("grokPill").hidden = !g.connected;
      if (g.connected) $("grokPill").textContent = "Grok · " + (g.session_id || "").slice(0, 8);

      const btn = $("btnConnect");
      btn.disabled = !!g.connected;
      btn.textContent = g.connected ? "Connected" : "Connect Grok";

      renderFeed(state.events, state.grok_activity);
      renderRail(state.previews);
      maybeAutoPreview(state.grok_activity);

      if (!primarySet) {
        primarySet = true;
        if (state.primary_preview) {
          const p = (state.previews || []).find((x) => x.url === state.primary_preview) || state.previews?.[0];
          if (p) openPreview(p.url, p.path, p.type);
          else {
            $("previewUrl").value = state.primary_preview;
            syncPreview(true, { switchTab: true });
          }
        }
      } else if (!userPreviewLocked && mode === "preview" && state.primary_preview) {
        const cur = normalizePreviewInput($("previewUrl").value) || $("previewUrl").value.trim();
        if (!cur || cur === state.primary_preview) {
          $("previewUrl").value = state.primary_preview;
          syncPreview(false);
        }
      }

      if (mode === "build" && !buildDirty) {
        const edit = [...(state.grok_activity || [])].reverse().find((a) => a.path && (a.code || a.output));
        if (edit?.path) {
          const p = relPath(edit.path);
          if (p && p !== $("buildPath").value.trim()) openFile(p, "build");
        }
      }

      if (termMode === "mirror" && state.terminals?.length && !$("terminalDock").classList.contains("collapsed")) {
        const t = state.terminals.find((x) => x.running) || state.terminals[0];
        if (t) {
          $("termOutput").textContent = (t.command ? "$ " + t.command + "\n\n" : "") + (t.output_tail || "");
        }
      }
    } catch (err) {
      if (err.name === "AbortError") return;
      const pill = $("livePill");
      pill.classList.remove("ok");
      pill.textContent = "Offline";
    } finally {
      tickInFlight = false;
    }
  }

  function schedulePoll() {
    clearInterval(pollTimer);
    pollTimer = setInterval(tick, pollMs);
  }

  async function connectGrok() {
    const btn = $("btnConnect");
    btn.disabled = true;
    btn.textContent = "Connecting…";
    try {
      const r = await fetch("/api/grok/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.ok === false) throw new Error(d.error || d.detail || String(r.status));
      userPreviewLocked = false;
      primarySet = false;
      await tick();
      toast("Grok session linked", "ok");
    } catch (err) {
      toast("Connect failed: " + (err.message || "error"), "error");
    } finally {
      btn.disabled = !!state?.grok?.connected;
      btn.textContent = state?.grok?.connected ? "Connected" : "Connect Grok";
    }
  }

  function init() {
    document.querySelectorAll(".canvas-tabs .tab").forEach((b) => {
      b.addEventListener("click", () => setMode(b.dataset.mode));
    });

    $("feedList").addEventListener("click", onFeedClick);
    $("filesList").addEventListener("click", onRailClick);

    $("btnConnect").addEventListener("click", connectGrok);

    $("previewUrl").addEventListener("input", () => {
      userPreviewLocked = true;
    });
    $("previewUrl").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const u = normalizePreviewInput($("previewUrl").value);
        if (!u) {
          toast("Invalid preview URL or path", "warn");
          return;
        }
        userPreviewLocked = true;
        syncPreview(true, { switchTab: true });
      }
    });

    $("btnPreviewGo").addEventListener("click", () => {
      const u = normalizePreviewInput($("previewUrl").value);
      if (!u) {
        toast("Invalid preview URL or path", "warn");
        return;
      }
      userPreviewLocked = true;
      if (u.startsWith("http")) openPreview(u, null, "server");
      else openPreview(u, null, "html");
    });
    $("btnPreviewRefresh").addEventListener("click", () => syncPreview(true, { switchTab: false }));

    $("btnCodeToPreview").addEventListener("click", () => {
      if (!currentPath) {
        toast("No file open", "warn");
        return;
      }
      openPreview("/api/raw?path=" + encodeURIComponent(currentPath), currentPath, "html");
    });

    $("btnBuildSave").addEventListener("click", saveBuild);
    $("btnBuildReload").addEventListener("click", () => openFile($("buildPath").value.trim(), "build"));
    $("buildEditor").addEventListener("input", () => {
      buildDirty = true;
      clearTimeout(window._buildPreviewTimer);
      window._buildPreviewTimer = setTimeout(refreshBuildPreview, 700);
    });

    $("btnMirror").addEventListener("click", () => setTermMode("mirror"));
    $("btnShell").addEventListener("click", async () => {
      setTermMode("shell");
      try {
        const r = await fetch("/api/terminal/pty/start", { method: "POST" });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.error || String(r.status));
        toast("Shell ready", "ok");
      } catch (err) {
        toast("Shell failed: " + err.message, "error");
        setTermMode("mirror");
      }
    });

    $("termPick")?.addEventListener("change", refreshMirror);
    $("termInput").addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || termMode !== "shell") return;
      const line = $("termInput").value;
      $("termInput").value = "";
      try {
        await fetch("/api/terminal/pty/input", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data: line + "\n" }),
        });
        setTimeout(async () => {
          const d = await api("/api/terminal/pty/poll");
          if (d.output) $("termOutput").textContent += d.output;
        }, 80);
      } catch {
        toast("Shell input failed", "error");
      }
    });

    $("btnTermToggle").addEventListener("click", () => {
      const dock = $("terminalDock");
      const collapsed = dock.classList.toggle("collapsed");
      $("btnTermToggle").setAttribute("aria-expanded", String(!collapsed));
    });

    $("autoSync").addEventListener("change", (e) => {
      pollMs = e.target.checked ? POLL_FAST_MS : POLL_SLOW_MS * 0.6;
      schedulePoll();
    });

    document.addEventListener("visibilitychange", () => {
      pollMs = document.hidden ? POLL_SLOW_MS : $("autoSync").checked ? POLL_FAST_MS : POLL_SLOW_MS * 0.6;
      schedulePoll();
      if (!document.hidden) tick();
    });

    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "r") {
        e.preventDefault();
        syncPreview(true, { switchTab: mode === "preview" });
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "s" && mode === "build") {
        e.preventDefault();
        saveBuild();
      }
    });

    fetch("/api/grok/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }).catch(() => {});

    fetch("/api/settings")
      .then((r) => r.json())
      .then((s) => {
        settings = s;
      })
      .catch(() => {});

    setMode("preview");
    tick();
    schedulePoll();
    loadTermList();
    setInterval(loadTermList, 15000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();