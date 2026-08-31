from __future__ import annotations

import json
from datetime import date

import duckdb
import pandas as pd
import pytest

from qmt_local_data.catalog import CatalogBuilder, ViewSpec
from qmt_local_data.cli import _existing_database_scope
from qmt_local_data.manifest import ManifestStore
from qmt_local_data.pipeline import DatabaseBuilder
from qmt_local_data.research import ResearchData


class FakeClient:
    source_version = "fake-1"

    def market_data(self, codes, period, start="", end="", count=-1):
        return {
            code: pd.DataFrame(
                {
                    "open": [10.0],
                    "high": [11.0],
                    "low": [9.0],
                    "close": [10.5],
                    "preClose": [10.0],
                    "volume": [100.0],
                    "amount": [1000.0],
                    "suspendFlag": [0],
                },
                index=pd.Index(["20260105"], name="time"),
            )
            for code in codes
        }

    def download_market_data(self, code, period, start, end=""):
        raise AssertionError("download should not be called")


class DividendClient(FakeClient):
    def dividend_factors(self, code, start="", end=""):
        if code == "000002.SZ":
            return pd.DataFrame()
        return pd.DataFrame(
            {"interest": [1.0]},
            index=pd.Index(["20250101"], name="time"),
        )


def test_catalog_deduplicates_append_runs(data_config) -> None:
    store = ManifestStore(data_config.data_root)
    base = pd.DataFrame({"trade_date": [date(2026, 1, 5)], "stock_code": ["000001.SZ"], "close": [10.0]})
    store.publish_frame("processed", "stock_daily", base, "1.0")
    store.publish_frame("processed", "stock_daily", base.assign(close=11.0), "1.0")
    db = data_config.data_root / "database" / "qmt.duckdb"
    created = CatalogBuilder(store, db).refresh(
        [ViewSpec("daily_bar", "processed", "stock_daily", ("trade_date", "stock_code"))]
    )
    assert created == ["daily_bar"]
    with duckdb.connect(str(db), read_only=True) as connection:
        assert connection.execute("select close from daily_bar").fetchone()[0] == 11.0


def test_market_pipeline_checkpoint_makes_resume_idempotent(data_config) -> None:
    builder = DatabaseBuilder(data_config, FakeClient())
    first = builder.ingest_market(
        ["000001.SZ", "000002.SZ"], "stock", date(2026, 1, 1), date(2026, 1, 5), download=False
    )
    second = builder.ingest_market(
        ["000001.SZ", "000002.SZ"], "stock", date(2026, 1, 1), date(2026, 1, 5), download=False
    )
    assert len(first) == 1
    assert second == []
    active = builder.store.read_active_frame("processed", "stock_daily", ["trade_date", "stock_code"])
    assert len(active) == 2


def test_dividend_factors_publish_one_file_per_configured_batch(data_config) -> None:
    builder = DatabaseBuilder(
        data_config,
        DividendClient(),
        universe_scope="CURRENT_UNIVERSE_ONLY",
    )

    runs = builder.ingest_dividend_factors(
        ["000004.SZ", "000003.SZ", "000002.SZ", "000001.SZ"],
        date(2025, 1, 1),
        date(2026, 1, 1),
    )

    manifest = builder.store.load_active("raw", "corporate_action")
    frame = builder.store.read_active_frame("raw", "corporate_action", ["stock_code"])
    assert len(runs) == 2
    assert manifest is not None
    assert len(manifest.files) == 2
    assert manifest.metadata["batch_index"] == 2
    assert manifest.metadata["code_count"] == 2
    assert manifest.metadata["normalization_status"] == "RAW_ONLY_PENDING_FACTOR_SEMANTICS_VALIDATION"
    assert sorted(frame["stock_code"].tolist()) == ["000001.SZ", "000003.SZ", "000004.SZ"]


def test_current_universe_scope_cannot_publish_all_a(data_config) -> None:
    builder = DatabaseBuilder(data_config, FakeClient(), universe_scope="CURRENT_UNIVERSE_ONLY")
    with pytest.raises(ValueError, match="cannot publish a universe named ALL_A"):
        builder.build_universe()


def test_current_universe_is_published_with_explicit_scope(data_config) -> None:
    builder = DatabaseBuilder(data_config, FakeClient(), universe_scope="CURRENT_UNIVERSE_ONLY")
    builder.store.publish_frame(
        "processed",
        "security_master",
        pd.DataFrame(
            {"stock_code": ["000001.SZ"], "list_date": [date(2020, 1, 1)], "delist_date": [None]}
        ),
        "1.0",
    )
    builder.store.publish_frame(
        "processed",
        "trade_calendar",
        pd.DataFrame(
            {"market": ["SH"], "trade_date": [date(2026, 1, 5)], "is_open": [True]}
        ),
        "1.0",
    )
    builder.build_universe("CURRENT_SURVIVORS")
    manifest = builder.store.load_active("derived", "historical_universe")
    frame = builder.store.read_active_frame(
        "derived", "historical_universe", ["universe_name", "trade_date", "stock_code"]
    )
    assert manifest is not None
    assert manifest.metadata["universe_scope"] == "CURRENT_UNIVERSE_ONLY"
    assert manifest.metadata["accepted_for_unbiased_backtest"] is False
    assert frame["universe_name"].unique().tolist() == ["CURRENT_SURVIVORS"]
    master_run = builder.store.load_active("processed", "security_master").run_id
    calendar_run = builder.store.load_active("processed", "trade_calendar").run_id
    assert master_run in manifest.input_runs
    assert calendar_run in manifest.input_runs


def test_update_inherits_current_universe_scope_from_database_status(data_config) -> None:
    initial = DatabaseBuilder(data_config, FakeClient(), universe_scope="CURRENT_UNIVERSE_ONLY")
    initial.write_database_status("READY_CURRENT_UNIVERSE_ONLY", phase0_gate_passed=False)

    scope = _existing_database_scope(data_config)
    updater = DatabaseBuilder(data_config, FakeClient(), universe_scope=scope)
    updater.ingest_market(
        ["000001.SZ"], "stock", date(2026, 1, 1), date(2026, 1, 5), download=False
    )
    manifest = updater.store.load_active("processed", "stock_daily")
    status = json.loads(
        (data_config.data_root / "metadata" / "database_status.json").read_text(encoding="utf-8")
    )

    assert manifest is not None
    assert manifest.metadata["universe_scope"] == "CURRENT_UNIVERSE_ONLY"
    assert status["state"] == "READY_CURRENT_UNIVERSE_ONLY"
    assert status["accepted_for_unbiased_backtest"] is False


def test_research_api_enforces_point_in_time_and_mapping_semantics(data_config) -> None:
    store = ManifestStore(data_config.data_root)
    store.publish_frame(
        "processed",
        "stock_daily",
        pd.DataFrame(
            {
                "trade_date": [date(2026, 1, 5)],
                "stock_code": ["000001.SZ"],
                "close": [10.5],
            }
        ),
        "1.0",
    )
    store.publish_frame(
        "processed",
        "financial",
        pd.DataFrame(
            {
                "stock_code": ["000001.SZ"] * 3,
                "table_name": ["Top10Holder"] * 3,
                "source_record_key": ["rank1-v1", "rank2-v1", "rank1-v2"],
                "logical_record_key": ["rank1", "rank2", "rank1"],
                "snapshot_version_key": ["snapshot-v1", "snapshot-v1", "snapshot-v2"],
                "report_period": [date(2025, 12, 31)] * 3,
                "announce_date": [date(2026, 3, 1), date(2026, 3, 1), date(2026, 4, 1)],
                "available_date": [date(2026, 3, 2), date(2026, 3, 2), date(2026, 4, 2)],
                "rank": [1, 2, 1],
                "quantity": [100.0, 80.0, 110.0],
            }
        ),
        "1.0",
    )
    store.publish_frame(
        "derived",
        "future_main_mapping",
        pd.DataFrame(
            {
                "mapping_type": ["EOD_OBSERVED", "NEXT_TRADE_DAY"],
                "observation_trade_date": [date(2026, 1, 5), date(2026, 1, 5)],
                "effective_trade_date": [date(2026, 1, 5), date(2026, 1, 6)],
                "product": ["IF", "IF"],
                "contract_code": ["IF2601.IF", "IF2601.IF"],
            }
        ),
        "1.0",
    )
    database = data_config.data_root / "database" / "qmt.duckdb"
    CatalogBuilder(store, database).refresh()
    research = ResearchData(database)

    assert research.get_daily_bar(["000001.SZ"]).iloc[0]["close"] == 10.5
    early = research.get_financial_pit(["000001.SZ"], date(2026, 3, 31))
    late = research.get_financial_pit(["000001.SZ"], date(2026, 4, 30))
    assert len(early) == 2
    assert len(late) == 1
    assert dict(zip(early["rank"], early["quantity"])) == {1: 100.0, 2: 80.0}
    assert dict(zip(late["rank"], late["quantity"])) == {1: 110.0}
    mapping = research.get_future_main(["IF"], "NEXT_TRADE_DAY")
    assert mapping.iloc[0]["effective_trade_date"].date() == date(2026, 1, 6)
