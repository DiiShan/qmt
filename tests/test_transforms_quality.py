from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from qmt_local_data.errors import QualityGateError
from qmt_local_data.quality import (
    enforce_quality,
    validate_aggregate_volatility,
    validate_daily_bars,
    validate_security_master,
    validate_stock_volatility,
)
from qmt_local_data.transforms import (
    assign_financial_availability,
    build_historical_universe,
    normalize_market_data,
    normalize_instrument_details,
    normalize_trading_dates,
)


def test_normalize_stock_market_data_from_qmt_shape() -> None:
    raw = {
        "000001.SZ": pd.DataFrame(
            {
                "open": [10],
                "high": [12],
                "low": [9],
                "close": [11],
                "preClose": [9.5],
                "volume": [100],
                "amount": [1000],
                "suspendFlag": [0],
            },
            index=pd.Index([1787414400000], name="time"),
        )
    }
    frame = normalize_market_data(raw, "stock")
    assert frame.iloc[0]["trade_date"] == date(2026, 8, 23)
    assert frame.iloc[0]["stock_code"] == "000001.SZ"
    assert frame.iloc[0]["pre_close"] == 9.5


def test_normalize_future_accepts_xtquant_settlement_typo() -> None:
    raw = {
        "IF2608.IF": pd.DataFrame(
            {
                "time": [1787241600000],
                "open": [4000],
                "high": [4010],
                "low": [3990],
                "close": [4005],
                "volume": [10],
                "openInterest": [20],
                "settelementPrice": [4003],
            }
        )
    }
    frame = normalize_market_data(raw, "future")
    assert frame.iloc[0]["settlement"] == 4003


@pytest.mark.parametrize(
    "sentinel",
    ["10001011", "10001111", "10011011", "10011111", "10111111"],
)
def test_security_master_ignores_known_xtquant_expiry_sentinels(sentinel) -> None:
    frame = normalize_instrument_details(
        {
            "688001.SH": {
                "InstrumentName": "sample",
                "OpenDate": "20190722",
                "ExpireDate": sentinel,
            }
        }
    )
    assert frame.iloc[0]["list_date"] == date(2019, 7, 22)
    assert pd.isna(frame.iloc[0]["delist_date"])
    assert frame.iloc[0]["delist_date_quality"] == "INVALID_SENTINEL_IGNORED"


def test_security_master_keeps_unknown_reverse_interval_for_quality_error() -> None:
    frame = normalize_instrument_details(
        {
            "600000.SH": {
                "InstrumentName": "invalid sample",
                "OpenDate": "20200101",
                "ExpireDate": "20191231",
            }
        }
    )
    assert frame.iloc[0]["delist_date"] == date(2019, 12, 31)
    report = validate_security_master(frame)
    with pytest.raises(QualityGateError, match="listing_interval=1"):
        enforce_quality(report)


def test_quality_gate_blocks_duplicate_and_invalid_ohlc() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 1, 1)] * 2,
            "stock_code": ["000001.SZ"] * 2,
            "open": [10, 10],
            "high": [9, 9],
            "low": [8, 8],
            "close": [11, 11],
            "volume": [1, 1],
        }
    )
    report = validate_daily_bars(frame, "stock_code", "stock_daily")
    with pytest.raises(QualityGateError):
        enforce_quality(report)


def test_financial_availability_is_next_open_day() -> None:
    calendar = normalize_trading_dates(
        [pd.Timestamp("2026-04-30").timestamp() * 1000, pd.Timestamp("2026-05-06").timestamp() * 1000], "SH"
    )
    financial = pd.DataFrame(
        {"stock_code": ["000001.SZ"], "report_period": ["20260331"], "announce_date": ["20260430"]}
    )
    result = assign_financial_availability(financial, calendar)
    assert result.iloc[0]["available_date"] == date(2026, 5, 6)


def test_top_holder_rows_have_distinct_logical_keys_but_revisions_share_them() -> None:
    calendar = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 2), date(2026, 4, 2)],
            "is_open": [True, True],
        }
    )
    financial = pd.DataFrame(
        {
            "stock_code": ["000001.SZ"] * 4,
            "table_name": ["Top10FlowHolder"] * 4,
            "endDate": ["20251231"] * 4,
            "declareDate": ["20260301", "20260301", "20260401", "20260401"],
            "rank": [1, 2, 1, 2],
            "quantity": [100.0, 80.0, 110.0, 85.0],
        }
    )
    result = assign_financial_availability(financial, calendar)
    rank1 = result[result["rank"] == 1]
    rank2 = result[result["rank"] == 2]

    assert rank1["logical_record_key"].nunique() == 1
    assert rank2["logical_record_key"].nunique() == 1
    assert rank1.iloc[0]["logical_record_key"] != rank2.iloc[0]["logical_record_key"]
    assert result["source_record_key"].nunique() == 4
    assert result["snapshot_version_key"].nunique() == 2


def test_historical_universe_respects_listing_interval() -> None:
    master = pd.DataFrame(
        {
            "stock_code": ["OLD.SH"],
            "list_date": [date(2020, 1, 2)],
            "delist_date": [date(2020, 1, 3)],
        }
    )
    calendar = pd.DataFrame(
        {"trade_date": [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)], "is_open": True}
    )
    result = build_historical_universe(master, calendar)
    assert result["trade_date"].tolist() == [date(2020, 1, 2), date(2020, 1, 3)]


def test_stock_volatility_quality_blocks_non_null_invalid_return() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 1, 5)],
            "stock_code": ["A"],
            "ret_1d": [0.0],
            "valid_return_flag": [False],
            "rv5": [0.0],
            "rv20": [0.0],
            "rv60": [0.0],
            "valid_obs_5": [0],
            "valid_obs_20": [0],
            "valid_obs_60": [0],
        }
    )
    report = validate_stock_volatility(frame, (5, 20, 60))
    with pytest.raises(QualityGateError, match="invalid_return_is_null=1"):
        enforce_quality(report)


def test_market_volatility_quality_blocks_invalid_coverage() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 1, 5)],
            "universe_name": ["ALL_A"],
            "eligible_stock_count": [1],
            "valid_return_count": [1],
            "coverage_ratio": [1.1],
            "quality_status": ["PASS"],
        }
    )
    report = validate_aggregate_volatility(frame, "market_vol_daily")
    with pytest.raises(QualityGateError, match="bounded_metric_range=1"):
        enforce_quality(report)
