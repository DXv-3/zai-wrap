/**
 * Build Watch — simple “watch your app” UI
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
  const GUIDE_KEY = "bw_guide_dismissed";
  const POLL_MS = 1200;

  let state = null;
  let pollTimer = null;
  let tickInFlight = false;
  let tickAbort = null;
  let lastFeedSig = "";
  let lastRailSig = "";
  let lastPreviewBase = "";
  let primarySet = false;
  let userPreviewLocked = false;
  let currentPath = "";
  let fileEditMode = false;
  let grokActsCache = [];
  let toastTimer = null;

  function toast(msg, kind = "info") {
    const el = $("toast");
    el.textContent = msg;
    el.className = "toast show " + (kind || "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.classList.remove("show");
      el.hidden = true;
    }, 3500);
  }

  async function api(path, opts = {}) {
    const r = await fetch(path, { ...opts, signal: opts.signal });
    if (!r.ok && opts.expectOk !== false) {
      let detail = "";
      try {
        const j = await r.clone().json();
        detail = j.error || "";
      } catch {
        /* */
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

  function isSelfUrl(url) {
    if (!url) return true;
    try {
      const u = new URL(url.startsWith("http") ? url : location.origin + url);
      return u.port === location.port && (u.hostname === "127.0.0.1" || u.hostname === "localhost");
    } catch {
      return url.includes("/canvas") || url === "/" || url.endsWith(":8790");
    }
  }

  function normalizePreviewInput(raw) {
    const u = (raw || "").trim();
    if (!u) return "";
    if (/^https?:\/\//i.test(u)) {
      try {
        const p = new URL(u);
        if (!["http:", "https:"].includes(p.protocol)) return "";
        if (isSelfUrl(u)) return "";
        return u;
      } catch {
        return "";
      }
    }
    const clean = u.replace(/^\//, "").replace(/\\/g, "/");
    if (!clean || clean.includes("..")) return "";
    return "/api/raw?path=" + encodeURIComponent(clean);
  }

  function updateStatusLine() {
    const el = $("statusLine");
    const g = state?.grok || {};
    const hasPreview = !!lastPreviewBase && $("previewFrame").getAttribute("src");

    if (!state) {
      el.textContent = "Connecting to Build Watch…";
      el.className = "status-line";
      return;
    }
    if (!g.connected) {
      el.textContent =
        "Not linked yet → Open Grok Build in another window, then click Link Grok (top right).";
      el.className = "status-line warn";
      return;
    }
    if (!hasPreview) {
      const proj = state.project_name || "your project";
      el.textContent =
        `Grok is linked ✓ No app preview yet — in Grok run npm run dev for ${proj}, or click Open a file. (Start Build Watch from your project folder: cd ${proj} && build-watch on)`;
      el.className = "status-line warn";
      return;
    }
    el.textContent = `Watching your app · Grok linked · project ${state.project_name || ""}`;
    el.className = "status-line ok";
  }

  function updateGuide() {
    const dismissed = localStorage.getItem(GUIDE_KEY) === "1";
    const g = state?.grok || {};
    const hasPreview = !!lastPreviewBase;
    $("step1")?.classList.add("done");
    $("step2")?.classList.toggle("done", !!g.connected);
    $("step3")?.classList.toggle("done", hasPreview);
    const guide = $("guide");
    if (dismissed || hasPreview) {
      guide.hidden = true;
    } else {
      guide.hidden = false;
    }
  }

  function syncPreview(force) {
    const raw = $("previewUrl").value.trim() || (!userPreviewLocked ? state?.primary_preview : "") || "";
    const url = normalizePreviewInput(raw) || (raw.startsWith("http") ? raw : "");
    if (!url || isSelfUrl(url)) {
      $("previewLoading").hidden = true;
      $("previewFrame").removeAttribute("src");
      lastPreviewBase = "";
      updateStatusLine();
      updateGuide();
      return;
    }
    const base = url.split("?")[0];
    if (!force && base === lastPreviewBase && $("previewFrame").getAttribute("src")) {
      updateStatusLine();
      return;
    }
    lastPreviewBase = base;
    $("previewLoading").hidden = false;
    const full = url.startsWith("http") ? url : location.origin + (url.startsWith("/") ? url : "/" + url);
    $("previewFrame").onload = () => {
      $("previewLoading").hidden = true;
      $("guide").hidden = true;
      localStorage.setItem(GUIDE_KEY, "1");
      updateStatusLine();
      updateGuide();
    };
    $("previewFrame").src = full + (full.includes("?") ? "&" : "?") + "_bw=" + Date.now();
    updateStatusLine();
    updateGuide();
  }

  function openPreview(url, path) {
    if (path && /\.md$/i.test(path)) {
      openFileDialog(relPath(path), false);
      return;
    }
    if (!url && path) {
      url = "/api/raw?path=" + encodeURIComponent(relPath(path));
    }
    if (!url || isSelfUrl(url)) {
      toast("That URL is this dashboard — pick your app’s dev server or an HTML file", "warn");
      return;
    }
    userPreviewLocked = true;
    $("previewUrl").value = url.startsWith("http") ? url : url;
    if (path) currentPath = relPath(path);
    syncPreview(true);
    document.querySelectorAll(".file-row").forEach((el) => {
      el.classList.toggle("active", relPath(el.dataset.path || "") === currentPath);
    });
  }

  function renderFeed(events, grokActs) {
    grokActsCache = grokActs || [];
    const sig = [(events || []).length, grokActsCache.length, grokActsCache.at(-1)?.path].join("|");
    if (sig === lastFeedSig) return;
    lastFeedSig = sig;

    const merged = [];
    grokActsCache.forEach((a, i) => merged.push({ grok: true, idx: i, ...a }));
    (events || []).forEach((e) => merged.push({ grok: false, ...e }));
    merged.sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));

    const el = $("feedList");
    if (!merged.length) {
      el.innerHTML =
        '<p class="empty">Nothing yet. After you link Grok and it edits files, steps show up here.</p>';
      return;
    }
    el.innerHTML = merged
      .slice(0, 50)
      .map((item) => {
        if (item.grok) {
          const rp = item.path ? relPath(item.path) : "";
          const file = rp ? `<div class="file-link" data-path="${esc(rp)}">Open ${esc(rp)}</div>` : "";
          const body =
            item.type === "shell"
              ? esc(item.command || "")
              : esc(item.title || item.text || "Edit");
          return `<article class="bubble grok" data-idx="${item.idx}">
            <div class="meta">Grok · ${esc(item.status || "update")}</div>${body}${file}</article>`;
        }
        return `<article class="bubble">
          <div class="meta">${esc(item.kind || "note")}</div>${esc(item.msg || "")}</article>`;
      })
      .join("");
  }

  function renderFiles(previews) {
    const sig = (previews || []).map((p) => p.url + p.path).join("|");
    if (sig === lastRailSig) return;
    lastRailSig = sig;

    const el = $("filesList");
    const items = (previews || []).filter((p) => !isSelfUrl(p.url));
    if (!items.length) {
      el.innerHTML =
        '<p class="empty">No HTML or dev server found yet. Tell Grok: “run npm run dev” or create an index.html.</p>';
      return;
    }
    el.innerHTML = items
      .map((p) => {
        const tag = p.type === "server" ? '<span class="tag live">dev server</span>' : '<span class="tag">file</span>';
        const hint = p.type === "server" ? "Opens your running app" : "Opens in preview";
        return `<div class="file-row" data-url="${esc(p.url || "")}" data-path="${esc(p.path || "")}" data-type="${esc(p.type || "")}">
          ${tag}<strong>${esc(p.label || "Open")}</strong>
          <span>${esc(hint)} · ${esc(p.path || p.url || "")}</span></div>`;
      })
      .join("");
  }

  async function openFileDialog(path, editable) {
    if (!path) return;
    currentPath = path;
    fileEditMode = editable;
    $("fileDialogTitle").textContent = path;
    $("fileDialogBody").textContent = "Loading…";
    $("btnFileSave").hidden = !editable;
    $("fileDialog").showModal();
    try {
      const d = await api("/api/file?path=" + encodeURIComponent(path));
      $("fileDialogBody").textContent = d.content ?? "";
    } catch (err) {
      $("fileDialogBody").textContent = "Could not load: " + err.message;
    }
  }

  async function saveFileDialog() {
    if (!currentPath) return;
    try {
      const r = await fetch("/api/file/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: currentPath, content: $("fileDialogBody").textContent }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) throw new Error(d.error || r.status);
      toast("Saved " + currentPath, "ok");
      if (PREVIEWABLE.test(currentPath)) {
        $("previewUrl").value = "/api/raw?path=" + encodeURIComponent(currentPath);
        syncPreview(true);
      }
      $("fileDialog").close();
    } catch (err) {
      toast("Save failed: " + err.message, "error");
    }
  }

  function togglePanel(name) {
    const act = name === "activity";
    const panel = act ? $("panelActivity") : $("panelFiles");
    const btn = act ? $("btnActivity") : $("btnFiles");
    const open = panel.hidden;
    $("panelActivity").hidden = true;
    $("panelFiles").hidden = true;
    $("btnActivity").classList.remove("active");
    $("btnFiles").classList.remove("active");
    $("btnActivity").setAttribute("aria-expanded", "false");
    $("btnFiles").setAttribute("aria-expanded", "false");
    if (open) {
      panel.hidden = false;
      btn.classList.add("active");
      btn.setAttribute("aria-expanded", "true");
    }
  }

  async function tick() {
    if (tickInFlight) return;
    tickInFlight = true;
    if (tickAbort) tickAbort.abort();
    tickAbort = new AbortController();
    try {
      state = await api("/api/canvas", { signal: tickAbort.signal });
      $("projectName").textContent = state.project_name || "—";
      $("projectName").title = state.project || "";

      const g = state.grok || {};
      const btn = $("btnConnect");
      btn.disabled = !!g.connected;
      btn.textContent = g.connected ? "Grok linked ✓" : "Link Grok";

      renderFeed(state.events, state.grok_activity);
      renderFiles(state.previews);

      const primary = state.primary_preview;
      if (!primarySet && primary && !isSelfUrl(primary)) {
        primarySet = true;
        const match = (state.previews || []).find((p) => p.url === primary);
        $("previewUrl").value = primary;
        if (match?.type === "markdown") {
          /* skip auto iframe for md */
        } else {
          syncPreview(true);
        }
      } else if (!userPreviewLocked && primary && !isSelfUrl(primary)) {
        const cur = normalizePreviewInput($("previewUrl").value);
        if (!cur || cur === primary) {
          $("previewUrl").value = primary;
          syncPreview(false);
        }
      }

      if (g.connected && !$("terminalDock").classList.contains("collapsed")) {
        const t = (state.terminals || []).find((x) => x.running) || state.terminals?.[0];
        if (t) {
          $("termOutput").textContent =
            (t.command ? "$ " + t.command + "\n\n" : "") + (t.output_tail || "");
        }
      }

      updateStatusLine();
      updateGuide();
    } catch (err) {
      if (err.name === "AbortError") return;
      $("statusLine").textContent = "Build Watch offline — run: build-watch on";
      $("statusLine").className = "status-line err";
    } finally {
      tickInFlight = false;
    }
  }

  async function connectGrok() {
    $("btnConnect").disabled = true;
    try {
      const r = await fetch("/api/grok/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok && d.ok !== true) throw new Error(d.error || "connect failed");
      userPreviewLocked = false;
      primarySet = false;
      await tick();
      toast("Linked to Grok — keep building there; watch the preview here", "ok");
    } catch (err) {
      toast("Link failed: " + err.message + " — is Grok Build running?", "error");
    } finally {
      $("btnConnect").disabled = !!state?.grok?.connected;
      $("btnConnect").textContent = state?.grok?.connected ? "Grok linked ✓" : "Link Grok";
    }
  }

  function init() {
    $("btnConnect").addEventListener("click", connectGrok);
    $("btnHelp").addEventListener("click", () => $("helpDialog").showModal());
    $("helpClose").addEventListener("click", () => $("helpDialog").close());
    $("btnDismissGuide").addEventListener("click", () => {
      localStorage.setItem(GUIDE_KEY, "1");
      $("guide").hidden = true;
    });

    $("btnActivity").addEventListener("click", () => togglePanel("activity"));
    $("btnFiles").addEventListener("click", () => togglePanel("files"));
    document.querySelectorAll(".close-panel").forEach((b) => {
      b.addEventListener("click", () => togglePanel(b.dataset.close));
    });

    $("feedList").addEventListener("click", (ev) => {
      const link = ev.target.closest(".file-link");
      if (link) {
        ev.stopPropagation();
        const p = link.dataset.path;
        if (PREVIEWABLE.test(p)) openPreview("/api/raw?path=" + encodeURIComponent(p), p);
        else openFileDialog(p, false);
        return;
      }
      const bubble = ev.target.closest("[data-idx]");
      if (bubble) {
        const act = grokActsCache[Number(bubble.dataset.idx)];
        if (act?.path) {
          const p = relPath(act.path);
          if (PREVIEWABLE.test(p)) openPreview("/api/raw?path=" + encodeURIComponent(p), p);
          else openFileDialog(p, false);
        }
      }
    });

    $("filesList").addEventListener("click", (ev) => {
      const row = ev.target.closest(".file-row");
      if (!row) return;
      const type = row.dataset.type;
      const path = row.dataset.path;
      const url = row.dataset.url;
      if (type === "markdown" && path) openFileDialog(relPath(path), false);
      else openPreview(url, path);
      togglePanel("files");
    });

    $("previewUrl").addEventListener("input", () => {
      userPreviewLocked = true;
    });
    $("previewUrl").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        userPreviewLocked = true;
        syncPreview(true);
      }
    });
    $("btnPreviewGo").addEventListener("click", () => {
      userPreviewLocked = true;
      const u = normalizePreviewInput($("previewUrl").value);
      if (!u) {
        toast("Enter your app URL (from npm run dev) or a path like index.html", "warn");
        return;
      }
      openPreview(u, null);
    });
    $("btnPreviewRefresh").addEventListener("click", () => syncPreview(true));

    $("btnTermToggle").addEventListener("click", () => {
      const dock = $("terminalDock");
      const open = dock.classList.toggle("collapsed");
      $("btnTermToggle").setAttribute("aria-expanded", String(!open));
      $("btnTermToggle").textContent = open ? "Show Grok terminal output" : "Hide terminal";
    });

    $("fileDialogClose").addEventListener("click", () => $("fileDialog").close());
    $("btnFilePreview").addEventListener("click", () => {
      if (currentPath && PREVIEWABLE.test(currentPath)) {
        openPreview("/api/raw?path=" + encodeURIComponent(currentPath), currentPath);
        $("fileDialog").close();
      } else toast("This file type opens as text, not in the preview", "warn");
    });
    $("btnFileSave").addEventListener("click", saveFileDialog);

    fetch("/api/grok/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }).catch(() => {});

    tick();
    pollTimer = setInterval(tick, POLL_MS);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) tick();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();