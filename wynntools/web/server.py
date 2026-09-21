"""Local web app: view and edit build files, run the solver with live progress.

Security model (the app will also host a shell terminal): it only listens on
127.0.0.1, rejects any Host header other than localhost (blocks DNS rebinding),
and requires a random per-run token, delivered once in the URL and then kept in
an HttpOnly cookie.
"""
import asyncio
import contextlib
import json
import secrets
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import buildfile
from .. import inventory as inv_mod
from .. import settings as settings_mod
from ..codec import SLOTS, TOME_SLOTS
from ..data import VERSIONS, GameData
from ..gear_solver import CLASS_WEAPON, Spec, solve_gear, upgrades
from ..presets import PRESETS
from ..rules import ability_points
from ..tree_solver import solve_tree
from ..verify import stat
from . import terminal as term_mod
from .terminal import TerminalSession, available_clis

STATIC = Path(__file__).parent / "static"
STATE_FILE = ".server.json"       # in builds/: how a second `wt serve` finds the first
COOKIE = "wt_token"
EDITABLE = ("name", "notes", "level", "equipment", "tomes", "tree", "powders", "aspects",
            "skillpoints")
SUMMARY_STATS = ("hp", "mr", "spd", "eSteal", "lb", "poison", "maxMana", "sdPct", "mdPct")


UNAUTHORIZED_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Wynn Toolbox</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:34rem;
margin:15vh auto;padding:0 16px;color:#1b1e25;background:#f4f5f8}
@media (prefers-color-scheme:dark){body{color:#e6e8ee;background:#111318}}
code{background:rgba(127,127,127,.18);padding:1px 5px;border-radius:4px}</style></head>
<body><h1>This link has expired</h1>
<p>Each time <code>wt serve</code> starts, it makes a new private link. Open the
link it printed in the terminal (it ends in <code>?token=&hellip;</code>).</p>
<p>If you've lost it, stop the server and run <code>uv run wt serve</code> again.</p>
</body></html>"""


class Cancelled(Exception):
    pass


def create_app(builds_dir, port, token=None, terminal_cwd=None):
    builds_dir = Path(builds_dir).resolve()
    builds_dir.mkdir(parents=True, exist_ok=True)
    token = token or secrets.token_urlsafe(24)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    gd = GameData()
    jobs = {}
    term = TerminalSession(terminal_cwd or builds_dir.parent)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        yield
        term.close()                      # don't leave the shell running after exit

    app = FastAPI(title="Wynn Toolbox", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.token = token
    app.state.terminal = term

    # ------------------------------------------------------------ security
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("host") not in allowed_hosts:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        # The token in the URL wins over the cookie: after `wt serve` restarts
        # with a new token, the browser still sends the old session's cookie.
        supplied = request.query_params.get("token") or request.headers.get("x-wt-token") \
            or request.cookies.get(COOKIE)
        if not supplied or not secrets.compare_digest(supplied, token):
            if not request.url.path.startswith(("/api/", "/static/")):
                return HTMLResponse(UNAUTHORIZED_PAGE, status_code=401)
            return JSONResponse({"detail": "missing or wrong token; use the URL printed "
                                 "by `wt serve`"}, status_code=401)
        response = await call_next(request)
        if request.query_params.get("token"):
            response.set_cookie(COOKIE, token, httponly=True, samesite="strict")
        return response

    # ------------------------------------------------------------ helpers
    inv_path = builds_dir / "inventory.json"
    settings_path = builds_dir / "settings.json"
    RESERVED = {inv_path.name, settings_path.name, STATE_FILE}

    def inv():
        return inv_mod.load(inv_path)

    def path_for(name):
        p = (builds_dir / name).resolve()
        if p.parent != builds_dir or p.suffix != ".json":
            raise HTTPException(400, "build files must be .json directly inside builds/")
        if p.name in RESERVED:
            raise HTTPException(400, f"{p.name} is reserved for the app's own data")
        return p

    def version(p):
        """File version stamp, as a string: nanosecond times exceed what a
        JavaScript number can hold exactly, so a numeric stamp would round in
        the browser and every save would look like a conflict."""
        return str(p.stat().st_mtime_ns)

    def listing():
        out = []
        for p in sorted(builds_dir.glob("*.json")):
            if p.name in RESERVED:
                continue
            try:
                doc = buildfile.refresh(buildfile.read(p), gd, inv())
                st = doc.get("status") or {}
                weapon = (doc.get("equipment") or [None] * 9)[8]
                try:
                    cls = gd.weapon_class(weapon) if weapon else None
                except (KeyError, ValueError, NotImplementedError):
                    cls = None
                out.append({
                    "file": p.name, "name": doc.get("name") or p.stem,
                    "level": doc.get("level"), "weapon": weapon, "class": cls,
                    "verified": st.get("verified"),
                    "totals": {k: (st.get("totals") or {}).get(k, 0) for k in SUMMARY_STATS},
                    "mtime": version(p)})
            except (ValueError, KeyError, OSError) as e:
                out.append({"file": p.name, "name": p.stem, "error": str(e),
                            "mtime": version(p)})
        return out

    def checked(doc):
        try:
            return buildfile.refresh({k: doc[k] for k in doc if not k.startswith("_")}, gd, inv())
        except (KeyError, ValueError, NotImplementedError) as e:
            raise HTTPException(422, str(e).strip('"'))

    # ------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/assets/{name}")
    def asset(name: str):
        from fastapi.responses import FileResponse
        from ..data import CACHE_DIR, MEDIA
        if name not in MEDIA:
            raise HTTPException(404, "unknown asset")
        path = CACHE_DIR / "media" / name
        if not path.exists():
            from ..data import fetch
            fetch()
        if not path.exists():
            raise HTTPException(404, "icons not downloaded (offline?)")
        return FileResponse(path, media_type="image/png",
                            headers={"Cache-Control": "max-age=86400"})

    # ------------------------------------------------------------ reference data
    @app.get("/api/meta")
    def meta():
        return {"slots": SLOTS, "tome_slots": TOME_SLOTS, "version": VERSIONS[gd.version],
                "classes": sorted(CLASS_WEAPON),
                "presets": [{"name": k, "class": v["class"], "about": v["about"]}
                            for k, v in PRESETS.items()],
                "majors": sorted((k, v.get("displayName", k)) for k, v in gd.majids.items()),
                "stats": ["eSteal", "poison", "lb", "hp", "mr", "ms", "sdPct", "mdPct",
                          "spd", "xpb", "hprRaw", "ls"]}

    def item_summary(it):
        ids = {}
        for k, v in it.items():
            if k in ("hp", "lvl", "id", "slots", "lvlLow", "hpLow") or k.endswith("Req"):
                continue
            numeric = isinstance(v, (int, float)) and not isinstance(v, bool)
            if (numeric and v) or (isinstance(v, dict) and v.get("raw")):
                ids[k] = [stat(it, k, "min"), stat(it, k), stat(it, k, "max")]
        for k, (lo, hi) in (it.get("rolls") or {}).items():
            if lo or hi:
                ids[k] = [lo, (lo + hi) // 2, hi]
        damage = {k: it[k] for k in ("nDam", "eDam", "tDam", "wDam", "fDam", "aDam")
                  if isinstance(it.get(k), str) and it[k] != "0-0"}
        out = {"name": gd.name(it), "tier": it.get("tier"), "lvl": it.get("lvl"),
               "type": it.get("type"), "majors": it.get("majorIds") or [],
               "slots": it.get("slots") or 0, "hp_base": it.get("hp") or 0,
               "atkSpd": it.get("atkSpd"), "damage": damage, "ids": ids,
               "classReq": it.get("classReq"), "set": gd.set_of.get(gd.name(it)),
               "stats": {k: stat(it, k) for k in ("hp", "eSteal", "poison", "lb", "mr",
                                                   "maxMana", "spd") if stat(it, k)},
               "reqs": [it.get(r) or 0 for r in ("strReq", "dexReq", "intReq",
                                                  "defReq", "agiReq")]}
        if gd.name(it).startswith("CR-"):
            c = it["craft"]
            from ..crafting import NO_INGREDIENT, ingredient_sources
            out["sources"] = {n: ingredient_sources(gd.crafts.ing_by_name[n])
                              for n in dict.fromkeys(c.ingredients) if n != NO_INGREDIENT}
            out["craft"] = {"recipe": c.recipe, "ingredients": c.ingredients,
                            "mat_tiers": list(c.mat_tiers), "durability": it["durability"],
                            "problems": it["problems"],
                            "ranges": {k: list(v) for k, v in it["rolls"].items() if any(v)},
                            "crafter": "https://wynnbuilder.github.io/crafter/#" + gd.name(it)[3:]}
        return out

    @app.get("/api/items")
    def items(slot: str, level: int = 121, cls: str | None = None, q: str = ""):
        kind = {"ring1": "ring", "ring2": "ring"}.get(slot, slot)
        if kind == "weapon":
            kinds = {CLASS_WEAPON[cls]} if cls else set(CLASS_WEAPON.values())
        elif kind == "any":
            kinds = {"helmet", "chestplate", "leggings", "boots", "ring", "bracelet", "necklace",
                     *CLASS_WEAPON.values()}
        else:
            kinds = {kind}
        q = q.lower().strip()
        hits = []
        for it in gd.items:
            if it.get("type") not in kinds or (it.get("lvl") or 0) > level:
                continue
            cr = it.get("classReq")
            if cls and cr and cr.lower() != cls.lower():
                continue
            name = gd.name(it)
            if q and q not in name.lower():
                continue
            hits.append(it)
        hits.sort(key=lambda i: (not gd.name(i).lower().startswith(q), -(i.get("lvl") or 0)))
        return [item_summary(i) for i in hits[:40]]

    @app.get("/api/item")
    def item(name: str):
        try:
            return item_summary(gd.item(name))
        except (KeyError, ValueError, NotImplementedError) as e:
            raise HTTPException(404, str(e).strip('"'))

    @app.post("/api/craft-suggest")
    async def craft_suggest(request: Request):
        from ..craft_solver import CraftSpec, suggest_crafts
        body = await request.json()
        kind = {"ring1": "ring", "ring2": "ring"}.get(body["slot"], body["slot"])
        if kind == "weapon":
            if not body.get("cls"):
                raise HTTPException(422, "pick a weapon first so the class is known")
            kind = CLASS_WEAPON[body["cls"]]
        try:
            res = await asyncio.to_thread(
                suggest_crafts, CraftSpec(kind, int(body["level"]), body["objective"],
                                          roll=body.get("roll", "base")), gd.crafts,
                int(body.get("top", 3)))
        except (KeyError, ValueError) as e:
            raise HTTPException(422, str(e))
        for _, it in res:
            gd._craft_cache[it["name"]] = it
        return [{"score": sc, **item_summary(it)} for sc, it in res]

    @app.get("/api/tomes")
    def tomes():
        out = {}
        for t in gd.tome_by_name.values():
            out.setdefault(t["type"], []).append(
                {"name": gd.name(t), "lvl": t.get("lvl"),
                 "stats": {k: v for k, v in t.items()
                           if isinstance(v, (int, float)) and not isinstance(v, bool)
                           and k not in ("id", "lvl", "remapID") and v}})
        for v in out.values():
            v.sort(key=lambda t: (-(t["lvl"] or 0), t["name"]))
        return out

    @app.get("/api/compare")
    def compare_api(a: str, b: str, roll: str = "base"):
        from ..compare import compare
        builds = []
        for name in (a, b):
            p = path_for(name)
            if not p.exists():
                raise HTTPException(404, f"no build {name}")
            try:
                builds.append(buildfile.to_build(buildfile.read(p), gd))
            except KeyError as e:
                raise HTTPException(422, f"{name}: {e}")
        return compare(*builds, gd, "max" if roll == "perfect" else "base", inv())

    @app.get("/api/aspects/{cls}")
    def aspects_api(cls: str):
        if cls not in gd.atrees:
            raise HTTPException(404, f"no aspects for {cls}")
        return [{"name": a["displayName"], "rarity": a.get("tier"),
                 "tiers": [{"threshold": t.get("threshold"),
                            "desc": (t.get("description") or "").replace("</br>", "\n")}
                           for t in a["tiers"]]}
                for a in sorted(gd.aspects(cls), key=lambda a: a["displayName"])]

    @app.get("/api/tree/{cls}")
    def tree(cls: str):
        if cls not in gd.atrees:
            raise HTTPException(404, f"no tree for {cls}")
        return [{"id": n["id"], "name": n["display_name"], "cost": n.get("cost") or 0,
                 "row": n["display"]["row"], "col": n["display"]["col"],
                 "icon": n["display"].get("icon", "node_0"),
                 "archetype": n.get("archetype") or "", "req": n.get("archetype_req") or 0,
                 "parents": n["parents"], "deps": n.get("dependencies") or [],
                 "blockers": n.get("blockers") or [],
                 "req_archetype": n.get("req_archetype") or n.get("archetype") or "",
                 "desc": (n.get("desc") or "").replace("</br>", "\n")}
                for n in gd.tree(cls)]

    @app.post("/api/solve-tree")
    async def solve_tree_api(request: Request):
        body = await request.json()
        P = PRESETS.get(body.get("preset"))
        if not P:
            raise HTTPException(422, "unknown preset")
        tree = gd.tree(P["class"])
        sel = solve_tree(tree, P["weights"], ability_points(int(body["level"])))
        return sorted(n["display_name"] for n in tree if n["id"] in sel)

    # ------------------------------------------------------------ builds
    @app.get("/api/builds")
    def builds():
        return listing()

    @app.get("/api/builds/{name}")
    def get_build(name: str):
        p = path_for(name)
        if not p.exists():
            raise HTTPException(404, "no such build")
        doc = buildfile.read(p)
        try:
            # Re-check on every open so a file saved by older code, or edited by
            # hand without `wt link --write`, never shows stale numbers.
            doc = buildfile.refresh(doc, gd, inv())
        except (KeyError, ValueError, NotImplementedError) as e:
            doc = {**doc, "status": {**(doc.get("status") or {}), "verified": False,
                                     "problems": [f"can't read this build: {e}"]}}
        return {**doc, "_mtime": version(p), "_ap_cap": ability_points(doc.get("level") or 1)}

    @app.post("/api/check")
    async def check(request: Request):
        doc = checked(await request.json())
        return {**doc, "_ap_cap": ability_points(doc.get("level") or 1)}

    @app.put("/api/builds/{name}")
    async def put_build(name: str, request: Request):
        body = await request.json()
        p = path_for(name)
        base = body.get("_mtime")
        if p.exists() and base is not None and version(p) != str(base):
            raise HTTPException(409, "this build changed on disk since you opened it")
        old = buildfile.read(p) if p.exists() else {}
        doc = {**{k: v for k, v in old.items() if k not in buildfile.GENERATED},
               **{k: body[k] for k in EDITABLE if k in body}}
        doc = checked(doc)
        buildfile.write(p, doc)
        return {**doc, "_mtime": version(p),
                "_ap_cap": ability_points(doc.get("level") or 1)}

    @app.post("/api/import")
    async def import_link(request: Request):
        from ..codec import decode
        body = await request.json()
        p = path_for(body["file"])
        if p.exists():
            raise HTTPException(409, f"{p.name} already exists")
        try:
            b = decode(body["link"], gd)
        except (ValueError, KeyError, NotImplementedError) as e:
            raise HTTPException(422, f"could not read that link: {e}")
        doc = checked({"name": body.get("name") or p.stem, "notes": "",
                       **buildfile.from_build(b, gd)})
        buildfile.write(p, doc)
        return {"file": p.name}

    @app.get("/api/events")
    async def events(request: Request):
        """Server-sent events whenever a build file is added, changed or removed."""
        async def stream():
            seen = {x["file"]: x["mtime"] for x in listing()}
            while not await request.is_disconnected():
                await asyncio.sleep(1)
                now = {p.name: version(p) for p in builds_dir.glob("*.json")
                       if p.name not in RESERVED}
                changed = [f for f in now if seen.get(f) != now[f]]
                removed = [f for f in seen if f not in now]
                if changed or removed:
                    seen = now
                    yield f"data: {json.dumps({'changed': changed, 'removed': removed})}\n\n"
                else:
                    yield ": keep-alive\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")

    # ------------------------------------------------------------ solver jobs
    @app.post("/api/solve")
    async def solve(request: Request):
        body = await request.json()
        raw = body["spec"]
        p = path_for(body["file"])
        try:
            spec = Spec(cls=raw["class"], level=int(raw["level"]), objective=raw["objective"],
                        floors=raw.get("floors") or {},
                        require_major=raw.get("require_major") or [],
                        force={k: v for k, v in (raw.get("force") or {}).items() if v},
                        exclude=set(raw.get("exclude") or []),
                        exclude_tiers=set(raw.get("exclude_tiers") or []),
                        tomes=[gd.tome(t)["id"] if t else None for t in raw.get("tomes") or []],
                        topn=int(raw.get("topn") or 8), crafted=bool(raw.get("crafted")),
                        roll=raw.get("roll") or "base")
        except (KeyError, ValueError, TypeError) as e:
            raise HTTPException(422, f"bad spec: {e}")
        owned = inv()
        if body.get("owned_only"):
            spec.only, spec.inventory, spec.crafted = owned.names(), owned, False
        preset = body.get("tree_preset") or None
        if preset and PRESETS[preset]["class"] != spec.cls:
            raise HTTPException(422, f"preset {preset} is for {PRESETS[preset]['class']}")
        # Exact search by default; damage minimums need the shortlist search.
        exact = body.get("exact", True) and not spec.floors.get("damage")
        damage_tree(spec, preset)
        job = {"id": uuid.uuid4().hex[:10], "state": "running", "progress": None,
               "file": p.name, "error": None, "search": "exact" if exact else "shortlists", "cancel": False, "started": time.time()}
        jobs[job["id"]] = job

        def on_progress(pr):
            job["progress"] = pr
            if job["cancel"]:
                raise Cancelled()

        def run():
            try:
                if exact:
                    from ..gear_milp import solve_gear_exact
                    r = solve_gear_exact(spec, gd, progress=lambda p: on_progress(
                        {"fraction": None, "nodes": p["round"], "best": round(p["best"], 2),
                         "elapsed": p["elapsed"], "exact": True}))
                else:
                    r = solve_gear(spec, gd, progress=on_progress)
                if r is None:
                    job["state"], job["error"] = "failed", "no build satisfies these constraints"
                    return
                tomes = [t or None for t in raw.get("tomes") or []]
                doc = {"name": body.get("name") or p.stem, "notes": body.get("notes", ""),
                       "level": spec.level, "equipment": r.equipment,
                       "tomes": tomes + [None] * (len(TOME_SLOTS) - len(tomes)),
                       "spec": raw, "tree_preset": preset}
                if preset:
                    b = buildfile.to_build({**doc, "tree": []}, gd)
                    b.atree = solve_tree(gd.tree(spec.cls), PRESETS[preset]["weights"],
                                         ability_points(spec.level))
                    doc["tree"] = buildfile.from_build(b, gd)["tree"]
                buildfile.write(p, buildfile.refresh(doc, gd, owned))
                job["state"] = "done"
            except Cancelled:
                job["state"] = "cancelled"
            except Exception as e:   # surface anything else to the page
                job["state"], job["error"] = "failed", f"{type(e).__name__}: {e}"

        threading.Thread(target=run, daemon=True).start()
        return {"job": job["id"]}

    @app.get("/api/inventory")
    def get_inventory():
        i = inv()
        return {**i.to_json(), "unknown": inv_mod.validate(i, gd)}

    @app.post("/api/inventory")
    async def change_inventory(request: Request):
        """{"action": "add"|"remove", "kind": "item"|"tome"|"craft", "name": ..., "rolls": {...}?}"""
        body = await request.json()
        i, name, kind = inv(), body.get("name") or "", body.get("kind", "item")
        try:
            if kind == "tome":
                gd.tome(name)
            else:
                gd.item(name)
        except (KeyError, ValueError, NotImplementedError):
            raise HTTPException(422, f"unknown {kind}: {name}")
        if body.get("action") == "add":
            if kind == "tome":
                i.tomes.append(name)
            elif name.startswith("CR-"):
                if name not in i.crafts:
                    i.crafts.append(name)
            else:
                entry = i.items.setdefault(name, {})
                if "rolls" in body:
                    rolls = {k: int(v) for k, v in (body["rolls"] or {}).items() if v not in ("", None)}
                    if rolls:
                        entry["rolls"] = rolls
                    else:
                        entry.pop("rolls", None)
        elif body.get("action") == "remove":
            if kind == "tome":
                if name in i.tomes:
                    i.tomes.remove(name)
            else:
                i.items.pop(name, None)
                if name in i.crafts:
                    i.crafts.remove(name)
        else:
            raise HTTPException(422, "action must be add or remove")
        inv_mod.save(i, inv_path)
        return i.to_json()

    def damage_tree(spec, preset):
        """Damage minimums are checked on a fixed tree: the preset's."""
        if not spec.floors.get("damage"):
            return
        if not preset or preset not in PRESETS:
            raise HTTPException(422, "damage minimums need a tree preset")
        if PRESETS[preset]["class"] != spec.cls:
            raise HTTPException(422, f"preset {preset} is for {PRESETS[preset]['class']}")
        spec.atree = set(solve_tree(gd.tree(spec.cls), PRESETS[preset]["weights"],
                                    ability_points(spec.level)))

    @app.get("/api/spells")
    def spells_api(cls: str, preset: str = "", level: int = 105):
        """Spell names a preset's tree gives (for damage minimums)."""
        from ..damage import collect_spells, merge_tree
        if cls not in gd.atrees:
            raise HTTPException(404, "unknown class")
        active = set()
        if preset in PRESETS and PRESETS[preset]["class"] == cls:
            active = set(solve_tree(gd.tree(cls), PRESETS[preset]["weights"], ability_points(level)))
        spells = collect_spells(merge_tree(cls, active, gd))
        return [{"name": sp["name"], "base_spell": b, "melee": b == 0} for b, sp in sorted(spells.items())]

    @app.post("/api/upgrades")
    async def upgrades_api(request: Request):
        body = await request.json()
        raw = body["spec"]
        try:
            spec = Spec(cls=raw["class"], level=int(raw["level"]), objective=raw["objective"],
                        floors=raw.get("floors") or {}, require_major=raw.get("require_major") or [],
                        force={k: v for k, v in (raw.get("force") or {}).items() if v},
                        exclude_tiers=set(raw.get("exclude_tiers") or []),
                        tomes=[gd.tome(t)["id"] if t else None for t in raw.get("tomes") or []],
                        topn=int(raw.get("topn") or 8))
        except (KeyError, ValueError, TypeError) as e:
            raise HTTPException(422, f"bad spec: {e}")
        damage_tree(spec, body.get("tree_preset") or None)
        owned = inv()
        if not owned.names():
            raise HTTPException(422, "your inventory is empty; mark some items as owned first")
        job = {"id": uuid.uuid4().hex[:10], "state": "running", "progress": None, "file": None,
               "error": None, "cancel": False, "result": None, "started": time.time()}
        jobs[job["id"]] = job

        def on_progress(pr):
            job["progress"] = pr
            if job["cancel"]:
                raise Cancelled()

        def run():
            try:
                base, ups = upgrades(spec, gd, owned, per_slot=int(body.get("per_slot") or 6),
                                     top=int(body.get("top") or 10), progress=on_progress)
                job["result"] = {
                    "base": None if base is None else {"score": base.score, "equipment": base.equipment},
                    "upgrades": [{"item": u.item, "slot": u.slot, "gain": u.gain,
                                  "score": u.result.score, "equipment": u.result.equipment} for u in ups]}
                job["state"] = "done"
            except Cancelled:
                job["state"] = "cancelled"
            except Exception as e:
                job["state"], job["error"] = "failed", f"{type(e).__name__}: {e}"

        threading.Thread(target=run, daemon=True).start()
        return {"job": job["id"]}

    @app.post("/api/jobs/{jid}/cancel")
    def cancel(jid: str):
        if jid not in jobs:
            raise HTTPException(404, "no such job")
        jobs[jid]["cancel"] = True
        return {"ok": True}

    @app.get("/api/jobs/{jid}/events")
    async def job_events(jid: str, request: Request):
        if jid not in jobs:
            raise HTTPException(404, "no such job")

        async def stream():
            while not await request.is_disconnected():
                j = jobs[jid]
                yield "data: " + json.dumps({k: j.get(k) for k in ("state", "progress", "file",
                                                                   "error", "result")}) + "\n\n"
                if j["state"] != "running":
                    return
                await asyncio.sleep(0.25)
        return StreamingResponse(stream(), media_type="text/event-stream")

    # ------------------------------------------------------------ settings
    @app.get("/api/settings")
    def get_settings():
        return settings_mod.load(settings_path)

    @app.put("/api/settings")
    async def put_settings(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "expected a JSON object")
        try:
            return settings_mod.save(body, settings_path)
        except ValueError as e:
            raise HTTPException(422, str(e))

    # ------------------------------------------------------------ terminal
    @app.get("/api/terminal/clis")
    def clis():
        return {**available_clis(), "running": term.launched and term.alive()}

    def start_ai(key):
        """Type the command that starts AI `key`, if it is installed."""
        cmd = term_mod.launch_command(key)
        if cmd:
            term.launched = True
            asyncio.create_task(term.run(cmd))

    def autolaunch():
        """Start the saved AI once per fresh shell: a page reload reattaches to
        the running one, and quitting the AI leaves the player at the prompt."""
        ai = settings_mod.load(settings_path)["ai"]
        if not term.launched and ai not in (None, settings_mod.SHELL):
            start_ai(ai)

    @app.websocket("/ws/terminal")
    async def terminal_ws(ws: WebSocket):
        # The HTTP middleware does not see websockets, so check everything here.
        # Origin matters most: without it any site open in the browser could
        # connect to this shell (cross-site websocket hijacking).
        origins = {f"http://{h}" for h in allowed_hosts}
        supplied = ws.cookies.get(COOKIE) or ""
        if ws.headers.get("host") not in allowed_hosts \
                or ws.headers.get("origin") not in origins \
                or not secrets.compare_digest(supplied, token):
            await ws.close(code=1008)
            return
        await ws.accept()
        term.ensure()
        queue = term.attach()
        await ws.send_bytes(bytes(term.scrollback))
        autolaunch()

        async def pump():
            while True:
                await ws.send_bytes(await queue.get())
        pump_task = asyncio.create_task(pump())
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                if msg["type"] == "input":
                    term.write(msg["data"])
                elif msg["type"] == "resize":
                    term.resize(int(msg["cols"]), int(msg["rows"]))
                elif msg["type"] == "run":           # by key only; never a command
                    start_ai(msg.get("cmd"))
                elif msg["type"] == "start":         # the saved AI, once per shell
                    autolaunch()
                elif msg["type"] == "install":
                    cmd = term_mod.install_command(msg.get("cmd"))
                    if cmd:
                        asyncio.create_task(term.run(cmd))
                elif msg["type"] == "install-node":
                    cmd = term_mod.node_install_command()
                    if cmd:
                        asyncio.create_task(term.run(cmd))
                elif msg["type"] == "restart":
                    term.close()
                    term.ensure()
                    autolaunch()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            pump_task.cancel()
            term.detach(queue)

    return app


def running_instance(builds_dir):
    """The URL of a `wt serve` already running for these builds, or None."""
    import urllib.request
    try:
        state = json.loads((Path(builds_dir) / STATE_FILE).read_text())
        port, token = int(state["port"]), str(state["token"])
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/settings",
                                     headers={"x-wt-token": token})
        with urllib.request.urlopen(req, timeout=2) as r:
            if r.status == 200:
                return f"http://127.0.0.1:{port}/?token={token}"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def free_port(start, tries=20):
    import socket
    import sys
    for port in range(start, start + tries):
        with socket.socket() as s:
            # Like uvicorn: a port left in TIME_WAIT by the last run is reusable,
            # so a quick restart keeps its port (and the page's saved layout).
            # On Windows SO_REUSEADDR would allow stealing a live port instead.
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"no free port between {start} and {start + tries - 1}")


def serve(builds_dir="builds", port=8765, open_browser=True):
    import os
    import webbrowser

    import uvicorn
    builds_dir = Path(builds_dir)
    url = running_instance(builds_dir)
    if url:
        print(f"Wynn Toolbox is already running at:\n  {url}", flush=True)
        if open_browser:
            webbrowser.open(url)
        return
    port = free_port(port)
    app = create_app(builds_dir, port)
    url = f"http://127.0.0.1:{port}/?token={app.state.token}"
    state = builds_dir / STATE_FILE
    # Readable only by this user: the token is the session's password.
    fd = os.open(state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"port": port, "token": app.state.token, "pid": os.getpid()}, f)
    print(f"Wynn Toolbox is running at:\n  {url}\n(only this computer can connect; "
          f"the token in the link is the password for this session)\n\n"
          f"Keep this window open while you use Wynn Toolbox. Close it (or press Ctrl+C) "
          f"to quit.", flush=True)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        state.unlink(missing_ok=True)
