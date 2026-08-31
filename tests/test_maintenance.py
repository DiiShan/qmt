from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import yaml

from qmt_local_data.maintenance import (
    DAILY_MAINTAINED_DATASETS,
    FULL_REBUILD_DATASETS,
    MANUAL_DATASETS,
    build_maintenance_plan,
)


def test_every_declared_dataset_is_classified_for_one_click_maintenance() -> None:
    declared = set(yaml.safe_load(Path("config/datasets.yaml").read_text(encoding="utf-8"))["datasets"])
    classified = DAILY_MAINTAINED_DATASETS | FULL_REBUILD_DATASETS | MANUAL_DATASETS

    assert declared == classified


def test_maintenance_plan_rewinds_configured_open_day_lookback(data_config) -> None:
    database = data_config.data_root / "database" / "qmt.duckdb"
    database.parent.mkdir(parents=True)
    days = [date(2026, 8, 3) + timedelta(days=index) for index in range(20)]
    open_days = [day for day in days if day.weekday() < 5]
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE trade_calendar(market VARCHAR, trade_date DATE, is_open BOOLEAN)")
        connection.executemany(
            "INSERT INTO trade_calendar VALUES ('SH', ?, TRUE)", [(day,) for day in open_days]
        )
        connection.execute("CREATE TABLE daily_bar(trade_date DATE)")
        connection.execute("INSERT INTO daily_bar VALUES (?)", [open_days[-1]])
        connection.execute("CREATE TABLE index_daily(index_code VARCHAR, trade_date DATE)")
        connection.executemany(
            "INSERT INTO index_daily VALUES (?, ?)",
            [(code, open_days[-2]) for code in data_config.markets.indexes],
        )

    plan = build_maintenance_plan(data_config, open_days[-1], full=False)

    assert plan.stock_start == open_days[-11]
    assert plan.index_start == open_days[-12]
    assert plan.calendar_start == open_days[-12]
    assert plan.revision_lookback_trade_days == 10
