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

// ------------------------------------------------------------------ game display constants
// Symbols, colours and naming follow WynnBuilder so builds read the same in both.
const ELEMENTS = {
  str: { sym: "✤", name: "Strength", el: "Earth", cls: "earth", def: "eDef" },
  dex: { sym: "✦", name: "Dexterity", el: "Thunder", cls: "thunder", def: "tDef" },
  int: { sym: "❉", name: "Intelligence", el: "Water", cls: "water", def: "wDef" },
  def: { sym: "✹", name: "Defence", el: "Fire", cls: "fire", def: "fDef" },
  agi: { sym: "❋", name: "Agility", el: "Air", cls: "air", def: "aDef" },
};
const ELEM_BY_PREFIX = { e: "str", t: "dex", w: "int", f: "def", a: "agi" };
const ITEM_SPRITE = ["bow", "spear", "wand", "dagger", "relik", "helmet", "chestplate", "leggings",
  "boots", "ring", "bracelet", "necklace"];
const SLOT_TYPE = { helmet: "helmet", chestplate: "chestplate", leggings: "leggings", boots: "boots",
  ring1: "ring", ring2: "ring", bracelet: "bracelet", necklace: "necklace" };
const TYPE_CLASS = { wand: "Mage", bow: "Archer", dagger: "Assassin", spear: "Warrior", relik: "Shaman" };
const CLASS_WEAPON = Object.fromEntries(Object.entries(TYPE_CLASS).map(([w, c]) => [c, w]));
const NODE_ATLAS = { node_0: 0, node_1: 1, node_2: 2, node_3: 4, node_4: 3, node_archer: 5,
  node_warrior: 6, node_mage: 7, node_assassin: 8, node_shaman: 9 };
const ID_INFO = {
  hpBonus: ["Health", ""], hprRaw: ["Health Regen (raw)", ""], hprPct: ["Health Regen", "%"],
  mr: ["Mana Regen", "/5s"], ms: ["Mana Steal", "/3s"], ls: ["Life Steal", "/3s"],
  maxMana: ["Max Mana", ""], spd: ["Walk Speed", "%"], atkTier: ["Attack Speed", " tier"],
  sdPct: ["Spell Damage", "%"], sdRaw: ["Spell Damage (raw)", ""], mdPct: ["Main Attack Damage", "%"],
  mdRaw: ["Main Attack Damage (raw)", ""], poison: ["Poison", "/3s"], eSteal: ["Stealing", "%"],
  lb: ["Loot Bonus", "%"], xpb: ["Combat XP Bonus", "%"], ref: ["Reflection", "%"],
  thorns: ["Thorns", "%"], expd: ["Exploding", "%"], healPct: ["Healing Efficiency", "%"],
  kb: ["Knockback", "%"], jh: ["Jump Height", ""], sprint: ["Sprint", "%"], sprintReg: ["Sprint Regen", "%"],
  gXp: ["Gather XP Bonus", "%"], gSpd: ["Gather Speed", "%"], lq: ["Loot Quality", "%"],
  spRegen: ["Soul Point Regen", "%"], weakenEnemy: ["Weaken Enemy", "%"], slowEnemy: ["Slow Enemy", "%"],
  critDamPct: ["Critical Damage", "%"], rDefPct: ["Elemental Defence", "%"], mainAttackRange: ["Main Attack Range", "%"],
};
const ELEM_NAMES = { e: "Earth", t: "Thunder", w: "Water", f: "Fire", a: "Air", n: "Neutral", r: "Elemental" };
const ID_SUFFIXES = { DamPct: ["Damage", "%"], DefPct: ["Defence", "%"], Def: ["Defence", ""],
  SdPct: ["Spell Damage", "%"], SdRaw: ["Spell Damage", ""], MdPct: ["Main Attack Damage", "%"],
  MdRaw: ["Main Attack Damage", ""], DamRaw: ["Damage", ""], DamAddMin: ["Min Damage", ""], DamAddMax: ["Max Damage", ""] };

/** [label, unit, element key or null] for an ID, named the way WynnBuilder names it. */
function idLabel(key) {
  if (ID_INFO[key]) return [...ID_INFO[key], null];
  if (ELEMENTS[key]) return [ELEMENTS[key].name, "", key];
  const sp = key.match(/^sp(Pct|Raw)(\d)$/);
  if (sp) return [`${["1st", "2nd", "3rd", "4th"][+sp[2] - 1]} Spell Cost`, sp[1] === "Pct" ? "%" : "", null];
  const m = key.match(/^([etwfanr])(DamPct|DefPct|Def|SdPct|SdRaw|MdPct|MdRaw|DamRaw|DamAddMin|DamAddMax)$/);
  if (m) return [`${ELEM_NAMES[m[1]]} ${ID_SUFFIXES[m[2]][0]}`, ID_SUFFIXES[m[2]][1], ELEM_BY_PREFIX[m[1]] || null];
  return [key.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase()), "", null];
}

const sign = (v) => (v > 0 ? `+${fmt(v)}` : fmt(v));
/** replaceChildren, but skipping null/false entries (the DOM would print them as text). */
const setKids = (el, ...kids) => el.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
const majorName = (key) => (S.meta.majors.find(([k]) => k === key)?.[1]) || key.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
function elemTag(key) {
  if (!key) return null;
  const e = ELEMENTS[key];
  return h("span", { class: `el ${e.cls}` }, e.sym + " ");
}

// ------------------------------------------------------------------ icons
function itemIcon(type, size = 44) {
  const idx = ITEM_SPRITE.indexOf(type);
  const el = h("div", { class: "eq-icon", "aria-hidden": "true" });
  if (idx < 0) return el;
  const inner = h("div", { class: "sprite" });
  inner.style.cssText = `width:${size}px;height:${size}px;background-image:url(/assets/items.png);` +
    `background-size:${12 * size}px ${size}px;background-position:-${idx * size}px 0`;
  el.append(inner);
  return el;
}

// ------------------------------------------------------------------ item info + autocomplete
async function itemInfo(slot, name) {
  if (!name) return null;
  if (S.items[name]) return S.items[name];
  const it = name.startsWith("CR-")
    ? await api("GET", `/api/item?name=${encodeURIComponent(name)}`).catch(() => null)
    : (await api("GET", `/api/items?slot=${slot}&q=${encodeURIComponent(name)}`)).find((x) => x.name === name);
  if (it) S.items[name] = { ...it, cls: TYPE_CLASS[it.type] };
  return S.items[name] || null;
}

function displayName(name) {
  if (!name) return "";
  return name.startsWith("CR-") ? `Crafted ${S.items[name]?.type || "item"}` : name;
}

/** One-line summary used under slots and in search results. */
function itemLine(it) {
  if (!it) return [];
  const bits = [];
  if (it.stats.hp) bits.push(h("span", { class: "hp" }, `♥ ${fmt(it.stats.hp)}`));
  bits.push(h("span", { class: "muted" }, it.craft ? it.craft.recipe : `Lv. ${it.lvl}`));
  if (it.slots) bits.push(h("span", { class: "muted" }, `${it.slots} slot${it.slots > 1 ? "s" : ""}`));
  for (const [k, v] of Object.entries(it.stats)) {
    if (k === "hp") continue;
    const [label, unit] = idLabel(k);
    bits.push(h("span", { class: v >= 0 ? "pos" : "neg" }, `${label} ${sign(v)}${unit}`));
  }
  for (const m of it.majors) bits.push(h("span", { class: "major", title: "Major ID" }, majorName(m)));
  const out = [];
  bits.forEach((b, i) => { if (i) out.push(" · "); out.push(b); });
  return out;
}

/** WynnBuilder-style item card, shown on hover. */
function itemCard(it) {
  const title = it.craft ? `Crafted ${it.type}` : it.name;
  const lines = [h("div", { class: `ic-name tier-${it.tier}` }, title),
    h("div", { class: "ic-sub muted" }, it.craft ? `${it.craft.recipe} · materials ${it.craft.mat_tiers.join("/")}`
      : `${it.tier} ${it.type} · Lv. ${it.lvl}` + (it.classReq ? ` · ${it.classReq} only` : ""))];
  if (it.atkSpd) lines.push(h("div", { class: "ic-row" }, h("span", {}, "Attack Speed"),
    h("span", {}, it.atkSpd.replace("_", " ").toLowerCase().replace(/^./, (c) => c.toUpperCase()))));
  for (const [k, v] of Object.entries(it.damage || {})) {
    const el = ELEM_BY_PREFIX[k[0]];
    lines.push(h("div", { class: "ic-row" }, h("span", {}, elemTag(el), `${ELEM_NAMES[k[0]]} Damage`), h("span", {}, v)));
  }
  if (it.hp_base) lines.push(h("div", { class: "ic-row" }, h("span", { class: "hp" }, "♥ Health"), h("span", {}, fmt(it.hp_base))));
  const reqs = it.reqs.map((v, i) => [SKILLS[i], v]).filter(([, v]) => v);
  if (reqs.length) {
    lines.push(h("div", { class: "ic-gap" }));
    for (const [s, v] of reqs) lines.push(h("div", { class: "ic-row muted" },
      h("span", {}, elemTag(s), `${ELEMENTS[s].name} Min`), h("span", {}, fmt(v))));
  }
  const ids = Object.entries(it.ids || {});
  if (ids.length) lines.push(h("div", { class: "ic-gap" }));
  for (const [k, [lo, mid, hi]] of ids) {
    const [label, unit, el] = idLabel(k);
    const range = lo !== hi ? h("span", { class: "muted range" }, ` ${fmt(lo)} to ${fmt(hi)}`) : null;
    lines.push(h("div", { class: "ic-row" }, h("span", {}, elemTag(el), label),
      h("span", {}, h("span", { class: mid >= 0 ? "pos" : "neg" }, `${sign(mid)}${unit}`), range)));
  }
  for (const m of it.majors) lines.push(h("div", { class: "ic-major" }, `+${majorName(m)}`));
  if (it.slots) lines.push(h("div", { class: "ic-sub muted" }, `[${it.slots}] powder slots`));
  if (it.craft) {
    const counts = {};
    for (const x of it.craft.ingredients) if (x !== "No Ingredient") counts[x] = (counts[x] || 0) + 1;
    lines.push(h("div", { class: "ic-gap" }), h("div", { class: "ic-sub" },
      "Ingredients: " + (Object.entries(counts).map(([n, c]) => (c > 1 ? `${c}× ${n}` : n)).join(", ") || "none")));
    if (it.craft.problems.length) lines.push(h("div", { class: "neg" }, "⚠ " + it.craft.problems.join("; ")));
  }
  return h("div", { class: "item-card" }, lines);
}

let tipTimer;
function attachTooltip(el, getItem) {
  const tip = $("#tooltip");
  const showTip = () => {
    const it = getItem();
    if (!it) return;
    tip.replaceChildren(itemCard(it));
    tip.hidden = false;
    const r = el.getBoundingClientRect(), tr = tip.getBoundingClientRect();
    let x = r.right + 10, y = r.top;
    if (x + tr.width > innerWidth - 8) x = Math.max(8, r.left - tr.width - 10);
    y = Math.min(y, innerHeight - tr.height - 8);
    tip.style.left = `${x}px`; tip.style.top = `${Math.max(8, y)}px`;
  };
  el.addEventListener("mouseenter", () => { clearTimeout(tipTimer); tipTimer = setTimeout(showTip, 150); });
  el.addEventListener("mouseleave", () => { clearTimeout(tipTimer); tip.hidden = true; });
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
        itemIcon(o.type, 28),
        h("div", {}, h("div", { class: `tier-${o.tier}` }, o.name), h("div", { class: "sub" }, itemLine(o))))));
    wrap.append(list);
  };
  const pick = (i) => { const o = opts[i]; input.value = o.name; close(); onPick(o); };
  const load = debounce(async () => { opts = await fetchOptions(input.value).catch(() => []); sel = -1; draw(); }, 150);
  input.addEventListener("input", load);
  input.addEventListener("focus", () => { input.select(); load(); });
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
    const key = t.poison ? `poison ${fmt(t.poison)}` : t.eSteal ? `Stealing ${t.eSteal}%` : `♥ ${fmt(t.hp)}`;
    ul.append(h("li", { class: S.cur?.file === b.file ? "active" : "", onclick: () => openBuild(b.file) },
      itemIcon(CLASS_WEAPON[b.class] || "", 28),
      h("div", { class: "bl-text" },
        h("div", { class: "bl-name" }, h("span", { class: "dot " + (b.error ? "bad" : b.verified ? "ok" : "bad") }), b.name),
        h("div", { class: "bl-sub" }, b.error ? "can't read file" : `${b.class || "?"} · Lv. ${b.level} · ${key}`))));
  }
}

// ------------------------------------------------------------------ build editor
const EDITABLE = ["name", "notes", "level", "equipment", "tomes", "tree", "powders", "skillpoints"];
const editable = (doc) => Object.fromEntries(EDITABLE.filter((k) => k in doc).map((k) => [k, doc[k]]));
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
S.roll = store.get("wt-roll") === "perfect" ? "perfect" : "typical";

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

const slotLabel = (slot) => ({ ring1: "Ring 1", ring2: "Ring 2" })[slot] || slot.replace(/^./, (c) => c.toUpperCase());

function rollToggle() {
  const mk = (val, label) => h("button", { class: "seg" + (S.roll === val ? " on" : ""), "aria-pressed": S.roll === val,
    title: val === "typical" ? "Every rolled stat at 100% (typical items)" : "Every rolled stat at 130%, as WynnBuilder shows",
    onclick: () => { S.roll = val; store.set("wt-roll", val); renderEditorSummaryOnly(); } }, label);
  return h("span", { class: "segs", id: "roll-toggle" }, mk("typical", "Typical"), mk("perfect", "Perfect"));
}
function renderEditorSummaryOnly() {
  $("#roll-toggle")?.replaceWith(rollToggle());
  renderDerived();
}

async function renderEditor() {
  const c = S.cur, d = c.doc, ed = $("#editor");
  const notes = h("textarea", { rows: 4, placeholder: "Notes about this build…", "aria-label": "Notes",
    oninput: (e) => edit((x) => { x.notes = e.target.value; }, false) });
  notes.value = d.notes || "";
  const tomesOpen = store.get("wt-tomes-open") === "1";
  const tomesPanel = h("details", { class: "panel", id: "ed-tomes-panel", open: tomesOpen },
    h("summary", { class: "panel-h" }, h("span", { id: "ed-tomes-sum" }, "Tomes")),
    h("div", { id: "ed-tomes", class: "tomes" }));
  tomesPanel.addEventListener("toggle", () => store.set("wt-tomes-open", tomesPanel.open ? "1" : "0"));
  ed.replaceChildren(
    h("div", { class: "ed-head" },
      h("input", { class: "name", value: d.name || "", "aria-label": "Build name",
        oninput: (e) => edit((x) => { x.name = e.target.value; }, false) }),
      h("span", { id: "ed-badge" }),
      h("button", { id: "ed-revert", onclick: () => openBuild(c.file) }, "Revert"),
      h("button", { id: "ed-save", class: "primary", onclick: save }, "Save")),
    h("div", { id: "ed-banners" }),
    h("div", { class: "ed-grid" },
      h("div", { class: "ed-main" },
        h("section", { class: "panel" }, h("div", { id: "ed-equip", class: "equip" })),
        h("section", { class: "panel" }, h("div", { id: "ed-sp", class: "sp" }), h("div", { id: "ed-sp-foot", class: "sp-foot" })),
        tomesPanel,
        h("section", { class: "panel" }, h("div", { class: "panel-h", id: "ed-tree-h" }), h("div", { id: "ed-tree" }))),
      h("aside", { class: "ed-side" },
        h("section", { class: "panel" }, h("div", { class: "panel-h" }, h("span", {}, "Summary"), rollToggle()),
          h("div", { id: "ed-tiles", class: "summary" })),
        h("section", { class: "panel" }, h("div", { class: "panel-h" }, "Checks"), h("div", { id: "ed-checks", class: "summary" })),
        h("section", { class: "panel" }, h("div", { class: "panel-h" }, "Notes"), notes))));
  renderEquipment(); renderTomes(); await renderTree(); renderDerived();
}

function renderEquipment() {
  const d = S.cur.doc, box = $("#ed-equip");
  const col = (slots) => h("div", { class: "eq-col" }, slots.map((s) => slotView(s)));
  const right = col(["ring1", "ring2", "bracelet", "necklace"]);
  right.append(h("div", { class: "eq-extra" },
    h("label", { class: "lvl" }, "Level",
      h("input", { class: "level", type: "number", min: 1, max: 121, value: d.level, "aria-label": "Level",
        onchange: (e) => edit((x) => { x.level = Math.max(1, Math.min(121, +e.target.value || 1)); }) })),
    h("div", { class: "row" },
      h("a", { id: "ed-open", class: "btn", target: "_blank", rel: "noopener" }, "Open in WynnBuilder"),
      h("button", { onclick: copyLink }, "Copy link"))));
  box.replaceChildren(col(["helmet", "chestplate", "leggings", "boots", "weapon"]), right);
}

function slotView(slot) {
  const i = S.meta.slots.indexOf(slot);
  const cur = () => S.cur.doc.equipment[i];
  const cls = weaponClass(S.cur.doc.equipment[8]);
  const typeNow = () => (slot === "weapon" ? (S.items[cur()]?.type || CLASS_WEAPON[weaponClass(cur())] || "") : SLOT_TYPE[slot]);
  const icon = h("div", { class: "eq-icon-wrap" }, itemIcon(typeNow()));
  const input = h("input", { class: "eq-name tier-" + (S.items[cur()]?.tier || "none"), value: displayName(cur()),
    placeholder: `No ${slotLabel(slot).toLowerCase()}`, "aria-label": slot, spellcheck: "false" });
  const meta = h("div", { class: "eq-line" }, itemLine(S.items[cur()]));
  const craftBox = h("div", { class: "craft-box", hidden: true });
  const refresh = () => {
    input.value = displayName(cur());
    input.className = "eq-name tier-" + (S.items[cur()]?.tier || "none");
    icon.replaceChildren(itemIcon(typeNow()));
    meta.replaceChildren(...itemLine(S.items[cur()]));
  };
  const craftBtn = h("button", { class: "mini", title: "Suggest a crafted item for this slot",
    onclick: () => openCraft(slot, i, craftBox, refresh) }, "Craft…");
  const ac = autocomplete(input,
    // Weapons are not class-filtered so picking one can switch the class.
    (q) => api("GET", `/api/items?slot=${slot}&level=${S.cur.doc.level}` +
      `${slot !== "weapon" && cls ? `&cls=${cls}` : ""}&q=${encodeURIComponent(q)}`),
    (o) => {
      S.items[o.name] = { ...o, cls: TYPE_CLASS[o.type] };
      const oldCls = weaponClass(S.cur.doc.equipment[8]);
      edit((x) => { x.equipment[i] = o.name; if (slot === "weapon" && TYPE_CLASS[o.type] !== oldCls) x.tree = []; });
      if (slot === "weapon" && TYPE_CLASS[o.type] !== oldCls) { renderEquipment(); renderTree(); } else refresh();
    });
  input.addEventListener("change", () => {
    if (!input.value.trim()) { edit((x) => { x.equipment[i] = null; }); refresh(); }
  });
  input.addEventListener("blur", () => setTimeout(() => { if (input.value.trim()) input.value = displayName(cur()); }, 160));
  attachTooltip(icon, () => S.items[cur()]);
  attachTooltip(meta, () => S.items[cur()]);
  return h("div", { class: "slot" }, icon,
    h("div", { class: "eq-body" },
      h("div", { class: "eq-top" }, h("span", { class: "eq-label" }, slotLabel(slot)), craftBtn),
      ac, meta, craftBox));
}

async function openCraft(slot, i, box, refresh) {
  if (!box.hidden) { box.hidden = true; return; }
  const d = S.cur.doc, cls = weaponClass(d.equipment[8]);
  const goal = Object.keys(d.spec?.objective || {})[0] || "eSteal";
  const statSel = h("select", { "aria-label": "Stat to maximize" }, S.meta.stats.map((s) => h("option", { value: s }, idLabel(s)[0])));
  statSel.value = goal;
  const out = h("div");
  const find = async () => {
    out.replaceChildren(h("div", { class: "hint" }, "Searching ingredient layouts…"));
    try {
      const res = await api("POST", "/api/craft-suggest", { slot, level: d.level, cls, objective: { [statSel.value]: 1 }, top: 3 });
      if (!res.length) { out.replaceChildren(h("div", { class: "hint" }, "No valid craft for this slot at this level.")); return; }
      out.replaceChildren(...res.map((r) => {
        const opt = h("div", { class: "craft-opt" },
          h("div", { class: "eq-line" }, itemLine(r)),
          h("div", { class: "hint" }, "Ingredients: " + (() => {
            const counts = {};
            for (const x of r.craft.ingredients) if (x !== "No Ingredient") counts[x] = (counts[x] || 0) + 1;
            return Object.entries(counts).map(([n, c]) => (c > 1 ? `${c}× ${n}` : n)).join(", ") || "none";
          })()),
          h("div", { class: "row" },
            h("button", { class: "mini primary", onclick: () => {
              S.items[r.name] = { ...r, cls: TYPE_CLASS[r.type] };
              edit((x) => { x.equipment[i] = r.name; });
              refresh(); box.hidden = true;
            } }, "Use this craft"),
            h("a", { href: r.craft.crafter, target: "_blank", rel: "noopener" }, "open in WynnBuilder crafter")));
        attachTooltip(opt.firstChild, () => r);
        return opt;
      }));
    } catch (e) { out.replaceChildren(h("div", { class: "hint" }, e.message)); }
  };
  box.replaceChildren(h("div", { class: "row" }, "Best crafted", h("strong", {}, ` ${slotLabel(slot).replace(/ \d/, "").toLowerCase()} `), "for", statSel,
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
    const tomes = S.tomes[type] || [];
    const info = h("div", { class: "eq-line" });
    const describe = () => {
      const t = tomes.find((x) => x.name === sel.value);
      info.replaceChildren(...(t ? [h("span", { class: "muted" }, `Lv. ${t.lvl}`),
        ...Object.entries(t.stats).flatMap(([a, b]) => { const [l, u] = idLabel(a); return [" · ", h("span", { class: b >= 0 ? "pos" : "neg" }, `${l} ${sign(b)}${u}`)]; })] : []));
    };
    const sel = h("select", { "aria-label": slot, onchange: (e) => { edit((x) => { x.tomes[k] = e.target.value || null; }); describe(); } },
      h("option", { value: "" }, "— none —"), tomes.map((t) => h("option", { value: t.name }, t.name)));
    sel.value = d.tomes[k] || "";
    describe();
    box.append(h("div", { class: "tome" }, h("label", {}, slot.replace(/Tome(\d)/, " tome $1").replace(/Xp/, " XP").replace(/^./, (c) => c.toUpperCase())), sel, info));
  });
}

// ------------------------------------------------------------------ ability tree (drawn like WynnBuilder's)
const TREE_CELL = 54, TREE_SPRITE = 48;

async function renderTree() {
  const d = S.cur.doc, box = $("#ed-tree"), head = $("#ed-tree-h"), cls = weaponClass(d.equipment[8]);
  if (!cls) {
    head.replaceChildren(h("span", { id: "ed-tree-title" }, "Ability tree"));
    box.replaceChildren(h("p", { class: "muted" }, "Pick a weapon to choose a class tree."));
    S.cur.drawChips = null;
    return;
  }
  const tree = await treeFor(cls);
  const presetSel = h("select", { "aria-label": "Fill tree from preset" }, h("option", { value: "" }, "Fill from preset…"),
    ...S.meta.presets.filter((p) => p.class === cls).map((p) => h("option", { value: p.name, title: p.about }, p.name)));
  presetSel.onchange = async () => {
    if (!presetSel.value) return;
    const names = await api("POST", "/api/solve-tree", { preset: presetSel.value, level: S.cur.doc.level });
    edit((x) => { x.tree = names; }); paint(); presetSel.value = "";
  };
  head.replaceChildren(h("span", { id: "ed-tree-title" }, `${cls} ability tree`),
    h("span", { class: "actions" }, presetSel,
      h("button", { onclick: () => { edit((x) => { x.tree = []; }); paint(); } }, "Clear")));

  const byId = new Map(tree.map((n) => [n.id, n]));
  const root = tree.find((n) => !n.parents.length);
  const rows = Math.max(...tree.map((n) => n.row)) + 1, cols = Math.max(8, ...tree.map((n) => n.col)) + 1;
  const canvas = h("div", { class: "tree-canvas" });
  canvas.style.width = `${cols * TREE_CELL}px`; canvas.style.height = `${rows * TREE_CELL}px`;
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("width", cols * TREE_CELL); svg.setAttribute("height", rows * TREE_CELL);
  svg.setAttribute("class", "tree-lines");
  const mid = (v) => v * TREE_CELL + TREE_CELL / 2;
  const lines = [];
  for (const n of tree) for (const pid of n.parents) {
    const p = byId.get(pid); if (!p) continue;
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", `M${mid(p.col)} ${mid(p.row)} H${mid(n.col)} V${mid(n.row)}`);
    svg.append(path); lines.push([p, n, path]);
  }
  canvas.append(svg);
  const desc = h("div", { class: "tree-desc" });
  const nodes = new Map();
  for (const n of tree) {
    const spr = h("span", { class: "node-spr" });
    const b = h("button", { class: "node", "aria-label": n.name }, spr);
    b.style.left = `${n.col * TREE_CELL}px`; b.style.top = `${n.row * TREE_CELL}px`;
    b.addEventListener("mouseenter", () => describe(n));
    b.addEventListener("focus", () => describe(n));
    b.addEventListener("mouseleave", () => describeDefault());
    b.addEventListener("click", () => {
      if (n.id === root.id) return;
      edit((x) => { const s = new Set(x.tree || []); s.has(n.name) ? s.delete(n.name) : s.add(n.name); x.tree = [...s]; });
      paint(); describe(n);
    });
    nodes.set(n.id, { b, spr });
    canvas.append(b);
  }
  function active() { const on = new Set(S.cur.doc.tree || []); on.add(root.name); return on; }
  function paint() {
    const on = active(), failed = new Set(S.cur.doc.status?.tree_failed || []);
    for (const n of tree) {
      const sel = on.has(n.name);
      const avail = !sel && n.parents.some((pid) => on.has(byId.get(pid)?.name));
      const { b, spr } = nodes.get(n.id);
      spr.style.backgroundPosition = `-${(NODE_ATLAS[n.icon] ?? 0) * TREE_SPRITE}px -${(sel ? 2 : avail ? 1 : 0) * TREE_SPRITE}px`;
      b.classList.toggle("on", sel); b.classList.toggle("fail", failed.has(n.name));
      b.setAttribute("aria-pressed", String(sel));
      b.title = `${n.name} (${n.cost} AP)` + (failed.has(n.name) ? " — can't activate" : "");
    }
    for (const [p, n, path] of lines) path.setAttribute("class", on.has(p.name) && on.has(n.name) ? "on" : "");
  }
  function describe(n) {
    const names = (ids) => ids.map((i) => byId.get(i)?.name).filter(Boolean).join(", ");
    const text = n.desc.replace(/<[^>]*>/g, "").replace(/&emsp;/g, " ").replace(/&nbsp;/g, " ");
    const on = active().has(n.name);
    setKids(desc,
      h("div", { class: "td-name" }, n.name),
      h("div", { class: "muted" }, `${n.cost} AP` + (n.archetype ? ` · ${n.archetype}` : "") +
        (n.req ? ` · needs ${n.req} ${n.archetype} abilities first` : "")),
      h("div", { class: "td-text" }, text),
      n.deps.length ? h("div", { class: "muted" }, `Requires: ${names(n.deps)}`) : null,
      n.blockers.length ? h("div", { class: "muted" }, `Can't be taken with: ${names(n.blockers)}`) : null,
      h("div", { class: on ? "pos" : "muted" }, on ? "Selected — click to remove" : "Click to add"));
  }
  function describeDefault() {
    const on = active();
    desc.replaceChildren(h("div", { class: "td-name" }, `Active abilities: ${on.size}`),
      h("div", { class: "muted" }, "Hover an ability for details. Click to add or remove it."),
      h("ul", { class: "td-list" }, ...tree.filter((n) => on.has(n.name)).map((n) => h("li", {}, n.name))));
  }
  S.cur.drawChips = paint;
  paint(); describeDefault();
  box.replaceChildren(h("div", { class: "tree-wrap" }, h("div", { class: "tree-scroll" }, canvas), desc));
}

// ------------------------------------------------------------------ derived panels
const SUMMARY_ROWS = [
  ["hp", "Health", "", null, true],
  ["hprRaw", "Health Regen (raw)", ""], ["hprPct", "Health Regen", "%"],
  ...SKILLS.map((s) => [ELEMENTS[s].def, `${ELEMENTS[s].el} Defence`, "", s, true]),
  "-",
  ["mr", "Mana Regen", "/5s", null, true], ["ms", "Mana Steal", "/3s"],
  ["__mana", "Max Mana", "", null, true], ["ls", "Life Steal", "/3s"],
  "-",
  ["atkTier", "Attack Speed Bonus", " tier"], ["spd", "Walk Speed", "%", null, true],
  ["sdPct", "Spell Damage", "%"], ["sdRaw", "Spell Damage (raw)", ""],
  ["mdPct", "Main Attack Damage", "%"], ["mdRaw", "Main Attack Damage (raw)", ""],
  ["poison", "Poison", "/3s"],
  ["xpb", "Combat XP Bonus", "%"], ["lb", "Loot Bonus", "%"], ["eSteal", "Stealing", "%"],
  ["ref", "Reflection", "%"], ["thorns", "Thorns", "%"], ["expd", "Exploding", "%"],
];

function statRow(label, value, cls = "", extra = null) {
  return h("div", { class: "srow" }, h("span", { class: "sl" }, label), h("span", { class: "sv " + cls }, value, extra));
}

function renderSummary(st) {
  const t = (S.roll === "perfect" ? st.totals_max : st.totals) || {};
  const out = [];
  for (const r of SUMMARY_ROWS) {
    if (r === "-") { if (out.length && !out[out.length - 1].classList.contains("sep")) out.push(h("div", { class: "sep" })); continue; }
    const [key, label, unit, el, always] = r;
    const v = key === "__mana" ? st.mana_spare_into_int : t[key];
    if (!always && !v) continue;
    const lab = key === "hp" ? h("span", {}, h("span", { class: "hp" }, "♥ "), label) : h("span", {}, elemTag(el), label);
    const cls = key === "hp" || key === "__mana" ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
    let extra = null;
    if (key === "poison" && v) extra = h("span", { class: "muted" }, `  (${fmt(Math.floor(v / 3))}/s)`);
    if (key === "__mana") extra = h("span", { class: "muted" }, `  (${fmt(st.mana_min_int)} at min Int)`);
    out.push(statRow(lab, `${key === "hp" || key === "__mana" ? fmt(v) : sign(v)}${unit}`, cls, extra));
  }
  $("#ed-tiles").replaceChildren(...out,
    h("p", { class: "hint" }, S.roll === "perfect"
      ? "Perfect rolls: every rolled stat at 130%. This matches WynnBuilder's numbers."
      : "Typical rolls: every rolled stat at 100%. Switch to Perfect to match WynnBuilder."));
}

function renderChecks(st) {
  const c = S.cur;
  const ap = st.ap || [0, 0];
  const crafted = c.doc.equipment.filter((n) => n && n.startsWith("CR-")).length;
  setKids($("#ed-checks"),
    statRow("Status", c.checking ? "checking…" : st.verified ? "✓ Verified" : `⚠ ${st.problems?.length || 0} problem(s)`,
      c.checking ? "" : st.verified ? "pos" : "neg"),
    statRow("Skill points", `${fmt(st.sp_total)} / ${fmt(st.sp_available)}`, st.sp_total > st.sp_available ? "neg" : ""),
    statRow("Ability points", `${ap[0]} / ${ap[1]}`, ap[0] > ap[1] ? "neg" : ""),
    crafted ? statRow("Crafted items", `${crafted}`, "", h("span", { class: "muted" }, "  (ranges)")) : null,
    h("p", { class: "hint" }, "Skill points are assigned automatically in the link. Aspects aren't set."));
}

function renderSP(st) {
  const need = st.sp_need || {};
  $("#ed-sp").replaceChildren(...SKILLS.map((s) => {
    const e = ELEMENTS[s], v = need[s] ?? 0;
    return h("div", { class: "sp-box" + (v > 100 ? " over" : "") },
      h("div", { class: `sp-h ${e.cls}` }, `${e.sym} ${e.name}`),
      h("div", { class: "sp-v" }, fmt(v)),
      h("div", { class: "bar" }, h("i", { style: `width:${Math.min(100, v)}%` })),
      h("div", { class: "sp-sub" }, "to assign"));
  }));
  const left = (st.sp_available ?? 0) - (st.sp_total ?? 0);
  $("#ed-sp-foot").replaceChildren("Assigned ", h("strong", {}, fmt(st.sp_total)), " skill points. Remaining: ",
    h("strong", { class: left < 0 ? "neg" : "pos" }, fmt(left)));
}

function renderDerived() {
  const c = S.cur, d = c.doc, st = d.status || {};
  $("#ed-badge").replaceChildren(h("span", { class: "badge " + (c.checking ? "pending" : st.verified ? "ok" : "bad") },
    c.checking ? "checking…" : st.verified ? "✓ Verified" : `⚠ ${st.problems?.length || 0} problem(s)`));
  const open = $("#ed-open"); if (open) open.href = d.link || "#";
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

  renderSP(st); renderSummary(st); renderChecks(st);
  const filled = (d.tomes || []).filter(Boolean).length;
  const sum = $("#ed-tomes-sum"); if (sum) sum.textContent = `Tomes · ${filled}/14 filled`;
  const title = $("#ed-tree-title");
  if (title && st.ap) title.textContent = `${weaponClass(d.equipment[8]) || ""} ability tree · ${st.ap[0]}/${st.ap[1]} AP`;
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
  f.goal = h("select", {}, m.stats.map((s) => h("option", { value: s }, idLabel(s)[0])));
  f.tie = h("select", {}, h("option", { value: "" }, "none"), m.stats.map((s) => h("option", { value: s }, idLabel(s)[0])));
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
      ...m.presets.filter((p) => p.class === f.cls.value).map((p) => h("option", { value: p.name, title: p.about }, p.name)));
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
