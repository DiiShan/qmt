from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from .adjustment import audit_xtdata_adjustment_factors
from .config import DataConfig, load_config
from .errors import QmtLocalDataError
from .lock import ProjectLock
from .pipeline import DatabaseBuilder, load_database_status
from .qmt_client import XtDataClient


# Every dataset declared in config/datasets.yaml must remain classified here.
# tests/test_maintenance.py makes an unclassified future dataset a test failure.
DAILY_MAINTAINED_DATASETS = frozenset(
    {
        "stock_daily",
        "index_daily",
        "security_master",
        "current_stock_list",
        "delisted_stock_list",
        "index_membership_snapshot_daily",
        "sector_membership_snapshot_daily",
        "trade_calendar",
    }
)
FULL_REBUILD_DATASETS = frozenset(
    {
        "adjust_factor",
        "stock_vol_daily",
        "market_vol_daily",
        "index_vol_daily",
    }
)
MANUAL_DATASETS = frozenset(
    {
        # These remain manual until the complete historical CFFEX contract source is closed.
        "future_daily",
        "future_main_mapping",
        "future_basis_daily",
    }
)


@dataclass(frozen=True)
class MaintenancePlan:
    as_of: date
    calendar_start: date
    stock_start: date
    index_start: date
    revision_lookback_trade_days: int
    full: bool

    def to_dict(self) -> dict[str, Any]:
        return {key: value.isoformat() if isinstance(value, date) else value for key, value in asdict(self).items()}


def _database_scope(config: DataConfig) -> str:
    status = load_database_status(config.data_root)
    if status is None:
        raise QmtLocalDataError("Database status is missing; initialize the database first")
    state = str(status.get("state") or "")
    scope = str(status.get("universe_scope") or "")
    if state != f"READY_{scope}" or scope not in {"FULL_HISTORY", "CURRENT_UNIVERSE_ONLY"}:
        raise QmtLocalDataError(f"Database is not ready for one-click update: state={state}, scope={scope}")
    return scope


def _rewind_open_days(
    connection: duckdb.DuckDBPyConnection,
    anchor: date | None,
    lookback: int,
    fallback: date,
) -> date:
    if anchor is None:
        return fallback
    rows = connection.execute(
        """
        SELECT trade_date
        FROM trade_calendar
        WHERE market = 'SH' AND is_open AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        [anchor, lookback + 1],
    ).fetchall()
    return min((row[0] for row in rows), default=fallback)


def build_maintenance_plan(config: DataConfig, as_of: date, *, full: bool) -> MaintenancePlan:
    if as_of < config.project.history_start:
        raise ValueError("Maintenance as-of date is before project.history_start")
    database = config.data_root / "database" / "qmt.duckdb"
    if not database.exists():
        raise FileNotFoundError(f"DuckDB catalog does not exist: {database}")
    lookback = config.ingestion.revision_lookback_trade_days
    with duckdb.connect(str(database), read_only=True) as connection:
        stock_anchor = connection.execute(
            "SELECT MAX(trade_date) FROM daily_bar WHERE trade_date <= ?", [as_of]
        ).fetchone()[0]
        index_rows = connection.execute(
            """
            SELECT index_code, MAX(trade_date)
            FROM index_daily
            WHERE index_code IN (SELECT UNNEST(?)) AND trade_date <= ?
            GROUP BY index_code
            """,
            [list(config.markets.indexes), as_of],
        ).fetchall()
        maxima = {str(code): maximum for code, maximum in index_rows}
        index_anchor = (
            min(maxima.values())
            if set(config.markets.indexes) <= set(maxima) and maxima
            else None
        )
        stock_start = _rewind_open_days(
            connection, stock_anchor, lookback, config.project.history_start
        )
        index_start = _rewind_open_days(
            connection, index_anchor, lookback, config.project.history_start
        )
    return MaintenancePlan(
        as_of=as_of,
        calendar_start=min(stock_start, index_start),
        stock_start=stock_start,
        index_start=index_start,
        revision_lookback_trade_days=lookback,
        full=full,
    )


def _validate_reference_relationships(database: Path) -> None:
    checks = {
        "current/delisted overlap": (
            "SELECT COUNT(*) FROM current_stock_list c INNER JOIN delisted_stock_list d USING(stock_code)"
        ),
        "current stock absent/non-current in security_master": (
            "SELECT COUNT(*) FROM current_stock_list c LEFT JOIN security_master m USING(stock_code) "
            "WHERE m.stock_code IS NULL OR m.listing_status <> 'CURRENT'"
        ),
        "eligible universe row before listing": (
            "SELECT COUNT(*) FROM historical_universe u INNER JOIN security_master m USING(stock_code) "
            "WHERE u.eligible_flag AND u.trade_date < m.list_date"
        ),
    }
    with duckdb.connect(str(database), read_only=True) as connection:
        failures = {name: connection.execute(sql).fetchone()[0] for name, sql in checks.items()}
    failures = {name: count for name, count in failures.items() if count}
    if failures:
        raise QmtLocalDataError(f"Reference relationship validation failed: {failures}")


def run_database_update(
    config_path: Path,
    *,
    as_of: date,
    full: bool = False,
) -> dict[str, Any]:
    config = load_config(config_path)
    scope = _database_scope(config)
    plan = build_maintenance_plan(config, as_of, full=full)
    client = XtDataClient()
    builder = DatabaseBuilder(config, client, universe_scope=scope)
    result: dict[str, Any] = {"plan": plan.to_dict(), "mode": "full" if full else "daily"}
    try:
        stock_codes = client.discover_stock_codes(
            config.markets.stock_sectors, config.markets.stock_suffixes
        )
        with ProjectLock(config.data_root):
            result["trade_calendar_run"] = builder.build_trade_calendar(
                "SH", plan.calendar_start, as_of
            )
            result["stock_batches"] = len(
                builder.ingest_market(
                    stock_codes, "stock", plan.stock_start, as_of, download=True
                )
            )
            result["index_batches"] = len(
                builder.ingest_market(
                    config.markets.indexes,
                    "index",
                    plan.index_start,
                    as_of,
                    download=True,
                )
            )
            result["reference_runs"] = builder.update_reference_data(as_of)
            builder.refresh_catalog()

            if full:
                calendar = builder.store.read_active_frame(
                    "processed", "trade_calendar", ["market", "trade_date"]
                )
                result["financial_runs"] = builder.ingest_financial(
                    stock_codes,
                    calendar,
                    plan.stock_start,
                    as_of,
                    download=True,
                )
                result["corporate_action_runs"] = builder.ingest_dividend_factors(
                    stock_codes, plan.stock_start, as_of
                )
                universe_name = "ALL_A" if scope == "FULL_HISTORY" else "CURRENT_SURVIVORS"
                result["historical_universe_run"] = builder.build_universe(universe_name)
                builder.refresh_catalog()

                factor_version = "xtdata_dr_cumprod_v1"
                audit = audit_xtdata_adjustment_factors(
                    config, factor_version=factor_version
                )
                result["adjust_factor_run"] = builder.publish_validated_adjust_factor(
                    audit.factors,
                    factor_version=factor_version,
                    validation_evidence=audit.evidence,
                )
                stock_run, market_run, index_run = builder.build_volatility_derived(
                    config.project.history_start,
                    as_of,
                    rebuild_from=config.project.history_start,
                )
                result["volatility_runs"] = {
                    "stock_vol_daily": stock_run,
                    "market_vol_daily": market_run,
                    "index_vol_daily": index_run,
                }
                builder.refresh_catalog()

            result["storage_audit"] = str(builder.write_storage_audit())
            result["database_status"] = str(
                builder.write_database_status(
                    f"READY_{scope}",
                    bool((load_database_status(config.data_root) or {}).get("phase0_gate_passed")),
                )
            )
    finally:
        client.disconnect()

    from .cli import main as cli_main

    if cli_main(["validate", "--config", str(config_path)]) != 0:
        raise QmtLocalDataError("Final active-manifest validation failed")
    _validate_reference_relationships(config.data_root / "database" / "qmt.duckdb")
    result["validated"] = True
    result["not_updated_automatically"] = sorted(MANUAL_DATASETS)
    if not full:
        result["full_rebuild_datasets_skipped"] = sorted(FULL_REBUILD_DATASETS)
    return result
