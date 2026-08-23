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
)


@pytest.fixture
def data_config(tmp_path: Path) -> DataConfig:
    return DataConfig(
        project=ProjectConfig(tmp_path / "db", "Asia/Shanghai", date(2011, 1, 1), date(2014, 1, 1), "1d", "zstd"),
        storage=StorageConfig(25, 30, 40, 100, 0.01, 1.25, None),
        ingestion=IngestionConfig(2, 1, (0,), 10),
        markets=MarketsConfig(("沪深A股",), (".SH", ".SZ", ".BJ"), ("000300.SH",)),
        futures=FuturesConfig(("IF", "IH", "IC", "IM"), "oi_then_volume_v1", {"IF": "000300.SH"}),
        financial=FinancialConfig(("Balance",)),
    )
