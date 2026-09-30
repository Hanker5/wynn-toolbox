import json
import os
from pathlib import Path

import pytest

# No routine checks for a new game version during tests (subprocesses inherit it);
# tests that need one stub the download and clear this.
os.environ["WYNN_TOOLBOX_OFFLINE"] = "1"

from wynntools.data import GameData

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def gd():
    return GameData()


@pytest.fixture(scope="session")
def links():
    return {k: v for k, v in json.loads((FIXTURES / "links.json").read_text()).items()
            if not k.startswith("_")}
