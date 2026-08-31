from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from qmt_local_data.volatility import (
    calculate_index_volatility,
    calculate_implied_correlation,
    calculate_market_volatility,
    calculate_rolling_percentile,
    calculate_sector_volatility,
    calculate_stock_returns,
    calculate_stock_volatility,
)


def _dates(count: int, start: date = date(2025, 1, 1)) -> list[date]:
    return [start + timedelta(days=index) for index in range(count)]


def _returns_frame(values: dict[str, list[float | None]]) -> pd.DataFrame:
    rows = []
    dates = _dates(max(len(item) for item in values.values()))
    for code, series in values.items():
        for trade_date, value in zip(dates, series):
            rows.append(
                {
                    "trade_date": trade_date,
                    "stock_code": code,
                    "ret_1d": value,
                    "log_ret_1d": np.log1p(value) if value is not None and value > -1 else np.nan,
                    "valid_return_flag": value is not None,
                }
            )
    return pd.DataFrame(rows)


def test_constant_returns_have_zero_rv_and_no_infinite_shock(data_config) -> None:
    returns = _returns_frame({"A": [0.01] * 140})
    result = calculate_stock_volatility(returns, data_config.volatility)
    assert result.iloc[-1]["rv20"] == pytest.approx(0)
    assert result.iloc[-1]["rv120"] == pytest.approx(0)
    assert result["shock_z20"].isna().all()
    assert not np.isinf(result.select_dtypes("number").to_numpy()).any()


def test_complete_synchronized_panel_has_implied_correlation_one() -> None:
    sequence = np.sin(np.linspace(0, 4, 60)) / 100
    panel = _returns_frame({"A": sequence.tolist(), "B": sequence.tolist(), "C": sequence.tolist()})
    value, count = calculate_implied_correlation(panel, 60)
    assert count == 3
    assert value == pytest.approx(1.0)


def test_seeded_independent_panel_has_near_zero_implied_correlation() -> None:
    generator = np.random.default_rng(20260827)
    panel = _returns_frame({f"S{i}": generator.normal(0, 0.01, 1000).tolist() for i in range(20)})
    value, count = calculate_implied_correlation(panel, 1000)
    assert count == 20
    assert abs(value) < 0.05


def test_implied_correlation_matches_volatility_weighted_pairwise_value() -> None:
    values = np.array(
        [
            [0.01, 0.02, -0.01],
            [0.02, 0.01, 0.00],
            [-0.01, -0.02, 0.01],
            [0.00, 0.01, 0.02],
            [0.03, 0.02, 0.01],
        ]
    )
    panel = _returns_frame({f"S{i}": values[:, i].tolist() for i in range(3)})
    actual, _ = calculate_implied_correlation(panel, 5)
    covariance = np.cov(values, rowvar=False, ddof=1)
    sigma = np.sqrt(np.diag(covariance))
    weighted_sum = 0.0
    weight_total = 0.0
    correlation = np.corrcoef(values, rowvar=False)
    for left in range(3):
        for right in range(left + 1, 3):
            weight = sigma[left] * sigma[right]
            weighted_sum += weight * correlation[left, right]
            weight_total += weight
    assert actual == pytest.approx(weighted_sum / weight_total)


def test_implied_correlation_uses_only_complete_window_stocks() -> None:
    panel = _returns_frame(
        {
            "A": [0.01, 0.02, -0.01, 0.01, 0.02],
            "B": [0.01, 0.02, -0.01, 0.01, 0.02],
            "SUSPENDED": [0.01, None, -0.01, 0.01, 0.02],
        }
    )
    value, count = calculate_implied_correlation(panel, 5)
    assert count == 2
    assert value == pytest.approx(1.0)


def test_suspension_is_null_and_resumption_uses_last_valid_close() -> None:
    dates = _dates(4)
    daily = pd.DataFrame(
        {
            "trade_date": dates,
            "stock_code": ["A"] * 4,
            "close_adjusted": [10.0, 10.0, 10.0, 11.0],
            "suspend_flag": [0, 1, 1, 0],
            "volume": [100, 0, 0, 100],
        }
    )
    result = calculate_stock_returns(daily)
    assert pd.isna(result.iloc[1]["ret_1d"])
    assert pd.isna(result.iloc[2]["ret_1d"])
    assert result.iloc[3]["ret_1d"] == pytest.approx(0.1)
    assert not result.iloc[1]["valid_return_flag"]


def test_prior_only_percentile_cannot_change_from_future_values() -> None:
    base = pd.Series([1.0, 2.0, 3.0, 2.0, 4.0])
    changed = base.copy()
    changed.iloc[4] = -1000.0
    first = calculate_rolling_percentile(base, 3, 2)
    second = calculate_rolling_percentile(changed, 3, 2)
    assert first.iloc[3] == second.iloc[3]
    assert first.iloc[3] == pytest.approx(2 / 3)


def test_universe_pit_excludes_future_listing() -> None:
    dates = _dates(3)
    daily = pd.DataFrame(
        {
            "trade_date": dates * 2,
            "stock_code": ["OLD"] * 3 + ["NEW"] * 3,
            "close_adjusted": [10, 11, 12, 10, 11, 12],
            "suspend_flag": 0,
            "volume": 100,
        }
    )
    universe = pd.DataFrame(
        {
            "trade_date": [*dates, dates[2]],
            "stock_code": ["OLD", "OLD", "OLD", "NEW"],
            "eligible_flag": True,
        }
    )
    result = calculate_stock_returns(daily, universe)
    assert result[result["trade_date"] < dates[2]]["stock_code"].unique().tolist() == ["OLD"]
    assert set(result[result["trade_date"] == dates[2]]["stock_code"]) == {"OLD", "NEW"}


def test_known_shock_breadth_is_exact(data_config) -> None:
    stock = pd.DataFrame(
        {
            "trade_date": [date(2026, 1, 5)] * 4,
            "stock_code": list("ABCD"),
            "ret_1d": [0.01, -0.01, 0.02, -0.02],
            "rv20": [0.2] * 4,
            "rv20_pct252": [0.1, 0.2, 0.8, 0.9],
            "shock_z20": [2.5, -2.5, 0.5, -0.5],
        }
    )
    result = calculate_market_volatility(
        stock, data_config.volatility, universe_name="ALL_A", universe_scope="FULL_HISTORY"
    )
    row = result.iloc[0]
    assert row["shock_up_breadth"] == pytest.approx(0.25)
    assert row["shock_down_breadth"] == pytest.approx(0.25)
    assert row["shock_abs_breadth"] == pytest.approx(0.5)
    assert row["highvol_breadth_80"] == pytest.approx(0.5)


def test_sector_membership_is_point_in_time(data_config) -> None:
    dates = _dates(2)
    stock = pd.DataFrame(
        {
            "trade_date": [dates[0], dates[1], dates[1]],
            "stock_code": ["A", "A", "B"],
            "ret_1d": [0.01, 0.01, 0.02],
            "rv20": [0.2, 0.2, 0.3],
            "rv20_pct252": [0.5, 0.5, 0.6],
            "shock_z20": [0.0, 0.0, 0.0],
        }
    )
    membership = pd.DataFrame(
        {
            "trade_date": [dates[0], dates[1], dates[1]],
            "sector_type": ["industry"] * 3,
            "sector_code": ["X"] * 3,
            "sector_name": ["Example"] * 3,
            "stock_code": ["A", "A", "B"],
        }
    )
    config = replace(data_config.volatility, sector_min_stock_count=2)
    result = calculate_sector_volatility(
        stock, membership, config, universe_name="ALL_A", universe_scope="FULL_HISTORY"
    )
    assert result.loc[result["trade_date"] == dates[0], "eligible_stock_count"].iloc[0] == 1
    assert result.loc[result["trade_date"] == dates[1], "eligible_stock_count"].iloc[0] == 2


def test_stock_rv_respects_market_day_minimum_observations(data_config) -> None:
    values = [0.01, None, -0.01, 0.02, -0.02]
    result = calculate_stock_volatility(_returns_frame({"A": values}), data_config.volatility)
    final = result.iloc[-1]
    assert final["valid_obs_5"] == 4
    assert pd.notna(final["rv5"])


def test_market_cross_section_includes_rv5_and_rv60_medians(data_config) -> None:
    stock = pd.DataFrame(
        {
            "trade_date": [date(2026, 1, 5)] * 3,
            "stock_code": ["A.SH", "B.SZ", "C.BJ"],
            "ret_1d": [0.01, -0.01, 0.02],
            "rv5": [0.10, 0.30, 0.20],
            "rv20": [0.20, 0.40, 0.30],
            "rv60": [0.30, 0.50, 0.40],
            "rv20_pct252": [0.2, 0.5, 0.8],
            "shock_z20": [0.0, 0.0, 0.0],
        }
    )
    result = calculate_market_volatility(
        stock,
        data_config.volatility,
        universe_name="ALL_A",
        universe_scope="FULL_HISTORY",
    )
    row = result.iloc[0]
    assert row["median_stock_rv5"] == pytest.approx(0.20)
    assert row["median_stock_rv20"] == pytest.approx(0.30)
    assert row["median_stock_rv60"] == pytest.approx(0.40)


def test_index_volatility_uses_index_close_without_adjustment_factor(data_config) -> None:
    dates = _dates(130)
    closes = 1000 * np.cumprod(1 + np.sin(np.arange(130)) * 0.01)
    daily = pd.DataFrame(
        {
            "trade_date": [*dates, dates[-1] + timedelta(days=1)],
            "index_code": "000300.SH",
            "close": [*closes, closes[-1]],
            "volume": [100] * len(dates) + [0],
        }
    )
    result = calculate_index_volatility(
        daily,
        data_config.volatility,
        index_names={"000300.SH": "沪深300"},
    )
    assert result["index_name"].unique().tolist() == ["沪深300"]
    assert pd.isna(result.iloc[0]["ret_1d"])
    assert pd.notna(result.iloc[-1]["rv5"])
    assert pd.notna(result.iloc[-1]["rv60"])
    assert result.iloc[-1]["valid_obs_120"] == 120
    assert len(result) == len(dates)
