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
from ..codec import SLOTS, TOME_SLOTS
from ..data import VERSIONS, GameData
from ..gear_solver import CLASS_WEAPON, Spec, solve_gear
from ..presets import PRESETS
from ..rules import ability_points
from ..tree_solver import solve_tree
from ..verify import stat
from .terminal import TerminalSession, available_clis

STATIC = Path(__file__).parent / "static"
COOKIE = "wt_token"
EDITABLE = ("name", "notes", "level", "equipment", "tomes", "tree", "powders", "skillpoints")
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
    def path_for(name):
        p = (builds_dir / name).resolve()
        if p.parent != builds_dir or p.suffix != ".json":
            raise HTTPException(400, "build files must be .json directly inside builds/")
        return p

    def version(p):
        """File version stamp, as a string: nanosecond times exceed what a
        JavaScript number can hold exactly, so a numeric stamp would round in
        the browser and every save would look like a conflict."""
        return str(p.stat().st_mtime_ns)

    def listing():
        out = []
        for p in sorted(builds_dir.glob("*.json")):
            try:
                doc = buildfile.refresh(buildfile.read(p), gd)
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
            return buildfile.refresh({k: doc[k] for k in doc if not k.startswith("_")}, gd)
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
               "classReq": it.get("classReq"),
               "stats": {k: stat(it, k) for k in ("hp", "eSteal", "poison", "lb", "mr",
                                                   "maxMana", "spd") if stat(it, k)},
               "reqs": [it.get(r) or 0 for r in ("strReq", "dexReq", "intReq",
                                                  "defReq", "agiReq")]}
        if gd.name(it).startswith("CR-"):
            c = it["craft"]
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
            doc = buildfile.refresh(doc, gd)
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
                now = {p.name: version(p) for p in builds_dir.glob("*.json")}
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
                        tomes=[gd.tome(t)["id"] for t in raw.get("tomes") or [] if t],
                        topn=int(raw.get("topn") or 8), crafted=bool(raw.get("crafted")),
                        roll=raw.get("roll") or "base")
        except (KeyError, ValueError, TypeError) as e:
            raise HTTPException(422, f"bad spec: {e}")
        preset = body.get("tree_preset") or None
        if preset and PRESETS[preset]["class"] != spec.cls:
            raise HTTPException(422, f"preset {preset} is for {PRESETS[preset]['class']}")
        job = {"id": uuid.uuid4().hex[:10], "state": "running", "progress": None,
               "file": p.name, "error": None, "cancel": False, "started": time.time()}
        jobs[job["id"]] = job

        def on_progress(pr):
            job["progress"] = pr
            if job["cancel"]:
                raise Cancelled()

        def run():
            try:
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
                buildfile.write(p, buildfile.refresh(doc, gd))
                job["state"] = "done"
            except Cancelled:
                job["state"] = "cancelled"
            except Exception as e:   # surface anything else to the page
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
                yield "data: " + json.dumps({k: j[k] for k in ("state", "progress", "file",
                                                               "error")}) + "\n\n"
                if j["state"] != "running":
                    return
                await asyncio.sleep(0.25)
        return StreamingResponse(stream(), media_type="text/event-stream")

    # ------------------------------------------------------------ terminal
    @app.get("/api/terminal/clis")
    def clis():
        return available_clis()

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
                elif msg["type"] == "run":
                    allowed = {c["cmd"] for c in available_clis()}
                    if msg["cmd"] in allowed:
                        await term.run(msg["cmd"])
                elif msg["type"] == "restart":
                    term.close()
                    term.ensure()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            pump_task.cancel()
            term.detach(queue)

    return app


def serve(builds_dir="builds", port=8765, open_browser=True):
    import webbrowser

    import uvicorn
    app = create_app(builds_dir, port)
    url = f"http://127.0.0.1:{port}/?token={app.state.token}"
    print(f"Wynn Toolbox is running at:\n  {url}\n(only this computer can connect; "
          f"the token in the link is the password for this session)", flush=True)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
