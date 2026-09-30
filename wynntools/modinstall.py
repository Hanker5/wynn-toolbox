"""Install the chest-export mod into a Minecraft folder, set up to find this app.

    install(minecraft_dir, builds_dir) -> {"jar", "removed", "config", "builds_path", "warnings"}

Copies the mod's jar (committed in wynn-chest-export/build/libs/) into the folder's
`mods/`, taking out older copies of it, and sets `builds_path` in
`config/wynngpt-chest-export.json` to this app's builds folder (other settings in that
file stay). The folder can be the Minecraft folder itself (the one with `mods/`,
`config/`, `saves/`, `options.txt`) or its `mods/` folder.

`candidates()` looks for Minecraft folders where the usual launchers keep them
(the vanilla launcher, Prism and MultiMC instances, the Modrinth App, CurseForge),
Flatpak installs included, to offer them instead of a typed path.
"""
import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JARS = ROOT / "wynn-chest-export" / "build" / "libs"
MOD_ID = "wynngpt-chest-export"
CONFIG = f"{MOD_ID}.json"
_JAR = re.compile(rf"^{MOD_ID}-(\d+(?:\.\d+)*)\.jar$")
_MARKERS = ("mods", "config", "saves", "options.txt", "resourcepacks")


class InstallError(ValueError):
    """Something the player can fix (a wrong folder, no permission, ...)."""


def _version(path):
    m = _JAR.match(path.name)
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def bundled_jar(jars=JARS):
    """The newest mod jar the app ships (not the -sources jar)."""
    found = [p for p in Path(jars).glob(f"{MOD_ID}-*.jar") if _version(p)]
    if not found:
        raise InstallError(f"the mod's jar isn't in {jars}; build it with ./gradlew build in wynn-chest-export")
    return max(found, key=_version)


def minecraft_folder(path):
    """The Minecraft folder for what the player typed: the folder itself, or its mods folder."""
    raw = str(path or "").strip().strip('"').strip("'")
    if not raw:
        raise InstallError("type the path of your Minecraft folder")
    folder = Path(os.path.expandvars(os.path.expanduser(raw)))
    if folder.name == "mods" and folder.is_dir():
        folder = folder.parent
    if not folder.is_dir():
        raise InstallError(f"there's no folder {folder}")
    if not any((folder / m).exists() for m in _MARKERS):
        raise InstallError(f"{folder} doesn't look like a Minecraft folder (no mods, config, saves or "
                           f"options.txt); pick the one your launcher uses for the Wynncraft instance")
    return folder.resolve()


def install(minecraft_dir, builds_dir, jars=JARS):
    folder = minecraft_folder(minecraft_dir)
    jar = bundled_jar(jars)
    builds = Path(builds_dir).resolve()
    mods, config_dir = folder / "mods", folder / "config"
    warnings, removed = [], []
    try:
        mods.mkdir(exist_ok=True)
        for old in mods.glob(f"{MOD_ID}-*.jar"):
            if old.name != jar.name:
                old.unlink()
                removed.append(old.name)
        shutil.copyfile(jar, mods / jar.name)
        config_dir.mkdir(exist_ok=True)
        config = config_dir / CONFIG
        try:
            settings = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
        except ValueError:
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        settings["builds_path"] = str(builds)
        config.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    except PermissionError as e:
        raise InstallError(f"no permission to write in {folder}: {e.filename or e}") from e
    except OSError as e:
        raise InstallError(f"couldn't write in {folder}: {e}") from e
    if not any(mods.glob("fabric-api*.jar")):
        warnings.append("Fabric API isn't in this mods folder: the mod needs it (and Fabric Loader), "
                        "from modrinth.com/mod/fabric-api for Minecraft 1.21.11")
    if "/.var/app/" in folder.as_posix():
        app = folder.as_posix().split("/.var/app/", 1)[1].split("/", 1)[0]
        warnings.append(f"This launcher is a Flatpak: it can't see the app's builds folder until you allow it. "
                        f"Run: flatpak override --user --filesystem={builds}:ro {app} (then restart the launcher)")
    return {"jar": str(mods / jar.name), "removed": removed, "config": str(config_dir / CONFIG),
            "builds_path": str(builds), "warnings": warnings}


def status(minecraft_dir, builds_dir, jars=JARS):
    """Is the bundled mod installed in `minecraft_dir`, and set up for this app?"""
    jar = bundled_jar(jars)
    try:
        folder = minecraft_folder(minecraft_dir)
    except InstallError as e:
        return {"folder": str(minecraft_dir or ""), "problem": str(e)}
    installed = sorted(p.name for p in (folder / "mods").glob(f"{MOD_ID}-*.jar")) if (folder / "mods").is_dir() else []
    try:
        path = json.loads((folder / "config" / CONFIG).read_text(encoding="utf-8")).get("builds_path")
    except (OSError, ValueError, AttributeError):
        path = None
    return {"folder": str(folder), "installed": installed, "current": jar.name in installed,
            "configured": bool(path) and Path(path).resolve() == Path(builds_dir).resolve()}


def candidates(home=None):
    """Minecraft folders the usual launchers keep, newest first: [{"path", "launcher", "fabric_api", "installed"}]."""
    home = Path(home or Path.home())
    appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    mac = home / "Library" / "Application Support"
    flat = home / ".var" / "app"
    roots = [
        ("Minecraft launcher", [home / ".minecraft", appdata / ".minecraft", mac / "minecraft"]),
        ("Prism Launcher", _instances([home / ".local/share/PrismLauncher", appdata / "PrismLauncher", mac / "PrismLauncher",
                                       flat / "org.prismlauncher.PrismLauncher/data/PrismLauncher"])),
        ("MultiMC", _instances([home / ".local/share/multimc", appdata / "MultiMC", home / "MultiMC"])),
        ("Modrinth App", [p for base in (home / ".local/share/ModrinthApp", appdata / "ModrinthApp", mac / "ModrinthApp",
                                         flat / "com.modrinth.ModrinthApp/data/ModrinthApp")
                          for p in _children(base / "profiles")]),
        ("CurseForge", [p for base in (home / "curseforge/minecraft/Instances",
                                       home / "Documents/curseforge/minecraft/Instances")
                        for p in _children(base)]),
    ]
    out, seen = [], set()
    for launcher, paths in roots:
        for p in paths:
            try:
                if not p.is_dir() or not any((p / m).exists() for m in _MARKERS) or p.resolve() in seen:
                    continue
                seen.add(p.resolve())
                mods = p / "mods"
                out.append({"path": str(p), "launcher": launcher,
                            "fabric_api": mods.is_dir() and any(mods.glob("fabric-api*.jar")),
                            "installed": mods.is_dir() and any(mods.glob(f"{MOD_ID}-*.jar")),
                            "_t": max((q.stat().st_mtime for q in (p, mods) if q.exists()), default=0)})
            except OSError:
                continue
    out.sort(key=lambda c: (not c["installed"], not c["fabric_api"], -c["_t"]))
    for c in out:
        del c["_t"]
    return out


def _children(base):
    try:
        return sorted(p for p in Path(base).iterdir() if p.is_dir())
    except OSError:
        return []


def _instances(bases):
    """Prism/MultiMC instances keep the game in <instance>/.minecraft (or /minecraft)."""
    return [q for base in bases for inst in _children(Path(base) / "instances")
            for q in (inst / ".minecraft", inst / "minecraft")]

