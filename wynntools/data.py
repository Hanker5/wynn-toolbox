"""Fetch and cache WynnBuilder's public data, keyed by game version."""
import json
import os
import re
import time
import urllib.request
from functools import cache
from pathlib import Path

BASE_URL = "https://wynnbuilder.github.io"
CACHE_DIR = Path(os.environ.get("WYNN_TOOLBOX_CACHE")          # empty counts as unset
                 or Path(__file__).resolve().parent.parent / "data")

# A copy of `wynn_version_names` in WynnBuilder's js/load_item.js. A build link
# stores the index into this list in its 10-bit version field. WynnBuilder appends
# a name after each game patch; `refresh_versions` reads its current list
# (data/versions.json), so a patch needs no new release. This copy is the fallback
# before the first fetch or offline; the scheduled CI run flags it when it falls behind.
BUILTIN_VERSIONS = [
    "2.0.1.1", "2.0.1.2", "2.0.2.1", "2.0.2.3", "2.0.3.1", "2.0.4.1", "2.0.4.3",
    "2.0.4.4", "2.1.0.0", "2.1.0.1", "2.1.1.0", "2.1.1.1", "2.1.1.2", "2.1.1.3",
    "2.1.1.4", "2.1.1.5", "2.1.1.6", "2.1.1.7", "2.1.2.0", "2.1.3.0", "2.1.3.4",
    "2.1.4.0", "2.1.5.0", "2.1.6.0", "2.2.0.0", "2.2.0.7", "2.2.0.12", "2.2.0.14",
    "2.2.0.19", "2.2.0.21", "2.2.0.31", "2.2.1.0", "2.2.2.0", "2.2.3.0", "2.2.4.0",
]
VERSIONS = list(BUILTIN_VERSIONS)   # only ever grows, in place: indices never change
VERSIONS_URL = "https://wynnbuilder.github.io/js/load_item.js"
CHECK_EVERY = 12 * 3600             # seconds between routine checks for a new version
RETRY_AFTER = 3600                  # ... and after a failed one (offline)


class UnknownVersion(NotImplementedError):
    """A link names a version newer than any the toolbox knows, and WynnBuilder's
    current list couldn't be read."""

# Per-version files live under data/<version>/. Items, tomes and ingredients for
# the latest version come from WynnBuilder's "baseline" bundle instead; for an
# older one (a link made before a patch) from that version's own folder, as
# WynnBuilder's `load_old_version` reads them.
_VERSIONED = {"encoding": "encoding_consts.json", "atree": "atree.json",
              "majid": "majid.json", "aspects": "aspects.json"}
_OLD = {"items": "items.json", "tomes": "tomes.json", "ingreds": "ingreds.json",
        "recipes": "recipes.json"}
_BASELINE = {"items": "data/baseline/compressed/compress.json",
             "tomes": "data/baseline/tomes.json",
             "ingreds": "data/baseline/compressed/ingreds_compress.json",
             "recipes": "data/baseline/compressed/recipes_compress.json"}

# Images used by the web app, fetched from WynnBuilder at run time (not stored in
# this repo; some are derived from Wynncraft's own art). Credit: WynnBuilder.
MEDIA = {"items.png": "media/items/new.png",          # 12 item-type icons, 120px each
         "atree-icons.png": "media/atree/icons.png",  # 10 node types x 3 states, 32px
         "atree-connectors.png": "media/atree/connectors.png"}  # 12 x 4 connector tiles, 18px

WEAPON_CLASS = {"wand": "Mage", "bow": "Archer", "dagger": "Assassin",
                "spear": "Warrior", "relik": "Shaman"}


def latest():
    """Index of the newest version known (a function: the list can grow while
    the app runs)."""
    return len(VERSIONS) - 1


def _versions_file():
    return CACHE_DIR / "versions.json"


def _download(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def parse_versions(js):
    """The names in `wynn_version_names = [...]` in WynnBuilder's load_item.js."""
    m = re.search(r"wynn_version_names\s*=\s*\[(.*?)\]", js, re.S)
    names = re.findall(r"""['"]([^'"]+)['"]""", m.group(1)) if m else []
    if not names:
        raise ValueError("no wynn_version_names list in WynnBuilder's load_item.js")
    return names


def _adopt(names):
    """Take a longer list that keeps every known index; ignore anything else.
    Returns the names added."""
    if len(names) <= len(VERSIONS) or names[:len(VERSIONS)] != VERSIONS:
        return []
    added = names[len(VERSIONS):]
    VERSIONS.extend(added)
    return added


def _saved_versions():
    try:
        return json.loads(_versions_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_versions(ok):
    saved = _saved_versions()
    saved.update({"versions": VERSIONS, "checked": time.time(), "ok": ok})
    try:
        _versions_file().parent.mkdir(parents=True, exist_ok=True)
        _versions_file().write_text(json.dumps(saved, indent=1), encoding="utf-8")
    except OSError:
        pass


def load_saved_versions():
    """Adopt the list the last check saved (data/versions.json)."""
    return _adopt(_saved_versions().get("versions") or [])


def refresh_versions(timeout=10):
    """Read WynnBuilder's current version list. Returns the names added.
    Raises OSError (network) or ValueError (page changed) on failure."""
    try:
        names = parse_versions(_download(VERSIONS_URL, timeout).decode("utf-8"))
    except (OSError, ValueError):
        _save_versions(ok=False)
        raise
    added = _adopt(names)
    _save_versions(ok=True)
    return added


def _offline():
    return bool(os.environ.get("WYNN_TOOLBOX_OFFLINE"))


def check_versions(timeout=3):
    """A routine check for a new game version: at most every CHECK_EVERY seconds
    (RETRY_AFTER after a failure), never raises. Returns the names added."""
    if _offline():
        return []
    saved = _saved_versions()
    wait = CHECK_EVERY if saved.get("ok") else RETRY_AFTER
    if time.time() - saved.get("checked", 0) < wait:
        return []
    try:
        return refresh_versions(timeout)
    except (OSError, ValueError):
        return []


_asked = {}


def ensure_version(version):
    """True when `version` is known, checking WynnBuilder's list first if it
    isn't (a link made after a patch). Asks at most once a minute per version."""
    if version < len(VERSIONS):
        return True
    if _offline() or time.time() - _asked.get(version, 0) < 60:
        return False
    _asked[version] = time.time()
    try:
        refresh_versions()
    except (OSError, ValueError):
        return False
    return version < len(VERSIONS)


def _url(kind, version):
    if kind in _BASELINE and version == latest():
        return f"{BASE_URL}/{_BASELINE[kind]}"
    return f"{BASE_URL}/data/{VERSIONS[version]}/{(_OLD | _VERSIONED)[kind]}"


def fetch(version=None, refresh=False, progress=None):
    """Download every data file for `version` (default: the latest) into the
    cache. Returns the cache dir. `progress` is called with (done, total, name)
    after each file."""
    version = latest() if version is None else version
    out = CACHE_DIR / VERSIONS[version]
    out.mkdir(parents=True, exist_ok=True)
    media = CACHE_DIR / "media"
    media.mkdir(parents=True, exist_ok=True)
    todo = [(out / f"{kind}.json", _url(kind, version), 120, False)
            for kind in [*_BASELINE, *_VERSIONED]] + \
           [(media / name, f"{BASE_URL}/{rel}", 60, True) for name, rel in MEDIA.items()]
    todo = [t for t in todo if refresh or not t[0].exists()]
    for done, (dest, url, timeout, optional) in enumerate(todo, 1):
        try:
            dest.write_bytes(_download(url, timeout))
        except OSError:
            if not optional:      # icons are optional; the app falls back to plain slots
                raise
        if progress:
            progress(done, len(todo), dest.name)
    _load.cache_clear()
    return out


def load(kind, version=None):
    return _load(kind, latest() if version is None else version)


@cache
def _load(kind, version):
    path = CACHE_DIR / VERSIONS[version] / f"{kind}.json"
    if not path.exists():
        fetch(version)
    return json.loads(path.read_text(encoding="utf-8"))


load.cache_clear = _load.cache_clear


def _with_redirects(entries):
    by_id = {e["id"]: e for e in entries if "remapID" not in e}
    for e in entries:
        if "remapID" in e and e["remapID"] in by_id:
            by_id[e["id"]] = by_id[e["remapID"]]
    return by_id


class GameData:
    """Lookup tables for one game version."""

    def __init__(self, version=None):
        version = latest() if version is None else version
        self.version = version
        self.enc = load("encoding", version)
        # Entries with a remapID are redirects from a retired id to the current
        # item (WynnBuilder's redirectMap); their own stats are stale. Old ids
        # resolve to the current item, and names only ever mean current items.
        raw = [i for i in load("items", version)["items"] if "id" in i]
        self.items = [i for i in raw if "remapID" not in i]
        self.item_by_name = {self.name(i): i for i in self.items}
        self.item_by_id = _with_redirects(raw)
        raw_tomes = load("tomes", version)["tomes"]
        self.tomes = [t for t in raw_tomes if "remapID" not in t]
        self.tome_by_id = _with_redirects(raw_tomes)
        # Plain names are unique; the ֎-marked duplicates are cosmetic variants.
        self.tome_by_name = {self.name(t): t for t in self.tomes if "֎" not in self.name(t)}
        self.atrees = load("atree", version)
        # Items don't name their set; WynnBuilder builds this map from the set list.
        self.sets = load("items", version).get("sets") or {}
        self.set_of = {item: name for name, st in self.sets.items() for item in st["items"]}
        self.majids = load("majid", version)

    def for_version(self, version):
        """This data, or another version's when a decoded link needs it (a link
        from a patch the toolbox learned of while this command ran)."""
        return self if self.version == version else GameData(version)

    @staticmethod
    def name(obj):
        return obj.get("displayName") or obj["name"]

    @property
    def crafts(self):
        """Ingredient and recipe tables, loaded on first use."""
        if not hasattr(self, "_crafts"):
            from .crafting import CraftData
            self._crafts = CraftData(self.version)
            self._craft_cache = {}
        return self._crafts

    def item(self, name):
        """A normal item by name, or a crafted item by its "CR-" hash."""
        if name.startswith("CR-"):
            cd = self.crafts
            if name not in self._craft_cache:
                from .crafting import craft_item, decode_craft_hash
                self._craft_cache[name] = craft_item(decode_craft_hash(name, cd), cd)
            return self._craft_cache[name]
        try:
            return self.item_by_name[name]
        except KeyError:
            raise KeyError(f"unknown item {name!r}") from None

    def tome(self, key):
        if isinstance(key, int):
            return self.tome_by_id[key]
        try:
            return self.tome_by_name[key]
        except KeyError:
            raise KeyError(f"unknown tome {key!r}") from None

    def weapon_class(self, weapon_name):
        return WEAPON_CLASS[self.item(weapon_name)["type"]]

    def tree(self, cls):
        return self.atrees[cls]

    def aspects(self, cls):
        if not hasattr(self, "_aspects"):
            self._aspects = load("aspects", self.version)
        return self._aspects.get(cls, [])


load_saved_versions()
