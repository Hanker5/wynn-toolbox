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
// action: optional {label, onclick}, e.g. Undo; the toast then stays up longer.
function toast(msg, action) {
  const t = $("#toast"); t.replaceChildren(msg); t.classList.add("show");
  t.classList.toggle("has-action", !!action);
  if (action) t.append(h("button", { class: "mini", onclick: () => { t.classList.remove("show"); action.onclick(); } }, action.label));
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show", "has-action"), action ? 8000 : 2600);
}
const fmt = (n) => (typeof n === "number" ? n.toLocaleString() : n ?? "—");
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const slug = (s) => (s || "build").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "build";
const weaponClass = (name) => S.items[name]?.cls;

function show(which) {
  for (const id of ["empty", "editor", "solver", "inventory", "compare"]) $("#" + id).hidden = id !== which;
  reportView();
}

// Tell the server what this page shows, so the AI in the terminal can act on
// "this build" (`wt current`), including edits the player hasn't saved yet.
const VIEWS = ["empty", "editor", "solver", "inventory", "compare"];
const reportView = debounce(() => {
  if (document.hidden) return;                     // the tab the player is looking at wins
  const view = VIEWS.find((id) => !$("#" + id).hidden) || "empty";
  const c = S.cur;
  api("PUT", "/api/view", { view, file: c?.file ?? null, dirty: !!c?.dirty,
    doc: c?.dirty ? editable(c.doc) : null }).catch(() => {});
}, 300);

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
/** Item-type icon from WynnBuilder's sprite sheet, with its tier-coloured glow. */
function itemIcon(type, size = 44, tier = null) {
  const idx = ITEM_SPRITE.indexOf(type);
  const el = h("div", { class: "eq-icon", "aria-hidden": "true" });
  if (idx < 0) return el;
  const inner = h("div", { class: "sprite" + (tier ? ` ${tier}-shadow` : "") });
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
  if (it.set) lines.push(h("div", { class: "ic-set" }, `${it.set} set piece`));
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
        itemIcon(o.type, 28, o.tier),
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

/** A search box over grouped options ({key, label, group, disabled?}): type to filter (every word
 * must match the label, key or group), arrows and Enter to pick, Escape to close. */
function searchPicker({ label, placeholder, options, onPick }) {
  const input = h("input", { type: "text", role: "combobox", "aria-label": label, placeholder, autocomplete: "off",
    "aria-autocomplete": "list", "aria-expanded": "false" });
  const wrap = h("div", { class: "ac picker" }, input);
  let list = null, shown = [], sel = -1;
  const close = () => { list?.remove(); list = null; sel = -1; input.setAttribute("aria-expanded", "false"); };
  const matches = () => {
    const words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    return options().filter((o) => { const hay = `${o.label} ${o.key} ${o.group}`.toLowerCase(); return words.every((w) => hay.includes(w)); });
  };
  const draw = () => {
    list?.remove();
    shown = matches();
    const pickable = shown.filter((o) => !o.disabled);
    if (sel >= pickable.length) sel = pickable.length - 1;
    const kids = []; let group = null, n = 0;
    for (const o of shown) {
      if (o.group !== group) { group = o.group; kids.push(h("div", { class: "pk-group" }, group)); }
      const idx = o.disabled ? -1 : n++;
      kids.push(h("div", { class: "pk-item" + (o.disabled ? " off" : "") + (!o.disabled && idx === sel ? " sel" : ""), role: "option",
        "aria-disabled": o.disabled ? "true" : null, "aria-selected": !o.disabled && idx === sel ? "true" : "false",
        onmousedown: (e) => { e.preventDefault(); if (!o.disabled) choose(o); } }, o.label));
    }
    list = h("div", { class: "ac-list pk-list", role: "listbox" }, kids.length ? kids : h("div", { class: "pk-none" }, "No match"));
    wrap.append(list);
    input.setAttribute("aria-expanded", "true");
    list.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
  };
  const choose = (o) => { input.value = ""; close(); onPick(o.key); input.focus(); };
  input.addEventListener("input", () => { sel = input.value.trim() ? 0 : -1; draw(); });
  input.addEventListener("focus", draw);
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", (e) => {
    const pickable = shown.filter((o) => !o.disabled);
    if (e.key === "ArrowDown") { if (!list) draw(); sel = Math.min(pickable.length - 1, sel + 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); }
    else if (e.key === "Enter" && list && pickable.length) { choose(pickable[Math.max(0, sel)]); e.preventDefault(); }
    else if (e.key === "Escape") close();
  });
  wrap.refresh = () => { if (list) draw(); };      // options changed while the list is open
  return wrap;
}

// ------------------------------------------------------------------ inventory
S.inv = { items: {}, tomes: [], crafts: [] };
const owns = (name) => !!name && (name in S.inv.items || S.inv.crafts.includes(name));
async function loadInventory() {
  S.inv = await api("GET", "/api/inventory");
  const n = Object.keys(S.inv.items).length + S.inv.crafts.length;
  $("#open-inventory").textContent = `Inventory · ${n} item${n === 1 ? "" : "s"}`;
}
async function setOwned(name, own, extra = {}) {
  const kind = name.startsWith("CR-") ? "craft" : extra.kind || "item";
  S.inv = await api("POST", "/api/inventory", { action: own ? "add" : "remove", kind, name, ...extra });
  await loadInventory();
  if (S.cur && !$("#editor").hidden) { S.cur.checking = true; runCheck(); }
}
function ownButton(getName) {
  const b = h("button", { class: "mini own", title: "Mark whether you own this item" });
  const draw = () => {
    const n = getName();
    b.disabled = !n;
    b.textContent = owns(n) ? "★ Owned" : "☆ Own";
    b.classList.toggle("on", owns(n));
  };
  b.onclick = async () => { const n = getName(); if (n) { await setOwned(n, !owns(n)); draw(); } };
  draw();
  b.redraw = draw;
  return b;
}

async function renderInventory() {
  await loadInventory();
  const inv = S.inv, box = $("#inventory");
  const names = [...Object.keys(inv.items), ...inv.crafts];
  await Promise.all(names.map((n) => itemInfo("any", n)));
  const addInput = h("input", { placeholder: "Search any item to add…", "aria-label": "Add owned item" });
  const addAc = autocomplete(addInput, (q) => api("GET", `/api/items?slot=any&q=${encodeURIComponent(q)}`),
    async (o) => { S.items[o.name] = { ...o, cls: TYPE_CLASS[o.type] }; await setOwned(o.name, true); renderInventory(); });
  const rows = names.sort().map((n) => {
    const it = S.items[n];
    const rolls = (inv.items[n] || {}).rolls || {};
    const rolled = Object.entries(it?.ids || {}).filter(([, [lo, , hi]]) => lo !== hi);
    const inputs = rolled.map(([k, [lo, mid, hi]]) => {
      const [label, unit] = idLabel(k);
      const inp = h("input", { type: "number", placeholder: `${mid}`, title: `${label}: rolls ${lo} to ${hi}${unit}`,
        "aria-label": `${n} ${label}`, value: rolls[k] ?? "" });
      inp.dataset.id = k;
      return h("label", { class: "roll" }, h("span", { class: "muted" }, `${label}${unit ? ` (${unit.trim()})` : ""}`), inp);
    });
    const save = h("button", { class: "mini", onclick: async () => {
      const r = {};
      for (const inp of card.querySelectorAll("input[data-id]")) if (inp.value !== "") r[inp.dataset.id] = +inp.value;
      await setOwned(n, true, { rolls: r }); toast("Rolls saved");
    } }, "Save rolls");
    const card = h("div", { class: "inv-item" },
      h("div", { class: "row" }, itemIcon(it?.type, 32, it?.tier),
        h("span", { class: `tier-${it?.tier} inv-name` }, displayName(n)),
        h("span", { class: "grow" }),
        rolled.length && !n.startsWith("CR-") ? save : null,
        h("button", { class: "mini danger", onclick: async () => { await setOwned(n, false); renderInventory(); } }, "Remove")),
      rolled.length && !n.startsWith("CR-") ? h("div", { class: "rolls" }, inputs) : null,
      h("div", { class: "eq-line" }, itemLine(it)));
    attachTooltip(card.querySelector(".eq-icon"), () => S.items[n]);
    return card;
  });
  const tomeTypes = Object.keys(S.tomes).sort();
  const tomeSel = h("select", { "aria-label": "Add owned tome" }, h("option", { value: "" }, "Add a tome you own…"),
    ...tomeTypes.map((t) => h("optgroup", { label: t }, ...S.tomes[t].map((x) => h("option", { value: x.name }, x.name)))));
  tomeSel.onchange = async () => { if (tomeSel.value) { await setOwned(tomeSel.value, true, { kind: "tome" }); renderInventory(); } };
  setKids(box,
    h("div", { class: "head" }, h("h2", { style: "margin:0;flex:1" }, "Inventory")),
    h("p", { class: "hint" }, "Mark the items you own. The solver can then build only from these (\"Only items I own\") and rank what to get next. Enter real roll values if you know them; blank means a typical 100% roll."),
    h("section", { class: "panel" }, h("div", { class: "panel-h" }, `Items · ${names.length}`), addAc,
      rows.length ? h("div", { class: "inv-list" }, rows) : h("p", { class: "muted" }, "Nothing yet. Search above, or use the ☆ Own button on a build's items.")),
    h("section", { class: "panel" }, h("div", { class: "panel-h" }, `Tomes · ${inv.tomes.length}`), tomeSel,
      h("div", { class: "inv-list" }, inv.tomes.map((t, i) => h("div", { class: "row inv-tome" }, h("span", {}, t), h("span", { class: "grow" }),
        h("button", { class: "mini danger", onclick: async () => { await setOwned(t, false, { kind: "tome" }); renderInventory(); } }, "Remove"))))));
}

// ------------------------------------------------------------------ sidebar
async function loadList() {
  S.builds = await api("GET", "/api/builds");
  const ul = $("#build-list"); ul.replaceChildren();
  if (!S.builds.length) ul.append(h("li", { class: "muted" }, "No builds yet."));
  const files = new Set(S.builds.map((b) => b.file));
  const kids = (f) => S.builds.filter((b) => b.parent === f);
  const item = (b, cand) => {
    const t = b.totals || {};
    const key = t.poison ? `poison ${fmt(t.poison)}` : t.eSteal ? `Stealing ${t.eSteal}%` : `♥ ${fmt(t.hp)}`;
    const n = kids(b.file).length;
    return h("li", { class: (S.cur?.file === b.file ? "active" : "") + (cand ? " cand" : ""), onclick: () => openBuild(b.file) },
      itemIcon(CLASS_WEAPON[b.class] || "", cand ? 22 : 28),
      h("div", { class: "bl-text" },
        h("div", { class: "bl-name" }, h("span", { class: "dot " + (b.error ? "bad" : b.verified ? "ok" : "bad") }),
          cand && b.name.includes(": ") ? b.name.slice(b.name.indexOf(": ") + 2) : b.name,
          n ? h("span", { class: "badge-count", title: `${n} candidate${n > 1 ? "s" : ""}` }, n) : null),
        h("div", { class: "bl-sub" }, b.error ? "can't read file" : `${cand ? "candidate · " : `${b.class || "?"} · Lv. ${b.level} · `}${key}`)));
  };
  for (const b of S.builds) {
    if (b.parent && files.has(b.parent)) continue;           // listed under its build
    ul.append(item(b, false));
    for (const k of kids(b.file)) ul.append(item(k, true));
  }
}

// ------------------------------------------------------------------ build editor
const EDITABLE = ["name", "notes", "level", "equipment", "tomes", "tree", "powders", "aspects", "skillpoints", "locked"];
const editable = (doc) => Object.fromEntries(EDITABLE.filter((k) => k in doc).map((k) => [k, doc[k]]));
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
S.roll = store.get("wt-roll") === "perfect" ? "perfect" : "typical";

async function openBuild(file, { quiet, force } = {}) {
  if (!force && S.cur?.dirty && S.cur.file !== file && !confirm("Discard unsaved changes to this build?")) return;
  const doc = await api("GET", `/api/builds/${encodeURIComponent(file)}`);
  S.cur = { file, doc, mtime: doc._mtime, dirty: false, conflict: false, checkError: null };
  await Promise.all(doc.equipment.map((n, i) => itemInfo(S.meta.slots[i], n)));
  await renderEditor();
  loadList();
  if (!quiet) show("editor"); else reportView();
}

// Deleting moves the file to builds/.trash on the server, so Undo can bring it back.
async function deleteBuild() {
  const c = S.cur, name = c.doc.name || c.file;
  const text = [`${c.file} will be moved to builds/.trash, where you can still get it back.`];
  if (c.dirty) text.push("Its unsaved changes will be lost.");
  const go = await ask(`Delete “${name}”?`, text,
    [{ label: "Delete", value: true, danger: true }, { label: "Cancel", value: false }]);
  if (!go || S.cur !== c) return;
  let r;
  try { r = await api("DELETE", `/api/builds/${encodeURIComponent(c.file)}`); }
  catch (e) { toast(`Couldn't delete ${c.file}: ${e.message}`); return; }
  S.cur = null;
  await loadList();
  show("empty");
  toast(`Deleted “${name}”`, { label: "Undo", onclick: async () => {
    try { await api("POST", "/api/trash/restore", { trash: r.trash, file: r.file }); }
    catch (e) { toast(`Couldn't restore it: ${e.message}`); return; }
    await openBuild(r.file);
    toast(`Restored “${name}”`);
  } });
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
  const aspectsPanel = h("details", { class: "panel", id: "ed-aspects-panel", open: store.get("wt-aspects-open") === "1" },
    h("summary", { class: "panel-h" }, h("span", { id: "ed-aspects-sum" }, "Aspects")),
    h("div", { id: "ed-aspects", class: "aspects" }));
  aspectsPanel.addEventListener("toggle", () => store.set("wt-aspects-open", aspectsPanel.open ? "1" : "0"));
  ed.replaceChildren(
    h("div", { class: "ed-head" },
      h("input", { class: "name", value: d.name || "", "aria-label": "Build name",
        oninput: (e) => edit((x) => { x.name = e.target.value; }, false) }),
      h("span", { id: "ed-badge" }),
      h("button", { id: "ed-delete", class: "danger", title: "Delete this build (it goes to builds/.trash)",
        onclick: deleteBuild }, "Delete"),
      h("button", { id: "ed-improve", title: "Search for a better build from this one (results become candidates)",
        onclick: () => (c.dirty ? toast("Save (or revert) your changes first") : openSolverFor(c)) }, "Improve…"),
      h("button", { id: "ed-revert", onclick: () => openBuild(c.file) }, "Revert"),
      h("button", { id: "ed-save", class: "primary", onclick: save }, "Save")),
    h("div", { id: "ed-banners" }),
    h("div", { class: "ed-grid" },
      h("div", { class: "ed-main" },
        h("section", { class: "panel" }, h("div", { id: "ed-equip", class: "equip" })),
        h("section", { class: "panel", id: "ed-cands-panel", hidden: true },
          h("div", { class: "panel-h" }, h("span", {}, "Candidates"), h("span", { class: "actions", id: "ed-cands-actions" })),
          h("div", { id: "ed-cands" })),
        h("section", { class: "panel" }, h("div", { id: "ed-sp", class: "sp" }), h("div", { id: "ed-sp-foot", class: "sp-foot" })),
        tomesPanel, aspectsPanel, powderPanel(),
        h("section", { class: "panel" }, h("div", { class: "panel-h", id: "ed-tree-h" }), h("div", { id: "ed-tree" }))),
      h("aside", { class: "ed-side" },
        h("section", { class: "panel", id: "ed-surv-panel" }, h("div", { class: "panel-h" }, h("span", {}, "Survivability"), rollToggle()),
          h("div", { id: "ed-surv", class: "summary" })),
        h("section", { class: "panel" }, h("div", { class: "panel-h" }, h("span", {}, "Summary")),
          h("div", { id: "ed-tiles", class: "summary" })),
        h("section", { class: "panel", id: "ed-damage-panel", hidden: true },
          h("div", { class: "panel-h" }, h("span", { id: "ed-damage-h" }, "Damage")),
          h("div", { id: "ed-damage", class: "summary" })),
        h("section", { class: "panel", id: "ed-sets-panel", hidden: true }, h("div", { class: "panel-h" }, "Set bonuses"),
          h("div", { id: "ed-sets", class: "summary" })),
        h("section", { class: "panel" }, h("div", { class: "panel-h" }, "Checks"), h("div", { id: "ed-checks", class: "summary" })),
        h("section", { class: "panel" }, h("div", { class: "panel-h" }, "Notes"), notes))));
  renderEquipment(); renderTomes(); await renderTree(); await renderAspects(); renderDerived();
  renderCandidates();
}

// ------------------------------------------------------------------ powder planner
function powderPanel() {
  const panel = h("details", { class: "panel", id: "ed-powder-panel", open: store.get("wt-powders-open") === "1" },
    h("summary", { class: "panel-h" }, "Powder planner"), h("div", { id: "ed-powder" }));
  panel.addEventListener("toggle", () => { store.set("wt-powders-open", panel.open ? "1" : "0"); if (panel.open) renderPowderPlanner(); });
  if (panel.open) setTimeout(renderPowderPlanner);
  return panel;
}

function renderPowderPlanner() {
  const box = $("#ed-powder"); if (!box) return;
  const d = S.cur.doc, cls = weaponClass(d.equipment[8]);
  const dmg = d.status?.damage?.typical;
  const measures = [["melee_dps", "Main-attack DPS"], ...(cls === "Shaman" ? [["puppet_dps", "Puppet DPS"], ["summon_dps", "Total summon DPS"]] : []),
    ...((dmg?.spells || []).slice(1).filter((sp) => sp.summary != null && sp.summary_type !== "heal").map((sp) => [`damage:${sp.name}`, sp.name]))];
  const wgoal = h("select", { "aria-label": "Weapon powder goal" }, h("option", { value: "" }, "leave the weapon"),
    h("optgroup", { label: "Passive damage" }, measures.map(([k, l]) => h("option", { value: k }, l))),
    h("optgroup", { label: "Powder-special playstyle" }, S.meta.specials.map((x) => h("option", { value: `special:${x.weapon}` }, `${x.weapon} (${ELEMENTS[ELEM_OF[x.element]].el})`))));
  wgoal.value = measures[0][0];
  const measure = h("select", { "aria-label": "Damage to score a special by" }, measures.map(([k, l]) => h("option", { value: k }, l)));
  const agoal = h("select", { "aria-label": "Armor powder goal" }, h("option", { value: "" }, "leave the armor"),
    h("option", { value: "hp" }, "Most health"), h("option", { value: "eledef" }, "Balanced elemental defence"),
    h("optgroup", { label: "Armor-special playstyle" }, S.meta.specials.map((x) => h("option", { value: `special:${x.element}` }, `${x.armor} (${ELEMENTS[ELEM_OF[x.element]].el})`))));
  agoal.value = "eledef";
  const tier = h("select", { "aria-label": "Powder tier" }, [7, 6, 5, 4, 3, 2, 1].map((t) => h("option", { value: t }, `tier ${t}`)));
  const out = h("div");
  const sync = () => { measure.closest("label").hidden = !wgoal.value.startsWith("special:"); };
  wgoal.onchange = sync;
  const n = (v) => fmt(Math.round(v));
  const go = h("button", { class: "mini primary", onclick: async () => {
    out.replaceChildren(h("p", { class: "hint" }, "Trying every mix…"));
    try {
      const r = await api("POST", "/api/powders", { doc: editable(d), weapon_goal: wgoal.value || null, armor_goal: agoal.value || null,
        tier: +tier.value, measure: measure.value });
      const kids = [];
      if (r.weapon) {
        const w = r.weapon, label = measures.find(([k]) => k === w.measure)?.[1] || w.measure;
        kids.push(h("div", { class: "plan", id: "plan-weapon" }, h("strong", {}, "Weapon: "), w.powders.join(" "),
          h("div", {}, `${label}: ${n(w.before)} → `, h("strong", { class: w.value >= w.before ? "pos" : "neg" }, n(w.value))),
          w.burst?.average != null ? h("div", { class: "muted" }, `${w.burst.name} hit: ${n(w.burst.average)}`) : null,
          h("div", { class: "hint" }, w.special ? `With ${w.special.weapon[0]} on at power ${w.special.weapon[1]}; the Damage panel's main numbers keep specials off.`
            : "Powder specials off (as WynnBuilder shows)."),
          h("button", { class: "mini", onclick: () => { edit((x) => { x.powders = x.powders || [[], [], [], [], []]; x.powders[4] = w.powders; }); renderEquipment(); toast("Weapon powders applied. Save to keep them."); } }, "Apply")));
      } else if (wgoal.value) kids.push(h("p", { class: "hint" }, "The weapon has no powder slots."));
      if (r.armor) {
        const a = r.armor, lowB = a.before.lowest, lowA = a.lowest;
        kids.push(h("div", { class: "plan", id: "plan-armor" }, h("strong", {}, "Armor: "),
          Object.entries(a.powders).filter(([, v]) => v.length).map(([s, v]) => `${slotLabel(s)} ${v.join(" ")}`).join(" · ") || "no slots",
          h("div", {}, `Health ${n(a.before.hp)} → `, h("strong", {}, n(a.hp)), ` · lowest elemental defence ${n(lowB)} → `,
            h("strong", { class: lowA < 0 ? "neg" : "pos" }, n(lowA))),
          h("button", { class: "mini", onclick: () => { edit((x) => { x.powders = x.powders || [[], [], [], [], []]; ["helmet", "chestplate", "leggings", "boots"].forEach((s, k) => { x.powders[k] = a.powders[s]; }); }); renderEquipment(); toast("Armor powders applied. Save to keep them."); } }, "Apply")));
      }
      setKids(out, kids.length ? kids : h("p", { class: "hint" }, "Pick a goal."));
    } catch (e) { out.replaceChildren(h("p", { class: "neg" }, e.message)); }
  } }, "Suggest");
  setKids(box, h("div", { class: "form" }, h("label", {}, "Weapon", wgoal), h("label", {}, "Score the special by", measure),
      h("label", {}, "Armor", agoal), h("label", {}, "Tier", tier)),
    h("div", { class: "row", style: "margin-top:8px" }, go), out,
    h("p", { class: "hint" }, "Weapon and armor are planned separately. Weapon: every order of every element at the tier (order matters: the first powder converts first). " +
      "A powder special needs two or more tier IV+ powders of its element; the tiers set its power. " +
      "Armor: every mix of elements (health is the same for any element). Typical rolls, with this build's tree."));
  sync();
}

// ------------------------------------------------------------------ candidates
// Builds a search made for this one ("parent" in the file). Compare, use one, trash the rest.
async function renderCandidates() {
  const c = S.cur, panel = $("#ed-cands-panel"); if (!panel) return;
  if (!S.builds.some((b) => b.parent === c.file)) { panel.hidden = true; return; }
  let r;
  try { r = await api("GET", `/api/builds/${encodeURIComponent(c.file)}/candidates`); } catch { return; }
  if (S.cur !== c) return;
  panel.hidden = !r.candidates.length;
  const n = (v) => (v == null ? "—" : fmt(Math.round(v)));
  const pup = [r.parent, ...r.candidates].some((x) => x.row?.puppet_dps != null);
  const cells = (row) => [n(row.hp), n(row.ehp), n(row.hpr), n(row.lowest_eledef), n(row.sp_total), n(row.melee_dps),
    ...(pup ? [n(row.puppet_dps)] : [])].map((v) => h("td", {}, v));
  const rows = [h("tr", { class: "cand-parent" }, h("td", {}, h("strong", {}, "This build")), ...cells(r.parent.row), h("td", {}))];
  for (const x of r.candidates) {
    rows.push(h("tr", {}, h("td", { title: x.file }, h("span", { class: "dot " + (x.verified ? "ok" : "bad") }), " ", x.name.replace(`${c.doc.name}: `, "")),
      ...(x.row ? cells(x.row) : [h("td", { colspan: pup ? 7 : 6, class: "neg" }, x.error)]),
      h("td", { class: "cand-actions" },
        h("button", { class: "mini", onclick: () => openBuild(x.file) }, "Open"),
        h("button", { class: "mini", onclick: () => { S.compare = [c.file, x.file]; renderCompare(); show("compare"); } }, "Compare"),
        h("button", { class: "mini primary", onclick: () => chooseCandidate(c.file, x.file, x.name) }, "Use this one"),
        h("button", { class: "mini danger", onclick: () => trashOne(x.file, x.name) }, "Trash"))));
  }
  setKids($("#ed-cands"), h("table", { class: "cmp cands" },
    h("thead", {}, h("tr", {}, ...["", "Health", "Effective HP", "HP regen", "Lowest ele. def.", "Skill points", "Main-attack DPS",
      ...(pup ? ["Puppet DPS"] : []), ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, rows)),
    h("p", { class: "hint" }, "Typical rolls. \"Use this one\" puts that candidate's gear, tree, powders and skill points into this build (its name, notes and locks stay) and moves the candidate to the trash."));
  setKids($("#ed-cands-actions"), h("button", { class: "mini danger", onclick: () => trashCandidates(c.file) }, `Trash all ${r.candidates.length}`));
}

async function chooseCandidate(parent, file, name) {
  if (S.cur?.dirty && S.cur.file === parent) { toast("Save (or revert) this build first"); return; }
  const go = await ask(`Use “${name}”?`, [`Its gear, tree, powders and skill points replace this build's in ${parent}. The build keeps its name and notes; ${file} goes to the trash.`],
    [{ label: "Use it", value: true, primary: true }, { label: "Cancel", value: false }]);
  if (!go) return;
  try { await api("POST", `/api/builds/${encodeURIComponent(parent)}/choose`, { candidate: file }); }
  catch (e) { toast(e.message); return; }
  await loadList();
  const rest = S.builds.filter((b) => b.parent === parent).length;
  await openBuild(parent, { force: true });
  if (rest && await ask("Trash the other candidates?", [`${rest} other candidate${rest > 1 ? "s" : ""} of this build ${rest > 1 ? "are" : "is"} left. They go to builds/.trash, and Undo brings them back.`],
    [{ label: "Trash them", value: true, danger: true }, { label: "Keep them", value: false }])) await trashCandidates(parent, true);
  else toast("Done");
}

async function trashCandidates(parent, noAsk = false) {
  if (!noAsk && !await ask("Trash all candidates?", ["They go to builds/.trash, and Undo brings them back."],
    [{ label: "Trash them", value: true, danger: true }, { label: "Cancel", value: false }])) return;
  const r = await api("POST", `/api/builds/${encodeURIComponent(parent)}/trash-candidates`, {});
  await loadList(); renderCandidates();
  toast(`Moved ${r.items.length} candidate${r.items.length === 1 ? "" : "s"} to the trash`, { label: "Undo", onclick: async () => {
    await api("POST", "/api/trash/restore-many", { items: r.items }); await loadList(); renderCandidates(); toast("Restored");
  } });
}

async function trashOne(file, name) {
  const r = await api("DELETE", `/api/builds/${encodeURIComponent(file)}`);
  await loadList(); renderCandidates();
  toast(`Trashed “${name}”`, { label: "Undo", onclick: async () => {
    await api("POST", "/api/trash/restore", { trash: r.trash, file: r.file }); await loadList(); renderCandidates();
  } });
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
  const icon = h("div", { class: "eq-icon-wrap" }, itemIcon(typeNow(), 44, S.items[cur()]?.tier));
  const input = h("input", { class: "eq-name tier-" + (S.items[cur()]?.tier || "none"), value: displayName(cur()),
    placeholder: `No ${slotLabel(slot).toLowerCase()}`, "aria-label": slot, spellcheck: "false" });
  const meta = h("div", { class: "eq-line" }, itemLine(S.items[cur()]));
  const craftBox = h("div", { class: "craft-box", hidden: true });
  const powderBox = POWDER_SLOTS.includes(slot) ? powderInput(slot, () => S.items[cur()]) : null;
  const refresh = () => {
    input.value = displayName(cur());
    input.className = "eq-name tier-" + (S.items[cur()]?.tier || "none");
    icon.replaceChildren(itemIcon(typeNow(), 44, S.items[cur()]?.tier));
    meta.replaceChildren(...itemLine(S.items[cur()]));
    ownBtn.redraw?.();
    powderBox?.redraw();
  };
  const craftBtn = h("button", { class: "mini", title: "Suggest a crafted item for this slot",
    onclick: () => openCraft(slot, i, craftBox, refresh) }, "Craft…");
  const ownBtn = ownButton(() => cur());
  const locked = () => (S.cur.doc.locked || []).includes(slot);
  const lockBtn = h("button", { class: "mini lock", title: "Locked items stay when you search from this build (Improve, Fix)" });
  const drawLock = () => { lockBtn.textContent = locked() ? "🔒 Locked" : "Lock"; lockBtn.classList.toggle("on", locked()); lockBtn.setAttribute("aria-pressed", String(locked())); };
  lockBtn.onclick = () => {
    edit((x) => { const l = new Set(x.locked || []); l.has(slot) ? l.delete(slot) : l.add(slot); x.locked = [...l]; }, false);
    drawLock();
  };
  drawLock();
  const ac = autocomplete(input,
    // Weapons are not class-filtered so picking one can switch the class.
    (q) => api("GET", `/api/items?slot=${slot}&level=${S.cur.doc.level}` +
      `${slot !== "weapon" && cls ? `&cls=${cls}` : ""}&q=${encodeURIComponent(q)}`),
    (o) => {
      S.items[o.name] = { ...o, cls: TYPE_CLASS[o.type] };
      const oldCls = weaponClass(S.cur.doc.equipment[8]);
      edit((x) => { x.equipment[i] = o.name; if (slot === "weapon" && TYPE_CLASS[o.type] !== oldCls) { x.tree = []; x.aspects = null; } });
      if (slot === "weapon" && TYPE_CLASS[o.type] !== oldCls) { renderEquipment(); renderTree(); renderAspects(); } else refresh();
    });
  input.addEventListener("change", () => {
    if (!input.value.trim()) { edit((x) => { x.equipment[i] = null; }); refresh(); }
  });
  input.addEventListener("blur", () => setTimeout(() => { if (input.value.trim()) input.value = displayName(cur()); }, 160));
  attachTooltip(icon, () => S.items[cur()]);
  attachTooltip(meta, () => S.items[cur()]);
  return h("div", { class: "slot" }, icon,
    h("div", { class: "eq-body" },
      h("div", { class: "eq-top" }, h("span", { class: "eq-label" }, slotLabel(slot)),
        h("span", { class: "row tight" }, lockBtn, ownBtn, craftBtn)),
      ac, meta, powderBox, craftBox));
}

// Powders, typed as WynnBuilder does: element letter + tier ("t6 t6 e6" or "t6t6e6").
const POWDER_SLOTS = ["helmet", "chestplate", "leggings", "boots", "weapon"];
const POWDER_EL = { e: "earth", t: "thunder", w: "water", f: "fire", a: "air" };
function parsePowders(text) {
  const t = text.toLowerCase().replace(/[\s,]+/g, "");
  const out = [];
  for (let i = 0; i < t.length; i += 2) {
    const p = t.slice(i, i + 2);
    if (!/^[etwfa][1-7]$/.test(p)) return null;
    out.push(p);
  }
  return out;
}
function powderInput(slot, item) {
  const k = POWDER_SLOTS.indexOf(slot);
  const cur = () => (S.cur.doc.powders || [])[k] || [];
  const chips = h("span", { class: "powder-chips" });
  const box = h("input", { class: "powders", spellcheck: "false", "aria-label": `${slot} powders`,
    value: cur().join(" ") });
  const draw = () => {
    const slots = item()?.slots || 0;
    box.placeholder = slots ? `${slots} powder slot${slots > 1 ? "s" : ""}` : "no powder slots";
    box.title = slots ? "Element + tier, like t6 t6 (earth e, thunder t, water w, fire f, air a)" : "";
    box.disabled = !slots && !cur().length;
    chips.replaceChildren(...cur().map((p) => h("span", { class: `powder ${POWDER_EL[p[0]]}` }, `${ELEMENTS[ELEM_BY_PREFIX[p[0]]].sym}${p[1]}`)));
  };
  box.addEventListener("change", () => {
    const got = parsePowders(box.value), slots = item()?.slots || 0;
    const bad = got === null || got.length > slots;
    box.classList.toggle("invalid", bad);
    box.title = got === null ? "Use element + tier, like t6 or e4" : bad ? `Only ${slots} slot(s)` : "";
    if (bad) return;
    edit((x) => { x.powders = x.powders || [[], [], [], [], []]; x.powders[k] = got; });
    box.value = got.join(" "); draw();
  });
  draw();
  const wrap = h("div", { class: "powder-row" }, box, chips);
  wrap.redraw = () => { box.value = cur().join(" "); draw(); };
  return wrap;
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
          ingredientSources(r),
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

function ingredientSources(r) {
  // Each ingredient with the mobs that drop it (WynnBuilder's data), nearest spot first listed.
  const counts = {};
  for (const x of r.craft.ingredients) if (x !== "No Ingredient") counts[x] = (counts[x] || 0) + 1;
  const rows = Object.entries(counts).map(([n, c]) => {
    const src = r.sources?.[n] || [];
    const where = /Powder [IVX]+$/.test(n) ? "a powder" : !src.length ? "no mob listed (merchant, quest or gathering?)"
      : src.slice(0, 3).map((e) => e.spots.length ? `${e.mob} (${e.spots[0][0]}, ${e.spots[0][2]})${e.spots.length > 1 ? ` +${e.spots.length - 1}` : ""}` : e.mob).join(", ")
        + (src.length > 3 ? `, ${src.length - 3} more` : "");
    return h("li", {}, h("strong", {}, c > 1 ? `${c}× ${n}` : n), h("span", { class: "muted" }, ` · ${where}`));
  });
  return h("details", { class: "sources" }, h("summary", { class: "hint" }, `Ingredients: ${Object.keys(counts).join(", ") || "none"} · where to get them`),
    h("ul", {}, rows), h("div", { class: "hint" }, "Coordinates are (x, z). From WynnBuilder's ingredient data."));
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

// ------------------------------------------------------------------ aspects
async function renderAspects() {
  const d = S.cur.doc, box = $("#ed-aspects"); if (!box) return;
  const cls = weaponClass(d.equipment[8]);
  const sum = $("#ed-aspects-sum");
  if (!cls) { box.replaceChildren(h("p", { class: "hint" }, "Pick a weapon first: aspects belong to a class.")); if (sum) sum.textContent = "Aspects"; return; }
  S.aspects ??= {};
  S.aspects[cls] ??= await api("GET", `/api/aspects/${cls}`);
  const all = S.aspects[cls], byName = Object.fromEntries(all.map((a) => [a.name, a]));
  const cur = () => (S.cur.doc.aspects || [null, null, null, null, null]);
  const setAt = (k, v) => edit((x) => { const a = [...(x.aspects || [null, null, null, null, null])]; a[k] = v; x.aspects = a.some(Boolean) ? a : null; });
  const rows = [0, 1, 2, 3, 4].map((k) => {
    const entry = cur()[k];
    const sel = h("select", { "aria-label": `Aspect ${k + 1}` }, h("option", { value: "" }, "— none —"),
      all.map((a) => h("option", { value: a.name, class: `tier-${a.rarity}` }, a.name)));
    const tier = h("select", { "aria-label": `Aspect ${k + 1} tier`, class: "tier-sel" });
    const info = h("div", { class: "eq-line" });
    const draw = () => {
      const a = byName[sel.value];
      sel.className = a ? `tier-${a.rarity}` : "";
      tier.replaceChildren(...(a ? a.tiers.map((t, i) => h("option", { value: i + 1 }, `Tier ${i + 1}`)) : []));
      tier.disabled = !a; tier.hidden = !a;
      const e = cur()[k];
      if (a && e) tier.value = String(e[1]);
      info.replaceChildren(...(a && e ? [h("span", { class: "muted" }, `${a.rarity} · `), a.tiers[e[1] - 1]?.desc || ""] : []));
    };
    sel.value = entry?.[0] || "";
    sel.onchange = () => { const a = byName[sel.value]; setAt(k, a ? [a.name, a.tiers.length] : null); draw(); drawSum(); };
    tier.onchange = () => { setAt(k, [sel.value, +tier.value]); draw(); };
    draw();
    return h("div", { class: "aspect" }, sel, tier, info);
  });
  const drawSum = () => { if (sum) sum.textContent = `Aspects · ${cur().filter(Boolean).length}/5`; };
  drawSum();
  box.replaceChildren(...rows, h("p", { class: "hint" }, "New aspects start at their top tier. Aspects change abilities, so they show up in the Damage panel."));
}

// ------------------------------------------------------------------ ability tree
// A port of WynnBuilder's tree drawing (js/builder/atree.js: render_AT,
// resolve_connector, atree_set_edge, abil_can_activate; GPL-3.0), using its
// node and connector art so trees read the same as on WynnBuilder.
const TREE_CELL = 40;                        // one grid square
const NODE_PX = TREE_CELL * 2;               // node art is drawn at 200% of a square
const CONN_PX = TREE_CELL * 1.125;           // connector tiles at 112.5%
// connector type (left right up down) -> highlight -> [x, y] tile in connectors.png
const CONNECTOR_ATLAS = {
  "1100": { "0000": [0, 0], "1100": [1, 0] },
  "1010": { "0000": [2, 0], "1010": [3, 0] },
  "0110": { "0000": [4, 0], "0110": [5, 0] },
  "1001": { "0000": [6, 0], "1001": [7, 0] },
  "0101": { "0000": [8, 0], "0101": [9, 0] },
  "0011": { "0000": [10, 0], "0011": [11, 0] },
  "1101": { "0000": [0, 1], "1101": [1, 1], "1100": [2, 1], "1001": [3, 1], "0101": [4, 1] },
  "0111": { "0000": [5, 1], "0111": [6, 1], "0110": [7, 1], "0101": [8, 1], "0011": [9, 1] },
  "1110": { "0000": [0, 2], "1110": [1, 2], "1100": [2, 2], "1010": [3, 2], "0110": [4, 2] },
  "1011": { "0000": [5, 2], "1011": [6, 2], "1010": [7, 2], "1001": [8, 2], "0011": [9, 2] },
  "1111": { "0000": [0, 3], "1111": [1, 3], "1110": [2, 3], "1101": [3, 3], "1100": [4, 3], "1011": [5, 3],
            "1010": [6, 3], "1001": [7, 3], "0111": [8, 3], "0110": [9, 3], "0101": [10, 3], "0011": [11, 3] },
};

/** Connector cells for every parent->child edge, merged per cell (resolve_connector). */
function treeConnectors(tree, byId) {
  const cells = new Map();                  // "row,col" -> {connections:[l,r,u,d]}
  const edges = new Map();                  // child id -> Map(parent id -> [cell keys])
  const add = (key, conn) => {
    if (!cells.has(key)) { cells.set(key, { connections: [...conn] }); return; }
    const c = cells.get(key).connections;
    for (let i = 0; i < 4; i++) c[i] += conn[i];
  };
  for (const n of tree) {
    const perParent = new Map();
    for (const pid of n.parents) {
      const p = byId.get(pid); if (!p) continue;
      const keys = [];
      for (let r = n.row - 1; r > p.row; r--) { keys.push(`${r},${n.col}`); add(`${r},${n.col}`, [0, 0, 1, 1]); }
      for (let c = Math.min(p.col, n.col) + 1; c < Math.max(p.col, n.col); c++) {
        keys.push(`${p.row},${c}`); add(`${p.row},${c}`, [1, 1, 0, 0]);
      }
      if (p.row !== n.row && p.col !== n.col) {
        const conn = [0, 0, 0, 1];
        conn[p.col > n.col ? 1 : 0] = 1;
        keys.push(`${p.row},${n.col}`); add(`${p.row},${n.col}`, conn);
      }
      perParent.set(pid, keys);
    }
    edges.set(n.id, perParent);
  }
  for (const c of cells.values()) c.type = c.connections.map((x) => (x ? "1" : "0")).join("");
  return { cells, edges };
}

/** Which unselected nodes could be taken now (abil_can_activate over the reachable set). */
// Which nodes are on, which can be added, and which are blocked. Selected nodes
// are replayed like WynnBuilder (in its order, one-way blockers), so the page
// agrees with the checks; a node to ADD is blocked by conflicts either way
// ("excludes"), like the tree solver.
function treeAvailability(tree, byId, selected, apCap) {
  const root = tree.find((n) => !n.parents.length);
  const reachable = new Set(), arch = new Map();
  let cost = 0;
  const blockersOf = (n, twoWay) => (twoWay ? n.excludes : n.blockers).filter((b) => reachable.has(b));
  const canActivate = (n, pointsLeft, twoWay = false) => {
    if (!n.parents.length) return true;
    if (n.deps.some((d) => !reachable.has(d))) return false;
    if (blockersOf(n, twoWay).length) return false;
    if (!n.parents.some((p) => reachable.has(p))) return false;
    if (n.req && (arch.get(n.req_archetype) || 0) < n.req) return false;
    return n.cost <= pointsLeft;
  };
  let pending = tree.filter((n) => selected.has(n.id) || n.id === root.id);
  for (;;) {
    const still = [];
    for (const n of pending) {
      if (!canActivate(n, 9999)) { still.push(n); continue; }
      if (n.archetype) arch.set(n.archetype, (arch.get(n.archetype) || 0) + 1);
      cost += n.cost; reachable.add(n.id);
    }
    if (still.length === pending.length) break;
    pending = still;
  }
  const left = apCap - cost;
  const unselected = tree.filter((n) => !selected.has(n.id));
  const blocked = new Map(unselected.map((n) => [n.id, blockersOf(n, true)]).filter(([, b]) => b.length));
  return { active: reachable, blocked,
           avail: new Set(unselected.filter((n) => canActivate(n, left, true)).map((n) => n.id)) };
}

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
  const rows = Math.max(...tree.map((n) => n.row)) + 1, cols = 9;
  const pad = TREE_CELL / 2;                 // node art overhangs its square by half a square
  const canvas = h("div", { class: "tree-canvas" });
  canvas.style.width = `${cols * TREE_CELL + 2 * pad}px`;
  canvas.style.height = `${rows * TREE_CELL + 2 * pad}px`;
  const nodeCells = new Set(tree.map((n) => `${n.row},${n.col}`));
  const { cells, edges } = treeConnectors(tree, byId);

  const connEls = new Map();
  for (const [key, c] of cells) {
    if (nodeCells.has(key)) continue;        // WynnBuilder hides links drawn over a node
    const [r, col] = key.split(",").map(Number);
    const el = h("span", { class: "tree-conn" });
    el.style.left = `${pad + col * TREE_CELL + (TREE_CELL - CONN_PX) / 2}px`;
    el.style.top = `${pad + r * TREE_CELL + (TREE_CELL - CONN_PX) / 2}px`;
    connEls.set(key, el); canvas.append(el);
  }
  const nodes = new Map();
  for (const n of tree) {
    const art = h("span", { class: "tree-node-art" });
    art.style.left = `${pad + n.col * TREE_CELL - TREE_CELL / 2}px`;
    art.style.top = `${pad + n.row * TREE_CELL - TREE_CELL / 2}px`;
    const hit = h("button", { class: "tree-hit", "aria-label": n.name });
    hit.style.left = `${pad + n.col * TREE_CELL}px`; hit.style.top = `${pad + n.row * TREE_CELL}px`;
    hit.addEventListener("mouseenter", () => describe(n));
    hit.addEventListener("focus", () => describe(n));
    hit.addEventListener("mouseleave", () => describeDefault());
    hit.addEventListener("click", () => {
      if (n.id === root.id) return;
      const by = availability(selectedIds()).blocked.get(n.id);
      if (by) { toast(`${n.name} can't be taken with ${names(by)}. Remove that first.`); describe(n); return; }
      edit((x) => { const s = new Set(x.tree || []); s.has(n.name) ? s.delete(n.name) : s.add(n.name); x.tree = [...s]; });
      paint(); describe(n);
    });
    nodes.set(n.id, { art, hit });
    canvas.append(art, hit);
  }

  const names = (ids) => ids.map((i) => byId.get(i)?.name).filter(Boolean).join(", ");
  const availability = (sel) => treeAvailability(tree, byId, sel, S.cur.doc.status?.ap?.[1] ?? S.cur.doc._ap_cap ?? 45);
  const selectedIds = () => {
    const names = new Set(S.cur.doc.tree || []);
    return new Set(tree.filter((n) => n.id === root.id || names.has(n.name)).map((n) => n.id));
  };
  const setTile = (el, [x, y]) => { el.style.backgroundPosition = `-${x * CONN_PX}px -${y * CONN_PX}px`; };

  function paint() {
    const sel = selectedIds();
    const failed = new Set(S.cur.doc.status?.tree_failed || []);
    const { avail, blocked } = availability(sel);
    for (const n of tree) {
      const { art, hit } = nodes.get(n.id);
      const state = sel.has(n.id) ? 2 : avail.has(n.id) ? 1 : 0;
      art.style.backgroundPosition = `-${(NODE_ATLAS[n.icon] ?? 0) * NODE_PX}px -${state * NODE_PX}px`;
      const by = blocked.get(n.id);
      hit.classList.toggle("fail", failed.has(n.name));
      hit.classList.toggle("blocked", !!by);
      hit.setAttribute("aria-pressed", String(sel.has(n.id)));
      hit.title = `${n.name} (${n.cost} AP)` + (failed.has(n.name) ? " — can't be activated"
        : by ? ` — blocked by ${names(by)}` : "");
    }
    // atree_set_edge, recomputed from scratch: an edge is lit when both ends are selected
    const hl = new Map([...cells.keys()].map((k) => [k, [0, 0, 0, 0]]));
    for (const n of tree) for (const [pid, keys] of edges.get(n.id)) {
      if (!(sel.has(n.id) && sel.has(pid))) continue;
      const p = byId.get(pid);
      const childSide = p.col > n.col ? 0 : 1, parentSide = 1 - childSide;
      for (const key of keys) {
        const c = cells.get(key), state = hl.get(key);
        if (c.type.split("1").length - 1 > 2) {  // T-branch or 4-way: light individual arms
          const [r, col] = key.split(",").map(Number);
          if (r === p.row) state[parentSide]++; else state[2]++;
          if (col === n.col) state[3]++; else state[childSide]++;
        } else {
          state[0]++;
        }
      }
    }
    for (const [key, el] of connEls) {
      const c = cells.get(key), state = hl.get(key), atlas = CONNECTOR_ATLAS[c.type];
      if (!atlas) { el.hidden = true; continue; }
      let tile;
      if (c.type.split("1").length - 1 > 2) tile = atlas[state.map((v) => (v ? "1" : "0")).join("")] || atlas["0000"];
      else tile = state[0] > 0 ? atlas[c.type] : atlas["0000"];
      setTile(el, tile);
    }
  }
  function describe(n) {
    const text = n.desc.replace(/<[^>]*>/g, "").replace(/&emsp;/g, " ").replace(/&nbsp;/g, " ");
    const on = selectedIds().has(n.id);
    const by = on ? null : availability(selectedIds()).blocked.get(n.id);
    setKids(desc,
      h("div", { class: "td-name" }, n.name),
      h("div", { class: "muted" }, `${n.cost} AP` + (n.archetype ? ` · ${n.archetype}` : "") +
        (n.req ? ` · needs ${n.req} ${n.req_archetype} abilities first` : "")),
      h("div", { class: "td-text" }, text),
      n.deps.length ? h("div", { class: "muted" }, `Requires: ${names(n.deps)}`) : null,
      n.excludes.length ? h("div", { class: "muted" }, `Can't be taken with: ${names(n.excludes)}`) : null,
      by ? h("div", { class: "neg" }, `Blocked by ${names(by)}, which is selected. Remove it to take this.`)
        : h("div", { class: on ? "pos" : "muted" }, n.id === root.id ? "Always active" : on ? "Selected — click to remove" : "Click to add"));
  }
  function describeDefault() {
    const sel = selectedIds();
    desc.replaceChildren(h("div", { class: "td-name" }, `Active abilities: ${sel.size}`),
      h("div", { class: "muted" }, "Hover an ability for details. Click to add or remove it."),
      h("ul", { class: "td-list" }, ...tree.filter((n) => sel.has(n.id)).map((n) => h("li", {}, n.name))));
  }
  const desc = h("div", { class: "tree-desc" });
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

const ELEM_OF = { e: "str", t: "dex", w: "int", f: "def", a: "agi" };

function renderSurvival(st) {
  const box = $("#ed-surv"); if (!box) return;
  const sv = (st.survivability || {})[S.roll === "perfect" ? "perfect" : "typical"];
  if (!sv) { box.replaceChildren(h("p", { class: "hint" }, "Checking…")); return; }
  const n = (v) => (v == null ? "—" : fmt(Math.round(v)));
  const skill = (k, pct, what) => {
    const e = ELEMENTS[k], v = sv[k];
    return statRow(h("span", {}, elemTag(k), `${e.name} (final)`), fmt(v), v < 0 ? "neg" : "",
      pct == null ? null : h("span", { class: "muted" }, `  ${pct.toFixed(1)}% ${what}`));
  };
  const low = sv.lowest?.element;
  const eledef = Object.entries(sv.eledefs).map(([e, v]) => {
    const key = ELEM_OF[e];
    return h("div", { class: "srow" + (e === low ? " lowest" : "") },
      h("span", { class: "sl" }, elemTag(key), `${ELEMENTS[key].el} Defence`, e === low ? h("span", { class: "tag-low" }, "lowest") : null),
      h("span", { class: "sv " + (v < 0 ? "neg" : v > 0 ? "pos" : "") }, v > 0 ? `+${n(v)}` : n(v)));
  });
  const warns = (st.warnings || []).map((w) => h("div", { class: `warn-row ${w.level}` },
    h("span", { class: "grow" }, w.message),
    w.fix ? h("button", { class: "mini fix-btn", "data-code": w.code, title: w.fix.why ? `Search for ${w.fix.why}` : "Set skill points back to automatic",
      onclick: () => fixBuild(w) }, w.fix.action === "auto_sp" ? "Auto skill points" : "Fix…") : null));
  setKids(box,
    statRow(h("span", {}, h("span", { class: "hp" }, "♥ "), "Health"), n(sv.hp)),
    statRow("Effective HP", n(sv.ehp), "big", sv.ehp == null ? h("span", { class: "muted" }, "  (pick a weapon)") : null),
    statRow("Effective HP (no agility)", n(sv.ehp_no_agi)),
    statRow("Health regen", n(sv.hpr), sv.hpr != null && sv.hpr <= 0 ? "neg" : ""),
    skill("def", sv.def_pct, "resist"), skill("agi", sv.agi_pct, "dodge"),
    h("div", { class: "sep" }), ...eledef,
    warns.length ? h("div", { class: "warns", id: "ed-warnings" }, warns) : null,
    h("p", { class: "hint" }, "Elemental defences include % bonuses, as WynnBuilder shows them. " +
      "Effective HP is WynnBuilder's: health against defence, agility and class, not elemental defences."));
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
    h("p", { class: "hint" }, (Object.values(st.sp_manual || {}).some(Boolean)
      ? "Some skill points are set by hand; the link keeps them, as WynnBuilder does. "
      : "Skill points are assigned automatically in the link. ") +
      ((c.doc.aspects || []).some(Boolean) ? "" : "No aspects set.")));
}

const DAMAGE_CLASS = { Neutral: "neutral", Earth: "earth", Thunder: "thunder", Water: "water", Fire: "fire", Air: "air" };
const f2 = (x) => (x ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function spellCard(sp, alt = null) {
  // One spell, as WynnBuilder's right column shows it: name (mana), the headline
  // number, and on click every part with its non-crit / crit ranges per element.
  const title = h("span", { class: "sp-name" }, sp.name,
    sp.cost ? h("span", { class: "mana" }, ` (${f2(sp.cost)})`) : null);
  const lines = [];
  if (sp.dps != null) {
    lines.push(statRow("Average DPS", f2(sp.dps), "dmg"), statRow("Attack speed", sp.attack_speed),
      statRow("Per attack", f2(sp.summary), "dmg"));
  } else if (sp.summary != null) {
    lines.push(statRow(sp.display, f2(sp.summary), sp.summary_type === "heal" ? "heal" : "dmg"));
  }
  if (alt) {       // the same spell with powder specials on
    const a = alt.dps ?? alt.summary, b = sp.dps ?? sp.summary;
    if (a != null && b != null) lines.push(statRow("With specials", f2(a), "dmg special",
      b ? h("span", { class: a > b ? "pos" : a < b ? "neg" : "muted" }, `  ${a >= b ? "+" : ""}${((a / b - 1) * 100).toFixed(1)}%`) : null));
  }
  const parts = sp.parts.map((p) => h("div", { class: "part" },
    h("div", { class: "part-h" }, p.name),
    p.type === "heal" ? statRow("Healing", f2(p.heal), "heal") : [
      statRow("Average", f2(p.average), "dmg"),
      statRow("Non-crit", f2(p.non_crit)),
      ...p.ranges.map((r) => statRow(h("span", { class: DAMAGE_CLASS[r[0]] }, r[0]),
        h("span", { class: DAMAGE_CLASS[r[0]] }, `${f2(r[1])} – ${f2(r[2])}`))),
      statRow("Crit", f2(p.crit)),
      ...p.ranges.map((r) => statRow(h("span", { class: DAMAGE_CLASS[r[0]] }, r[0]),
        h("span", { class: DAMAGE_CLASS[r[0]] }, `${f2(r[3])} – ${f2(r[4])}`))),
    ]));
  return h("details", { class: "spell" }, h("summary", {}, title, ...lines), ...parts);
}

function renderDamage(st) {
  const all = st.damage, panel = $("#ed-damage-panel");
  if (!panel) return;
  panel.hidden = !all;
  if (!all) return;
  if (all.error) { $("#ed-damage").replaceChildren(h("p", { class: "hint neg" }, `Couldn't compute damage: ${all.error}`)); return; }
  const dmg = S.roll === "perfect" ? all.perfect : all.typical, d = dmg.defense;
  const sc = S.cur.scenario?.result ? (S.roll === "perfect" ? S.cur.scenario.result.perfect : S.cur.scenario.result.typical) : null;
  const altOf = (name) => sc?.spells.find((x) => x.name === name) || null;
  const open = new Set([...document.querySelectorAll("#ed-damage details.spell[open]")].map((x) => x.dataset.name));
  const cards = dmg.spells.map((sp) => { const c = spellCard(sp, altOf(sp.name)); c.dataset.name = sp.name; c.open = open.has(sp.name); return c; });
  const knobs = [...Object.entries(dmg.sliders).map(([k, v]) => `${k} ${v.default}/${v.max}`), ...dmg.toggles.map((t) => `${t} off`)];
  $("#ed-damage").replaceChildren(...[          // filter: replaceChildren would print a skipped row as "null"
    statRow(h("span", {}, h("span", { class: "hp" }, "♥ "), "Effective HP"), fmt(Math.round(d.ehp))),
    statRow("Effective HP (no agi)", fmt(Math.round(d.ehp_no_agi))),
    statRow("HP regen", fmt(Math.round(d.hpr))),
    dmg.poison_tick ? statRow("Poison", `${fmt(dmg.poison_tick)}/s`, "pos") : null,
    statRow("Crit chance", `${dmg.crit_chance}%`),
    h("div", { class: "sep" }),
    specialsBox(sc, dmg.powders_give),
    ...cards,
    h("p", { class: "hint" }, `${S.roll === "perfect" ? "Perfect" : "Typical"} rolls. Click a spell for every part. ` +
      "Summons (puppets, effigy, hummingbirds, totems) are spell damage. Before the target's elemental defences. " +
      "No potions or raid buffs; powder specials " + (sc ? "compared above (the main numbers leave them off)" : "off, as on WynnBuilder") +
      (knobs.length ? `; ability sliders at WynnBuilder's defaults (${knobs.join(", ")})` : "") + "."),
  ].filter(Boolean));
}

// Powder specials, as a scenario next to WynnBuilder's default (off): a weapon
// special at a power, and the armor specials' damage boosts.
function specialsBox(sc, give) {
  const c = S.cur, cur = c.scenario?.specials || { weapon: give?.weapon || null, armor: {} };
  const wsel = h("select", { "aria-label": "Weapon powder special", class: "inline" }, h("option", { value: "" }, "no weapon special"),
    S.meta.specials.map((x) => h("option", { value: x.weapon }, x.weapon)));
  wsel.value = cur.weapon?.[0] || "";
  const power = h("select", { "aria-label": "Special power", class: "inline" }, [1, 2, 3, 4, 5, 6, 7].map((n) => h("option", { value: n }, `power ${n}`)));
  power.value = String(cur.weapon?.[1] || 7);
  const boosts = S.meta.specials.map((x) => {
    const inp = h("input", { type: "number", min: 0, max: x.cap, value: cur.armor?.[x.element] || "", placeholder: "0",
      "aria-label": `${x.armor} boost`, title: `${x.armor}: % ${ELEMENTS[ELEM_OF[x.element]].el} damage boost, 0-${x.cap}` });
    inp.dataset.el = x.element;
    return h("label", { class: "boost" }, elemTag(ELEM_OF[x.element]), `${x.armor} %`, inp);
  });
  const go = h("button", { class: "mini", onclick: async () => {
    const armor = {};
    for (const l of boosts) { const i = l.querySelector("input"); if (i.value !== "" && +i.value > 0) armor[i.dataset.el] = +i.value; }
    const specials = { weapon: wsel.value ? [wsel.value, +power.value] : null, armor };
    if (!specials.weapon && !Object.keys(armor).length) { c.scenario = null; renderDerived(); return; }
    c.scenario = { specials, result: null };
    await fetchScenario();
  } }, "Compare");
  const off = h("button", { class: "mini", onclick: () => { c.scenario = null; renderDerived(); } }, "Off");
  const burst = sc?.powder_special;
  return h("details", { class: "specials", open: !!c.scenario || null, id: "ed-specials" },
    h("summary", {}, "Powder specials: ", h("strong", {}, c.scenario ? "compared" : "off"), h("span", { class: "muted" }, " (WynnBuilder's default)")),
    h("div", { class: "row" }, wsel, power), h("div", { class: "boosts" }, boosts), h("div", { class: "row" }, go, c.scenario ? off : null),
    burst?.average != null ? statRow(`${burst.name} hit (power ${burst.power})`, f2(burst.average), "dmg") : null,
    burst?.boost ? statRow(`${burst.name}: damage boost`, `+${burst.boost}%`) : null,
    c.scenario?.error ? h("p", { class: "hint neg" }, c.scenario.error) : null,
    h("p", { class: "hint", id: "ed-powders-give" }, give && (give.weapon || give.armor.length)
      ? "Your powders give: " + [give.weapon ? `${give.weapon[0]} power ${give.weapon[1]} (weapon)` : null,
        ...give.armor.map((a) => `${a.name} power ${a.power} (${a.slot})`)].filter(Boolean).join(", ") +
        ". Armor specials' boosts depend on the fight (health missing, kills, mana, hits, nearby mobs): set the % you expect."
      : "Your powders give no special: it takes two or more tier IV+ powders of one element on an item, and their tiers set its power."));
}

async function fetchScenario() {
  const c = S.cur; if (!c?.scenario) return;
  const sent = JSON.stringify(editable(c.doc));
  try {
    const r = await api("POST", "/api/damage", { doc: editable(c.doc), specials: c.scenario.specials });
    if (S.cur !== c || JSON.stringify(editable(c.doc)) !== sent || !c.scenario) return;
    c.scenario.result = r; c.scenario.error = null;
  } catch (e) { if (c.scenario) c.scenario.error = e.message; }
  renderDerived();
}

function renderSets(st) {
  const sets = st.sets || [];
  $("#ed-sets-panel").hidden = !sets.length;
  const out = [];
  for (const set of sets) {
    out.push(h("div", { class: "srow set-h" }, h("span", { class: "tier-Set" }, set.name),
      h("span", { class: "muted" }, `${set.pieces}/${set.of} pieces`)));
    const entries = Object.entries(set.bonus);
    if (!entries.length) out.push(h("div", { class: "hint" }, "No bonus at this many pieces."));
    for (const [k, v] of entries) {
      if (k === "majorIds") { for (const m of v) out.push(statRow(h("span", { class: "major" }, majorName(m)), "")); continue; }
      const [label, unit, el] = idLabel(k === "hpBonus" ? "hpBonus" : k);
      out.push(statRow(h("span", {}, elemTag(el), label), `${sign(v)}${unit}`, v >= 0 ? "pos" : "neg"));
    }
  }
  $("#ed-sets").replaceChildren(...out);
}

// js/build_utils.js skillPointsToPercentage, and what each skill's percentage does
// (builder_graph.js: skillpoint_final_mult and skp_effects).
const spToPct = (sp) => (sp <= 0 ? 0 : (0.9908 / (1 - 0.9908)) * (1 - 0.9908 ** Math.min(sp, 150)) / 100);
const SP_EFFECT = { str: [1, "damage"], dex: [1, "crit"], int: [0.5 / spToPct(150), "cost red."],
  def: [0.867, "resist"], agi: [0.951, "dodge"] };

// Skill points as WynnBuilder keeps them: a skill set by hand stores its FINAL
// total in the link (null = automatic), and the points assigned follow from it.
// Players think in assigned points, so that's what the boxes edit.
function setAssigned(skill, assigned) {
  const st = S.cur.doc.status || {}, k = SKILLS.indexOf(skill);
  edit((x) => {
    const sp = [...(x.skillpoints || [null, null, null, null, null])];
    sp[k] = assigned === null ? null
      : assigned - (st.sp_auto_need?.[skill] ?? 0) + (st.sp_auto_final?.[skill] ?? 0);
    x.skillpoints = sp.some((v) => v !== null) ? sp : null;
  });
}

function renderSP(st) {
  const need = st.sp_need || {}, manual = st.sp_manual || {}, min = st.sp_auto_need || {};
  const box = $("#ed-sp");
  const focused = box.contains(document.activeElement) ? document.activeElement.dataset.skill : null;
  box.replaceChildren(...SKILLS.map((s) => {
    const e = ELEMENTS[s], v = need[s] ?? 0, final = st.sp_final?.[s] ?? v, eff = st.sp_effective?.[s] ?? final;
    const low = v < (min[s] ?? 0), over = v > 100;
    const input = h("input", { type: "number", class: "sp-in" + (manual[s] ? " manual" : ""), value: v,
      "aria-label": `${e.name} assigned`, title: manual[s] ? "Set by hand" : "Automatic: the fewest points this gear needs" });
    input.dataset.skill = s;
    input.addEventListener("change", () => {
      if (input.value.trim() === "") { setAssigned(s, null); return; }
      const n = Math.round(+input.value);
      if (Number.isFinite(n)) setAssigned(s, n);
    });
    const [mult, what] = SP_EFFECT[s];
    return h("div", { class: "sp-box" + (over || low ? " over" : "") + (manual[s] ? " is-manual" : "") },
      h("div", { class: `sp-h ${e.cls}` }, `${e.sym} ${e.name}`),
      h("div", { class: "sp-edit" }, input,
        manual[s] ? h("button", { class: "mini sp-auto", title: "Back to automatic", "aria-label": `${e.name} automatic`,
          onclick: () => setAssigned(s, null) }, "Auto") : h("span", { class: "sp-tag muted" }, "auto")),
      h("div", { class: "bar" }, h("i", { style: `width:${Math.max(0, Math.min(100, v))}%` })),
      h("div", { class: "sp-sub" }, `gear needs ${fmt(min[s] ?? 0)}`),
      h("div", { class: "sp-sub" }, "final ", h("strong", { class: final < 0 ? "neg" : "" }, fmt(final)),
        eff !== final ? h("span", {}, ` · tree ${fmt(eff)}`) : null),
      h("div", { class: "sp-sub" }, `${(spToPct(eff) * 100 * mult).toFixed(1)}% ${what}`),
      low ? h("div", { class: "sp-warn neg" }, `below the ${fmt(min[s])} the gear needs`) : null,
      over ? h("div", { class: "sp-warn neg" }, "over 100 in one skill") : null);
  }));
  if (focused) box.querySelector(`input[data-skill="${focused}"]`)?.focus();
  const left = (st.sp_available ?? 0) - (st.sp_total ?? 0);
  const anyManual = Object.values(manual).some(Boolean);
  setKids($("#ed-sp-foot"), h("span", { class: "grow" }, "Assigned ", h("strong", {}, fmt(st.sp_total)),
      ` of ${fmt(st.sp_available)}. Remaining: `, h("strong", { class: left < 0 ? "neg" : "pos", id: "sp-left" }, fmt(left)),
      anyManual ? h("span", { class: "muted" }, " · some set by hand") : h("span", { class: "muted" }, " · automatic")),
    h("button", { class: "mini", id: "sp-auto-all", disabled: !anyManual, title: "Let WynnBuilder assign every skill (the fewest points the gear needs)",
      onclick: () => edit((x) => { x.skillpoints = null; }) }, "Auto"));
}

function renderDerived() {
  const c = S.cur, d = c.doc, st = d.status || {};
  $("#ed-badge").replaceChildren(h("span", { class: "badge " + (c.checking ? "pending" : st.verified ? "ok" : "bad") },
    c.checking ? "checking…" : st.verified ? "✓ Verified" : `⚠ ${st.problems?.length || 0} problem(s)`));
  const open = $("#ed-open"); if (open) open.href = d.link || "#";
  $("#ed-save").disabled = !c.dirty;
  $("#ed-revert").disabled = !c.dirty;

  const banners = $("#ed-banners"); banners.replaceChildren();
  if (d.parent) {
    const parent = S.builds.find((b) => b.file === d.parent);
    banners.append(h("div", { class: "banner cand", id: "ed-cand-banner" },
      h("span", { class: "grow" }, `A candidate for “${parent?.name || d.parent}”.`),
      parent ? h("button", { onclick: () => chooseCandidate(d.parent, c.file, d.name || c.file) }, "Use this one") : null,
      parent ? h("button", { onclick: () => { S.compare = [d.parent, c.file]; renderCompare(); show("compare"); } }, "Compare") : null,
      parent ? h("button", { onclick: () => openBuild(d.parent) }, "Open the build") : h("span", { class: "muted" }, "(that build is gone)")));
  }
  if (c.conflict) banners.append(h("div", { class: "banner warn" },
    h("span", { class: "grow" }, "This build was changed on disk (maybe by the AI) while you were editing."),
    h("button", { onclick: () => openBuild(c.file) }, "Load their version"),
    h("button", { onclick: () => { c.conflict = false; c.overwrite = true; renderDerived(); } }, "Keep mine")));
  if (c.checkError) banners.append(h("div", { class: "banner bad" }, c.checkError));
  else if (st.problems?.length) banners.append(h("div", { class: "banner bad" },
    h("div", {}, h("strong", {}, "Problems"), h("ul", {}, st.problems.map((p) => h("li", {}, p))))));

  renderSP(st); renderSurvival(st); renderSummary(st); renderDamage(st); renderSets(st); renderChecks(st);
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
  if (c.scenario) fetchScenario();
}, 350);

function edit(mutate, recheck = true) {
  const c = S.cur; if (!c) return;
  mutate(c.doc); c.dirty = true;
  if (recheck) { c.checking = true; runCheck(); }
  renderDerived(); reportView();
}

async function save() {
  const c = S.cur;
  try {
    let mtime = c.mtime;
    if (c.overwrite) mtime = (await api("GET", `/api/builds/${encodeURIComponent(c.file)}`))._mtime;
    const out = await api("PUT", `/api/builds/${encodeURIComponent(c.file)}`, { ...editable(c.doc), _mtime: mtime });
    Object.assign(c, { doc: out, mtime: out._mtime, dirty: false, conflict: false, overwrite: false, checkError: null });
    toast(out.status.verified ? "Saved · verified" : "Saved, but the build has problems");
    renderDerived(); loadList(); reportView();
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
// Minimums, grouped as the form shows them. Keys are the spec's "floors" (AGENTS.md).
const FLOOR_GROUPS = [
  ["Survival", [["hp", "Health", "e.g. 17000"], ["ehp", "Effective HP", "e.g. 40000"],
    ["hprRaw", "HP regen (raw)", "e.g. 200"], ["hpr", "HP regen (with %)", "e.g. 300"],
    ["min_eledef", "Every elemental defence", "e.g. 0"],
    ["eDef", "Earth defence", ""], ["tDef", "Thunder defence", ""], ["wDef", "Water defence", ""],
    ["fDef", "Fire defence", ""], ["aDef", "Air defence", ""]]],
  ["Skill points (final, after gear)", SKILLS.map((s) => [s, ELEMENTS[s].name, ""])],
  ["Mana and movement", [["mr", "Mana regen", "e.g. 20"], ["mana", "Max mana", "e.g. 113"], ["spd", "Walk speed %", "e.g. 0"]]],
  ["Damage", [["weapon_dps", "Weapon DPS (listed)", "e.g. 700"], ["melee_dps", "Main-attack DPS", ""],
    ["puppet_dps", "Puppet DPS", ""], ["summon_dps", "Total summon DPS", ""]]],
];
const DERIVED_FLOORS = ["ehp", "hpr", "melee_dps", "puppet_dps", "summon_dps"];

/** Open the solver for an open build: its class, level, spec and tree, the weapon and
 * locked items kept, results saved as candidates. `fix`: a Survivability warning's fix. */
async function openSolverFor(c, fix = null) {
  const d = c.doc, spec = d.spec || {};
  const keep = { weapon: d.equipment[8] };
  for (const slot of d.locked || []) { const n = d.equipment[S.meta.slots.indexOf(slot)]; if (n) keep[slot] = n; }
  const objective = Object.keys(spec.objective || {}).length ? spec.objective : { ehp: 1 };
  renderSolver({ from: c.file, name: `${d.name || c.file}: ${fix?.why || "improved"}`,
    cls: weaponClass(d.equipment[8]), level: d.level, objective,
    floors: { ...(spec.floors || {}), ...(fix?.floors || {}) }, force: { ...(spec.force || {}), ...keep },
    locked: Object.keys(keep), tree: d.tree || [], tomes: d.tomes, exclude: spec.exclude || [],
    exclude_tiers: spec.exclude_tiers || [], require_major: spec.require_major || [],
    exclude_major: spec.exclude_major || [], caps: spec.caps || {},
    at_most_one: spec.at_most_one || [], prefer: spec.prefer || {}, why: fix?.why,
    defaultGoal: !Object.keys(spec.objective || {}).length });
  show("solver");
}

async function fixBuild(w) {
  if (w.fix.action === "auto_sp") {
    edit((x) => { x.skillpoints = null; });
    toast("Skill points set back to automatic. Save to keep it.");
    return;
  }
  if (S.cur.dirty) { toast("Save (or revert) your changes first: the search starts from the saved build."); return; }
  await openSolverFor(S.cur, w.fix);
}

/** A chip list of item names with an item search box, e.g. items to leave out. */
function itemChips(label, names, onChange) {
  const box = h("div", { class: "chips" });
  const draw = () => box.replaceChildren(...[...names].map((n) =>
    h("span", { class: "chip on", title: "remove", onclick: () => { names.delete(n); draw(); onChange?.(); } }, `${n} ✕`)));
  const input = h("input", { placeholder: "Search an item…", "aria-label": label });
  const ac = autocomplete(input, (q) => api("GET", `/api/items?slot=any&q=${encodeURIComponent(q)}`),
    (o) => { names.add(o.name); input.value = ""; draw(); onChange?.(); });
  draw();
  return h("div", {}, ac, box);
}

function renderSolver(pre = {}) {
  const m = S.meta, f = {};
  const field = (label, el, title) => h("label", { title }, label, el);
  const num = (name, ph) => (f[name] = h("input", { type: "number", placeholder: ph || "" }));
  f.name = h("input", { placeholder: "e.g. Stealing Summoner", value: pre.name || "" });
  f.cls = h("select", {}, m.classes.map((c) => h("option", { value: c }, c)));
  if (pre.cls) f.cls.value = pre.cls;
  f.level = h("input", { type: "number", value: pre.level || 105, min: 1, max: 121 });
  f.goal = h("select", { "aria-label": "Maximize" });
  const statOptions = () => m.stat_groups.map((g) => h("optgroup", { label: g.group }, g.stats.map((s) => h("option", { value: s.key }, s.label))));
  f.tie = h("select", {}, h("option", { value: "" }, "none"), statOptions());
  f.weapon = h("input", { placeholder: "any", value: pre.force?.weapon || "" });
  f.mythic = h("input", { type: "checkbox", checked: (pre.exclude_tiers || []).includes("Mythic") });
  f.crafted = h("input", { type: "checkbox" });
  f.owned = h("input", { type: "checkbox" });
  f.exact = h("input", { type: "checkbox", checked: true });
  f.tomesFrom = h("select", {}, h("option", { value: "" }, "no tomes"), S.builds.map((b) => h("option", { value: b.file }, b.name)));
  if (pre.from) f.tomesFrom.value = pre.from;
  f.preset = h("select", { "aria-label": "Tree preset" });
  f.topn = h("input", { type: "number", value: 8, min: 4, max: 20 });
  f.asCandidate = h("input", { type: "checkbox", checked: !!pre.from });
  const majors = new Set(pre.require_major || []);
  const exclude = new Set(pre.exclude || []);
  const prefer = new Set(Object.keys(pre.prefer || {}));
  const groups = (pre.at_most_one || []).map((g) => [...g]);
  const kept = { ...(pre.force || {}) }; delete kept.weapon;
  const noMajors = new Set(pre.exclude_major || []);
  const noMajorChips = h("div", { class: "chips" });
  const drawNoMajors = () => noMajorChips.replaceChildren(...[...noMajors].map((k) =>
    h("span", { class: "chip on", title: "remove", onclick: () => { noMajors.delete(k); drawNoMajors(); } }, `no ${k} ✕`)));
  const noMajorIn = h("select", {}, h("option", { value: "" }, "Add a major ID to avoid…"),
    m.majors.map(([k, name]) => h("option", { value: k }, name)));
  noMajorIn.onchange = () => { if (noMajorIn.value) { noMajors.add(noMajorIn.value); majors.delete(noMajorIn.value); drawMajors(); } noMajorIn.value = ""; drawNoMajors(); };
  drawNoMajors();
  const majorChips = h("div", { class: "chips" });
  const drawMajors = () => majorChips.replaceChildren(...[...majors].map((k) =>
    h("span", { class: "chip on", title: "remove", onclick: () => { majors.delete(k); drawMajors(); } }, `${k} ✕`)));
  const majorIn = h("select", {}, h("option", { value: "" }, "Add a required major ID…"),
    m.majors.map(([k, name]) => h("option", { value: k }, name)));
  majorIn.onchange = () => { if (majorIn.value) { majors.add(majorIn.value); noMajors.delete(majorIn.value); drawNoMajors(); } majorIn.value = ""; drawMajors(); };
  drawMajors();

  // "At most one of these": build a group, then add it.
  const draft = new Set();
  const groupBox = h("div");
  const drawGroups = () => groupBox.replaceChildren(...groups.map((g, i) => h("div", { class: "chips" },
    h("span", { class: "muted" }, "at most one of:"), ...g.map((n) => h("span", { class: "chip" }, n)),
    h("button", { class: "mini", onclick: () => { groups.splice(i, 1); drawGroups(); } }, "remove"))));
  const draftChips = itemChips("Add to an 'at most one' group", draft);
  const addGroup = h("button", { class: "mini", onclick: () => {
    if (draft.size < 2) { toast("Pick at least two items for a group"); return; }
    groups.push([...draft]); draft.clear(); draftChips.querySelector(".chips").replaceChildren(); drawGroups();
  } }, "Add group");
  drawGroups();

  const syncPresets = () => {
    const own = pre.tree?.length && pre.cls === f.cls.value;
    f.preset.replaceChildren(h("option", { value: "" }, own ? "this build's own tree" : "none (gear only)"),
      ...m.presets.filter((p) => p.class === f.cls.value).map((p) => h("option", { value: p.name, title: p.about }, p.name)));
  };
  let spells = [];
  const syncGoals = () => {
    const keep = f.goal.value || Object.keys(pre.objective || {})[0] || "eSteal";
    const shaman = f.cls.value === "Shaman";
    const derived = m.derived.filter((g) => shaman || !["puppet_dps", "summon_dps"].includes(g.key));
    setKids(f.goal,
      ...statOptions(),
      h("optgroup", { label: "Worked out by WynnBuilder's model" }, derived.map((g) =>
        h("option", { value: g.key }, g.label + (g.damage ? " (needs a tree)" : "")))),
      spells.length ? h("optgroup", { label: "Spell damage (needs a tree)" }, spells.filter((sp) => !sp.melee).map((sp) =>
        h("option", { value: `damage:${sp.name}` }, sp.name))) : null);
    f.goal.value = [...f.goal.options].some((o) => o.value === keep) ? keep : "eSteal";
    f.tdamage.replaceChildren(...[["melee_dps", "Main-attack DPS"], ...(shaman ? [["puppet_dps", "Puppet DPS"], ["summon_dps", "Total summon DPS"]] : []),
      ...spells.filter((sp) => !sp.melee).map((sp) => [`damage:${sp.name}`, sp.name])].map(([k, l]) => h("option", { value: k }, l)));
    drawPicker();
  };
  const syncSpells = async () => {
    const preset = f.preset.value || m.presets.find((p) => p.class === f.cls.value)?.name;
    spells = f.preset.value || pre.tree?.length
      ? await api("GET", `/api/spells?cls=${f.cls.value}&preset=${encodeURIComponent(preset || "")}&level=${+f.level.value || 105}`) : [];
    syncGoals();
  };
  f.tdamage = h("select", { "aria-label": "Damage to trade", class: "inline" });
  f.ttank = h("select", { "aria-label": "Survival to trade", class: "inline" }, h("option", { value: "ehp" }, "Effective HP"),
    h("option", { value: "ehp_no_agi" }, "Effective HP (no agility)"));
  f.cls.onchange = () => { syncPresets(); syncSpells(); }; syncPresets();
  f.preset.onchange = syncSpells; f.level.addEventListener("change", syncSpells);
  const weaponAc = autocomplete(f.weapon, (q) => api("GET", `/api/items?slot=weapon&cls=${f.cls.value}&level=${f.level.value}&q=${encodeURIComponent(q)}`), () => {});

  // Requirements: only the ones the player adds, each a row (at least / at most / value).
  const shown = new Set(FLOOR_GROUPS.flatMap(([, rows]) => rows.map(([k]) => k)));
  const itemStats = new Set(m.stat_groups.flatMap((g) => g.stats.map((x) => x.key)));
  const labelOf = new Map(FLOOR_GROUPS.flatMap(([, rows]) => rows.map(([k, l]) => [k, l])));
  for (const g of m.stat_groups) for (const x of g.stats) if (!labelOf.has(x.key)) labelOf.set(x.key, x.label);
  const ruleLabel = (k) => (k.startsWith("damage:") ? `${k.slice(7)} damage` : labelOf.get(k) || k);
  const rules = [
    ...Object.entries(pre.floors || {}).flatMap(([k, v]) => k === "damage"
      ? Object.entries(v).map(([n, x]) => ({ key: `damage:${n}`, kind: "min", value: x }))
      : typeof v === "number" ? [{ key: k, kind: "min", value: v }] : []),
    ...Object.entries(pre.caps || {}).map(([key, value]) => ({ key, kind: "max", value }))];
  const ruleBox = h("div", { class: "rules" });
  const quick = h("div", { class: "chips" });
  let pickerOptions = [];
  f.add = searchPicker({ label: "Add a requirement", placeholder: "Search a stat, DPS or spell to require…",
    options: () => pickerOptions, onPick: (k) => addRule(k) });
  const drawRules = () => {
    ruleBox.replaceChildren(...rules.map((r, i) => {
      const kind = h("select", { "aria-label": `${ruleLabel(r.key)}: at least or at most`, disabled: !itemStats.has(r.key),
        onchange: (ev) => { r.kind = ev.target.value; } }, h("option", { value: "min" }, "at least"), h("option", { value: "max" }, "at most"));
      kind.value = r.kind;
      return h("div", { class: "rule" },
        h("span", { class: "rule-name" }, ruleLabel(r.key),
          DERIVED_FLOORS.includes(r.key) || r.key.startsWith("damage:") ? h("span", { class: "muted", title: "Worked out by WynnBuilder's model: uses the shortlist search" }, " · model") : null),
        kind,
        h("input", { type: "number", "aria-label": ruleLabel(r.key), value: r.value ?? "", placeholder: "value",
          oninput: (ev) => { r.value = ev.target.value === "" ? null : +ev.target.value; } }),
        h("button", { class: "mini", "aria-label": `Remove ${ruleLabel(r.key)}`, onclick: () => { rules.splice(i, 1); drawRules(); drawPicker(); } }, "✕"));
    }));
    ruleBox.hidden = !rules.length;
    const none = $("#no-rules"); if (none) none.hidden = !!rules.length;
  };
  const addRule = (key) => {
    if (!key || rules.some((r) => r.key === key)) return;
    rules.push({ key, kind: "min", value: null }); drawRules(); drawPicker();
    ruleBox.lastElementChild?.querySelector("input")?.focus();
  };
  function drawPicker() {
    const shaman = f.cls.value === "Shaman", used = new Set(rules.map((r) => r.key));
    const opts = [];
    for (const [title, rows] of FLOOR_GROUPS) {
      for (const [k, l] of rows) if (!used.has(k) && (shaman || !["puppet_dps", "summon_dps"].includes(k))) opts.push({ key: k, label: l, group: title });
    }
    if (spells.length) {
      for (const sp of spells) if (!used.has(`damage:${sp.name}`))
        opts.push({ key: `damage:${sp.name}`, label: sp.melee ? `${sp.name} (DPS)` : sp.name, group: "Spell damage" });
    } else opts.push({ key: "", label: "Pick a tree preset to require a spell's damage", group: "Spell damage", disabled: true });
    for (const g of m.stat_groups) for (const x of g.stats)
      if (!shown.has(x.key) && !used.has(x.key)) opts.push({ key: x.key, label: x.label, group: `Item stat: ${g.group}` });
    pickerOptions = opts;
    f.add.refresh();
    quick.replaceChildren(...["hp", "ehp", "mr", "spd", "min_eledef"].filter((k) => !used.has(k)).map((k) =>
      h("button", { class: "chip", onclick: () => addRule(k) }, `+ ${ruleLabel(k)}`)));
  }
  drawRules();

  const bar = h("i"), status = h("div", { class: "hint", id: "solver-status" }), cancelBtn = h("button", { class: "danger", hidden: true }, "Cancel");
  const runBtn = h("button", { class: "primary", id: "solver-run" }, "Find the best build");
  const tradeBtn = h("button", { id: "solver-trade", title: "A few legal builds from max damage to max survival, side by side" }, "Show trade-offs");
  const upBtn = h("button", { title: "Rank items you don't own by how much each would improve your best owned-only build" },
    "What should I get next?");
  const resultBox = h("div", { id: "solver-result" });

  async function readForm() {
    const floors = {}, caps = {};
    for (const r of rules) {
      if (r.value == null || Number.isNaN(r.value)) continue;
      if (r.key.startsWith("damage:")) (floors.damage ||= {})[r.key.slice(7)] = r.value;
      else if (r.kind === "max") caps[r.key] = r.value;
      else floors[r.key] = r.value;
    }
    const objective = { [f.goal.value]: 1 };
    if (f.tie.value && f.tie.value !== f.goal.value) objective[f.tie.value] = 0.01;
    let tomes = [];
    if (f.tomesFrom.value) tomes = (await api("GET", `/api/builds/${encodeURIComponent(f.tomesFrom.value)}`)).tomes || [];
    const force = { ...kept };
    if (f.weapon.value) force.weapon = f.weapon.value;
    return { class: f.cls.value, level: +f.level.value, objective, floors,
      require_major: [...majors], exclude_major: [...noMajors], caps, force, exclude: [...exclude], at_most_one: groups,
      prefer: Object.fromEntries([...prefer].map((n) => [n, 0])),
      exclude_tiers: f.mythic.checked ? ["Mythic"] : [], tomes, topn: +f.topn.value || 8,
      crafted: f.crafted.checked && !f.owned.checked };
  }
  const treeArgs = () => ({ tree_preset: f.preset.value || null,
    tree: !f.preset.value && pre.tree?.length && pre.cls === f.cls.value ? pre.tree : null });
  const parentFile = () => (f.asCandidate.checked && pre.from ? pre.from : null);
  const fileFor = (name) => {
    const short = pre.name && name.startsWith(pre.name.split(": ")[0] + ": ") ? name.slice(name.indexOf(": ") + 2) : name;
    const stem = parentFile() ? `${parentFile().replace(/\.json$/, "")}--${slug(short)}` : slug(name);
    let file = `${stem}.json`, n = 2;
    while (S.builds.some((b) => b.file === file)) file = `${stem}-${n++}.json`;
    return file;
  };
  function follow(job, onDone, onFail) {
    runBtn.disabled = upBtn.disabled = tradeBtn.disabled = true; cancelBtn.hidden = false;
    S.job = job;                // the app window's close button warns while it runs
    cancelBtn.onclick = () => api("POST", `/api/jobs/${job}/cancel`);
    const es = new EventSource(`/api/jobs/${job}/events`);
    es.onmessage = async (ev) => {
      const j = JSON.parse(ev.data), p = j.progress;
      if (p) {
        const mm = Math.floor(p.elapsed / 60), ss = String(Math.floor(p.elapsed % 60)).padStart(2, "0");
        const time = p.elapsed ? ` · ${mm}:${ss}` : "";
        if (p.fraction == null) {       // rounds or builds checked, not a known fraction
          bar.parentElement.classList.add("busy");
          status.textContent = (p.text || (p.exact ? `Exact search · round ${p.nodes} · best possible ${p.best}` : "Searching…")) + time;
        } else {
          bar.parentElement.classList.remove("busy");
          bar.style.width = `${(p.fraction * 100).toFixed(1)}%`;
          status.textContent = `${(p.fraction * 100).toFixed(1)}% · ${p.text || `${fmt(p.nodes)} checked · best so far ${p.best ?? "—"}`}${time}`;
        }
      }
      if (j.state !== "running") {
        es.close(); runBtn.disabled = upBtn.disabled = tradeBtn.disabled = false; cancelBtn.hidden = true;
        S.job = null;
        bar.parentElement.classList.remove("busy");
        if (j.state === "done") { bar.style.width = "100%"; status.textContent = j.note ? `Done: ${j.note}.` : "Done."; await onDone(j); }
        else if (j.state === "cancelled") status.textContent = "Cancelled.";
        else { status.textContent = ""; (onFail || showFailure)(j); }
      }
    };
  }
  function showFailure(j) {
    const ex = j.explanation;
    setKids(resultBox, h("div", { class: "card explain", id: "solver-explain" },
      h("h3", {}, "Why no build fits"),
      h("p", { class: "neg" }, ex?.summary || j.error || "No build satisfies these constraints."),
      ex?.lines?.length ? h("ul", {}, ex.lines.map((l) => h("li", {}, l))) : null,
      ex?.conflict?.length > 1 ? h("p", { class: "hint" }, "Loosen any one of these and try again.") : null,
      ex?.unsure ? h("p", { class: "hint" }, "Some checks ran out of time.") : null));
  }
  runBtn.onclick = async () => {
    const spec = await readForm();
    const name = f.name.value.trim() || `${f.cls.value} ${f.goal.selectedOptions[0]?.textContent || "build"}`;
    const file = fileFor(name);
    try {
      const { job, search } = await api("POST", "/api/solve", { spec, file, name, ...treeArgs(),
        owned_only: f.owned.checked, exact: f.exact.checked, parent: parentFile() });
      resultBox.replaceChildren();
      status.textContent = search === "local" ? "Local search: this takes a minute or more…" : "Searching…";
      follow(job, async (j) => { toast(parentFile() ? "Candidate saved" : "Build found"); await loadList(); openBuild(j.file); });
    } catch (e) { status.textContent = e.message; }
  };
  tradeBtn.onclick = async () => {
    const spec = await readForm();
    try {
      const { job } = await api("POST", "/api/tradeoffs", { spec, damage: f.tdamage.value, tank: f.ttank.value,
        ...treeArgs(), owned_only: f.owned.checked });
      resultBox.replaceChildren(h("div", { class: "hint" }, "Searching from all-out damage to all-out survival (a few minutes)…"));
      follow(job, async (j) => renderTradeoffs(j.result, spec));
    } catch (e) { status.textContent = e.message; }
  };
  function renderTradeoffs(r, spec) {
    if (!r.options.length) { resultBox.replaceChildren(h("p", { class: "neg" }, "No legal build found for these goals.")); return; }
    const shaman = f.cls.value === "Shaman";
    const dmgLabel = f.tdamage.selectedOptions[0]?.textContent || r.damage;
    const baseName = f.name.value.trim() || `${f.cls.value} trade-off`;
    const save = async (o, parent) => {
      const name = `${baseName}: ${o.label}`;
      const stem = parent ? `${parent.replace(/\.json$/, "")}--${slug(o.label)}` : slug(name);
      let file = `${stem}.json`, n = 2;
      while (S.builds.some((b) => b.file === file)) file = `${stem}-${n++}.json`;
      const out = await api("POST", "/api/candidates", { file, name, spec: { ...spec, objective: { [r.damage]: 1 } },
        equipment: o.equipment, skillpoints: o.skillpoints, ...treeArgs(), parent });
      await loadList();
      return out.file;
    };
    const rows = r.options.map((o) => h("tr", {},
      h("td", {}, h("strong", {}, o.label)),
      h("td", {}, fmt(Math.round(o.damage))), h("td", {}, fmt(Math.round(o.ehp))), h("td", {}, fmt(Math.round(o.hp))),
      h("td", { class: o.hpr <= 0 ? "neg" : "" }, fmt(Math.round(o.hpr))),
      h("td", { title: o.skillpoints ? "Some skill points set by hand" : "Automatic" }, `${o.sp_total}${o.skillpoints ? " *" : ""}`),
      shaman ? h("td", {}, fmt(Math.round(o.puppet_dps))) : null,
      h("td", {}, h("button", { class: "mini", onclick: async (e) => {
        e.target.disabled = true;
        try { const file = await save(o, parentFile()); toast(`Saved ${file}`); openBuild(file); } catch (err) { toast(err.message); e.target.disabled = false; }
      } }, "Save"))));
    const saveAll = h("button", { onclick: async () => {
      saveAll.disabled = true;
      try {
        let parent = parentFile();
        const opts = [...r.options];
        if (!parent) parent = await save(opts.splice(Math.min(1, opts.length - 1), 1)[0], null);  // balanced is the parent
        for (const o of opts) await save(o, parent);
        toast("Saved as candidates"); openBuild(parent);
      } catch (err) { toast(err.message); saveAll.disabled = false; }
    } }, parentFile() ? "Save all as candidates" : "Save all (balanced as the build, the rest as its candidates)");
    setKids(resultBox, h("div", { class: "card", id: "tradeoffs" }, h("h3", {}, "Trade-offs"),
      h("table", { class: "cmp trade" },
        h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, dmgLabel), h("th", {}, "Effective HP"), h("th", {}, "Health"),
          h("th", {}, "Health regen"), h("th", {}, "Skill points"), shaman ? h("th", {}, "Puppet DPS") : null, h("th", {}, ""))),
        h("tbody", {}, rows)),
      h("div", { class: "row" }, saveAll),
      h("p", { class: "hint" }, `Every row is a legal build (${r.checked} checked); none beats another on both damage and effective HP. ` +
        "Typical rolls; * = some skill points set by hand to reach these numbers. Found by local search: good builds, not proven the best.")));
  }
  const upgradesBox = h("div", { id: "upgrades" });
  upBtn.onclick = async () => {
    const spec = await readForm();
    try {
      const { job } = await api("POST", "/api/upgrades", { spec, top: 10, tree_preset: f.preset.value || null });
      upgradesBox.replaceChildren(h("div", { class: "hint" }, "Trying each item you don't own, one at a time…"));
      follow(job, async (j) => {
        status.textContent = "";
        const r = j.result, goal = idLabel(f.goal.value);
        await Promise.all(r.upgrades.map((u) => itemInfo(u.slot, u.item)));
        setKids(upgradesBox,
          h("div", { class: "panel-h" }, "What to get next"),
          r.base ? h("p", {}, `Best from what you own: ${goal[0]} ${fmt(r.base.score)}${goal[1]} — `,
                     h("span", { class: "muted" }, r.base.equipment.map((x) => displayName(x) || "(empty)").join(" / ")))
                 : h("p", { class: "neg" }, "You can't make a build that meets these goals from what you own yet."),
          r.upgrades.length ? h("div", { class: "inv-list" }, r.upgrades.map((u) => {
            const it = S.items[u.item];
            const row = h("div", { class: "row up-row" }, itemIcon(it?.type, 28, it?.tier),
              h("span", { class: `tier-${it?.tier} inv-name` }, u.item),
              h("span", { class: "muted" }, u.slot),
              h("span", { class: "grow" }),
              h("strong", { class: "pos" }, u.gain === null ? "makes a build possible" : `+${fmt(Math.round(u.gain * 100) / 100)}${goal[1]}`),
              ownButton(() => u.item));
            attachTooltip(row.firstChild, () => S.items[u.item]);
            return row;
          })) : h("p", { class: "muted" }, "No single item you don't own improves on that."),
          h("p", { class: "hint" }, "Each item is tried alone, added to everything you own; gains don't add up across items."));
      }, (j) => { upgradesBox.replaceChildren(h("p", { class: "neg" }, j.error || "Failed")); });
    } catch (e) { upgradesBox.replaceChildren(h("p", { class: "neg" }, e.message)); }
  };

  const keptList = Object.entries(kept);
  setKids($("#solver"),
    h("div", { class: "head" }, h("h2", { style: "margin:0;flex:1" }, pre.from ? "Search from this build" : "New build from goals")),
    pre.from ? h("div", { class: "banner warn", id: "solver-from" },
      h("span", { class: "grow" }, `Starting from ${pre.from}` + (pre.why ? `, to get ${pre.why}` : "") +
        `. Kept: ${[pre.force?.weapon && `weapon (${pre.force.weapon})`, ...keptList.map(([s, n]) => `${s} (${n})`)].filter(Boolean).join(", ") || "nothing"}.` +
        (pre.defaultGoal ? " This build has no saved goal, so the search maximizes effective HP: change Maximize below if you want something else." : "")),
      h("label", { class: "check" }, f.asCandidate, " Save results as candidates of this build")) : null,
    h("div", { class: "card" }, h("h3", {}, "Goal"),
      h("div", { class: "form tight" }, field("Name", f.name), field("Class", f.cls), field("Level", f.level),
        field("Maximize", f.goal), field("Tree", f.preset)),
      h("div", { class: "row checks" },
        h("label", { class: "check" }, f.mythic, "No mythics"),
        h("label", { class: "check" }, f.crafted, "Include crafted items"),
        h("label", { class: "check" }, f.owned, "Only items I own"))),
    h("div", { class: "card" }, h("h3", {}, "Requirements"),
      h("div", { class: "row add-row" }, f.add, quick), ruleBox,
      h("p", { class: "hint", id: "no-rules", hidden: !!rules.length }, "None yet: the search maximizes the goal alone. Add a minimum (or a maximum, for item stats) to constrain it."),
      h("details", { class: "more" }, h("summary", {}, "How these are counted"),
        h("p", { class: "hint" }, "Health, regen and defences count gear, tomes and set bonuses (raw elemental defences, as the Summary shows). " +
          "Skill-point minimums are met with spare points if the gear falls short; the build keeps them set by hand. Max mana assumes spare points go into Intelligence. " +
          "Any item stat works, at 100% rolls unless you own the item. " +
          "Effective HP, regen with %, DPS and spell damage are WynnBuilder's numbers with the tree and no powders; they use the shortlist search."))),
    h("details", { class: "card fold", open: !!(majors.size || noMajors.size || exclude.size || prefer.size || groups.length || pre.force?.weapon || pre.from) },
      h("summary", {}, "Items: weapon, major IDs, tomes, leave out"),
      h("div", { class: "form" }, field("Weapon (optional)", weaponAc), field("Tomes", f.tomesFrom),
        field("Required major IDs", majorIn), field("Avoid these major IDs", noMajorIn)),
      majorChips, noMajorChips,
      h("div", { class: "form", style: "margin-top:10px" },
        field("Leave out (unavailable, too expensive…)", itemChips("Leave out", exclude)),
        field("Prefer when it costs nothing", itemChips("Prefer", prefer)),
        field("At most one of", h("div", {}, draftChips, addGroup, groupBox))),
      h("p", { class: "hint" }, `Items on your Inventory page's unavailable list are always left out${Object.keys(S.inv.unavailable || {}).length ? ` (${Object.keys(S.inv.unavailable).length} now)` : ""}.`)),
    h("details", { class: "card fold" },
      h("summary", {}, "Search options"),
      h("div", { class: "form" }, field("Tiebreaker (tiny weight)", f.tie), field("Shortlist size", f.topn),
        h("label", { class: "check", title: "Finds the best build over every usable item. With a damage-model minimum the shortlist search is used instead." },
          f.exact, "Exact search (every item)")),
      h("p", { class: "hint" }, "Goals worked out by WynnBuilder's model (effective HP, DPS, …) use a local search: good builds, not proven the best. " +
        "Spare skill points then go where they help the goal, set by hand in the build. " +
        "Stats are 100% rolls (or your real rolls for items you own). With a damage-model minimum (or Exact search unticked) it searches per-slot shortlists; raise the shortlist size to double-check those.")),
    h("div", { class: "run-bar" }, h("div", { class: "progress" }, bar), status,
      h("div", { class: "row" }, runBtn, upBtn, cancelBtn)),
    h("div", { class: "row trade-row" }, tradeBtn, h("span", { class: "muted" }, "trade"), f.tdamage,
      h("span", { class: "muted" }, "against"), f.ttank),
    resultBox, upgradesBox);
  runBtn.disabled = tradeBtn.disabled = upBtn.disabled = true;      // until the goal list is in
  syncSpells().finally(() => { if (!S.job) runBtn.disabled = tradeBtn.disabled = upBtn.disabled = false; }).then(() => {
    if (pre.objective) {
      const [goal, ...rest] = Object.keys(pre.objective);
      if ([...f.goal.options].some((o) => o.value === goal)) f.goal.value = goal;
      if (rest[0] && [...f.tie.options].some((o) => o.value === rest[0])) f.tie.value = rest[0];
    }
  });
}

// ------------------------------------------------------------------ compare
const COMPARE_LABEL = { hp: "Health", ehp: "Effective HP", ehp_no_agi: "Effective HP (no agi)", hpr: "HP regen",
  sp_total: "Skill points assigned" };
function compareLabel(key) {
  if (COMPARE_LABEL[key]) return COMPARE_LABEL[key];
  if (key.startsWith("sp_")) return `${ELEMENTS[key.slice(3)].name} (total)`;
  return null;
}
async function renderCompare() {
  const box = $("#compare");
  const pick = (id, idx) => {
    const sel = h("select", { id, "aria-label": id === "cmp-a" ? "First build" : "Second build" },
      S.builds.map((b) => h("option", { value: b.file }, b.name)));
    sel.value = S.compare?.[idx] || S.builds[idx]?.file || "";
    return sel;
  };
  const a = pick("cmp-a", 0), b = pick("cmp-b", 1), out = h("div");
  const roll = h("span", { class: "segs" });
  let drawn = 0;                   // only the latest draw may fill the page
  const draw = async () => {
    const seq = ++drawn;
    S.compare = [a.value, b.value];
    roll.replaceChildren(...[["typical", "Typical"], ["perfect", "Perfect"]].map(([v, l]) =>
      h("button", { class: "seg" + (S.roll === v ? " on" : ""), onclick: () => { S.roll = v; store.set("wt-roll", v); draw(); } }, l)));
    if (!a.value || !b.value) { out.replaceChildren(h("p", { class: "muted" }, "You need two builds to compare.")); return; }
    out.replaceChildren(h("p", { class: "hint" }, "Comparing…"));
    try {
      const r = await api("GET", `/api/compare?a=${encodeURIComponent(a.value)}&b=${encodeURIComponent(b.value)}&roll=${S.roll}`);
      if (seq !== drawn) return;      // a newer choice is on its way
      const nameA = S.builds.find((x) => x.file === a.value)?.name, nameB = S.builds.find((x) => x.file === b.value)?.name;
      const itemCell = (it) => (it ? h("span", { class: `tier-${it.tier || "none"}` }, it.text) : h("span", { class: "muted" }, "—"));
      const num = (v) => (v == null ? "—" : fmt(Math.round(v)));
      const diffCell = (d) => (d == null || d === 0 ? h("td", { class: "muted" }, d === 0 ? "=" : "") :
        h("td", { class: d > 0 ? "pos" : "neg" }, `${d > 0 ? "+" : ""}${fmt(Math.round(d))}`));
      const statName = (k) => { const l = compareLabel(k); if (l) return l; const [label, , el] = idLabel(k); return h("span", {}, elemTag(el), label); };
      const table = (title, rows, cell) => h("table", { class: "cmp" },
        h("thead", {}, h("tr", {}, h("th", {}, title), h("th", {}, nameA), h("th", {}, nameB), h("th", {}, "Change"))),
        h("tbody", {}, rows.map(cell)));
      out.replaceChildren(
        table("Gear", r.gear, (row) => h("tr", { class: row.same ? "" : "changed" },
          h("td", {}, slotLabel(row.key)), h("td", {}, itemCell(row.a_item)), h("td", {}, itemCell(row.b_item)),
          h("td", { class: "muted" }, row.same ? "same" : "different"))),
        table("Stats", r.stats, (row) => h("tr", {}, h("td", {}, statName(row.key)), h("td", {}, num(row.a)), h("td", {}, num(row.b)), diffCell(row.diff))),
        r.damage.length ? table("Damage", r.damage, (row) => h("tr", {}, h("td", {}, compareLabel(row.key) || row.key),
          h("td", {}, num(row.a)), h("td", {}, num(row.b)), diffCell(row.diff))) : null,
        h("p", { class: "hint" }, `${S.roll === "perfect" ? "Perfect" : "Typical"} rolls. Damage is each spell's headline number (melee: average DPS).` +
          (r.same_class ? "" : " The builds are different classes, so their spells don't line up.")));
    } catch (e) { if (seq === drawn) out.replaceChildren(h("p", { class: "neg" }, e.message)); }
  };
  a.onchange = b.onchange = draw;
  box.replaceChildren(h("div", { class: "head" }, h("h2", { style: "margin:0;flex:1" }, "Compare builds"), roll),
    h("div", { class: "card" }, h("div", { class: "form" }, h("label", {}, "First build", a), h("label", {}, "Second build", b))),
    h("div", { class: "card" }, out));
  await draw();
}

// ------------------------------------------------------------------ live updates
function watch() {
  const es = new EventSource("/api/events");
  es.addEventListener("tools", (ev) => window.wtTerminal?.showTools(JSON.parse(ev.data)));
  es.onmessage = async (ev) => {
    const { changed, removed, open } = JSON.parse(ev.data);
    if (changed.includes("inventory.json") || removed.includes("inventory.json")) {
      await loadInventory();
      if (!$("#inventory").hidden) renderInventory();
    }
    await loadList();
    const c = S.cur; if (!c) return;
    if (removed.includes(c.file)) { toast("This build's file was deleted"); return; }
    if (changed.includes(c.file)) {
      const fresh = await api("GET", `/api/builds/${encodeURIComponent(c.file)}`);
      if (fresh._mtime === c.mtime) return;          // our own save
      if (!c.dirty) { await openBuild(c.file, { quiet: $("#editor").hidden }); toast("Updated from disk"); }
      else { c.conflict = true; renderDerived(); }
    }
    if (open) await showRequested(open);
  };
}

// The AI asked to show a build (`wt show`, or after `wt gear --save`). Never
// throw away the player's unsaved edits for it: point at the list instead.
async function showRequested(file) {
  const c = S.cur;
  if (c?.dirty && c.file !== file) { toast(`The AI saved ${file}. It's in the list on the left.`); return; }
  await openBuild(file);
  toast(`Opened ${file}`);
}

// ------------------------------------------------------------------ boot
async function boot() {
  if (location.search.includes("token=")) history.replaceState(null, "", "/");  // keep token out of history
  [S.meta, S.tomes] = await Promise.all([api("GET", "/api/meta"), api("GET", "/api/tomes")]);
  for (const el of document.querySelectorAll("#version, #tb-sub")) el.textContent = `data ${S.meta.version}`;
  $("#new-build").onclick = () => { renderSolver(); show("solver"); };
  $("#open-inventory").onclick = async () => { await renderInventory(); show("inventory"); };
  $("#open-compare").onclick = () => { renderCompare(); show("compare"); };
  $("#import-go").onclick = async () => {
    const link = $("#import-link").value.trim(), name = $("#import-name").value.trim();
    if (!link) return;
    let file = slug(name || "imported") + ".json", n = 2;
    while (S.builds.some((b) => b.file === file)) file = `${slug(name || "imported")}-${n++}.json`;
    try {
      $("#import-msg").textContent = "Checking the link…";
      const pv = await api("POST", "/api/import", { link, name, file, preview: true });
      if (!pv.readable) { $("#import-msg").textContent = pv.findings[0]?.message || "Couldn't read that link."; return; }
      const notable = pv.findings.filter((f) => f.level !== "info");
      if (notable.length) {
        const list = h("ul", { class: "findings" }, pv.findings.map((f) =>
          h("li", { class: f.level }, h("strong", {}, { error: "Problem: ", warn: "Note: ", info: "" }[f.level]), f.message)));
        const errors = notable.some((f) => f.level === "error");
        const go = await ask(errors ? "This build has problems" : "Before you import", [list,
          errors ? "You can still import it and fix it in the editor; it won't show as verified until then." : ""],
          [{ label: "Import", value: true, primary: !errors }, { label: "Cancel", value: false }]);
        if (!go) { $("#import-msg").textContent = "Not imported."; return; }
      }
      const out = await api("POST", "/api/import", { link, name, file });
      $("#import-msg").replaceChildren("Imported.", ...out.findings.filter((f) => f.level === "info")
        .map((f) => h("div", { class: "hint" }, f.message)));
      $("#import-link").value = ""; $("#import-name").value = "";
      await loadList(); openBuild(file);
    } catch (e) { $("#import-msg").textContent = e.message; }
  };
  window.addEventListener("beforeunload", (e) => { if (S.cur?.dirty) e.preventDefault(); });
  document.addEventListener("visibilitychange", reportView);
  window.addEventListener("focus", reportView);
  await Promise.all([loadList(), loadInventory()]);
  watch();
  reportView();
}
boot().catch((e) => { document.body.textContent = "Could not start: " + e.message; });
