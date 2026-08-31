from __future__ import annotations

from datetime import date

import pandas as pd

from qmt_local_data.reference import (
    build_current_stock_snapshot,
    build_index_membership_snapshot,
    build_sector_membership_snapshot,
)


def test_current_stock_snapshot_combines_official_and_qmt() -> None:
    official = pd.DataFrame(
        {
            "stock_code": ["600000.SH"],
            "stock_name": ["浦发银行"],
            "exchange": ["SH"],
            "list_date": [date(1999, 11, 10)],
            "delist_date": [None],
            "listing_status": ["CURRENT"],
            "as_of_date": [date(2026, 8, 30)],
            "source": ["SSE_OFFICIAL"],
        }
    )
    result = build_current_stock_snapshot(
        ["600000.SH", "920001.BJ"], official, date(2026, 8, 30)
    )
    assert result["stock_code"].tolist() == ["600000.SH", "920001.BJ"]
    assert result.set_index("stock_code").loc["600000.SH", "list_date"] == date(1999, 11, 10)
    assert result.set_index("stock_code").loc["920001.BJ", "source"] == "QMT_CURRENT_SECTOR"


def test_membership_snapshots_are_exact_date_observations() -> None:
    as_of = date(2026, 8, 30)
    indexes = build_index_membership_snapshot(
        {"000300.SH": {"600000.SH": 1.25}}, {"000300.SH": "沪深300"}, as_of
    )
    sectors = build_sector_membership_snapshot(
        {"SW1银行": ["600000.SH"], "SW1银行加权": ["600000.SH"]}, as_of
    )
    assert indexes.iloc[0]["snapshot_date"] == as_of
    assert indexes.iloc[0]["membership_quality"] == "OBSERVED_SNAPSHOT_ONLY"
    assert sectors["sector_type"].tolist() == ["SW1", "SW1"]
    assert sectors.iloc[0]["sector_name"] == "银行"
