from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigurationError


@dataclass(frozen=True)
class ProjectConfig:
    data_root: Path
    timezone: str
    history_start: date
    history_fallback_start: date
    stock_period: str
    compression: str


@dataclass(frozen=True)
class StorageConfig:
    target_gb: float
    warning_gb: float
    hard_limit_gb: float
    future_project_ceiling_gb: float
    minimum_free_gb: float
    batch_safety_factor: float
    qmt_cache_path: Path | None


@dataclass(frozen=True)
class IngestionConfig:
    initial_batch_size: int
    max_retries: int
    retry_backoff_seconds: tuple[int, ...]
    revision_lookback_trade_days: int
    financial_download_batch_reserve_mb: int = 256


@dataclass(frozen=True)
class MarketsConfig:
    stock_sectors: tuple[str, ...]
    stock_suffixes: tuple[str, ...]
    indexes: tuple[str, ...]


@dataclass(frozen=True)
class FuturesConfig:
    products: tuple[str, ...]
    main_rule_version: str
    spot_mapping: dict[str, str]


@dataclass(frozen=True)
class FinancialConfig:
    tables: tuple[str, ...]


@dataclass(frozen=True)
class VolatilityConfig:
    annualization_days: int
    windows: tuple[int, ...]
    min_obs_ratio: float
    percentile_windows: tuple[int, ...]
    percentile_min_obs_ratio: float
    shock_threshold: float
    highvol_percentiles: tuple[float, ...]
    ewma_halflife: float
    market_min_coverage_ratio: float
    sector_min_stock_count: int
    primary_universe: str
    correlation_windows: tuple[int, ...]
    warmup_safety_days: int
    index_universe: tuple[tuple[str, str], ...] = ()

    @property
    def index_names(self) -> dict[str, str]:
        return dict(self.index_universe)


@dataclass(frozen=True)
class DataConfig:
    project: ProjectConfig
    storage: StorageConfig
    ingestion: IngestionConfig
    markets: MarketsConfig
    futures: FuturesConfig
    financial: FinancialConfig
    volatility: VolatilityConfig

    @property
    def data_root(self) -> Path:
        return self.project.data_root


def _required(mapping: dict[str, Any], key: str, section: str) -> Any:
    if key not in mapping:
        raise ConfigurationError(f"Missing config value: {section}.{key}")
    return mapping[key]


def _as_date(value: Any, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be ISO date YYYY-MM-DD") from exc


def load_config(path: str | Path) -> DataConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    try:
        project_raw = raw["project"]
        storage_raw = raw["storage"]
        ingestion_raw = raw["ingestion"]
        markets_raw = raw["markets"]
        futures_raw = raw["futures"]
        financial_raw = raw["financial"]
        volatility_raw = raw["volatility"]
    except KeyError as exc:
        raise ConfigurationError(f"Missing config section: {exc.args[0]}") from exc

    root = Path(_required(project_raw, "data_root", "project"))
    if not root.is_absolute():
        raise ConfigurationError("project.data_root must be an absolute path")

    storage = StorageConfig(
        target_gb=float(_required(storage_raw, "target_gb", "storage")),
        warning_gb=float(_required(storage_raw, "warning_gb", "storage")),
        hard_limit_gb=float(_required(storage_raw, "hard_limit_gb", "storage")),
        future_project_ceiling_gb=float(_required(storage_raw, "future_project_ceiling_gb", "storage")),
        minimum_free_gb=float(storage_raw.get("minimum_free_gb", 10)),
        batch_safety_factor=float(storage_raw.get("batch_safety_factor", 1.25)),
        qmt_cache_path=Path(storage_raw["qmt_cache_path"]) if storage_raw.get("qmt_cache_path") else None,
    )
    if not (0 < storage.target_gb < storage.warning_gb < storage.hard_limit_gb <= storage.future_project_ceiling_gb):
        raise ConfigurationError("Storage thresholds must satisfy target < warning < hard <= ceiling")
    if storage.batch_safety_factor < 1:
        raise ConfigurationError("storage.batch_safety_factor must be >= 1")

    ingestion = IngestionConfig(
        initial_batch_size=int(_required(ingestion_raw, "initial_batch_size", "ingestion")),
        max_retries=int(_required(ingestion_raw, "max_retries", "ingestion")),
        retry_backoff_seconds=tuple(int(v) for v in ingestion_raw.get("retry_backoff_seconds", [])),
        revision_lookback_trade_days=int(ingestion_raw.get("revision_lookback_trade_days", 10)),
        financial_download_batch_reserve_mb=int(
            ingestion_raw.get("financial_download_batch_reserve_mb", 256)
        ),
    )
    if (
        ingestion.initial_batch_size <= 0
        or ingestion.max_retries < 0
        or ingestion.financial_download_batch_reserve_mb <= 0
    ):
        raise ConfigurationError("Batch size/reserve must be positive and retries non-negative")

    volatility = VolatilityConfig(
        annualization_days=int(volatility_raw.get("annualization_days", 252)),
        windows=tuple(int(value) for value in volatility_raw.get("windows", [5, 10, 20, 60, 120])),
        min_obs_ratio=float(volatility_raw.get("min_obs_ratio", 0.80)),
        percentile_windows=tuple(
            int(value) for value in volatility_raw.get("percentile_windows", [252, 756])
        ),
        percentile_min_obs_ratio=float(volatility_raw.get("percentile_min_obs_ratio", 0.50)),
        shock_threshold=float(volatility_raw.get("shock_threshold", 2.0)),
        highvol_percentiles=tuple(
            float(value) for value in volatility_raw.get("highvol_percentiles", [0.80, 0.90])
        ),
        ewma_halflife=float(volatility_raw.get("ewma_halflife", 20)),
        market_min_coverage_ratio=float(volatility_raw.get("market_min_coverage_ratio", 0.80)),
        sector_min_stock_count=int(volatility_raw.get("sector_min_stock_count", 5)),
        primary_universe=str(volatility_raw.get("primary_universe", "ALL_A")),
        correlation_windows=tuple(
            int(value) for value in volatility_raw.get("correlation_windows", [20, 60])
        ),
        warmup_safety_days=int(volatility_raw.get("warmup_safety_days", 20)),
        index_universe=tuple(
            (str(code), str(name))
            for code, name in (volatility_raw.get("index_universe", {}) or {}).items()
        ),
    )
    required_windows = {5, 10, 20, 60, 120}
    if not required_windows <= set(volatility.windows):
        raise ConfigurationError("volatility.windows must include 5, 10, 20, 60, and 120")
    if not set(volatility.correlation_windows) <= set(volatility.windows):
        raise ConfigurationError("volatility.correlation_windows must be included in volatility.windows")
    if not volatility.percentile_windows or min(volatility.percentile_windows) <= 0:
        raise ConfigurationError("volatility.percentile_windows must be positive")
    ratios = (
        volatility.min_obs_ratio,
        volatility.percentile_min_obs_ratio,
        volatility.market_min_coverage_ratio,
        *volatility.highvol_percentiles,
    )
    if any(value <= 0 or value > 1 for value in ratios):
        raise ConfigurationError("volatility ratios and percentiles must be in (0, 1]")
    if (
        volatility.annualization_days <= 0
        or volatility.shock_threshold <= 0
        or volatility.ewma_halflife <= 0
        or volatility.sector_min_stock_count < 2
        or volatility.warmup_safety_days < 0
    ):
        raise ConfigurationError("volatility counts, thresholds, and halflife are invalid")
    index_codes = [code for code, _ in volatility.index_universe]
    if len(index_codes) != len(set(index_codes)):
        raise ConfigurationError("volatility.index_universe contains duplicate index codes")
    if any(not code or not name for code, name in volatility.index_universe):
        raise ConfigurationError("volatility.index_universe codes and names must be non-empty")
    configured_market_indexes = {str(code) for code in markets_raw.get("indexes", [])}
    missing_market_indexes = set(index_codes) - configured_market_indexes
    if missing_market_indexes:
        raise ConfigurationError(
            "volatility.index_universe must be included in markets.indexes: "
            f"{sorted(missing_market_indexes)}"
        )

    return DataConfig(
        project=ProjectConfig(
            data_root=root,
            timezone=str(project_raw.get("timezone", "Asia/Shanghai")),
            history_start=_as_date(_required(project_raw, "history_start", "project"), "project.history_start"),
            history_fallback_start=_as_date(
                _required(project_raw, "history_fallback_start", "project"), "project.history_fallback_start"
            ),
            stock_period=str(project_raw.get("stock_period", "1d")),
            compression=str(project_raw.get("compression", "zstd")),
        ),
        storage=storage,
        ingestion=ingestion,
        markets=MarketsConfig(
            stock_sectors=tuple(markets_raw.get("stock_sectors", [])),
            stock_suffixes=tuple(markets_raw.get("stock_suffixes", [".SH", ".SZ", ".BJ"])),
            indexes=tuple(markets_raw.get("indexes", [])),
        ),
        futures=FuturesConfig(
            products=tuple(futures_raw.get("products", ["IF", "IH", "IC", "IM"])),
            main_rule_version=str(futures_raw.get("main_rule_version", "oi_then_volume_v1")),
            spot_mapping={str(k): str(v) for k, v in futures_raw.get("spot_mapping", {}).items()},
        ),
        financial=FinancialConfig(tables=tuple(financial_raw.get("tables", []))),
        volatility=volatility,
    )
