from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import duckdb

from .manifest import ManifestStore


@dataclass(frozen=True)
class ViewSpec:
    name: str
    layer: str
    dataset: str
    business_key: tuple[str, ...]
    where: str | None = None


DEFAULT_VIEWS = (
    ViewSpec("daily_bar", "processed", "stock_daily", ("trade_date", "stock_code")),
    ViewSpec("index_daily", "processed", "index_daily", ("trade_date", "index_code")),
    ViewSpec("future_daily", "processed", "future_daily", ("trade_date", "contract_code")),
    ViewSpec("security_master", "processed", "security_master", ("stock_code",)),
    ViewSpec("future_contracts", "processed", "future_contract_master", ("contract_code",)),
    ViewSpec("trade_calendar", "processed", "trade_calendar", ("market", "trade_date")),
    ViewSpec(
        "financial_pit",
        "processed",
        "financial",
        ("source_record_key",),
        "announce_date IS NOT NULL AND available_date IS NOT NULL",
    ),
    ViewSpec(
        "historical_universe",
        "derived",
        "historical_universe",
        ("universe_name", "trade_date", "stock_code"),
    ),
    ViewSpec(
        "future_main_mapping",
        "derived",
        "future_main_mapping",
        ("mapping_type", "effective_trade_date", "product"),
    ),
    ViewSpec("future_basis_daily", "derived", "future_basis_daily", ("trade_date", "contract_code")),
)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class CatalogBuilder:
    def __init__(self, store: ManifestStore, database_path: Path) -> None:
        self.store = store
        self.database_path = database_path

    def refresh(self, specs: Iterable[ViewSpec] = DEFAULT_VIEWS) -> list[str]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        created: list[str] = []
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS catalog_refresh_log "
                    "(refreshed_at TIMESTAMPTZ, view_name VARCHAR, manifest_run_id VARCHAR)"
                )
                for spec in specs:
                    manifest = self.store.load_active(spec.layer, spec.dataset)
                    if manifest is None:
                        continue
                    paths = [str(path.resolve()) for path in self.store.absolute_files(manifest)]
                    path_sql = "[" + ",".join(_quote(path) for path in paths) + "]"
                    keys = ", ".join(f'"{key}"' for key in spec.business_key)
                    where_sql = f"WHERE {spec.where}" if spec.where else ""
                    query = f"""
                        CREATE OR REPLACE VIEW "{spec.name}" AS
                        SELECT * EXCLUDE (_row_version)
                        FROM (
                            SELECT *, ROW_NUMBER() OVER (
                                PARTITION BY {keys}
                                ORDER BY CAST(_ingested_at AS TIMESTAMPTZ) DESC, source_run_id DESC
                            ) AS _row_version
                            FROM read_parquet({path_sql}, union_by_name=true)
                            {where_sql}
                        )
                        WHERE _row_version = 1
                    """
                    connection.execute(query)
                    connection.execute(
                        "INSERT INTO catalog_refresh_log VALUES (current_timestamp, ?, ?)",
                        [spec.name, manifest.run_id],
                    )
                    created.append(spec.name)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return created
