from __future__ import annotations

import json
import time

import pandas as pd
import pytest

from qmt_local_data.errors import LockError
from qmt_local_data.lock import ProjectLock
from qmt_local_data.manifest import ManifestStore


def test_manifest_append_is_immutable_and_active_is_atomic(data_config) -> None:
    store = ManifestStore(data_config.data_root)
    first = pd.DataFrame({"trade_date": [pd.Timestamp("2026-01-02").date()], "stock_code": ["000001.SZ"], "close": [10.0]})
    second = pd.DataFrame({"trade_date": [pd.Timestamp("2026-01-02").date()], "stock_code": ["000001.SZ"], "close": [11.0]})
    m1 = store.publish_frame("processed", "stock_daily", first, "1.0", date_column="trade_date")
    m2 = store.publish_frame("processed", "stock_daily", second, "1.0", date_column="trade_date")
    assert m1.run_id != m2.run_id
    assert len(m2.files) == 2
    assert not store.verify_active("processed", "stock_daily")
    active = store.read_active_frame("processed", "stock_daily", ["trade_date", "stock_code"])
    assert active.iloc[0]["close"] == 11.0
    assert all((data_config.data_root / record.relative_path).exists() for record in m2.files)
    assert all((data_config.data_root / record.relative_path).parent.joinpath("SUCCESS").exists() for record in m2.files)


def test_replace_manifest_drops_prior_components(data_config) -> None:
    store = ManifestStore(data_config.data_root)
    frame = pd.DataFrame({"id": [1], "value": ["a"]})
    store.publish_frame("derived", "sample", frame, "1.0")
    current = store.publish_frame("derived", "sample", frame.assign(value="b"), "1.0", mode="replace")
    assert len(current.files) == 1


def test_manifest_range_read_and_latest_valid_anchor(data_config) -> None:
    store = ManifestStore(data_config.data_root)
    frame = pd.DataFrame(
        {
            "trade_date": [
                pd.Timestamp("2026-01-02").date(),
                pd.Timestamp("2026-01-03").date(),
                pd.Timestamp("2026-01-04").date(),
            ],
            "stock_code": ["A", "A", "A"],
            "close": [10.0, 10.0, 11.0],
            "suspend_flag": [0, 1, 0],
            "volume": [100, 0, 100],
        }
    )
    store.publish_frame("processed", "stock_daily", frame, "1.0", date_column="trade_date")
    ranged = store.read_active_frame(
        "processed",
        "stock_daily",
        ["trade_date", "stock_code"],
        columns=["trade_date", "stock_code", "close"],
        date_column="trade_date",
        start=pd.Timestamp("2026-01-03").date(),
        end=pd.Timestamp("2026-01-04").date(),
    )
    assert ranged["trade_date"].tolist() == [
        pd.Timestamp("2026-01-03").date(),
        pd.Timestamp("2026-01-04").date(),
    ]
    anchor = store.read_active_latest_before(
        "processed",
        "stock_daily",
        business_key=["trade_date", "stock_code"],
        partition_by=["stock_code"],
        date_column="trade_date",
        before=pd.Timestamp("2026-01-04").date(),
        columns=["trade_date", "stock_code", "close", "suspend_flag", "volume"],
        predicate="suspend_flag = 0 AND volume > 0 AND close > 0",
    )
    assert anchor.iloc[0]["close"] == 10.0
    assert pd.Timestamp(anchor.iloc[0]["trade_date"]).date() == pd.Timestamp("2026-01-02").date()


def test_database_status_marks_current_universe_as_not_accepted(data_config) -> None:
    from qmt_local_data.pipeline import DatabaseBuilder

    builder = DatabaseBuilder(data_config, object(), universe_scope="CURRENT_UNIVERSE_ONLY")
    path = builder.write_database_status("READY_CURRENT_UNIVERSE_ONLY", phase0_gate_passed=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["universe_scope"] == "CURRENT_UNIVERSE_ONLY"
    assert payload["accepted_for_unbiased_backtest"] is False


def test_project_lock_refuses_active_and_requires_explicit_stale_break(data_config) -> None:
    first = ProjectLock(data_config.data_root, stale_after_seconds=1)
    first.acquire()
    with pytest.raises(LockError):
        ProjectLock(data_config.data_root, stale_after_seconds=1).acquire()
    payload = json.loads(first.path.read_text(encoding="utf-8"))
    payload["created_epoch"] = time.time() - 60
    first.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(LockError):
        ProjectLock(data_config.data_root, stale_after_seconds=1).acquire()
    replacement = ProjectLock(data_config.data_root, stale_after_seconds=1)
    replacement.acquire(break_stale=True)
    replacement.release()
