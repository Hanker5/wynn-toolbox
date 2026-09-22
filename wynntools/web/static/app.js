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
const EDITABLE = ["name", "notes", "level", "equipment", "tomes", "tree", "powders", "aspects", "skillpoints"];
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
      h("button", { id: "ed-revert", onclick: () => openBuild(c.file) }, "Revert"),
      h("button", { id: "ed-save", class: "primary", onclick: save }, "Save")),
    h("div", { id: "ed-banners" }),
    h("div", { class: "ed-grid" },
      h("div", { class: "ed-main" },
        h("section", { class: "panel" }, h("div", { id: "ed-equip", class: "equip" })),
        h("section", { class: "panel" }, h("div", { id: "ed-sp", class: "sp" }), h("div", { id: "ed-sp-foot", class: "sp-foot" })),
        tomesPanel, aspectsPanel,
        h("section", { class: "panel" }, h("div", { class: "panel-h", id: "ed-tree-h" }), h("div", { id: "ed-tree" }))),
      h("aside", { class: "ed-side" },
        h("section", { class: "panel" }, h("div", { class: "panel-h" }, h("span", {}, "Summary"), rollToggle()),
          h("div", { id: "ed-tiles", class: "summary" })),
        h("section", { class: "panel", id: "ed-damage-panel", hidden: true },
          h("div", { class: "panel-h" }, h("span", { id: "ed-damage-h" }, "Damage")),
          h("div", { id: "ed-damage", class: "summary" })),
        h("section", { class: "panel", id: "ed-sets-panel", hidden: true }, h("div", { class: "panel-h" }, "Set bonuses"),
          h("div", { id: "ed-sets", class: "summary" })),
        h("section", { class: "panel" }, h("div", { class: "panel-h" }, "Checks"), h("div", { id: "ed-checks", class: "summary" })),
        h("section", { class: "panel" }, h("div", { class: "panel-h" }, "Notes"), notes))));
  renderEquipment(); renderTomes(); await renderTree(); await renderAspects(); renderDerived();
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
        h("span", { class: "row tight" }, ownBtn, craftBtn)),
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
    h("p", { class: "hint" }, "Skill points are assigned automatically in the link. " +
      ((c.doc.aspects || []).some(Boolean) ? "" : "No aspects set.")));
}

const DAMAGE_CLASS = { Neutral: "neutral", Earth: "earth", Thunder: "thunder", Water: "water", Fire: "fire", Air: "air" };
const f2 = (x) => (x ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function spellCard(sp) {
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
  const open = new Set([...document.querySelectorAll("#ed-damage details.spell[open]")].map((x) => x.dataset.name));
  const cards = dmg.spells.map((sp) => { const c = spellCard(sp); c.dataset.name = sp.name; c.open = open.has(sp.name); return c; });
  const knobs = [...Object.entries(dmg.sliders).map(([k, v]) => `${k} ${v.default}/${v.max}`), ...dmg.toggles.map((t) => `${t} off`)];
  $("#ed-damage").replaceChildren(
    statRow(h("span", {}, h("span", { class: "hp" }, "♥ "), "Effective HP"), fmt(Math.round(d.ehp))),
    statRow("Effective HP (no agi)", fmt(Math.round(d.ehp_no_agi))),
    statRow("HP regen", fmt(Math.round(d.hpr))),
    dmg.poison_tick ? statRow("Poison", `${fmt(dmg.poison_tick)}/s`, "pos") : null,
    statRow("Crit chance", `${dmg.crit_chance}%`),
    h("div", { class: "sep" }),
    ...cards,
    h("p", { class: "hint" }, `${S.roll === "perfect" ? "Perfect" : "Typical"} rolls. Click a spell for every part. ` +
      "No potions, raid buffs or powder specials" + (knobs.length ? `; ability sliders at WynnBuilder's defaults (${knobs.join(", ")})` : "") + "."));
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

function renderSP(st) {
  const need = st.sp_need || {};
  $("#ed-sp").replaceChildren(...SKILLS.map((s) => {
    const e = ELEMENTS[s], v = need[s] ?? 0;
    return h("div", { class: "sp-box" + (v > 100 ? " over" : "") },
      h("div", { class: `sp-h ${e.cls}` }, `${e.sym} ${e.name}`),
      h("div", { class: "sp-v" }, fmt(v)),
      h("div", { class: "bar" }, h("i", { style: `width:${Math.min(100, v)}%` })),
      h("div", { class: "sp-sub" }, `assign · total ${fmt(st.sp_final?.[s] ?? v)}`));
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

  renderSP(st); renderSummary(st); renderDamage(st); renderSets(st); renderChecks(st);
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
  f.owned = h("input", { type: "checkbox" });
  f.exact = h("input", { type: "checkbox", checked: true });
  f.tomesFrom = h("select", {}, h("option", { value: "" }, "no tomes"), S.builds.map((b) => h("option", { value: b.file }, b.name)));
  f.preset = h("select", { "aria-label": "Tree preset" });
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
  f.dmgSpell = h("select", { "aria-label": "Spell for the damage minimum" });
  const syncSpells = async () => {
    const keep = f.dmgSpell.value;
    if (!f.preset.value) {
      f.dmgSpell.replaceChildren(h("option", { value: "" }, "pick a tree preset first"));
      f.dmgSpell.disabled = true; return;
    }
    const spells = await api("GET", `/api/spells?cls=${f.cls.value}&preset=${encodeURIComponent(f.preset.value)}&level=${+f.level.value || 105}`);
    f.dmgSpell.replaceChildren(h("option", { value: "" }, "none"),
      ...spells.map((sp) => h("option", { value: sp.name }, sp.melee ? `${sp.name} (DPS)` : sp.name)));
    f.dmgSpell.disabled = false;
    if (spells.some((sp) => sp.name === keep)) f.dmgSpell.value = keep;
  };
  f.cls.onchange = () => { syncPresets(); syncSpells(); }; syncPresets();
  f.preset.onchange = syncSpells; f.level.addEventListener("change", syncSpells); syncSpells();
  const weaponAc = autocomplete(f.weapon, (q) => api("GET", `/api/items?slot=weapon&cls=${f.cls.value}&level=${f.level.value}&q=${encodeURIComponent(q)}`), () => {});

  const bar = h("i"), status = h("div", { class: "hint" }), cancelBtn = h("button", { class: "danger", hidden: true }, "Cancel");
  const runBtn = h("button", { class: "primary" }, "Find the best build");
  async function readForm() {
    const floors = {};
    for (const k of ["hp", "mr", "spd", "mana", "weapon_dps"]) if (f[k].value !== "") floors[k] = +f[k].value;
    if (f.dmgSpell.value && f.dmg_min.value !== "") floors.damage = { [f.dmgSpell.value]: +f.dmg_min.value };
    const objective = { [f.goal.value]: 1 };
    if (f.tie.value && f.tie.value !== f.goal.value) objective[f.tie.value] = 0.01;
    let tomes = [];
    if (f.tomesFrom.value) tomes = (await api("GET", `/api/builds/${encodeURIComponent(f.tomesFrom.value)}`)).tomes || [];
    return { class: f.cls.value, level: +f.level.value, objective, floors,
      require_major: [...majors], force: f.weapon.value ? { weapon: f.weapon.value } : {},
      exclude_tiers: f.mythic.checked ? ["Mythic"] : [], tomes, topn: +f.topn.value || 8,
      crafted: f.crafted.checked && !f.owned.checked };
  }
  function follow(job, onDone) {
    runBtn.disabled = upBtn.disabled = true; cancelBtn.hidden = false;
    S.job = job;                // the app window's close button warns while it runs
    cancelBtn.onclick = () => api("POST", `/api/jobs/${job}/cancel`);
    const es = new EventSource(`/api/jobs/${job}/events`);
    es.onmessage = async (ev) => {
      const j = JSON.parse(ev.data), p = j.progress;
      if (p) {
        const mm = Math.floor(p.elapsed / 60), ss = String(Math.floor(p.elapsed % 60)).padStart(2, "0");
        if (p.exact) {       // the exact search has rounds, not a known fraction
          bar.parentElement.classList.add("busy");
          status.textContent = `Exact search · round ${p.nodes} · best possible ${p.best}` + (p.elapsed ? ` · ${mm}:${ss}` : "");
        } else {
          bar.style.width = `${(p.fraction * 100).toFixed(1)}%`;
          status.textContent = `${(p.fraction * 100).toFixed(1)}% · ${fmt(p.nodes)} checked · best so far ${p.best ?? "—"}` +
            (p.elapsed ? ` · ${mm}:${ss}` : "");
        }
      }
      if (j.state !== "running") {
        es.close(); runBtn.disabled = upBtn.disabled = false; cancelBtn.hidden = true;
        S.job = null;
        bar.parentElement.classList.remove("busy");
        if (j.state === "done") { bar.style.width = "100%"; await onDone(j); }
        else status.textContent = j.state === "cancelled" ? "Cancelled." : `Failed: ${j.error}`;
      }
    };
  }
  runBtn.onclick = async () => {
    const spec = await readForm();
    const name = f.name.value.trim() || `${f.cls.value} ${idLabel(f.goal.value)[0]}`;
    let file = slug(name) + ".json", n = 2;
    while (S.builds.some((b) => b.file === file)) file = `${slug(name)}-${n++}.json`;
    try {
      const { job } = await api("POST", "/api/solve", { spec, file, name, tree_preset: f.preset.value || null,
        owned_only: f.owned.checked, exact: f.exact.checked });
      upgradesBox.replaceChildren();
      follow(job, async (j) => { toast("Build found"); await loadList(); openBuild(j.file); });
    } catch (e) { status.textContent = e.message; }
  };
  const upgradesBox = h("div", { id: "upgrades" });
  const upBtn = h("button", { title: "Rank items you don't own by how much each would improve your best owned-only build" },
    "What should I get next?");
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
      });
    } catch (e) { upgradesBox.replaceChildren(h("p", { class: "neg" }, e.message)); }
  };

  $("#solver").replaceChildren(
    h("div", { class: "head" }, h("h2", { style: "margin:0;flex:1" }, "New build from goals")),
    h("div", { class: "card" }, h("h3", {}, "Who and what"),
      h("div", { class: "form" }, field("Name", f.name), field("Class", f.cls), field("Level", f.level),
        field("Maximize", f.goal), field("Tiebreaker (tiny weight)", f.tie), field("Tree preset", f.preset))),
    h("div", { class: "card" }, h("h3", {}, "Minimums (leave blank for none)"),
      h("div", { class: "form" }, field("Health", num("hp", "e.g. 17000")), field("Mana regen", num("mr", "e.g. 20")),
        field("Walk speed %", num("spd", "e.g. 0")), field("Max mana", num("mana", "e.g. 113")),
        field("Weapon DPS", num("weapon_dps", "e.g. 700")),
        field("Spell", f.dmgSpell), field("Spell damage at least", num("dmg_min", "e.g. 15000"))),
      h("p", { class: "hint" }, "Health and mana include base stats and the tomes below. Max mana assumes spare skill points go into Intelligence. " +
        "Spell damage is the spell's headline number as WynnBuilder shows it (melee: average DPS), with the preset's tree and no powders.")),
    h("div", { class: "card" }, h("h3", {}, "Requirements"),
      h("div", { class: "form" }, field("Required major IDs", majorIn), field("Weapon (optional)", weaponAc),
        field("Tomes", f.tomesFrom), field("Shortlist size", f.topn),
        h("label", { class: "check" }, f.mythic, "No mythics"),
        h("label", { class: "check" }, f.crafted, "Include crafted items"),
        h("label", { class: "check" }, f.owned, "Only items I own"),
        h("label", { class: "check", title: "Finds the best build over every usable item. With a spell damage minimum the shortlist search is used instead." },
          f.exact, "Exact search (every item)")),
      majorChips),
    h("div", { class: "card" }, h("h3", {}, "Run"), h("div", { class: "progress" }, bar), status,
      h("div", { class: "row", style: "margin-top:10px" }, runBtn, upBtn, cancelBtn),
      h("p", { class: "hint" }, "Stats are 100% rolls (or your real rolls for items you own). The exact search finds the best build over every usable item. " +
        "With a spell damage minimum (or Exact search unticked) it searches per-slot shortlists instead; raise the shortlist size to double-check those."),
      upgradesBox));
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
      await api("POST", "/api/import", { link, name, file });
      $("#import-msg").textContent = "Imported."; $("#import-link").value = ""; $("#import-name").value = "";
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
