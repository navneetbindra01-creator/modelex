import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modelex import Exchange  # noqa: E402


@pytest.fixture
def root():
    return ROOT


@pytest.fixture
def make_ex():
    def _make(asset_classes=None, auto=False):
        return Exchange.from_project(ROOT, asset_classes=asset_classes, auto_schedule=auto)
    return _make


@pytest.fixture
def eq(make_ex):
    """Equity exchange in CONTINUOUS."""
    from modelex import SetPhase
    ex = make_ex(["EQUITY"])
    ex.process(SetPhase("EQUITY_STD", "PRE_OPEN"))
    ex.process(SetPhase("EQUITY_STD", "CONTINUOUS"))
    return ex


def rejects(events):
    return [getattr(e, "reject_reason", None) and e.reject_reason.value for e in events
            if getattr(e, "reject_reason", None) is not None]


def trades(events):
    from modelex.types import fmt
    return [(fmt(e.price), fmt(e.qty)) for e in events if e.TYPE == "Trade"]
