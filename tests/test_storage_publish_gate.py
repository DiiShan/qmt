from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

from qmt_local_data.errors import StorageLimitError
from qmt_local_data.manifest import ManifestStore
from qmt_local_data.pipeline import DatabaseBuilder


class FinancialClient:
    source_version = "fake"

    def financial_data(self, codes, tables, start, end, report_type):
        return {
            codes[0]: {
                "Balance": pd.DataFrame(
                    {"m_timetag": ["20251231"], "m_anntime": ["20260301"], "tot_assets": [100.0]}
                )
            }
        }


def _blocked_config(data_config):
    storage = replace(
        data_config.storage,
        target_gb=0.000000001,
        warning_gb=0.000000002,
        hard_limit_gb=0.000000003,
        minimum_free_gb=0,
    )
    return replace(data_config, storage=storage)


def test_financial_publish_is_blocked_before_active_switch(data_config) -> None:
    builder = DatabaseBuilder(_blocked_config(data_config), FinancialClient())
    calendar = pd.DataFrame(
        {"trade_date": [date(2026, 3, 2)], "is_open": [True]}
    )
    with pytest.raises(StorageLimitError):
        builder.ingest_financial(
            ["000001.SZ"], calendar, date(2025, 1, 1), date(2026, 3, 2), download=False
        )
    assert builder.store.load_active("raw", "financial") is None
    assert builder.store.load_active("processed", "financial") is None


def test_universe_publish_is_blocked_before_active_switch(data_config) -> None:
    seed = ManifestStore(data_config.data_root)
    seed.publish_frame(
        "processed",
        "security_master",
        pd.DataFrame(
            {"stock_code": ["000001.SZ"], "list_date": [date(2020, 1, 1)], "delist_date": [None]}
        ),
        "1.0",
    )
    seed.publish_frame(
        "processed",
        "trade_calendar",
        pd.DataFrame(
            {"market": ["SH"], "trade_date": [date(2026, 1, 5)], "is_open": [True]}
        ),
        "1.0",
    )
    builder = DatabaseBuilder(_blocked_config(data_config), FinancialClient())
    with pytest.raises(StorageLimitError):
        builder.build_universe()
    assert builder.store.load_active("derived", "historical_universe") is None


def test_derived_publish_is_blocked_before_active_switch(data_config) -> None:
    seed = ManifestStore(data_config.data_root)
    seed.publish_frame(
        "processed",
        "future_daily",
        pd.DataFrame(
            {
                "trade_date": [date(2026, 1, 5)],
                "contract_code": ["IF2602.IF"],
                "product": ["IF"],
                "open_interest": [100.0],
                "volume": [50.0],
                "close": [4000.0],
                "settlement": [4001.0],
            }
        ),
        "1.0",
    )
    seed.publish_frame(
        "processed",
        "future_contract_master",
        pd.DataFrame({"contract_code": ["IF2602.IF"], "expire_date": [date(2026, 2, 20)]}),
        "1.0",
    )
    seed.publish_frame(
        "processed",
        "trade_calendar",
        pd.DataFrame(
            {
                "market": ["SH"],
                "trade_date": [date(2026, 1, 5)],
                "is_open": [True],
                "next_trade_date": [date(2026, 1, 6)],
            }
        ),
        "1.0",
    )
    seed.publish_frame(
        "processed",
        "index_daily",
        pd.DataFrame({"trade_date": [date(2026, 1, 5)], "index_code": ["000300.SH"], "close": [3990.0]}),
        "1.0",
    )
    builder = DatabaseBuilder(_blocked_config(data_config), FinancialClient())
    with pytest.raises(StorageLimitError):
        builder.build_futures_derived()
    assert builder.store.load_active("derived", "future_main_mapping") is None
    assert builder.store.load_active("derived", "future_basis_daily") is None
