/**
 * Build Watch Hub — simplified UI
 * Activity · Preview · Terminal
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
  let tab = "activity";
  let termMode = "mirror";
  let pollTimer = null;
  let lastTurnSig = "";

  function mdBasic(t) {
    return esc(t)
      .replace(/^### (.+)$/gm, "<h3>$1</h3>")
      .replace(/^## (.+)$/gm, "<h2>$1</h2>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");
  }

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

  function setTab(name) {
    tab = name;
    document.querySelectorAll(".tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
      b.setAttribute("aria-selected", b.dataset.tab === name ? "true" : "false");
    });
    ["activity", "preview", "terminal"].forEach((t) => {
      const panel = $("panel" + t.charAt(0).toUpperCase() + t.slice(1));
      const on = t === name;
      panel.classList.toggle("active", on);
      panel.hidden = !on;
    });
    if (name === "preview") syncPreview();
    if (name === "terminal" && termMode === "mirror") refreshMirror();
  }

  function renderFeed(events, grokActs) {
    const merged = [];
    (grokActs || []).forEach((a) => merged.push({ grok: true, ...a }));
    (events || []).forEach((e) => merged.push({ grok: false, ...e }));
    merged.sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));

    const el = $("feedList");
    if (!merged.length) {
      el.innerHTML = '<p class="empty">Waiting for Grok Build…</p>';
      return;
    }

    el.innerHTML = merged
      .slice(0, 50)
      .map((item) => {
        if (item.grok) {
          const label = item.title || item.type || "Grok";
          const detail = item.path || item.command || "";
          return `<article class="feed-item grok" data-path="${esc(item.path || "")}">
            <div class="meta">Grok · ${esc(label)}</div>${esc(detail)}</article>`;
        }
        const time = (item.ts || "").slice(11, 19);
        return `<article class="feed-item">
          <div class="meta">${esc(item.kind || "event")} · ${esc(time)}</div>${esc(item.msg || "")}</article>`;
      })
      .join("");

    el.querySelectorAll(".feed-item[data-path]").forEach((node) => {
      node.addEventListener("click", () => {
        const path = node.dataset.path;
        if (!path) return;
        const act = (grokActs || []).find((a) => a.path === path);
        if (act) showFile(act);
      });
    });
  }

  function renderTurns(turns) {
    const el = $("turnsList");
    if (!turns?.length) {
      el.innerHTML = '<p class="empty">Turns appear when Grok is connected.</p>';
      return;
    }

    el.innerHTML = [...turns]
      .reverse()
      .map((t) => {
        const ts = (t.ts_end || t.ts_start || "").slice(0, 19).replace("T", " ");
        return `<article class="turn-card" data-id="${esc(t.turn_id)}">
          <div class="turn-head">
            <span>${esc(ts)}</span>
            <div class="turn-actions">
              <button type="button" data-a="listen">Listen</button>
              <button type="button" data-a="copy">Copy</button>
            </div>
          </div>
          ${t.user_text ? `<div><strong>You:</strong> ${esc(t.user_text)}</div>` : ""}
          <div>${t.agent_text ? mdBasic(t.agent_text) : "…"}</div>
        </article>`;
      })
      .join("");

    el.querySelectorAll(".turn-actions button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const card = btn.closest(".turn-card");
        const t = turns.find((x) => x.turn_id === card?.dataset.id);
        if (!t) return;
        if (btn.dataset.a === "copy") navigator.clipboard.writeText(t.agent_text || "");
        if (btn.dataset.a === "listen") speakText(t.agent_text || "");
      });
    });
  }

  async function speakText(text) {
    if (!text?.trim()) return;
    await fetch("/api/tts/stop", { method: "POST" });
    await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice: settings.tts_voice || "Siri Voice 2" }),
    });
  }

  function renderFiles(previews) {
    const list = $("filesList");
    const items = previews || [];
    if (!items.length) {
      list.innerHTML = '<p class="empty" style="padding:8px">No files yet</p>';
      return;
    }
    list.innerHTML = items
      .map(
        (p) =>
          `<div class="file-chip" data-url="${esc(p.url || "")}" data-path="${esc(p.path || "")}">
            <strong>${esc(p.label || "Preview")}</strong>
            <span>${esc(p.path || p.url || "")}</span>
          </div>`
      )
      .join("");

    list.querySelectorAll(".file-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const path = chip.dataset.path;
        const url = chip.dataset.url;
        if (url) openPreview(url);
        else if (path) openRawFile(path);
      });
    });
  }

  function syncPreview() {
    const url = state?.primary_preview || $("previewUrl").value.trim();
    if (!url) {
      $("previewEmpty").hidden = false;
      $("previewFrame").src = "about:blank";
      return;
    }
    $("previewUrl").value = url;
    $("previewEmpty").hidden = true;
    const sep = url.includes("?") ? "&" : "?";
    $("previewFrame").src = url + sep + "t=" + Date.now();
  }

  function openPreview(url) {
    setTab("preview");
    state = state || {};
    state.primary_preview = url;
    $("previewUrl").value = url;
    syncPreview();
  }

  function openRawFile(path) {
    const rel = relPath(path);
    openPreview(location.origin + "/api/raw?path=" + encodeURIComponent(rel));
  }

  async function showFile(act) {
    const modal = $("fileModal");
    const rel = relPath(act.path);
    $("fileModalTitle").textContent = rel || act.title || "File";
    let text = act.code || act.output || "";
    if (!text && act.path) {
      try {
        const d = await api("/api/file?path=" + encodeURIComponent(rel));
        text = d.content || "";
      } catch {
        text = "(could not load file)";
      }
    }
    $("fileModalBody").textContent = text;
    modal.showModal();
  }

  async function refreshMirror() {
    const pin = $("termPick")?.value;
    const q = pin ? "?pin=" + encodeURIComponent(pin) : "";
    try {
      const d = await api("/api/terminal/mirror" + q, { expectOk: false });
      $("termOutput").textContent =
        (d.command ? "$ " + d.command + "\n\n" : "") + (d.output_tail || d.error || "No terminal output yet.");
    } catch {
      $("termOutput").textContent = "Could not load terminal mirror.";
    }
  }

  async function loadTermList() {
    try {
      const d = await api("/api/terminal/list");
      const sel = $("termPick");
      sel.innerHTML = (d.terminals || [])
        .map((t) => `<option value="${esc(t.path)}">${esc(t.name)}</option>`)
        .join("");
    } catch {
      /* ignore */
    }
  }

  function setTermMode(mode) {
    termMode = mode;
    const mirror = mode === "mirror";
    $("btnMirror").classList.toggle("active", mirror);
    $("btnShell").classList.toggle("active", !mirror);
    $("termInput").disabled = mirror;
    $("termHint").textContent = mirror
      ? "Mirrors your Grok Build terminal. Switch to shell to type commands."
      : "Interactive shell — press Enter to send input.";
    if (mirror) refreshMirror();
  }

  async function tick() {
    try {
      state = await api("/api/canvas");
      $("projectName").textContent = state.project_name || state.project || "—";

      const g = state.grok || {};
      const grokEl = $("grokPill");
      grokEl.hidden = !g.connected;
      if (g.connected) grokEl.textContent = "Grok · " + (g.session_id || "").slice(0, 8);

      const btn = $("btnConnect");
      btn.disabled = g.connected;
      btn.textContent = g.connected ? "Connected" : "Connect Grok";

      renderFeed(state.events, state.grok_activity);

      const turns = state.turns || [];
      const sig = turns.length + ":" + (turns[turns.length - 1]?.turn_id || "");
      if (sig !== lastTurnSig) {
        lastTurnSig = sig;
        renderTurns(turns);
      }

      renderFiles(state.previews);

      if (tab === "preview" && state.primary_preview) {
        const cur = $("previewUrl").value.trim();
        if (!cur || cur === state.primary_preview) {
          $("previewUrl").value = state.primary_preview;
          syncPreview();
        }
      }

      if (tab === "terminal" && termMode === "mirror" && state.terminals?.length) {
        const t = state.terminals.find((x) => x.running) || state.terminals[0];
        if (t) {
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
    document.querySelectorAll(".tab").forEach((b) => {
      b.addEventListener("click", () => setTab(b.dataset.tab));
    });

    $("btnConnect").addEventListener("click", async () => {
      $("btnConnect").disabled = true;
      $("btnConnect").textContent = "Connecting…";
      try {
        await fetch("/api/grok/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        await tick();
      } finally {
        $("btnConnect").disabled = state?.grok?.connected;
        $("btnConnect").textContent = state?.grok?.connected ? "Connected" : "Connect Grok";
      }
    });

    $("btnAdvanced").addEventListener("click", () => {
      location.href = "/canvas-legacy";
    });

    $("btnPreviewGo").addEventListener("click", () => {
      const u = $("previewUrl").value.trim();
      if (u) openPreview(u);
    });
    $("btnPreviewRefresh").addEventListener("click", syncPreview);

    $("btnMirror").addEventListener("click", () => setTermMode("mirror"));
    $("btnShell").addEventListener("click", async () => {
      setTermMode("shell");
      await fetch("/api/terminal/pty/start", { method: "POST" });
      $("termOutput").textContent += "\n[PTY shell started]\n";
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

    $("fileModalClose").addEventListener("click", () => $("fileModal").close());
    $("fileModal").addEventListener("click", (e) => {
      if (e.target === $("fileModal")) $("fileModal").close();
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

    setTab("activity");
    tick();
    pollTimer = setInterval(tick, 1000);
    loadTermList();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();