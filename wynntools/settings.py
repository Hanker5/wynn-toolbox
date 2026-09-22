"""App settings that stick between runs, stored as builds/settings.json.

    {"ai": "claude", "check_updates": true, "ignored_update": null, "window": null}

"ai" is the AI assistant the web app starts in its terminal panel on open:
a key of `web.terminal.AI_CLIS`, "shell" for a plain terminal, or null when
the player has not chosen yet (the app then shows its setup wizard).
"check_updates": whether the app looks for a newer version on GitHub at start.
"ignored_update": the commit the player chose to ignore; the app asks again
only when a newer one appears.
"window": the app window's last size and position
({"width", "height", "x", "y", "maximized"}).
"""
import json
import re
from pathlib import Path

DEFAULT = Path("builds/settings.json")
DEFAULTS = {"ai": None, "check_updates": True, "ignored_update": None, "window": None}
SHELL = "shell"
WINDOW_KEYS = {"width", "height", "x", "y", "maximized"}


def ai_choices():
    from .web.terminal import AI_CLIS
    return [c["key"] for c in AI_CLIS] + [SHELL]


def load(path=DEFAULT):
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = dict(DEFAULTS)
    for k, v in data.items():
        if k in DEFAULTS and _problem(k, v) is None:
            out[k] = v
    return out


def _problem(key, value):
    """Why `value` isn't valid for `key`, or None if it is."""
    if key == "ai":
        if value is not None and value not in ai_choices():
            return f"ai must be one of: {', '.join(ai_choices())}"
    elif key == "check_updates":
        if not isinstance(value, bool):
            return "check_updates must be true or false"
    elif key == "ignored_update":
        if value is not None and not (isinstance(value, str)
                                      and re.fullmatch(r"[0-9a-f]{7,40}", value)):
            return "ignored_update must be a commit id"
    elif key == "window":
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) - WINDOW_KEYS:
            return f"window must be an object with: {', '.join(sorted(WINDOW_KEYS))}"
        for k, v in value.items():
            ok = isinstance(v, bool) if k == "maximized" else (
                v is None or (isinstance(v, int) and not isinstance(v, bool)))
            if not ok:
                return f"window.{k} has the wrong type"
    return None


def save(data, path=DEFAULT):
    """Validate and write; returns the saved settings. Raises ValueError."""
    path = Path(path)
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
    for k, v in data.items():
        if (problem := _problem(k, v)):
            raise ValueError(problem)
    out = {**load(path), **data}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    return out
