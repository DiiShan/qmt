from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from qmt_local_data.config import ConfigurationError, load_config
from qmt_local_data.errors import StorageLimitError
from qmt_local_data.storage_guard import StorageGuard, StorageLevel


def test_repository_config_uses_requested_data_root() -> None:
    config = load_config(Path("config/data_config.yaml"))
    assert str(config.data_root) == r"E:\qmt_data"
    assert config.storage.target_gb == 25
    assert config.storage.warning_gb == 30
    assert config.storage.hard_limit_gb == 40
    assert config.volatility.windows == (5, 10, 20, 60, 120)
    assert config.volatility.correlation_windows == (20, 60)
    assert config.volatility.warmup_safety_days == 20
    assert config.volatility.index_names == {
        "000016.SH": "上证50",
        "000300.SH": "沪深300",
        "000905.SH": "中证500",
        "000852.SH": "中证1000",
        "000688.SH": "科创50",
        "399006.SZ": "创业板",
    }
    assert set(config.volatility.index_names) <= set(config.markets.indexes)
    assert {"000002.SH", "399107.SZ"} <= set(config.markets.indexes)


def test_invalid_threshold_order_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
project: {data_root: 'C:\\db', history_start: '2011-01-01', history_fallback_start: '2014-01-01'}
storage: {target_gb: 30, warning_gb: 20, hard_limit_gb: 40, future_project_ceiling_gb: 100}
ingestion: {initial_batch_size: 1, max_retries: 0}
markets: {}
futures: {}
financial: {}
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_storage_guard_blocks_projected_hard_limit(data_config) -> None:
    data_config.data_root.mkdir(parents=True)
    tiny = replace(data_config.storage, target_gb=0.000001, warning_gb=0.000002, hard_limit_gb=0.000003)
    guard = StorageGuard(data_config.data_root, tiny)
    snapshot = guard.snapshot(estimated_batch_bytes=10_000)
    assert snapshot.level == StorageLevel.HARD_LIMIT
    with pytest.raises(StorageLimitError):
        guard.enforce(estimated_batch_bytes=10_000)


def test_volatility_config_requires_frozen_windows(tmp_path: Path) -> None:
    source = Path("config/data_config.yaml").read_text(encoding="utf-8")
    path = tmp_path / "bad-volatility.yaml"
    path.write_text(source.replace("windows: [5, 10, 20, 60, 120]", "windows: [5, 20, 60]"), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="must include 5, 10, 20, 60, and 120"):
        load_config(path)
