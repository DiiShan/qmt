from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from qmt_local_data.config import (
    DataConfig,
    FinancialConfig,
    FuturesConfig,
    IngestionConfig,
    MarketsConfig,
    ProjectConfig,
    StorageConfig,
    VolatilityConfig,
)


@pytest.fixture
def data_config(tmp_path: Path) -> DataConfig:
    return DataConfig(
        project=ProjectConfig(tmp_path / "db", "Asia/Shanghai", date(2011, 1, 1), date(2014, 1, 1), "1d", "zstd"),
        storage=StorageConfig(25, 30, 40, 100, 0.01, 1.25, None),
        ingestion=IngestionConfig(2, 1, (0,), 10),
        markets=MarketsConfig(
            ("沪深A股",),
            (".SH", ".SZ", ".BJ"),
            ("000016.SH", "000300.SH", "000905.SH", "000852.SH", "000688.SH", "399006.SZ"),
        ),
        futures=FuturesConfig(("IF", "IH", "IC", "IM"), "oi_then_volume_v1", {"IF": "000300.SH"}),
        financial=FinancialConfig(("Balance",)),
        volatility=VolatilityConfig(
            252,
            (5, 10, 20, 60, 120),
            0.8,
            (252, 756),
            0.5,
            2.0,
            (0.8, 0.9),
            20,
            0.8,
            5,
            "ALL_A",
            (20, 60),
            20,
            (
                ("000016.SH", "上证50"),
                ("000300.SH", "沪深300"),
                ("000905.SH", "中证500"),
                ("000852.SH", "中证1000"),
                ("000688.SH", "科创50"),
                ("399006.SZ", "创业板"),
            ),
        ),
    )
