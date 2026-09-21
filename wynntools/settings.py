"""App settings that stick between runs, stored as builds/settings.json.

    {"ai": "claude"}

"ai" is the AI assistant the web app starts in its terminal panel on open:
a key of `web.terminal.AI_CLIS`, "shell" for a plain terminal, or null when
the player has not chosen yet (the app then shows its setup wizard).
"""
import json
from pathlib import Path

DEFAULT = Path("builds/settings.json")
DEFAULTS = {"ai": None}
SHELL = "shell"


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
    out = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    if out["ai"] not in ai_choices():
        out["ai"] = None
    return out


def save(data, path=DEFAULT):
    """Validate and write; returns the saved settings. Raises ValueError."""
    path = Path(path)
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
    if "ai" in data and data["ai"] is not None and data["ai"] not in ai_choices():
        raise ValueError(f"ai must be one of: {', '.join(ai_choices())}")
    out = {**load(path), **data}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    return out
