/**
 * Build Watch Hub — canvas v3
 * Maps feature matrix to /api/* bridge.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  let state = null;
  let settings = {};
  let mode = "workspace";
  let turnsCache = [];
  let selectedNodeId = null;
  let wsNodes = [];
  let wsPan = { x: 0, y: 0 };
  let wsZoom = 1;
  let pollTimer = null;
  let termMode = "mirror";
  let workshopPath = "";
  let lastTurnSig = "";
  let primarySet = false;

  const WRAPPERS = [
    { id: "w-analytics", name: "Analytics", cmd: "grok install @grok/wrapper-analytics", icon: "📊" },
    { id: "w-auth", name: "Auth", cmd: "grok install @grok/wrapper-auth", icon: "🔐" },
    { id: "w-errors", name: "Error Boundary", cmd: "grok install @grok/wrapper-errors", icon: "🛡" },
    { id: "w-theme", name: "Theme Sync", cmd: "grok install @grok/wrapper-theme", icon: "🎨" },
  ];

  const TEMPLATES = [
    { id: "t-dash", name: "Dashboard Starter", type: "template", cmd: "grok scaffold dashboard" },
    { id: "t-ecom", name: "E-Commerce Flow", type: "template", cmd: "grok scaffold ecommerce" },
    { id: "t-api", name: "API Layer", type: "template", cmd: "grok scaffold api" },
  ];

  const COMMANDS = [
    { label: "Extract to Custom Hook", cmd: "grok refactor --extract-hook", hint: "AI" },
    { label: "Generate API Layer", cmd: "grok generate api", hint: "AI" },
    { label: "Connect Grok session", cmd: "build-watch connect", hint: "CLI" },
    { label: "Rebuild turns", cmd: "POST /api/grok/rebuild-turns", hint: "API" },
    { label: "Open classic canvas", cmd: "/canvas-legacy", hint: "View" },
    { label: "Run smoke tests", cmd: "python3 scripts/test_api.py", hint: "Test" },
  ];

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
    if (!r.ok && opts.expectOk !== false) throw new Error(r.status);
    return r.json().catch(() => ({}));
  }

  function echoCmd(cmd) {
    $("cmdEcho").textContent = "$ " + cmd;
    appendTermLog("$ " + cmd + "\n");
  }

  function appendTermLog(text) {
    const el = $("termOutput");
    el.textContent += text;
    el.scrollTop = el.scrollHeight;
  }

  function setMode(m) {
    mode = m;
    document.querySelectorAll(".workspace-toolbar button").forEach((b) => {
      b.classList.toggle("active", b.dataset.view === m);
    });
    $("viewWorkspace").classList.toggle("active", m === "workspace");
    $("viewRead").classList.toggle("active", m === "read");
    $("viewSplit").classList.toggle("active", m === "split");
    $("viewDevices").classList.toggle("active", m === "devices");
    if (m === "read") renderTurns(turnsCache);
    if (m === "split") refreshSplit();
    if (m === "devices") refreshDevices();
  }

  function buildGraphNodes() {
    const nodes = [];
    let x = 80, y = 80;
    nodes.push({
      id: "n-grok",
      type: "Grok Bridge",
      title: state?.grok?.connected ? "Connected" : "Disconnected",
      sub: (state?.grok?.session_id || "—").slice(0, 12),
      x: 120,
      y: 100,
      wrapper: null,
    });
    nodes.push({
      id: "n-preview",
      type: "Live Preview",
      title: state?.project_name || "Project",
      sub: state?.primary_preview ? "Dev server" : "No preview",
      x: 380,
      y: 80,
    });
    nodes.push({
      id: "n-terminal",
      type: "Terminal",
      title: "Grok Build",
      sub: `${(state?.terminals || []).length} mirrors`,
      x: 380,
      y: 240,
    });
    (state?.grok_activity || []).slice(-6).forEach((a, i) => {
      nodes.push({
        id: "n-act-" + i,
        type: a.type === "shell" ? "Shell" : "Edit",
        title: a.title || a.path || "tool",
        sub: (a.path || "").split("/").pop() || a.status,
        x: 80 + (i % 3) * 200,
        y: 280 + Math.floor(i / 3) * 100,
        act: a,
      });
    });
    wsNodes = nodes;
    renderWorkspaceNodes();
    drawEdges();
  }

  function renderWorkspaceNodes() {
    const layer = $("nodeLayer");
    layer.innerHTML = wsNodes
      .map((n) => {
        const sel = n.id === selectedNodeId ? " selected" : "";
        const pause = n.paused ? " paused" : "";
        const wb = n.wrapper ? `<span class="wrapper-badge">${esc(n.wrapper)}</span>` : "";
        return `<div class="ws-node${sel}${pause}" data-id="${esc(n.id)}" style="left:${n.x + wsPan.x}px;top:${n.y + wsPan.y}px;transform:scale(${wsZoom})">
          <div class="node-type">${esc(n.type)}</div>
          <div class="node-title">${esc(n.title)}</div>
          <div class="node-sub">${esc(n.sub || "")}</div>${wb}
        </div>`;
      })
      .join("");
    layer.querySelectorAll(".ws-node").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        selectNode(el.dataset.id);
      });
      enableDrag(el);
    });
  }

  function drawEdges() {
    const svg = $("edgeSvg");
    const lines = [];
    const grok = wsNodes.find((n) => n.id === "n-grok");
    const preview = wsNodes.find((n) => n.id === "n-preview");
    const term = wsNodes.find((n) => n.id === "n-terminal");
    if (grok && preview) lines.push(edge(grok, preview));
    if (grok && term) lines.push(edge(grok, term));
    wsNodes.filter((n) => n.act).forEach((n) => {
      if (grok) lines.push(edge(grok, n, 0.35));
    });
    svg.innerHTML = lines.join("");
  }

  function edge(a, b, op = 0.55) {
    const ax = a.x + wsPan.x + 70;
    const ay = a.y + wsPan.y + 40;
    const bx = b.x + wsPan.x + 70;
    const by = b.y + wsPan.y + 20;
    const mx = (ax + bx) / 2;
    return `<path class="tether-line" style="opacity:${op}" d="M${ax},${ay} C${mx},${ay} ${mx},${by} ${bx},${by}"/>`;
  }

  function selectNode(id) {
    selectedNodeId = id;
    renderWorkspaceNodes();
    const n = wsNodes.find((x) => x.id === id);
    const insp = $("inspectorBody");
    if (!n) {
      insp.innerHTML = '<div class="inspector-empty">Select a node on the canvas</div>';
      return;
    }
    insp.innerHTML = `
      <div class="inspector-form">
        <label>Component</label>
        <input value="${esc(n.title)}" readonly />
        <label>Type</label>
        <input value="${esc(n.type)}" readonly />
        <label>Data source</label>
        <input value="${esc(n.sub || "")}" />
        <label>Glass / border</label>
        <select><option>Glassmorphism</option><option>Solid</option></select>
        <label>Shadow</label>
        <input type="range" min="0" max="100" value="40" />
        ${n.act?.path ? `<button type="button" id="btnOpenCode" style="margin-top:12px;width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--accent);color:#111;font-weight:600;cursor:pointer">Open code bubble</button>` : ""}
      </div>
      <div class="telemetry">
        <h4>Performance</h4>
        <div style="font-size:0.7rem;color:var(--muted);margin-bottom:4px">FPS (est.)</div>
        <div class="telemetry-bar"><span id="fpsBar"></span></div>
        <div style="font-size:0.7rem;color:var(--muted)">Latency ~${80 + Math.floor(Math.random() * 40)}ms</div>
      </div>`;
    if (n.act) {
      $("btnOpenCode")?.addEventListener("click", () => openCodeBubble(n.act));
      showSuggestion(n);
    }
    if (n.id === "n-preview" && state?.primary_preview) refreshDevices();
  }

  function showSuggestion(n) {
    const tip = $("suggestionTip");
    if (!n.act?.path) {
      tip.classList.remove("open");
      return;
    }
    tip.classList.add("open");
    tip.innerHTML = `Consider reviewing <strong>${esc(n.act.path.split("/").pop())}</strong> for side effects.<button type="button" id="tipApply">Apply: open split</button>`;
    tip.style.left = n.x + wsPan.x + 160 + "px";
    tip.style.top = n.y + wsPan.y + 20 + "px";
    $("tipApply")?.addEventListener("click", () => {
      setMode("split");
      loadSplitFile(relPath(n.act.path));
      tip.classList.remove("open");
    });
  }

  function relPath(path) {
    if (!path || !state) return path;
    const root = state.project;
    return path.startsWith(root) ? path.slice(root.length).replace(/^\//, "") : path;
  }

  async function openCodeBubble(act) {
    const bubble = $("codeBubble");
    bubble.classList.add("open");
    $("codeBubbleTitle").textContent = relPath(act.path) || act.title || "Code";
    let text = act.code || act.output || "";
    if (!text && act.path) {
      const d = await api("/api/file?path=" + encodeURIComponent(relPath(act.path)));
      text = d.content || "";
    }
    $("codeBubbleBody").textContent = text;
  }

  function enableDrag(el) {
    let startX, startY, nodeId, orig;
    el.addEventListener("pointerdown", (ev) => {
      nodeId = el.dataset.id;
      const n = wsNodes.find((x) => x.id === nodeId);
      if (!n) return;
      startX = ev.clientX;
      startY = ev.clientY;
      orig = { x: n.x, y: n.y };
      el.setPointerCapture(ev.pointerId);
      const move = (e) => {
        n.x = orig.x + (e.clientX - startX) / wsZoom;
        n.y = orig.y + (e.clientY - startY) / wsZoom;
        el.style.left = n.x + wsPan.x + "px";
        el.style.top = n.y + wsPan.y + "px";
        drawEdges();
      };
      const up = () => {
        el.releasePointerCapture(ev.pointerId);
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        renderWorkspaceNodes();
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
    });
  }

  function renderPalette() {
    $("wrapperPalette").innerHTML = WRAPPERS.map(
      (w) => `<div class="palette-item wrapper" draggable="true" data-wrapper="${esc(w.id)}" data-cmd="${esc(w.cmd)}">
        <span class="palette-icon">${w.icon}</span>${esc(w.name)}</div>`
    ).join("");
    $("templatePalette").innerHTML = TEMPLATES.map(
      (t) => `<div class="palette-item" draggable="true" data-cmd="${esc(t.cmd)}">
        <span class="palette-icon">◇</span>${esc(t.name)}</div>`
    ).join("");
    document.querySelectorAll(".palette-item").forEach((item) => {
      item.addEventListener("dragstart", (ev) => {
        ev.dataTransfer.setData("text/cmd", item.dataset.cmd || "");
        ev.dataTransfer.setData("text/wrapper", item.dataset.wrapper || "");
      });
    });
  }

  function renderStream(events, grokActs) {
    const merged = [];
    (grokActs || []).forEach((a) => merged.push({ _grok: true, ...a }));
    (events || []).forEach((e) => merged.push({ _grok: false, ...e }));
    merged.sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));
    $("streamMini").innerHTML =
      merged.slice(0, 40).map((item) => {
        if (item._grok) {
          return `<div class="stream-item grok" data-path="${esc(item.path || "")}">
            <div class="meta">grok · ${esc(item.title)}</div>${esc(item.path || item.command || "")}</div>`;
        }
        return `<div class="stream-item"><div class="meta">${esc(item.kind)} · ${esc((item.ts || "").slice(11, 19))}</div>${esc(item.msg)}</div>`;
      }).join("") || '<div class="stream-item"><div class="meta">waiting</div>Run Grok Build…</div>';
    $("streamMini").querySelectorAll(".stream-item").forEach((el) => {
      el.addEventListener("click", () => {
        const path = el.dataset.path;
        if (path) {
          const act = (grokActs || []).find((a) => a.path === path);
          if (act) openCodeBubble(act);
        }
      });
    });
    renderTimeline(events);
    updateDiff(events, grokActs);
  }

  function renderTimeline(events) {
    const evs = [...(events || [])].sort((a, b) => (a.ts || "").localeCompare(b.ts || ""));
    const nodes = [
      { label: "Scaffold", kind: "plan" },
      ...evs.slice(-8).map((e, i) => ({
        label: (e.kind || "note") + " " + (e.ts || "").slice(11, 16),
        kind: e.kind,
        i,
      })),
      { label: "HEAD", kind: "done" },
    ];
    $("timelineTrack").innerHTML = nodes
      .map((n, i) => `<button type="button" class="timeline-node${i === nodes.length - 1 ? " active" : ""}" data-i="${i}">${esc(n.label)}</button>`)
      .join("");
  }

  function updateDiff(events, grokActs) {
    const last = [...(grokActs || [])].reverse().find((a) => a.code);
    $("diffSummary").textContent = last
      ? `AI: ${last.title || "edit"} on ${relPath(last.path) || "file"} — +lines ${(last.code || "").split("\n").length}`
      : "No recent code diff — waiting for Grok edits";
    $("diffLeft").textContent = last?.code ? last.code.slice(0, 1200) : "// previous";
    $("diffRight").textContent = last?.output || last?.code?.slice(0, 1200) || "// current";
  }

  function renderTurns(turns) {
    if (!turns?.length) {
      $("readInner").innerHTML = '<div style="color:var(--muted);padding:24px">No turns yet — chat in Grok terminal.</div>';
      return;
    }
    $("readInner").innerHTML = [...turns].reverse().map((t) => {
      const ts = (t.ts_end || t.ts_start || "").slice(0, 19).replace("T", " ");
      return `<article class="turn-card" data-id="${esc(t.turn_id)}">
        <div class="turn-head"><span>${esc(ts)}</span>
          <div class="turn-actions">
            <button type="button" data-a="listen">Listen</button>
            <button type="button" data-a="copy">Copy</button>
            <button type="button" data-a="split">Split</button>
          </div></div>
        ${t.user_text ? `<div style="margin-bottom:8px"><strong>You:</strong> ${esc(t.user_text)}</div>` : ""}
        <div>${t.agent_text ? mdBasic(t.agent_text) : "…"}</div></article>`;
    }).join("");
    $("readInner").querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const t = turns.find((x) => x.turn_id === btn.closest(".turn-card").dataset.id);
        if (!t) return;
        if (btn.dataset.a === "copy") navigator.clipboard.writeText(t.agent_text || "");
        if (btn.dataset.a === "listen") speakText(t.agent_text || "");
        if (btn.dataset.a === "split") {
          setMode("split");
          $("splitPath").value = "";
        }
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

  async function loadSplitFile(path) {
    if (!path) return;
    const d = await api("/api/file?path=" + encodeURIComponent(path));
    $("splitEditor").value = d.content || "";
    $("splitPath").value = path;
    const url = location.origin + "/api/raw?path=" + encodeURIComponent(path) + "&t=" + Date.now();
    $("splitFrame").src = path.endsWith(".html") ? url : state?.primary_preview || "about:blank";
  }

  function refreshSplit() {
    const p = $("splitPath").value.trim();
    if (p) loadSplitFile(p);
    else if (state?.previews?.[0]?.path) loadSplitFile(state.previews[0].path);
  }

  function refreshDevices() {
    const url = state?.primary_preview || "about:blank";
    const q = url.includes("?") ? "&" : "?";
    const u = url + q + "t=" + Date.now();
    ["devWeb", "devIos", "devAndroid"].forEach((id) => {
      const f = $(id);
      if (f) f.src = u;
    });
  }

  function renderArtifacts(previews) {
    $("artifactList").innerHTML = (previews || [])
      .map(
        (p) =>
          `<div class="artifact-item" data-url="${esc(p.url)}" data-path="${esc(p.path || "")}" data-type="${esc(p.type)}">
            <strong>${esc(p.label)}</strong><br><span style="color:var(--muted);font-size:0.65rem">${esc(p.path || p.url)}</span></div>`
      )
      .join("");
    $("artifactList").querySelectorAll(".artifact-item").forEach((el) => {
      el.addEventListener("click", () => {
        const path = el.dataset.path;
        if (path) {
          setMode("split");
          loadSplitFile(path);
        } else if (el.dataset.url) {
          setMode("devices");
          state.primary_preview = el.dataset.url;
          refreshDevices();
        }
      });
    });
  }

  async function refreshMirror() {
    const pin = $("termPick")?.value;
    const q = pin ? "?pin=" + encodeURIComponent(pin) : "";
    const d = await api("/api/terminal/mirror" + q, { expectOk: false });
    $("termOutput").textContent =
      (d.command ? "$ " + d.command + "\n\n" : "") + (d.output_tail || d.error || "No terminal");
  }

  async function refreshShell() {
    const d = await api("/api/terminal/pty/poll");
    if (d.output) appendTermLog(d.output);
  }

  async function loadTermList() {
    const d = await api("/api/terminal/list");
    const sel = $("termPick");
    if (!sel) return;
    sel.innerHTML = (d.terminals || [])
      .map((t) => `<option value="${esc(t.path)}">${esc(t.name)}</option>`)
      .join("");
  }

  async function tick() {
    try {
      state = await api("/api/canvas");
      $("projectName").textContent = state.project_name || "—";
      $("livePill").style.display = "inline-flex";
      const g = state.grok || {};
      $("grokPill").style.display = g.connected ? "inline-flex" : "none";
      $("grokPill").textContent = g.connected ? "Grok · " + (g.session_id || "").slice(0, 8) : "";
      settings = state.settings || settings;

      const turns = state.turns || [];
      const sig = turns.length + ":" + (turns[turns.length - 1]?.turn_id || "");
      if (sig !== lastTurnSig) {
        lastTurnSig = sig;
        turnsCache = turns;
        if (mode === "read") renderTurns(turns);
      }

      renderStream(state.events, state.grok_activity);
      buildGraphNodes();
      renderArtifacts(state.previews);
      if (mode === "workspace" && state.terminals?.length) {
        const t = state.terminals.find((x) => x.running) || state.terminals[0];
        if (t && termMode === "mirror") $("termOutput").textContent = (t.command ? "$ " + t.command + "\n\n" : "") + (t.output_tail || "");
      }

      const fps = 55 + Math.floor(Math.random() * 12);
      const bar = $("fpsBar");
      if (bar) bar.style.width = fps + "%";

      if (!primarySet && g.connected) {
        primarySet = true;
        setMode("workspace");
      }
    } catch {
      $("livePill").textContent = "Offline";
    }
  }

  function openCmdPalette() {
    $("cmdPalette").classList.add("open");
    $("cmdInput").value = "";
    renderCmdResults("");
    $("cmdInput").focus();
  }

  function closeCmdPalette() {
    $("cmdPalette").classList.remove("open");
  }

  function renderCmdResults(q) {
    const ql = q.toLowerCase();
    const items = COMMANDS.filter((c) => c.label.toLowerCase().includes(ql) || c.cmd.toLowerCase().includes(ql));
    $("cmdResults").innerHTML = items
      .map(
        (c, i) =>
          `<div class="cmd-item${i === 0 ? " focused" : ""}" data-cmd="${esc(c.cmd)}"><span>${esc(c.label)}</span><span>${esc(c.hint)}</span></div>`
      )
      .join("");
    $("cmdResults").querySelectorAll(".cmd-item").forEach((el) => {
      el.addEventListener("click", () => runCmd(el.dataset.cmd));
    });
  }

  function runCmd(cmd) {
    closeCmdPalette();
    if (cmd === "/canvas-legacy") {
      location.href = "/canvas-legacy";
      return;
    }
    if (cmd.startsWith("POST ")) {
      fetch(cmd.replace("POST ", ""), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      echoCmd(cmd);
      return;
    }
    echoCmd(cmd);
    fetch("/api/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "cmd", msg: cmd }),
    }).catch(() => {});
  }

  function initWorkspaceDrop() {
    const wrap = $("viewWorkspace");
    wrap.addEventListener("dragover", (e) => e.preventDefault());
    wrap.addEventListener("drop", (e) => {
      e.preventDefault();
      const cmd = e.dataTransfer.getData("text/cmd");
      const wrapper = e.dataTransfer.getData("text/wrapper");
      if (cmd) {
        echoCmd(cmd);
        fetch("/api/event", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "plan", msg: "Dropped: " + cmd }),
        }).catch(() => {});
        if (wrapper) {
          const n = wsNodes[0];
          if (n) n.wrapper = WRAPPERS.find((w) => w.id === wrapper)?.name;
          renderWorkspaceNodes();
        }
      }
    });
  }

  function initCmdK() {
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        openCmdPalette();
      }
      if (e.key === "Escape") {
        closeCmdPalette();
        $("codeBubble").classList.remove("open");
      }
    });
    $("cmdInput").addEventListener("input", (e) => renderCmdResults(e.target.value));
    $("cmdPalette").addEventListener("click", (e) => {
      if (e.target === $("cmdPalette")) closeCmdPalette();
    });
  }

  function initUI() {
    renderPalette();
    initWorkspaceDrop();
    initCmdK();

    document.querySelectorAll(".workspace-toolbar button").forEach((b) => {
      b.addEventListener("click", () => setMode(b.dataset.view));
    });

    $("btnCmd").addEventListener("click", openCmdPalette);
    $("btnLegacy").addEventListener("click", () => (location.href = "/canvas-legacy"));
    $("btnDiff").addEventListener("click", () => $("diffDrawer").classList.toggle("open"));
    $("btnZoomIn").addEventListener("click", () => {
      wsZoom = Math.min(1.5, wsZoom + 0.1);
      renderWorkspaceNodes();
      drawEdges();
    });
    $("btnZoomOut").addEventListener("click", () => {
      wsZoom = Math.max(0.5, wsZoom - 0.1);
      renderWorkspaceNodes();
      drawEdges();
    });

    $("btnTermMirror").addEventListener("click", () => {
      termMode = "mirror";
      $("btnTermMirror").classList.add("active");
      $("btnTermShell").classList.remove("active");
      refreshMirror();
    });
    $("btnTermShell").addEventListener("click", async () => {
      termMode = "shell";
      $("btnTermShell").classList.add("active");
      $("btnTermMirror").classList.remove("active");
      await fetch("/api/terminal/pty/start", { method: "POST" });
      echoCmd("pty/start");
    });
    $("termPick")?.addEventListener("change", refreshMirror);
    $("dockInput").addEventListener("keydown", async (e) => {
      if (e.key !== "Enter") return;
      const line = $("dockInput").value;
      $("dockInput").value = "";
      await fetch("/api/terminal/pty/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: line + "\n" }),
      });
      setTimeout(refreshShell, 80);
    });

    $("codeBubbleClose").addEventListener("click", () => $("codeBubble").classList.remove("open"));

    $("autoSync").addEventListener("change", (e) => {
      const ms = e.target.checked ? 1000 : 3000;
      clearInterval(pollTimer);
      pollTimer = setInterval(tick, ms);
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

    tick();
    pollTimer = setInterval(tick, 1000);
    loadTermList();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initUI);
  else initUI();
})();