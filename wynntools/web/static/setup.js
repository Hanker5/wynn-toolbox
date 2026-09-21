"use strict";
// AI setup wizard: pick an AI CLI, install it in the terminal panel, start it.
// The choice is saved in builds/settings.json; the server starts that AI in
// every fresh terminal, so opening the app opens the AI.

(() => {
  const dlg = document.getElementById("setup");
  const sideBtn = document.getElementById("ai-settings");
  const W = { settings: { ai: null }, info: null, choice: null, step: "pick" };
  const SHELL = "shell";

  const cliOf = (key) => W.info?.clis.find((c) => c.key === key);
  const labelOf = (key) => (key === SHELL ? "Plain terminal" : cliOf(key)?.label || key);

  async function loadInfo() {
    W.info = await api("GET", "/api/terminal/clis");
    return W.info;
  }

  function drawSideButton() {
    const ai = W.settings.ai;
    sideBtn.textContent = ai ? `AI: ${labelOf(ai)} ⚙` : "Set up your AI assistant";
    sideBtn.classList.toggle("primary", !ai);
  }

  // ------------------------------------------------------------ pieces
  function commandBox(cmd) {
    const copy = h("button", { class: "mini", onclick: async () => {
      await navigator.clipboard.writeText(cmd).then(() => toast("Copied"), () => toast(cmd));
    } }, "Copy");
    return h("div", { class: "setup-cmd" }, h("code", {}, cmd), copy);
  }

  function runInTerminal(msg) {
    window.wtTerminal.open();
    window.wtTerminal.send(msg);
    toast("Running in the terminal on the right; watch it there");
  }

  function header(title, sub) {
    return [
      h("div", { class: "setup-head" },
        h("h2", { id: "setup-title" }, title),
        h("button", { class: "setup-x", "aria-label": "Close", onclick: () => dlg.close() }, "✕")),
      sub ? h("p", { class: "muted" }, sub) : null,
    ];
  }

  // ------------------------------------------------------------ steps
  function pickStep() {
    const cards = W.info.clis.map((c) => h("button", {
      class: "setup-card" + (W.choice === c.key ? " on" : ""), "aria-pressed": String(W.choice === c.key),
      onclick: () => { W.choice = c.key; draw(); },
    },
      h("span", { class: "setup-card-title" }, c.label, " ", h("span", { class: "muted" }, "by " + c.vendor)),
      h("span", { class: "badge " + (c.installed ? "ok" : "pending") }, c.installed ? "Installed" : "Not installed yet"),
      h("span", { class: "setup-card-sub" }, c.account)));
    cards.push(h("button", {
      class: "setup-card" + (W.choice === SHELL ? " on" : ""), "aria-pressed": String(W.choice === SHELL),
      onclick: () => { W.choice = SHELL; draw(); },
    },
      h("span", { class: "setup-card-title" }, "No AI, just a terminal"),
      h("span", { class: "setup-card-sub" }, "You can still use every tool yourself, or pick an AI later.")));
    const next = h("button", { class: "primary", disabled: !W.choice, onclick: afterPick }, "Next");
    return [
      ...header("Choose your AI assistant",
        "Wynn Toolbox is driven by an AI assistant that runs in the terminal panel. It reads this " +
        "folder's instructions, runs the tools and explains the results. Pick one you have an account " +
        "for. It will start by itself every time you open Wynn Toolbox, and you can change it any time " +
        "with the AI button in the sidebar."),
      h("div", { class: "setup-cards" }, cards),
      h("div", { class: "setup-foot" },
        W.settings.ai ? null : h("button", { onclick: () => dlg.close() }, "Skip for now"), next),
    ];
  }

  async function afterPick() {
    if (W.choice === SHELL) { await finish(); return; }
    W.step = cliOf(W.choice).installed ? "go" : "install";
    draw();
  }

  function installStep() {
    const c = cliOf(W.choice), node = W.info.node;
    const needNode = c.needs_node && !node.installed;
    const parts = [];
    let n = 1;
    if (needNode) {
      parts.push(h("h3", {}, `${n++}. Install Node.js first`),
        h("p", {}, `${c.label} runs on Node.js, which isn't installed yet.`));
      if (node.install) {
        parts.push(commandBox(node.install),
          h("div", { class: "row" },
            h("button", { onclick: () => runInTerminal({ type: "install-node" }) }, "Install Node.js for me"),
            h("a", { href: node.docs, target: "_blank", rel: "noopener" }, "Other ways to install")));
      } else {
        parts.push(h("p", {}, "Install the LTS version for your system, then come back and click Check again."),
          h("a", { class: "btn", href: node.docs, target: "_blank", rel: "noopener" }, "Download Node.js"));
      }
    }
    parts.push(h("h3", {}, `${n}. Install ${c.label}`), commandBox(c.install),
      h("div", { class: "row" },
        h("button", { class: "primary", disabled: needNode,
                      title: needNode ? "Install Node.js first" : null,
                      onclick: () => runInTerminal({ type: "install", cmd: c.key }) }, `Install ${c.label} for me`),
        h("a", { href: c.docs, target: "_blank", rel: "noopener" }, "Official instructions")));
    const msg = h("span", { class: "msg" });
    return [
      ...header(`Install ${c.label}`,
        "“Install for me” types the command into the terminal panel so you can watch it. It may ask " +
        "you to confirm something or type your password there. When it finishes, click Check again."),
      ...parts,
      h("div", { class: "setup-foot" },
        h("button", { onclick: () => { W.step = "pick"; draw(); } }, "Back"), msg,
        h("button", { onclick: async () => {
          await loadInfo();
          if (cliOf(W.choice).installed) { W.step = "go"; draw(); }
          else { draw(); dlg.querySelector(".setup-foot .msg").textContent =
            `${c.label} isn't found yet. If the install finished, try Check again in a few seconds.`; }
        } }, "Check again")),
    ];
  }

  function goStep() {
    const c = cliOf(W.choice);
    return [
      ...header(`${c.label} is ready`),
      h("ul", { class: "setup-list" },
        h("li", {}, c.login),
        h("li", {}, c.account),
        h("li", {}, "Then tell it what you want, e.g. “make me a Stealing Shaman build with at least 12,000 HP”."),
        h("li", {}, `${c.label} will start by itself whenever you open Wynn Toolbox. To change that, use the AI button in the sidebar.`)),
      h("div", { class: "setup-foot" },
        h("button", { onclick: () => { W.step = "pick"; draw(); } }, "Back"),
        h("button", { class: "primary", onclick: finish }, `Start ${c.label}`)),
    ];
  }

  async function finish() {
    const before = W.settings.ai;
    W.settings = await api("PUT", "/api/settings", { ai: W.choice });
    drawSideButton();
    dlg.close();
    window.wtTerminal.refresh();
    if (W.choice === SHELL) { toast("Saved: plain terminal"); return; }
    const label = labelOf(W.choice);
    // Something may already be running in the shell (another AI, or this one).
    if (W.info.running) {
      if (before === W.choice) { window.wtTerminal.open(); return; }
      if (confirm(`Restart the terminal with ${label} now? Anything running in it will close.`)) {
        window.wtTerminal.open();
        window.wtTerminal.send({ type: "restart" });     // the server starts the saved AI
      } else toast(`${label} will start the next time the terminal does`);
      return;
    }
    window.wtTerminal.open();
    window.wtTerminal.send({ type: "start" });           // starts the saved AI unless it already did
  }

  function draw() {
    const steps = { pick: pickStep, install: installStep, go: goStep };
    dlg.replaceChildren(h("div", { class: "setup-body" }, steps[W.step]()));
  }

  async function open() {
    await loadInfo();
    W.choice = W.settings.ai; W.step = "pick";
    draw();
    if (!dlg.open) dlg.showModal();
  }

  window.wtSetup = { open };
  sideBtn.addEventListener("click", open);

  (async () => {
    W.settings = await api("GET", "/api/settings");
    if (W.settings.ai && W.settings.ai !== SHELL) await loadInfo();
    drawSideButton();
    if (W.settings.ai === null) open();
    else if (W.settings.ai !== SHELL) window.wtTerminal.open();   // the server starts the AI
  })().catch((e) => console.error("setup:", e));
})();
