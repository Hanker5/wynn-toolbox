"use strict";
// Wynn Toolbox web app. All data is rendered with textContent (never innerHTML),
// because build files can be edited by anyone, including an AI agent.

const $ = (sel) => document.querySelector(sel);
const S = { meta: null, tomes: null, trees: {}, items: {}, builds: [], cur: null, job: null };
const SKILLS = ["str", "dex", "int", "def", "agi"];
const SKILL_NAMES = { str: "Strength", dex: "Dexterity", int: "Intelligence", def: "Defence", agi: "Agility" };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(method, path, body) {
  const r = await fetch(path, {
    method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.detail || r.statusText); e.status = r.status; e.data = data; throw e; }
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}
const fmt = (n) => (typeof n === "number" ? n.toLocaleString() : n ?? "—");
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const slug = (s) => (s || "build").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "build";
const weaponClass = (name) => S.items[name]?.cls;

function show(which) {
  for (const id of ["empty", "editor", "solver"]) $("#" + id).hidden = id !== which;
}

// ------------------------------------------------------------------ item info + autocomplete
async function itemInfo(slot, name) {
  if (!name) return null;
  if (S.items[name]) return S.items[name];
  const it = name.startsWith("CR-")
    ? await api("GET", `/api/item?name=${encodeURIComponent(name)}`).catch(() => null)
    : (await api("GET", `/api/items?slot=${slot}&q=${encodeURIComponent(name)}`)).find((x) => x.name === name);
  if (it) {
    const cls = { wand: "Mage", bow: "Archer", dagger: "Assassin", spear: "Warrior", relik: "Shaman" }[it.type];
    S.items[name] = { ...it, cls };
  }
  return S.items[name] || null;
}

function itemLine(it) {
  if (!it) return [];
  if (it.craft) {
    const ings = it.craft.ingredients.filter((x) => x !== "No Ingredient");
    const ranges = Object.entries(it.craft.ranges).map(([k, [a, b]]) => `${k} ${a}–${b}`);
    return [
      h("span", { class: "tier-Crafted" }, `Crafted ${it.type} · ${it.craft.recipe}`),
      ranges.length ? "  " + ranges.join(" · ") : "",
      it.stats.hp ? `  hp ${fmt(it.stats.hp)}` : "",
      h("div", {}, "Ingredients: " + (ings.join(", ") || "none") + "  ",
        h("a", { href: it.craft.crafter, target: "_blank", rel: "noopener" }, "open in crafter")),
      it.craft.problems.length ? h("div", { class: "tier-Fabled" }, "⚠ " + it.craft.problems.join("; ")) : "",
    ];
  }
  const bits = Object.entries(it.stats).map(([k, v]) => `${k} ${fmt(v)}`);
  const req = it.reqs.map((v, i) => (v ? `${SKILLS[i]} ${v}` : null)).filter(Boolean);
  return [
    h("span", { class: `tier-${it.tier}` }, `${it.tier} · lvl ${it.lvl}`),
    bits.length ? "  " + bits.join(" · ") : "",
    req.length ? `  (needs ${req.join(", ")})` : "",
    " ", ...it.majors.map((m) => h("span", { class: "major" }, m)),
  ];
}

function autocomplete(input, fetchOptions, onPick) {
  const wrap = h("div", { class: "ac" });
  input.replaceWith(wrap); wrap.append(input);
  let list = null, opts = [], sel = -1;
  const close = () => { list?.remove(); list = null; sel = -1; };
  const draw = () => {
    close();
    if (!opts.length) return;
    list = h("div", { class: "ac-list" }, opts.map((o, i) =>
      h("div", { class: "ac-item" + (i === sel ? " sel" : ""), onmousedown: (e) => { e.preventDefault(); pick(i); } },
        h("div", { class: `tier-${o.tier}` }, o.name),
        h("div", { class: "sub" }, itemLine(o)))));
    wrap.append(list);
  };
  const pick = (i) => { const o = opts[i]; input.value = o.name; close(); onPick(o); };
  const load = debounce(async () => { opts = await fetchOptions(input.value).catch(() => []); sel = -1; draw(); }, 150);
  input.addEventListener("input", load);
  input.addEventListener("focus", load);
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", (e) => {
    if (!list) return;
    if (e.key === "ArrowDown") { sel = Math.min(opts.length - 1, sel + 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); }
    else if (e.key === "Enter" && sel >= 0) { pick(sel); e.preventDefault(); }
    else if (e.key === "Escape") close();
  });
  return wrap;
}

// ------------------------------------------------------------------ sidebar
async function loadList() {
  S.builds = await api("GET", "/api/builds");
  const ul = $("#build-list"); ul.replaceChildren();
  if (!S.builds.length) ul.append(h("li", { class: "muted" }, "No builds yet."));
  for (const b of S.builds) {
    const t = b.totals || {};
    const key = t.poison ? `poison ${fmt(t.poison)}` : t.eSteal ? `Stealing ${t.eSteal}%` : `HP ${fmt(t.hp)}`;
    ul.append(h("li", { class: S.cur?.file === b.file ? "active" : "", onclick: () => openBuild(b.file) },
      h("div", { class: "bl-name" }, h("span", { class: "dot " + (b.error ? "bad" : b.verified ? "ok" : "bad") }), b.name),
      h("div", { class: "bl-sub" }, b.error ? "can't read file" : `${b.class || "?"} · lvl ${b.level} · ${key}`)));
  }
}

// ------------------------------------------------------------------ build editor
const EDITABLE = ["name", "notes", "level", "equipment", "tomes", "tree", "powders", "skillpoints"];
const editable = (doc) => Object.fromEntries(EDITABLE.filter((k) => k in doc).map((k) => [k, doc[k]]));

async function openBuild(file, { quiet } = {}) {
  if (S.cur?.dirty && S.cur.file !== file && !confirm("Discard unsaved changes to this build?")) return;
  const doc = await api("GET", `/api/builds/${encodeURIComponent(file)}`);
  S.cur = { file, doc, mtime: doc._mtime, dirty: false, conflict: false, checkError: null };
  await Promise.all(doc.equipment.map((n, i) => itemInfo(S.meta.slots[i], n)));
  await renderEditor();
  loadList();
  if (!quiet) show("editor");
}

async function treeFor(cls) {
  if (!cls) return null;
  S.trees[cls] ??= await api("GET", `/api/tree/${cls}`);
  return S.trees[cls];
}

async function renderEditor() {
  const c = S.cur, d = c.doc, ed = $("#editor");
  ed.replaceChildren(
    h("div", { class: "head" },
      h("input", { class: "name", value: d.name || "", "aria-label": "Build name",
        oninput: (e) => edit((x) => { x.name = e.target.value; }, false) }),
      h("label", { class: "muted" }, "Level ",
        h("input", { class: "level", type: "number", min: 1, max: 121, value: d.level,
          onchange: (e) => edit((x) => { x.level = Math.max(1, Math.min(121, +e.target.value || 1)); }) })),
      h("span", { id: "ed-badge" }),
      h("a", { id: "ed-open", target: "_blank", rel: "noopener" }, h("button", {}, "Open in WynnBuilder")),
      h("button", { onclick: copyLink }, "Copy link"),
      h("button", { id: "ed-revert", onclick: () => openBuild(c.file) }, "Revert"),
      h("button", { id: "ed-save", class: "primary", onclick: save }, "Save")),
    h("div", { id: "ed-banners" }),
    h("div", { id: "ed-tiles", class: "tiles" }),
    h("p", { class: "hint" }, "Big numbers are typical (100%) rolls. \"Perfect\" is a 130% roll, which is what WynnBuilder shows."),
    h("div", { class: "card" }, h("h3", {}, "Skill points needed"), h("div", { id: "ed-sp", class: "sp" })),
    h("div", { class: "card" }, h("h3", {}, "Equipment"), h("div", { id: "ed-equip", class: "equip" })),
    h("div", { class: "card" }, h("h3", {}, "Tomes"), h("div", { id: "ed-tomes", class: "tomes" })),
    h("div", { class: "card" }, h("h3", { id: "ed-tree-h" }), h("div", { id: "ed-tree" })),
    h("div", { class: "card" }, h("h3", {}, "Notes"),
      h("textarea", { rows: 3, value: d.notes || "", oninput: (e) => edit((x) => { x.notes = e.target.value; }, false) })));
  // textarea value must be set as a property
  ed.querySelector("textarea").value = d.notes || "";
  renderEquipment(); renderTomes(); await renderTree(); renderDerived();
}

function renderEquipment() {
  const d = S.cur.doc, box = $("#ed-equip"); box.replaceChildren();
  S.meta.slots.forEach((slot, i) => {
    const shown = (n) => (n && n.startsWith("CR-") ? `Crafted ${S.items[n]?.type || "item"}` : n || "");
    const input = h("input", { value: shown(d.equipment[i]), placeholder: "empty", "aria-label": slot });
    const meta = h("div", { class: "meta" }, itemLine(S.items[d.equipment[i]]));
    const craftBox = h("div", { class: "craft-box", hidden: true });
    const craftBtn = h("button", { class: "mini", title: "Suggest a crafted item for this slot",
      onclick: () => openCraft(slot, i, craftBox, input, meta) }, "Craft…");
    const cls = weaponClass(d.equipment[8]);
    const ac = autocomplete(input,
      // Weapons are not class-filtered so picking one can switch the class.
      (q) => api("GET", `/api/items?slot=${slot}&level=${d.level}` +
        `${slot !== "weapon" && cls ? `&cls=${cls}` : ""}&q=${encodeURIComponent(q)}`),
      (o) => {
        S.items[o.name] = { ...o, cls: { wand: "Mage", bow: "Archer", dagger: "Assassin", spear: "Warrior", relik: "Shaman" }[o.type] };
        const oldCls = weaponClass(d.equipment[8]);
        edit((x) => { x.equipment[i] = o.name; if (slot === "weapon" && S.items[o.name].cls !== oldCls) x.tree = []; });
        meta.replaceChildren(...itemLine(S.items[o.name]));
        if (slot === "weapon") renderTree();
      });
    input.addEventListener("change", () => {
      if (!input.value.trim()) { edit((x) => { x.equipment[i] = null; }); meta.replaceChildren(); }
    });
    box.append(h("div", { class: "slot" },
      h("label", { class: "slot-label" }, slot.replace(/(\d)/, " $1"), craftBtn), ac, meta, craftBox));
  });
}

async function openCraft(slot, i, box, input, meta) {
  if (!box.hidden) { box.hidden = true; return; }
  const d = S.cur.doc, cls = weaponClass(d.equipment[8]);
  const goal = Object.keys(d.spec?.objective || {})[0] || "eSteal";
  const statSel = h("select", {}, S.meta.stats.map((s) => h("option", { value: s }, s)));
  statSel.value = goal;
  const out = h("div");
  const find = async () => {
    out.replaceChildren(h("div", { class: "hint" }, "Searching ingredient layouts…"));
    try {
      const res = await api("POST", "/api/craft-suggest", { slot, level: d.level, cls, objective: { [statSel.value]: 1 }, top: 3 });
      if (!res.length) { out.replaceChildren(h("div", { class: "hint" }, "No valid craft for this slot at this level.")); return; }
      out.replaceChildren(...res.map((r) => h("div", { class: "craft-opt" },
        h("div", { class: "meta" }, itemLine(r)),
        h("button", { class: "mini primary", onclick: () => {
          S.items[r.name] = r;
          edit((x) => { x.equipment[i] = r.name; });
          input.value = `Crafted ${r.type}`; meta.replaceChildren(...itemLine(r)); box.hidden = true;
        } }, "Use this craft"))));
    } catch (e) { out.replaceChildren(h("div", { class: "hint" }, e.message)); }
  };
  box.replaceChildren(h("div", { class: "row" }, "Best crafted", h("strong", {}, ` ${slot.replace(/\d/, "")} `), "for", statSel,
    h("button", { class: "mini", onclick: find }, "Find")), out,
    h("div", { class: "hint" }, "Crafted stats are ranges from the ingredients; the middle of the range counts as typical."));
  box.hidden = false;
  find();
}

function renderTomes() {
  const d = S.cur.doc, box = $("#ed-tomes"); box.replaceChildren();
  d.tomes = d.tomes || Array(14).fill(null);
  S.meta.tome_slots.forEach((slot, k) => {
    const type = slot.replace(/\d+$/, "");
    const sel = h("select", { "aria-label": slot, onchange: (e) => edit((x) => { x.tomes[k] = e.target.value || null; }) },
      h("option", { value: "" }, "— none —"),
      (S.tomes[type] || []).map((t) => h("option", { value: t.name },
        `${t.name} (lvl ${t.lvl})` + (Object.keys(t.stats).length ? " — " + Object.entries(t.stats).map(([a, b]) => `${a} ${b}`).join(", ") : ""))));
    sel.value = d.tomes[k] || "";
    box.append(h("div", { class: "tome" }, h("label", {}, slot.replace(/Tome(\d)/, " tome $1").replace(/Xp/, " XP")), sel));
  });
}

async function renderTree() {
  const d = S.cur.doc, box = $("#ed-tree"), cls = weaponClass(d.equipment[8]);
  const head = $("#ed-tree-h");
  if (!cls) { head.replaceChildren("Ability tree"); box.replaceChildren(h("p", { class: "muted" }, "Pick a weapon to choose a class tree.")); return; }
  const tree = await treeFor(cls);
  const presets = S.meta.presets.filter((p) => p.class === cls);
  const presetSel = h("select", {}, h("option", { value: "" }, "Fill from preset…"), presets.map((p) => h("option", { value: p.name, title: p.about }, p.name)));
  presetSel.onchange = async () => {
    if (!presetSel.value) return;
    const names = await api("POST", "/api/solve-tree", { preset: presetSel.value, level: d.level });
    edit((x) => { x.tree = names; }); drawChips(); presetSel.value = "";
  };
  head.replaceChildren(h("span", { id: "ed-tree-title" }, `${cls} ability tree`),
    h("span", { class: "actions" }, presetSel, h("button", { onclick: () => { edit((x) => { x.tree = []; }); drawChips(); } }, "Clear")));
  const root = tree.find((n) => !n.parents.length);
  const groups = {};
  for (const n of tree) (groups[n.archetype || "Core"] ??= []).push(n);
  function drawChips() {
    const on = new Set(d.tree || []); on.add(root.name);
    const failed = new Set(S.cur.doc.status?.tree_failed || []);
    box.replaceChildren(...Object.entries(groups).map(([arch, nodes]) =>
      h("div", { class: "tree-arch" }, h("div", { class: "t" }, arch),
        h("div", { class: "chips" }, nodes.map((n) =>
          h("span", {
            class: "chip" + (on.has(n.name) ? " on" : "") + (failed.has(n.name) ? " fail" : ""),
            title: `${n.name} — ${n.cost} AP${n.req ? `, needs ${n.req} ${n.archetype}` : ""}\n\n${n.desc}`,
            onclick: () => {
              if (n.name === root.name) return;
              edit((x) => { const s = new Set(x.tree || []); s.has(n.name) ? s.delete(n.name) : s.add(n.name); x.tree = [...s]; });
              drawChips();
            },
          }, n.name, h("span", { class: "c" }, n.cost)))))));
  }
  S.cur.drawChips = drawChips;
  drawChips();
}

function renderDerived() {
  const c = S.cur, d = c.doc, st = d.status || {}, t = st.totals || {};
  const badge = $("#ed-badge");
  badge.replaceChildren(h("span", { class: "badge " + (c.checking ? "pending" : st.verified ? "ok" : "bad") },
    c.checking ? "checking…" : st.verified ? "✓ Verified" : `⚠ ${st.problems?.length || 0} problem(s)`));
  $("#ed-open").href = d.link || "#";
  $("#ed-save").disabled = !c.dirty;
  $("#ed-revert").disabled = !c.dirty;

  const banners = $("#ed-banners"); banners.replaceChildren();
  if (c.conflict) banners.append(h("div", { class: "banner warn" },
    h("span", { class: "grow" }, "This build was changed on disk (maybe by the AI) while you were editing."),
    h("button", { onclick: () => openBuild(c.file) }, "Load their version"),
    h("button", { onclick: () => { c.conflict = false; c.overwrite = true; renderDerived(); } }, "Keep mine")));
  if (c.checkError) banners.append(h("div", { class: "banner bad" }, c.checkError));
  else if (st.problems?.length) banners.append(h("div", { class: "banner bad" },
    h("div", {}, h("strong", {}, "Problems"), h("ul", {}, st.problems.map((p) => h("li", {}, p))))));

  const tile = (k, v, s) => h("div", { class: "tile" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v), s ? h("div", { class: "s" }, s) : null);
  const tm = st.totals_max || {};
  const perfect = (key, suffix = "") => (tm[key] !== undefined && tm[key] !== t[key] ? `perfect: ${fmt(tm[key])}${suffix}` : null);
  const tiles = [
    tile("Health", fmt(t.hp), perfect("hp")),
    tile("Max mana", fmt(st.mana_spare_into_int), `${fmt(st.mana_min_int)} with minimum Int`),
    tile("Mana regen", fmt(t.mr), perfect("mr")),
    tile("Walk speed", `${fmt(t.spd)}%`),
    tile("Skill points", `${fmt(st.sp_total)}/${fmt(st.sp_available)}`),
    tile("Ability points", st.ap ? `${st.ap[0]}/${st.ap[1]}` : "—"),
  ];
  if (t.eSteal) tiles.push(tile("Stealing", `${t.eSteal}%`, perfect("eSteal", "%")));
  if (t.lb) tiles.push(tile("Loot bonus", `${t.lb}%`, perfect("lb", "%")));
  if (t.poison) tiles.push(tile("Poison", fmt(t.poison), `${fmt(st.poison_per_second)}/sec · perfect: ${fmt(tm.poison)}`));
  if (t.sdPct) tiles.push(tile("Spell damage", `${t.sdPct}%`));
  if (t.mdPct) tiles.push(tile("Main attack", `${t.mdPct}%`));
  $("#ed-tiles").replaceChildren(...tiles);

  $("#ed-sp").replaceChildren(...SKILLS.map((s) => {
    const v = st.sp_need?.[s] ?? 0;
    return h("div", { class: v > 100 ? "over" : "" }, h("div", { class: "k muted" }, `${SKILL_NAMES[s]}: ${v}`),
      h("div", { class: "bar" }, h("i", { style: `width:${Math.min(100, v)}%` })));
  }));
  const title = $("#ed-tree-title");
  if (title && st.ap) title.textContent = `${weaponClass(d.equipment[8])} ability tree · ${st.ap[0]}/${st.ap[1]} AP`;
  S.cur.drawChips?.();
}

const runCheck = debounce(async () => {
  const c = S.cur; if (!c) return;
  const sent = JSON.stringify(editable(c.doc));
  try {
    const out = await api("POST", "/api/check", editable(c.doc));
    if (S.cur !== c || JSON.stringify(editable(c.doc)) !== sent) return;   // stale
    c.doc.status = out.status; c.doc.link = out.link; c.checkError = null;
  } catch (e) { c.checkError = e.message; }
  c.checking = false; renderDerived();
}, 350);

function edit(mutate, recheck = true) {
  const c = S.cur; if (!c) return;
  mutate(c.doc); c.dirty = true;
  if (recheck) { c.checking = true; runCheck(); }
  renderDerived();
}

async function save() {
  const c = S.cur;
  try {
    let mtime = c.mtime;
    if (c.overwrite) mtime = (await api("GET", `/api/builds/${encodeURIComponent(c.file)}`))._mtime;
    const out = await api("PUT", `/api/builds/${encodeURIComponent(c.file)}`, { ...editable(c.doc), _mtime: mtime });
    Object.assign(c, { doc: out, mtime: out._mtime, dirty: false, conflict: false, overwrite: false, checkError: null });
    toast(out.status.verified ? "Saved · verified" : "Saved, but the build has problems");
    renderDerived(); loadList();
  } catch (e) {
    if (e.status === 409) { c.conflict = true; renderDerived(); }
    else { c.checkError = e.message; renderDerived(); }
  }
}

async function copyLink() {
  if (!S.cur?.doc.link) return;
  await navigator.clipboard.writeText(S.cur.doc.link).then(() => toast("Link copied"), () => toast(S.cur.doc.link));
}

// ------------------------------------------------------------------ solver
function renderSolver() {
  const m = S.meta, f = {};
  const field = (label, el) => h("label", {}, label, el);
  const num = (name, ph) => (f[name] = h("input", { type: "number", placeholder: ph }));
  f.name = h("input", { placeholder: "e.g. Stealing Summoner" });
  f.cls = h("select", {}, m.classes.map((c) => h("option", { value: c }, c)));
  f.level = h("input", { type: "number", value: 105, min: 1, max: 121 });
  f.goal = h("select", {}, m.stats.map((s) => h("option", { value: s }, s)));
  f.tie = h("select", {}, h("option", { value: "" }, "none"), m.stats.map((s) => h("option", { value: s }, s)));
  f.weapon = h("input", { placeholder: "any" });
  f.mythic = h("input", { type: "checkbox" });
  f.crafted = h("input", { type: "checkbox" });
  f.tomesFrom = h("select", {}, h("option", { value: "" }, "no tomes"), S.builds.map((b) => h("option", { value: b.file }, b.name)));
  f.preset = h("select", {});
  f.topn = h("input", { type: "number", value: 8, min: 4, max: 20 });
  const majors = new Set();
  const majorChips = h("div", { class: "chips" });
  const drawMajors = () => majorChips.replaceChildren(...[...majors].map((k) =>
    h("span", { class: "chip on", title: "remove", onclick: () => { majors.delete(k); drawMajors(); } }, `${k} ✕`)));
  const majorIn = h("select", {}, h("option", { value: "" }, "Add a required major ID…"),
    m.majors.map(([k, name]) => h("option", { value: k }, name)));
  majorIn.onchange = () => { if (majorIn.value) majors.add(majorIn.value); majorIn.value = ""; drawMajors(); };
  const syncPresets = () => {
    f.preset.replaceChildren(h("option", { value: "" }, "none (gear only)"),
      m.presets.filter((p) => p.class === f.cls.value).map((p) => h("option", { value: p.name, title: p.about }, p.name)));
  };
  f.cls.onchange = syncPresets; syncPresets();
  const weaponAc = autocomplete(f.weapon, (q) => api("GET", `/api/items?slot=weapon&cls=${f.cls.value}&level=${f.level.value}&q=${encodeURIComponent(q)}`), () => {});

  const bar = h("i"), status = h("div", { class: "hint" }), cancelBtn = h("button", { class: "danger", hidden: true }, "Cancel");
  const runBtn = h("button", { class: "primary" }, "Find the best build");
  runBtn.onclick = async () => {
    const floors = {};
    for (const k of ["hp", "mr", "spd", "mana", "weapon_dps"]) if (f[k].value !== "") floors[k] = +f[k].value;
    const objective = { [f.goal.value]: 1 };
    if (f.tie.value && f.tie.value !== f.goal.value) objective[f.tie.value] = 0.01;
    let tomes = [];
    if (f.tomesFrom.value) tomes = (await api("GET", `/api/builds/${encodeURIComponent(f.tomesFrom.value)}`)).tomes || [];
    const name = f.name.value.trim() || `${f.cls.value} ${f.goal.value}`;
    let file = slug(name) + ".json", n = 2;
    while (S.builds.some((b) => b.file === file)) file = `${slug(name)}-${n++}.json`;
    const spec = { class: f.cls.value, level: +f.level.value, objective, floors,
      require_major: [...majors], force: f.weapon.value ? { weapon: f.weapon.value } : {},
      exclude_tiers: f.mythic.checked ? ["Mythic"] : [], tomes, topn: +f.topn.value || 8,
      crafted: f.crafted.checked };
    try {
      const { job } = await api("POST", "/api/solve", { spec, file, name, tree_preset: f.preset.value || null });
      runBtn.disabled = true; cancelBtn.hidden = false;
      cancelBtn.onclick = () => api("POST", `/api/jobs/${job}/cancel`);
      const es = new EventSource(`/api/jobs/${job}/events`);
      es.onmessage = async (ev) => {
        const j = JSON.parse(ev.data), p = j.progress;
        if (p) {
          bar.style.width = `${(p.fraction * 100).toFixed(1)}%`;
          const mm = Math.floor(p.elapsed / 60), ss = String(Math.floor(p.elapsed % 60)).padStart(2, "0");
          status.textContent = `${(p.fraction * 100).toFixed(1)}% · ${fmt(p.nodes)} combinations checked · best so far ${p.best ?? "—"} · ${mm}:${ss}`;
        }
        if (j.state !== "running") {
          es.close(); runBtn.disabled = false; cancelBtn.hidden = true;
          if (j.state === "done") { bar.style.width = "100%"; toast("Build found"); await loadList(); openBuild(j.file); }
          else status.textContent = j.state === "cancelled" ? "Cancelled." : `Failed: ${j.error}`;
        }
      };
    } catch (e) { status.textContent = e.message; }
  };

  $("#solver").replaceChildren(
    h("div", { class: "head" }, h("h2", { style: "margin:0;flex:1" }, "New build from goals")),
    h("div", { class: "card" }, h("h3", {}, "Who and what"),
      h("div", { class: "form" }, field("Name", f.name), field("Class", f.cls), field("Level", f.level),
        field("Maximize", f.goal), field("Tiebreaker (tiny weight)", f.tie), field("Tree preset", f.preset))),
    h("div", { class: "card" }, h("h3", {}, "Minimums (leave blank for none)"),
      h("div", { class: "form" }, field("Health", num("hp", "e.g. 17000")), field("Mana regen", num("mr", "e.g. 20")),
        field("Walk speed %", num("spd", "e.g. 0")), field("Max mana", num("mana", "e.g. 113")),
        field("Weapon DPS", num("weapon_dps", "e.g. 700"))),
      h("p", { class: "hint" }, "Health and mana include base stats and the tomes below. Max mana assumes spare skill points go into Intelligence.")),
    h("div", { class: "card" }, h("h3", {}, "Requirements"),
      h("div", { class: "form" }, field("Required major IDs", majorIn), field("Weapon (optional)", weaponAc),
        field("Tomes", f.tomesFrom), field("Shortlist size", f.topn),
        h("label", { class: "check" }, f.mythic, "No mythics"),
        h("label", { class: "check" }, f.crafted, "Include crafted items")),
      majorChips),
    h("div", { class: "card" }, h("h3", {}, "Run"), h("div", { class: "progress" }, bar), status,
      h("div", { class: "row", style: "margin-top:10px" }, runBtn, cancelBtn),
      h("p", { class: "hint" }, "Stats are 100% rolls. The search is exact within each slot's shortlist; raise the shortlist size to double-check a result.")));
}

// ------------------------------------------------------------------ live updates
function watch() {
  const es = new EventSource("/api/events");
  es.onmessage = async (ev) => {
    const { changed, removed } = JSON.parse(ev.data);
    await loadList();
    const c = S.cur; if (!c) return;
    if (removed.includes(c.file)) { toast("This build's file was deleted"); return; }
    if (changed.includes(c.file)) {
      const fresh = await api("GET", `/api/builds/${encodeURIComponent(c.file)}`);
      if (fresh._mtime === c.mtime) return;          // our own save
      if (!c.dirty) { await openBuild(c.file, { quiet: $("#editor").hidden }); toast("Updated from disk"); }
      else { c.conflict = true; renderDerived(); }
    }
  };
}

// ------------------------------------------------------------------ boot
async function boot() {
  if (location.search.includes("token=")) history.replaceState(null, "", "/");  // keep token out of history
  [S.meta, S.tomes] = await Promise.all([api("GET", "/api/meta"), api("GET", "/api/tomes")]);
  $("#version").textContent = `data ${S.meta.version}`;
  $("#new-build").onclick = () => { renderSolver(); show("solver"); };
  $("#import-go").onclick = async () => {
    const link = $("#import-link").value.trim(), name = $("#import-name").value.trim();
    if (!link) return;
    let file = slug(name || "imported") + ".json", n = 2;
    while (S.builds.some((b) => b.file === file)) file = `${slug(name || "imported")}-${n++}.json`;
    try {
      await api("POST", "/api/import", { link, name, file });
      $("#import-msg").textContent = "Imported."; $("#import-link").value = ""; $("#import-name").value = "";
      await loadList(); openBuild(file);
    } catch (e) { $("#import-msg").textContent = e.message; }
  };
  window.addEventListener("beforeunload", (e) => { if (S.cur?.dirty) e.preventDefault(); });
  await loadList();
  watch();
}
boot().catch((e) => { document.body.textContent = "Could not start: " + e.message; });
