import json
from pathlib import Path

import pytest

from wynntools.data import GameData

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def gd():
    return GameData()


@pytest.fixture(scope="session")
def links():
    return {k: v for k, v in json.loads((FIXTURES / "links.json").read_text()).items()
            if not k.startswith("_")}
