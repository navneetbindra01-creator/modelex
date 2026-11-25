from decimal import Decimal as D

import pytest

from modelex import MarketConfig, RefDataStore
from modelex.config import ConfigError
from modelex.refdata import RefDataError


def test_all_golden_source_files_load(root):
    store = RefDataStore.from_files(sorted((root / "refdata").glob("*.json")))
    assert set(store.asset_classes()) == {"EQUITY", "CRYPTO", "COMMODITY", "COLLECTIBLE"}
    assert store.get("GC-FEB27").multiplier == 100
    assert store.get("ART-PRINT-0001").unique
    assert store.get("BTC-USD").lot_size == D("0.0001")


def test_banded_tick_table(root):
    store = RefDataStore.from_files([root / "refdata" / "equities.json"])
    i = store.get("VOD.L")
    assert i.tick_for(D("0.5")) == D("0.001")
    assert i.tick_for(D("72.50")) == D("0.01")
    assert i.tick_for(D("11250")) == D("1")
    assert i.is_on_tick(D("268.45")) is False or i.tick_for(D("268.45")) == D("0.05")
    assert i.round_to_tick(D("72.556"), "down") == D("72.55")
    assert i.round_to_tick(D("9.9999"), "up") == D("10.00")


@pytest.mark.parametrize("bad,msg", [
    ({"symbol": "A", "tick_size": "0"}, "tick must be > 0"),
    ({"symbol": "A", "tick_size": "0.05", "reference_price": "10.02"}, "not on tick"),
    ({"symbol": "A", "tick_size": "0.01", "lot_size": "10", "min_qty": "5"}, "multiple of lot_size"),
    ({"symbol": "A", "tick_size": "0.01", "unique": True, "max_qty": "2"}, "unique items"),
    ({"symbol": "A", "tick_table": [{"from_price": "1", "tick": "0.1"}]}, "start at from_price 0"),
    ({"symbol": "A"}, "tick_size or tick_table required"),
    ({"tick_size": "0.01"}, "symbol is required"),
])
def test_refdata_rejects_bad_golden_source(bad, msg):
    with pytest.raises(RefDataError, match=msg):
        RefDataStore().load_dict({"asset_class": "EQUITY", "instruments": [bad]})


def test_refdata_duplicate_symbol():
    with pytest.raises(RefDataError, match="duplicate"):
        RefDataStore().load_dict({"asset_class": "EQUITY", "instruments": [
            {"symbol": "A", "tick_size": "0.01"}, {"symbol": "A", "tick_size": "0.01"}]})


def test_unknown_asset_class_schedule_is_config_error():
    with pytest.raises(ConfigError):
        MarketConfig.from_dict({"schedules": {}, "asset_classes": {"FX": {"schedule": "NOPE"}}})


def test_illegal_timeline_is_config_error():
    with pytest.raises(ConfigError, match="illegal timeline"):
        MarketConfig.from_dict({"schedules": {"S": {"initial_phase": "CLOSED",
                                                    "timeline": [{"time": "08:00", "phase": "POST_CLOSE"}]}}})
