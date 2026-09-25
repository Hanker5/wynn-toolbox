"use strict";
// The app window's own title bar and edges (only when the page runs inside the
// borderless pywebview window; a plain browser tab never shows them).
// Python side: wynntools/web/window.py (WindowApi).

// A small in-page question dialog (no native confirm(): it blocks the window).
// buttons: [{label, value, primary?, danger?}]; resolves to the chosen value, or null.
function ask(title, text, buttons) {
  const dlg = document.getElementById("ask");
  return new Promise((resolve) => {
    let answer = null;
    const btns = buttons.map((b) => h("button", {
      class: b.primary ? "primary" : b.danger ? "danger" : "",
      onclick: () => { answer = b.value; dlg.close(); },
    }, b.label));
    dlg.replaceChildren(h("div", { class: "setup-body" },
      h("div", { class: "setup-head" }, h("h2", {}, title)),
      ...(Array.isArray(text) ? text : [text]).map((t) => h("p", {}, t)),
      h("div", { class: "setup-foot" }, btns)));
    dlg.addEventListener("close", () => resolve(answer), { once: true });
    dlg.showModal();
    btns[btns.length - 1].focus();
  });
}

(() => {
  const bar = document.getElementById("titlebar");
  const drag = bar.querySelector(".tb-drag");
  const maxBtn = document.getElementById("tb-max");
  let api = null, native = false, maximized = false;

  function setMaximized(on) {
    maximized = !!on;
    document.body.classList.toggle("maximized", maximized);
    maxBtn.setAttribute("aria-label", maximized ? "Restore" : "Maximize");
    maxBtn.title = maximized ? "Restore" : "Maximize";
  }

  async function toggleMaximize() { setMaximized(await api.toggle_maximize()); }

  async function closeApp() {
    const worries = [];
    if (S.cur?.dirty) worries.push(`Your changes to ${S.cur.doc?.name || S.cur.file} aren't saved.`);
    if (S.job) worries.push("A build search is still running; it will stop.");
    if (worries.length) {
      const go = await ask("Close WynnGPT?", [...worries, "The terminal and any AI running in it will close too."],
        [{ label: "Cancel", value: false }, { label: "Close anyway", value: true, danger: true }]);
      if (!go) return;
    }
    api.close();
  }

  // Moving: a native move (Qt) starts once the mouse has moved a little, so a
  // double-click still reaches the page and maximizes.
  function wireMove() {
    if (!native) { drag.classList.add("pywebview-drag-region"); return; }
    drag.addEventListener("mousedown", (e) => {
      if (e.button !== 0 || e.detail > 1) return;
      const x0 = e.screenX, y0 = e.screenY;
      const move = (m) => {
        if (Math.abs(m.screenX - x0) + Math.abs(m.screenY - y0) < 4) return;
        stop(); api.start_move();
      };
      const stop = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", stop); };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", stop);
    });
  }

  // Resizing from the edges: native on Qt; elsewhere we move/resize ourselves.
  function wireResize() {
    for (const el of document.querySelectorAll(".rz")) {
      const edge = el.dataset.edge;
      el.addEventListener("pointerdown", async (e) => {
        if (e.button !== 0 || maximized) return;
        e.preventDefault();
        if (native) { api.start_resize(edge); return; }
        el.setPointerCapture(e.pointerId);
        const g0 = await api.geometry(), x0 = e.screenX, y0 = e.screenY;
        let pending = null, busy = false;
        const apply = async () => {
          if (busy || !pending) return;
          busy = true; const g = pending; pending = null;
          try { await api.set_geometry(g.x, g.y, g.width, g.height); } finally { busy = false; apply(); }
        };
        const onMove = (m) => {
          const dx = m.screenX - x0, dy = m.screenY - y0, g = { ...g0 };
          if (edge.includes("e")) g.width = g0.width + dx;
          if (edge.includes("s")) g.height = g0.height + dy;
          if (edge.includes("w")) { g.width = g0.width - dx; g.x = g0.x + dx; }
          if (edge.includes("n")) { g.height = g0.height - dy; g.y = g0.y + dy; }
          pending = g; apply();
        };
        const onUp = () => { el.removeEventListener("pointermove", onMove); el.removeEventListener("pointerup", onUp); };
        el.addEventListener("pointermove", onMove);
        el.addEventListener("pointerup", onUp);
      });
    }
  }

  async function start() {
    const a = window.pywebview?.api;
    if (api || !a?.close) return;
    api = a;
    native = await api.native_moves();
    setMaximized(await api.is_maximized());
    document.body.classList.add("app-window");
    bar.hidden = false;
    document.getElementById("tb-min").onclick = () => api.minimize();
    maxBtn.onclick = toggleMaximize;
    document.getElementById("tb-close").onclick = closeApp;
    drag.addEventListener("dblclick", toggleMaximize);
    wireMove();
    wireResize();
    // The window manager can maximize too (keyboard shortcuts, screen edges).
    window.addEventListener("resize", debounce(async () => setMaximized(await api.is_maximized()), 150));
    document.addEventListener("keydown", (e) => {
      if (e.key === "F11") { e.preventDefault(); api.toggle_fullscreen(); }
    });
  }

  window.wtWindow = { get open() { return !!api; } };
  if (window.pywebview?.api?.close) start();
  else window.addEventListener("pywebviewready", start);
})();
