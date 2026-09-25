"use strict";
// Update checker: asks the server (wynntools/updates.py) whether GitHub has a
// newer WynnGPT, and offers Update now / Ignore.

(() => {
  const dlg = document.getElementById("update");
  const sideBtn = document.getElementById("check-updates");
  const barBtn = document.getElementById("tb-update");
  const EVERY = 6 * 3600 * 1000;
  let last = null;

  const short = (sha) => (sha || "").slice(0, 7);
  const when = (iso) => { const d = iso && new Date(iso); return d && !isNaN(d) ? d.toLocaleDateString() : ""; };

  function drawButtons() {
    const on = !!last?.available;
    sideBtn.textContent = on ? "Update available" : "Check for updates";
    sideBtn.classList.toggle("update-on", on);
    barBtn.hidden = !on;
  }

  function changes(r) {
    if (r.ahead_by === null) return "A newer version is on GitHub. (This copy doesn't record its version; updating fixes that.)";
    return `${r.ahead_by} new change${r.ahead_by === 1 ? "" : "s"} on GitHub since your version (${short(r.current)}).`;
  }

  function draw(r) {
    const list = h("ul", { class: "update-list" }, r.commits.map((c) =>
      h("li", {}, c.message || short(c.sha), " ", h("span", { class: "muted" }, when(c.date)))));
    const more = r.ahead_by > r.commits.length ? h("p", { class: "muted" }, `…and ${r.ahead_by - r.commits.length} more.`) : null;
    const worries = [];
    if (S.cur?.dirty) worries.push(`Save your changes to ${S.cur.doc?.name || S.cur.file} first: they'd be lost.`);
    if (S.job) worries.push("A build search is running; updating stops it.");
    const foot = r.can_update
      ? [h("button", { onclick: ignore }, "Ignore"),
         h("button", { class: "primary", onclick: install }, "Update now")]
      : [h("button", { class: "primary", onclick: () => dlg.close() }, "Close")];
    dlg.replaceChildren(h("div", { class: "setup-body" },
      h("div", { class: "setup-head" },
        h("h2", { id: "update-title" }, "Update available"),
        h("button", { class: "setup-x", "aria-label": "Close", onclick: () => dlg.close() }, "✕")),
      h("p", {}, changes(r)),
      list, more,
      r.can_update
        ? h("p", { class: "muted" }, "Updating closes WynnGPT (and the terminal), installs the new version and opens it again. Your builds and settings are kept.")
        : h("p", {}, "This is a developer copy (a git clone): update it with ", h("code", {}, "git pull"), "."),
      worries.length ? h("div", { class: "banner warn" }, h("ul", {}, worries.map((w) => h("li", {}, w)))) : null,
      h("div", { class: "setup-foot" }, h("div", { class: "msg" }), foot)));
  }

  function openDialog() {
    if (!last?.available) return;
    draw(last);
    if (!dlg.open) dlg.showModal();
    dlg.querySelector(".setup-foot button.primary")?.focus();
  }

  async function ignore() {
    try { await api("POST", "/api/update/ignore", { commit: last.latest }); } catch (e) { toast(e.message); return; }
    last.ignored = true;
    dlg.close();
    toast("OK. You'll hear about the next update.");
  }

  async function install() {
    const msg = dlg.querySelector(".setup-foot .msg");
    for (const b of dlg.querySelectorAll("button")) b.disabled = true;
    msg.textContent = "Starting the update…";
    try {
      await api("POST", "/api/update/install", { commit: last.latest });
    } catch (e) {
      msg.textContent = `Couldn't start the update: ${e.message}`;
      for (const b of dlg.querySelectorAll("button")) b.disabled = false;
      return;
    }
    const reopen = window.wtWindow?.open
      ? "WynnGPT will close now and open again by itself when the update is done (a minute or two)."
      : "WynnGPT will stop now and open a new tab when the update is done (a minute or two). You can close this one.";
    dlg.replaceChildren(h("div", { class: "setup-body" },
      h("div", { class: "setup-head" }, h("h2", {}, "Updating…")),
      h("p", {}, reopen),
      h("div", { class: "progress busy" }, h("i", {}))));
    dlg.addEventListener("cancel", (e) => e.preventDefault());
  }

  async function check({ manual = false } = {}) {
    let r;
    try { r = await api("GET", `/api/update${manual ? "?force=true" : ""}`); }
    catch (e) { if (manual) toast(`Couldn't check for updates: ${e.message}`); return; }
    if (r.last_update) {
      toast(r.last_update.ok ? `Updated to ${short(r.last_update.to)}` : "The last update failed; see builds/update.log");
    }
    if (r.disabled) return;
    last = r;
    drawButtons();
    if (r.error) { if (manual) toast(`Couldn't check for updates: ${r.error}`); return; }
    if (!r.available) { if (manual) toast("WynnGPT is up to date"); return; }
    if (manual || !r.ignored) whenFree(openDialog);
  }

  // Don't cover the AI setup wizard: wait until it is closed.
  function whenFree(fn) {
    const setup = document.getElementById("setup");
    if (setup.open) setup.addEventListener("close", () => whenFree(fn), { once: true });
    else fn();
  }

  sideBtn.addEventListener("click", () => (last?.available ? openDialog() : check({ manual: true })));
  barBtn.addEventListener("click", openDialog);
  window.wtUpdates = { check };
  setTimeout(() => check(), 1500);        // after the setup wizard has had a chance to open
  setInterval(() => check(), EVERY);
})();
