/**
 * Build Watch — preview-first hub
 * Center: live preview + code + build split. Sides: stream + artifacts.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

  let state = null;
  let settings = {};
  let mode = "preview";
  let termMode = "mirror";
  let pollTimer = null;
  let primarySet = false;
  let currentPath = "";
  let buildDirty = false;
  let lastPreviewUrl = "";
  let lastGrokSig = "";

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    if (!r.ok && opts.expectOk !== false) throw new Error(String(r.status));
    return r.json().catch(() => ({}));
  }

  function relPath(path) {
    if (!path || !state?.project) return path || "";
    const root = state.project;
    return path.startsWith(root) ? path.slice(root.length).replace(/^\//, "") : path;
  }

  function setMode(m) {
    mode = m;
    document.querySelectorAll(".canvas-tabs .tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === m);
    });
    ["preview", "code", "build"].forEach((name) => {
      const pane = $("pane" + name.charAt(0).toUpperCase() + name.slice(1));
      const on = name === m;
      pane.classList.toggle("active", on);
      pane.hidden = !on;
    });
    if (m === "build" && $("buildPath").value.trim()) refreshBuildPreview();
  }

  function previewSrc(url) {
    if (!url) return "";
    if (url.startsWith("http")) return url;
    const origin = location.origin;
    return url.startsWith("/") ? origin + url : origin + "/" + url;
  }

  function syncPreview(force) {
    const url = $("previewUrl").value.trim() || state?.primary_preview || "";
    if (!url) {
      $("previewEmpty").hidden = false;
      $("previewFrame").src = "about:blank";
      lastPreviewUrl = "";
      return;
    }
    const full = previewSrc(url);
    const sep = full.includes("?") ? "&" : "?";
    const next = full + sep + "t=" + Date.now();
    if (!force && next.split("t=")[0] === lastPreviewUrl.split("t=")[0] && $("previewFrame").src !== "about:blank") return;
    lastPreviewUrl = next;
    $("previewUrl").value = url;
    $("previewEmpty").hidden = true;
    $("previewFrame").src = next;
    setMode("preview");
  }

  function openPreview(url, path, type) {
    if (!url && path) {
      const rel = relPath(path);
      if (path.endsWith(".md")) {
        openFile(rel, "code");
        return;
      }
      url = "/api/raw?path=" + encodeURIComponent(rel);
      type = type || "html";
    }
    if (url) {
      $("previewUrl").value = url.startsWith("http") ? url : url;
      if (path) currentPath = relPath(path);
      syncPreview(true);
      highlightRail(url, path);
    }
    if (type === "code" && path) openFile(relPath(path), "code");
  }

  function highlightRail(url, path) {
    document.querySelectorAll(".rail-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.url === url || el.dataset.path === path);
    });
  }

  async function openFile(path, targetMode) {
    if (!path) return;
    currentPath = path;
    const d = await api("/api/file?path=" + encodeURIComponent(path));
    const text = d.content ?? "";
    $("codePathLabel").textContent = path;
    $("codeView").textContent = text;
    $("buildPath").value = path;
    $("buildEditor").value = text;
    buildDirty = false;
    setMode(targetMode || "code");
    if (path.match(/\.(html?|tsx?|jsx?|vue)$/i)) {
      refreshBuildPreview();
    }
  }

  function refreshBuildPreview() {
    const path = $("buildPath").value.trim();
    if (!path) return;
    const url = location.origin + "/api/raw?path=" + encodeURIComponent(path) + "&t=" + Date.now();
    $("buildFrame").src = url;
  }

  async function saveBuild() {
    const path = $("buildPath").value.trim();
    if (!path) return;
    await fetch("/api/file/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content: $("buildEditor").value }),
    });
    buildDirty = false;
    $("codeView").textContent = $("buildEditor").value;
    refreshBuildPreview();
    syncPreview(true);
  }

  function renderFeed(events, grokActs) {
    const merged = [];
    (grokActs || []).forEach((a) => merged.push({ grok: true, ...a }));
    (events || []).forEach((e) => merged.push({ grok: false, ...e }));
    merged.sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));

    const el = $("feedList");
    if (!merged.length) {
      el.innerHTML = '<p class="empty">Run Grok Build — edits appear here and refresh preview.</p>';
      return;
    }

    el.innerHTML = merged.slice(0, 60).map((item) => {
      if (item.grok) {
        const running = item.status === "running" ? " running" : "";
        const body =
          item.type === "shell"
            ? esc(item.command || "") + (item.output ? "\n" + esc(item.output.slice(0, 400)) : "")
            : esc(item.text || item.command || item.path || "");
        const file = item.path
          ? `<div class="file-link" data-path="${esc(item.path)}">${esc(relPath(item.path))}</div>`
          : "";
        return `<article class="bubble grok${running}" data-grok="1">
          <div class="meta">Grok · ${esc(item.title || item.type)} · ${esc(item.status || "")}</div>
          ${body}${file}</article>`;
      }
      const time = (item.ts || "").slice(11, 19);
      const files = (item.files || [])
        .map((f) => `<div class="file-link" data-path="${esc(f)}">${esc(f)}</div>`)
        .join("");
      return `<article class="bubble">
        <div class="meta">${esc(item.kind || "event")} · ${esc(time)}</div>
        ${esc(item.msg || "")}${files}</article>`;
    }).join("");

    el.querySelectorAll(".file-link").forEach((node) => {
      node.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const p = relPath(node.dataset.path);
        const act = (grokActs || []).find((a) => relPath(a.path) === p || a.path === node.dataset.path);
        if (p.match(/\.(html?|tsx?|jsx?|vue)$/i)) {
          openPreview("/api/raw?path=" + encodeURIComponent(p), p, "html");
        } else {
          openFile(p, act?.code ? "build" : "code");
        }
      });
    });

    el.querySelectorAll(".bubble[data-grok]").forEach((node) => {
      node.addEventListener("click", () => {
        const link = node.querySelector(".file-link");
        if (link) return;
        const path = (grokActs || []).find((a) => node.textContent.includes(relPath(a.path)))?.path;
        if (path) openFile(relPath(path), "build");
      });
    });
  }

  function renderRail(previews) {
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

    list.querySelectorAll(".rail-item").forEach((chip) => {
      chip.addEventListener("click", () => {
        openPreview(chip.dataset.url, chip.dataset.path, chip.dataset.type);
      });
    });
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
      $("termPick").innerHTML = (d.terminals || [])
        .map((t) => `<option value="${esc(t.path)}">${esc(t.name)}</option>`)
        .join("");
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

  async function tick() {
    try {
      state = await api("/api/canvas");
      $("projectName").textContent = state.project_name || "—";

      const g = state.grok || {};
      $("grokPill").hidden = !g.connected;
      if (g.connected) $("grokPill").textContent = "Grok · " + (g.session_id || "").slice(0, 8);

      const btn = $("btnConnect");
      btn.disabled = !!g.connected;
      btn.textContent = g.connected ? "Connected" : "Connect Grok";

      renderFeed(state.events, state.grok_activity);
      renderRail(state.previews);

      const grokSig = (state.grok_activity || []).length + ":" + (state.grok_activity || []).slice(-1)[0]?.path;
      const latestHtml = [...(state.grok_activity || [])]
        .reverse()
        .find((a) => a.path && /\.(html?|tsx?|jsx?)$/i.test(a.path));
      if (grokSig !== lastGrokSig && latestHtml?.path && mode === "preview") {
        lastGrokSig = grokSig;
        const p = relPath(latestHtml.path);
        if (p.endsWith(".html") || p.endsWith(".htm")) {
          openPreview("/api/raw?path=" + encodeURIComponent(p), p, "html");
        }
      } else {
        lastGrokSig = grokSig;
      }

      if (!primarySet) {
        primarySet = true;
        if (state.primary_preview) {
          const p = (state.previews || []).find((x) => x.url === state.primary_preview) || state.previews?.[0];
          if (p) openPreview(p.url, p.path, p.type);
          else {
            $("previewUrl").value = state.primary_preview;
            syncPreview(true);
          }
        }
      } else if (mode === "preview" && state.primary_preview) {
        const cur = $("previewUrl").value.trim();
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

      if (termMode === "mirror" && state.terminals?.length) {
        const t = state.terminals.find((x) => x.running) || state.terminals[0];
        if (t && !$("terminalDock").classList.contains("collapsed")) {
          $("termOutput").textContent =
            (t.command ? "$ " + t.command + "\n\n" : "") + (t.output_tail || "");
        }
      }
    } catch {
      $("livePill").classList.remove("ok");
      $("livePill").textContent = "Offline";
    }
  }

  function init() {
    document.querySelectorAll(".canvas-tabs .tab").forEach((b) => {
      b.addEventListener("click", () => setMode(b.dataset.mode));
    });

    $("btnConnect").addEventListener("click", async () => {
      $("btnConnect").disabled = true;
      try {
        await fetch("/api/grok/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        await tick();
      } finally {
        $("btnConnect").disabled = !!state?.grok?.connected;
        $("btnConnect").textContent = state?.grok?.connected ? "Connected" : "Connect Grok";
      }
    });

    $("btnPreviewGo").addEventListener("click", () => {
      const u = $("previewUrl").value.trim();
      if (!u) return;
      if (u.startsWith("http")) openPreview(u, null, "server");
      else openPreview("/api/raw?path=" + encodeURIComponent(u), u, "html");
    });
    $("btnPreviewRefresh").addEventListener("click", () => syncPreview(true));

    $("btnCodeToPreview").addEventListener("click", () => {
      if (currentPath) openPreview("/api/raw?path=" + encodeURIComponent(currentPath), currentPath, "html");
    });

    $("btnBuildSave").addEventListener("click", saveBuild);
    $("btnBuildReload").addEventListener("click", () => openFile($("buildPath").value.trim(), "build"));
    $("buildEditor").addEventListener("input", () => {
      buildDirty = true;
      clearTimeout(window._buildPreviewTimer);
      window._buildPreviewTimer = setTimeout(refreshBuildPreview, 600);
    });

    $("btnMirror").addEventListener("click", () => setTermMode("mirror"));
    $("btnShell").addEventListener("click", async () => {
      setTermMode("shell");
      await fetch("/api/terminal/pty/start", { method: "POST" });
    });
    $("termPick")?.addEventListener("change", refreshMirror);
    $("termInput").addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || termMode !== "shell") return;
      const line = $("termInput").value;
      $("termInput").value = "";
      await fetch("/api/terminal/pty/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: line + "\n" }),
      });
      setTimeout(async () => {
        const d = await api("/api/terminal/pty/poll");
        if (d.output) $("termOutput").textContent += d.output;
      }, 80);
    });

    $("btnTermToggle").addEventListener("click", () => {
      const dock = $("terminalDock");
      const collapsed = dock.classList.toggle("collapsed");
      $("btnTermToggle").setAttribute("aria-expanded", String(!collapsed));
    });

    $("autoSync").addEventListener("change", (e) => {
      clearInterval(pollTimer);
      pollTimer = setInterval(tick, e.target.checked ? 1000 : 3000);
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
    pollTimer = setInterval(tick, 1000);
    loadTermList();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();