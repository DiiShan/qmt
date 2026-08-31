from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from qmt_local_data.catalog import CatalogBuilder
from qmt_local_data.errors import CapabilityGateError
from qmt_local_data.pipeline import DatabaseBuilder
from qmt_local_data.research import ResearchData


def _with_root(config, root):
    return replace(config, project=replace(config.project, data_root=root))


def _seed_volatility_database(config, *, corrected_close: float | None = None):
    builder = DatabaseBuilder(config, object(), universe_scope="CURRENT_UNIVERSE_ONLY")
    dates = [date(2025, 1, 1) + timedelta(days=index) for index in range(180)]
    calendar = pd.DataFrame(
        {
            "market": "SH",
            "trade_date": dates,
            "is_open": True,
            "previous_trade_date": [None, *dates[:-1]],
            "next_trade_date": [*dates[1:], None],
        }
    )
    builder.store.publish_frame(
        "processed", "trade_calendar", calendar, "1.0", mode="replace", date_column="trade_date"
    )

    generator = np.random.default_rng(20260827)
    rows = []
    for index, code in enumerate(("A.SH", "B.SZ", "C.BJ")):
        returns = generator.normal(0, 0.01 + index * 0.002, len(dates))
        prices = 100 * np.cumprod(1 + returns)
        if corrected_close is not None and code == "A.SH":
            prices[170] = corrected_close
        rows.extend(
            {
                "trade_date": trade_date,
                "stock_code": code,
                "close": float(price),
                "suspend_flag": 0,
                "volume": 1000,
            }
            for trade_date, price in zip(dates, prices)
        )
    daily = pd.DataFrame(rows)
    builder.store.publish_frame(
        "processed", "stock_daily", daily, "1.0", mode="replace", date_column="trade_date"
    )
    index_rows = []
    for index, code in enumerate(config.volatility.index_names):
        returns = generator.normal(0, 0.008 + index * 0.0005, len(dates))
        closes = 1000 * np.cumprod(1 + returns)
        index_rows.extend(
            {
                "trade_date": trade_date,
                "index_code": code,
                "close": float(close),
                "volume": 1000,
            }
            for trade_date, close in zip(dates, closes)
        )
    builder.store.publish_frame(
        "processed",
        "index_daily",
        pd.DataFrame(index_rows),
        "1.0",
        mode="replace",
        date_column="trade_date",
    )
    universe = daily[["trade_date", "stock_code"]].copy()
    universe["universe_name"] = "CURRENT_SURVIVORS"
    universe["eligible_flag"] = True
    universe["exclusion_reasons"] = ""
    universe["rule_version"] = "fixture_v1"
    builder.store.publish_frame(
        "derived",
        "historical_universe",
        universe,
        "1.0",
        mode="replace",
        date_column="trade_date",
        metadata={
            "universe_name": "CURRENT_SURVIVORS",
            "universe_scope": "CURRENT_UNIVERSE_ONLY",
            "accepted_for_unbiased_backtest": False,
        },
    )
    builder.store.publish_frame(
        "raw",
        "corporate_action",
        pd.DataFrame({"trade_date": [dates[0]], "stock_code": ["A.SH"], "dr": [1.0]}),
        "1.0",
        mode="replace",
        date_column="trade_date",
        metadata={"normalization_status": "RAW_ONLY_PENDING_FACTOR_SEMANTICS_VALIDATION"},
    )
    factor = pd.DataFrame(
        {
            "trade_date": [dates[0]] * 3,
            "stock_code": ["A.SH", "B.SZ", "C.BJ"],
            "factor": [1.0, 1.0, 1.0],
        }
    )
    evidence = [
        {"case": f"event-{index}", "case_type": "CORPORATE_ACTION", "status": "PASS"}
        for index in range(3)
    ]
    evidence.append({"case": "stable-window", "case_type": "NO_EVENT", "status": "PASS"})
    builder.publish_validated_adjust_factor(
        factor, factor_version="fixture_factor_v1", validation_evidence=evidence
    )
    builder.write_database_status("READY_CURRENT_UNIVERSE_ONLY", phase0_gate_passed=False)
    return builder, dates, daily


def _active_frame(builder, dataset, key):
    frame = builder.store.read_active_frame("derived", dataset, key)
    return frame.drop(columns=["source_run_id", "_ingested_at"], errors="ignore").sort_values(key).reset_index(
        drop=True
    )


def test_raw_only_factor_blocks_real_volatility_build(data_config) -> None:
    builder = DatabaseBuilder(data_config, object(), universe_scope="CURRENT_UNIVERSE_ONLY")
    builder.write_database_status("READY_CURRENT_UNIVERSE_ONLY", phase0_gate_passed=False)
    one_day = date(2026, 1, 5)
    builder.store.publish_frame(
        "processed",
        "trade_calendar",
        pd.DataFrame({"market": ["SH"], "trade_date": [one_day], "is_open": [True]}),
        "1.0",
    )
    builder.store.publish_frame(
        "processed",
        "stock_daily",
        pd.DataFrame({"trade_date": [one_day], "stock_code": ["A"], "close": [10.0]}),
        "1.0",
    )
    builder.store.publish_frame(
        "derived",
        "historical_universe",
        pd.DataFrame(
            {
                "trade_date": [one_day],
                "stock_code": ["A"],
                "universe_name": ["CURRENT_SURVIVORS"],
                "eligible_flag": [True],
            }
        ),
        "1.0",
        metadata={
            "universe_name": "CURRENT_SURVIVORS",
            "universe_scope": "CURRENT_UNIVERSE_ONLY",
        },
    )
    builder.store.publish_frame(
        "raw",
        "corporate_action",
        pd.DataFrame({"stock_code": ["A"], "dr": [1.0]}),
        "1.0",
        metadata={"normalization_status": "RAW_ONLY_PENDING_FACTOR_SEMANTICS_VALIDATION"},
    )
    with pytest.raises(CapabilityGateError, match="raw status=RAW_ONLY_PENDING_FACTOR_SEMANTICS_VALIDATION"):
        builder.check_volatility_prerequisites()
    with pytest.raises(CapabilityGateError, match="no-event"):
        builder.publish_validated_adjust_factor(
            pd.DataFrame({"trade_date": [one_day], "stock_code": ["A"], "factor": [1.0]}),
            factor_version="unvalidated",
            validation_evidence=[
                {"case_type": "CORPORATE_ACTION", "status": "PASS"} for _ in range(3)
            ],
        )
    assert builder.store.load_active("derived", "stock_vol_daily") is None


def test_volatility_pipeline_catalog_research_and_scope_gate(data_config) -> None:
    builder, dates, _ = _seed_volatility_database(data_config)
    stock_run, market_run, index_run = builder.build_volatility_derived(dates[160], dates[-1])
    assert stock_run and market_run and index_run
    stock_manifest = builder.store.load_active("derived", "stock_vol_daily")
    market_manifest = builder.store.load_active("derived", "market_vol_daily")
    index_manifest = builder.store.load_active("derived", "index_vol_daily")
    assert stock_manifest.config_hash
    assert market_manifest.input_runs
    assert market_manifest.metadata["universe_scope"] == "CURRENT_UNIVERSE_ONLY"
    assert market_manifest.metadata["universe_names"] == [
        "CURRENT_SURVIVORS",
        "SH_SZ_CURRENT_SURVIVORS",
    ]
    market_frame = _active_frame(
        builder, "market_vol_daily", ["trade_date", "universe_name"]
    )
    latest_market = market_frame[market_frame["trade_date"] == dates[-1]].set_index(
        "universe_name"
    )
    assert latest_market.loc["CURRENT_SURVIVORS", "eligible_stock_count"] == 3
    assert latest_market.loc["SH_SZ_CURRENT_SURVIVORS", "eligible_stock_count"] == 2
    assert {"median_stock_rv5", "median_stock_rv20", "median_stock_rv60"} <= set(
        market_frame.columns
    )
    assert index_manifest.metadata["price_basis"] == "official_index_close"
    assert builder.store.load_active("derived", "sector_vol_daily") is None

    database = data_config.data_root / "database" / "qmt.duckdb"
    created = CatalogBuilder(builder.store, database).refresh()
    assert "stock_vol_daily" in created
    assert "market_vol_daily" in created
    assert "index_vol_daily" in created
    research = ResearchData(database)
    assert not research.get_stock_volatility(["A.SH"]).empty
    assert not research.get_market_volatility("CURRENT_SURVIVORS").empty
    assert not research.get_market_volatility("SH_SZ_CURRENT_SURVIVORS").empty
    assert not research.get_index_volatility(["000300.SH"]).empty
    with pytest.raises(ValueError, match="CURRENT_UNIVERSE_ONLY"):
        research.get_market_volatility()
    with pytest.raises(FileNotFoundError, match="sector_vol_daily is BLOCKED"):
        research.get_sector_volatility("industry", universe_name="CURRENT_SURVIVORS")
    with pytest.raises(CapabilityGateError, match="sector membership"):
        builder.build_sector_volatility()


def test_full_and_daily_incremental_results_are_equal(data_config) -> None:
    full_config = _with_root(data_config, data_config.data_root.parent / "full-db")
    incremental_config = _with_root(data_config, data_config.data_root.parent / "incremental-db")
    full, dates, _ = _seed_volatility_database(full_config)
    incremental, _, _ = _seed_volatility_database(incremental_config)
    full.build_volatility_derived(dates[160], dates[-1])
    for trade_date in dates[160:]:
        incremental.build_volatility_derived(trade_date, trade_date)

    for dataset, key in (
        ("stock_vol_daily", ["trade_date", "stock_code"]),
        ("market_vol_daily", ["trade_date", "universe_name"]),
        ("index_vol_daily", ["trade_date", "index_code"]),
    ):
        assert_frame_equal(
            _active_frame(full, dataset, key),
            _active_frame(incremental, dataset, key),
            check_exact=False,
            rtol=1e-10,
            atol=1e-12,
        )


def test_rebuild_from_matches_fresh_corrected_full_build(data_config) -> None:
    rebuilt_config = _with_root(data_config, data_config.data_root.parent / "rebuilt-db")
    fresh_config = _with_root(data_config, data_config.data_root.parent / "fresh-corrected-db")
    rebuilt, dates, original = _seed_volatility_database(rebuilt_config)
    rebuilt.build_volatility_derived(dates[160], dates[-1])

    correction = original[
        (original["trade_date"] == dates[170]) & (original["stock_code"] == "A.SH")
    ].copy()
    correction["close"] = correction["close"] * 1.05
    rebuilt.store.publish_frame(
        "processed", "stock_daily", correction, "1.0", mode="append", date_column="trade_date"
    )
    rebuilt.build_volatility_derived(dates[170], dates[-1], rebuild_from=dates[170])

    corrected_close = float(correction.iloc[0]["close"])
    fresh, _, _ = _seed_volatility_database(fresh_config, corrected_close=corrected_close)
    fresh.build_volatility_derived(dates[160], dates[-1])
    for dataset, key in (
        ("stock_vol_daily", ["trade_date", "stock_code"]),
        ("market_vol_daily", ["trade_date", "universe_name"]),
        ("index_vol_daily", ["trade_date", "index_code"]),
    ):
        assert_frame_equal(
            _active_frame(rebuilt, dataset, key),
            _active_frame(fresh, dataset, key),
            check_exact=False,
            rtol=1e-10,
            atol=1e-12,
        )
