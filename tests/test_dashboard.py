from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from qmt_local_data.catalog import CatalogBuilder, ViewSpec
from qmt_local_data.cli import build_parser
from qmt_local_data.dashboard import (
    DashboardRepository,
    _default_date_range,
    _format_value,
    _numeric_metric_options,
)
from qmt_local_data.manifest import ManifestStore


def _repository(data_config, monkeypatch) -> tuple[DashboardRepository, ManifestStore]:
    config_path = data_config.data_root.parent / "data_config.yaml"
    config_path.write_text("placeholder: true\n", encoding="utf-8")
    monkeypatch.setattr("qmt_local_data.dashboard.load_config", lambda _: data_config)
    metadata = data_config.data_root / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    (metadata / "database_status.json").write_text(
        json.dumps(
            {
                "state": "READY_CURRENT_UNIVERSE_ONLY",
                "universe_scope": "CURRENT_UNIVERSE_ONLY",
                "accepted_for_unbiased_backtest": False,
            }
        ),
        encoding="utf-8",
    )
    return DashboardRepository(config_path), ManifestStore(data_config.data_root)


def test_dashboard_repository_reads_market_view(data_config, monkeypatch) -> None:
    repository, store = _repository(data_config, monkeypatch)
    store.publish_frame(
        "derived",
        "market_vol_daily",
        pd.DataFrame(
            {
                "trade_date": [date(2026, 1, 5), date(2026, 1, 6)],
                "universe_name": ["CURRENT_SURVIVORS"] * 2,
                "universe_scope": ["CURRENT_UNIVERSE_ONLY"] * 2,
                "ew_rv20": [0.20, 0.21],
                "coverage_ratio": [0.98, 0.99],
            }
        ),
        "1.0",
    )
    CatalogBuilder(store, repository.state.database_path).refresh()

    assert repository.state.universe_name == "CURRENT_SURVIVORS"
    assert repository.has_view("market_vol_daily")
    assert repository.date_bounds("market_vol_daily") == (date(2026, 1, 5), date(2026, 1, 6))
    assert repository.market_universes() == ["CURRENT_SURVIVORS"]
    result = repository.market_data(
        "CURRENT_SURVIVORS", date(2026, 1, 6), date(2026, 1, 6)
    )
    assert result["ew_rv20"].tolist() == [0.21]


def test_dashboard_repository_reads_sector_dimensions(data_config, monkeypatch) -> None:
    repository, store = _repository(data_config, monkeypatch)
    store.publish_frame(
        "derived",
        "sector_vol_daily",
        pd.DataFrame(
            {
                "trade_date": [date(2026, 1, 5), date(2026, 1, 5)],
                "sector_type": ["SW1", "SW1"],
                "sector_code": ["801010", "801020"],
                "sector_name": ["农林牧渔", "采掘"],
                "universe_name": ["CURRENT_SURVIVORS"] * 2,
                "universe_scope": ["CURRENT_UNIVERSE_ONLY"] * 2,
                "rv20": [0.25, 0.30],
            }
        ),
        "1.0",
    )
    CatalogBuilder(store, repository.state.database_path).refresh(
        [
            ViewSpec(
                "sector_vol_daily",
                "derived",
                "sector_vol_daily",
                ("trade_date", "sector_type", "sector_code", "universe_name"),
            )
        ]
    )

    assert repository.sector_types() == ["SW1"]
    assert repository.sectors("SW1")["sector_code"].tolist() == ["801010", "801020"]
    result = repository.sector_data("SW1", ["801010"], date(2026, 1, 5), date(2026, 1, 5))
    assert result["sector_name"].tolist() == ["农林牧渔"]


def test_dashboard_repository_reads_index_volatility(data_config, monkeypatch) -> None:
    repository, store = _repository(data_config, monkeypatch)
    store.publish_frame(
        "derived",
        "index_vol_daily",
        pd.DataFrame(
            {
                "trade_date": [date(2026, 1, 5)],
                "index_code": ["000300.SH"],
                "index_name": ["沪深300"],
                "close": [4500.0],
                "rv20": [0.20],
            }
        ),
        "1.0",
    )
    CatalogBuilder(store, repository.state.database_path).refresh()

    assert repository.index_catalog()["index_name"].tolist() == ["沪深300"]
    result = repository.index_data(
        ["000300.SH"], date(2026, 1, 5), date(2026, 1, 5)
    )
    assert result["rv20"].tolist() == [0.20]


def test_dashboard_keeps_missing_views_explicitly_blocked(data_config, monkeypatch) -> None:
    repository, _ = _repository(data_config, monkeypatch)

    assert not repository.database_exists()
    assert not repository.has_view("market_vol_daily")
    assert repository.date_bounds("sector_vol_daily") is None
    assert repository.sector_types() == []


def test_dashboard_formatting_and_metric_discovery() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 1, 5)],
            "quality_status": ["PASS"],
            "coverage_ratio": [0.975],
            "ew_rv20": [0.2345],
        }
    )

    assert _numeric_metric_options(frame, {"ew_rv20": "波动率"}) == ["ew_rv20", "coverage_ratio"]
    assert _format_value("coverage_ratio", 0.975) == "97.5%"
    assert _format_value("ew_rv20", 0.2345) == "23.45%"
    assert _format_value("rv20", float("nan")) == "—"
    assert _default_date_range((date(2020, 1, 1), date(2026, 1, 1))) == (
        date(2022, 12, 30),
        date(2026, 1, 1),
    )


def test_dashboard_cli_arguments() -> None:
    args = build_parser().parse_args(
        ["dashboard", "--config", "custom.yaml", "--host", "0.0.0.0", "--port", "8765"]
    )
    assert args.command == "dashboard"
    assert str(args.config) == "custom.yaml"
    assert args.host == "0.0.0.0"
    assert args.port == 8765
    update = build_parser().parse_args(
        ["update", "--start", "2026-08-21", "--asset", "index"]
    )
    assert update.asset == "index"
    market = build_parser().parse_args(
        ["build-market-volatility", "--rebuild-from", "2011-01-04"]
    )
    assert str(market.rebuild_from) == "2011-01-04"


def test_dashboard_rejects_invalid_port() -> None:
    from qmt_local_data.dashboard import launch_dashboard

    with pytest.raises(ValueError, match="between 1 and 65535"):
        launch_dashboard("config/data_config.yaml", host="127.0.0.1", port=0)
