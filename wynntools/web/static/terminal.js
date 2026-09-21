"use strict";
// Terminal panel: xterm.js attached to the server's persistent shell.

(() => {
  const panel = document.getElementById("terminal-panel");
  const toggle = document.getElementById("toggle-terminal");
  const note = document.getElementById("term-note");
  let term, fit, ws, retry = 0, opened = false;
  let pending = [];               // messages sent before the socket opened

  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  const savedWidth = store.get("wt-term-width");
  if (savedWidth) document.documentElement.style.setProperty("--term-width", savedWidth);

  function send(msg) {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    else pending.push(msg);
  }

  function connect() {
    ws = new WebSocket(`ws://${location.host}/ws/terminal`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      retry = 0; note.textContent = ""; term.reset(); fitNow();
      const queued = pending; pending = [];
      for (const m of queued) ws.send(JSON.stringify(m));
    };
    ws.onmessage = (ev) => term.write(new Uint8Array(ev.data));
    ws.onclose = () => {
      if (panel.hidden) return;
      note.textContent = "Disconnected, reconnecting…";
      setTimeout(connect, Math.min(5000, 500 * 2 ** retry++));
    };
  }

  function fitNow() {
    if (!fit || panel.hidden) return;
    fit.fit();
    send({ type: "resize", cols: term.cols, rows: term.rows });
  }

  async function open() {
    panel.hidden = false; toggle.textContent = "Hide terminal";
    store.set("wt-term-open", "1");
    if (!opened) {
      opened = true;
      term = new Terminal({ fontSize: 13, cursorBlink: true, scrollback: 5000,
        fontFamily: 'ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace',
        theme: { background: "#0b0d11", foreground: "#e6e8ee", cursor: "#7aa2f7" } });
      fit = new FitAddon.FitAddon();
      term.loadAddon(fit);
      term.open(document.getElementById("term"));
      term.onData((data) => send({ type: "input", data }));
      new ResizeObserver(() => fitNow()).observe(document.getElementById("term"));
      await drawClis();
    }
    if (!ws || ws.readyState > WebSocket.OPEN) connect();
    setTimeout(fitNow, 50);
    term.focus();
  }

  function close() {
    panel.hidden = true; toggle.textContent = "Show terminal";
    store.set("wt-term-open", "0");
    // The shell keeps running on the server; closing only detaches this page.
    ws?.close();
  }

  async function drawClis() {
    const box = document.getElementById("term-clis");
    const info = await fetch("/api/terminal/clis", { credentials: "same-origin" }).then((r) => r.json());
    const buttons = info.clis.filter((c) => c.installed).map((c) => {
      const b = document.createElement("button");
      b.textContent = c.label;
      b.title = `Type "${c.cmd}" here to start it. It reads AGENTS.md from this folder.`;
      b.onclick = () => { send({ type: "run", cmd: c.key }); term.focus(); };
      return b;
    });
    const setup = document.createElement("button");
    setup.textContent = buttons.length ? "AI setup…" : "Set up an AI…";
    setup.title = "Choose, install or change the AI assistant that starts here";
    setup.onclick = () => window.wtSetup?.open();
    box.replaceChildren(...buttons, setup);
    return info;
  }

  // drag to resize
  const handle = document.getElementById("term-resize");
  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const move = (ev) => {
      const w = Math.max(320, Math.min(window.innerWidth * 0.7, window.innerWidth - ev.clientX));
      document.documentElement.style.setProperty("--term-width", `${w}px`);
    };
    const up = () => {
      removeEventListener("mousemove", move); removeEventListener("mouseup", up);
      store.set("wt-term-width", getComputedStyle(document.documentElement).getPropertyValue("--term-width").trim());
      fitNow();
    };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  });

  toggle.addEventListener("click", () => (panel.hidden ? open() : close()));
  document.getElementById("term-close").addEventListener("click", close);
  document.getElementById("term-restart").addEventListener("click", () => {
    if (confirm("Close this shell (and anything running in it) and start a new one?")) send({ type: "restart" });
  });
  // The setup wizard (setup.js) opens the panel when an AI is chosen.
  window.wtTerminal = { open, send, refresh: () => (opened ? drawClis() : null),
                        focus: () => term?.focus() };
  if (store.get("wt-term-open") === "1") open();
})();
