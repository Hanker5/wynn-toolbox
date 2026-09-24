"""Candidates: builds a search made for another build, to compare and pick from.

A candidate is an ordinary build file with `"parent": "<parent file name>"`,
saved next to it as `<parent>--<name>.json` (`wt gear --parent`, `wt gear --edit
--candidate`, `wt tradeoffs --parent`, or the web app's solver). Choosing one
copies its gear, tree, powders, aspects and skill points into the parent
(which keeps its name, notes and locks) and moves the candidate to the trash;
the others can then go to the trash in one step. Trash is builds/.trash, so
nothing is erased.
"""
import os
import time
from pathlib import Path

from . import buildfile

TRASH_DIR = ".trash"
TAKEN = ("level", "equipment", "tomes", "tree", "powders", "aspects", "skillpoints",
         "spec", "tree_preset")


def to_trash(path):
    """Move a build into builds/.trash with a time stamp. Returns the trash file's name."""
    path = Path(path)
    trash = path.parent / TRASH_DIR
    trash.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest, n = trash / f"{path.stem}-{stamp}.json", 1
    while dest.exists():
        n += 1
        dest = trash / f"{path.stem}-{stamp}-{n}.json"
    os.replace(path, dest)
    return dest.name


def candidates(parent):
    """Candidate files of a build, oldest first."""
    parent = Path(parent)
    out = []
    for p in sorted(parent.parent.glob("*.json")):
        if p == parent:
            continue
        try:
            doc = buildfile.read(p)
        except (ValueError, OSError):
            continue
        if isinstance(doc, dict) and doc.get("parent") == parent.name:
            out.append(p)
    return sorted(out, key=lambda p: p.stat().st_mtime_ns)


def choose(parent, candidate, gd, inventory=None):
    """Put the candidate's build into the parent file and trash the candidate.
    Returns (new parent doc, trash name of the candidate)."""
    parent, candidate = Path(parent), Path(candidate)
    pdoc, cdoc = buildfile.read(parent), buildfile.read(candidate)
    if cdoc.get("parent") != parent.name:
        raise ValueError(f"{candidate.name} isn't a candidate of {parent.name}")
    doc = {k: v for k, v in pdoc.items() if k not in buildfile.GENERATED and k not in TAKEN}
    doc.update({k: cdoc[k] for k in TAKEN if k in cdoc})
    doc = buildfile.refresh(doc, gd, inventory)
    buildfile.write(parent, doc)
    return doc, to_trash(candidate)


def trash_candidates(parent, keep=()):
    """Trash every candidate of `parent` but those named in `keep`.
    Returns [(file name, trash name)] for undo."""
    keep = {Path(k).name for k in keep}
    return [(p.name, to_trash(p)) for p in candidates(parent) if p.name not in keep]
