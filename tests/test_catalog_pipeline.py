from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from qmt_local_data.catalog import CatalogBuilder, ViewSpec
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
                "stock_code": ["000001.SZ"] * 4,
                "table_name": ["Top10Holder"] * 4,
                "source_record_key": ["rank1-v1", "rank2-v1", "rank1-v2", "rank2-v2"],
                "logical_record_key": ["rank1", "rank2", "rank1", "rank2"],
                "report_period": [date(2025, 12, 31)] * 4,
                "announce_date": [date(2026, 3, 1), date(2026, 3, 1), date(2026, 4, 1), date(2026, 4, 1)],
                "available_date": [date(2026, 3, 2), date(2026, 3, 2), date(2026, 4, 2), date(2026, 4, 2)],
                "rank": [1, 2, 1, 2],
                "quantity": [100.0, 80.0, 110.0, 85.0],
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
    assert len(late) == 2
    assert dict(zip(early["rank"], early["quantity"])) == {1: 100.0, 2: 80.0}
    assert dict(zip(late["rank"], late["quantity"])) == {1: 110.0, 2: 85.0}
    mapping = research.get_future_main(["IF"], "NEXT_TRADE_DAY")
    assert mapping.iloc[0]["effective_trade_date"].date() == date(2026, 1, 6)
