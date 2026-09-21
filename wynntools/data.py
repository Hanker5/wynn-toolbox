"""Fetch and cache WynnBuilder's public data, keyed by game version."""
import json
import os
import urllib.request
from functools import cache
from pathlib import Path

BASE_URL = "https://wynnbuilder.github.io"
CACHE_DIR = Path(os.environ.get("WYNN_TOOLBOX_CACHE",
                                Path(__file__).resolve().parent.parent / "data"))

# Mirrors `wynn_version_names` in WynnBuilder's js/load_item.js. A build link stores
# the index into this list in its 10-bit version field.
VERSIONS = [
    "2.0.1.1", "2.0.1.2", "2.0.2.1", "2.0.2.3", "2.0.3.1", "2.0.4.1", "2.0.4.3",
    "2.0.4.4", "2.1.0.0", "2.1.0.1", "2.1.1.0", "2.1.1.1", "2.1.1.2", "2.1.1.3",
    "2.1.1.4", "2.1.1.5", "2.1.1.6", "2.1.1.7", "2.1.2.0", "2.1.3.0", "2.1.3.4",
    "2.1.4.0", "2.1.5.0", "2.1.6.0", "2.2.0.0", "2.2.0.7", "2.2.0.12", "2.2.0.14",
    "2.2.0.19", "2.2.0.21", "2.2.0.31", "2.2.1.0", "2.2.2.0", "2.2.3.0", "2.2.4.0",
]
LATEST = len(VERSIONS) - 1

# Per-version files live under data/<version>/. Items and tomes for the latest
# version come from WynnBuilder's "baseline" bundle instead.
_VERSIONED = {"encoding": "encoding_consts.json", "atree": "atree.json",
              "majid": "majid.json", "aspects": "aspects.json"}
_BASELINE = {"items": "data/baseline/compressed/compress.json",
             "tomes": "data/baseline/tomes.json"}

WEAPON_CLASS = {"wand": "Mage", "bow": "Archer", "dagger": "Assassin",
                "spear": "Warrior", "relik": "Shaman"}


def _url(kind, version):
    if kind in _BASELINE:
        if version != LATEST:
            raise NotImplementedError(
                f"{kind} data is only supported for the latest version ({VERSIONS[LATEST]}); "
                f"this link is for {VERSIONS[version]}.")
        return f"{BASE_URL}/{_BASELINE[kind]}"
    return f"{BASE_URL}/data/{VERSIONS[version]}/{_VERSIONED[kind]}"


def fetch(version=LATEST, refresh=False):
    """Download every data file for `version` into the cache. Returns the cache dir."""
    out = CACHE_DIR / VERSIONS[version]
    out.mkdir(parents=True, exist_ok=True)
    for kind in [*_BASELINE, *_VERSIONED]:
        dest = out / f"{kind}.json"
        if dest.exists() and not refresh:
            continue
        with urllib.request.urlopen(_url(kind, version), timeout=120) as r:
            dest.write_bytes(r.read())
    load.cache_clear()
    return out


@cache
def load(kind, version=LATEST):
    path = CACHE_DIR / VERSIONS[version] / f"{kind}.json"
    if not path.exists():
        fetch(version)
    return json.loads(path.read_text())


class GameData:
    """Lookup tables for one game version."""

    def __init__(self, version=LATEST):
        self.version = version
        self.enc = load("encoding", version)
        self.items = [i for i in load("items", version)["items"] if "id" in i]
        self.item_by_name = {self.name(i): i for i in self.items}
        self.item_by_id = {i["id"]: i for i in self.items}
        self.tomes = load("tomes", version)["tomes"]
        self.tome_by_id = {t["id"]: t for t in self.tomes}
        # Plain names are unique; the ֎-marked duplicates are cosmetic variants.
        self.tome_by_name = {self.name(t): t for t in self.tomes if "֎" not in self.name(t)}
        self.atrees = load("atree", version)
        self.majids = load("majid", version)

    @staticmethod
    def name(obj):
        return obj.get("displayName") or obj["name"]

    def item(self, name):
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
