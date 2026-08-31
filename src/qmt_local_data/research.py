from __future__ import annotations

from collections.abc import Iterable
from datetime import date
import json
from pathlib import Path

import duckdb
import pandas as pd


class ResearchData:
    """Read-only, point-in-time-aware research interface over the DuckDB catalog."""

    _DATE_COLUMNS = {
        "daily_bar": "trade_date",
        "index_daily": "trade_date",
        "future_daily": "trade_date",
        "future_basis_daily": "trade_date",
        "historical_universe": "trade_date",
        "stock_vol_daily": "trade_date",
        "market_vol_daily": "trade_date",
        "index_vol_daily": "trade_date",
        "sector_vol_daily": "trade_date",
        "current_stock_list": "as_of_date",
        "index_membership_snapshot_daily": "snapshot_date",
        "sector_membership_snapshot_daily": "snapshot_date",
    }

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        if not self.database_path.exists():
            raise FileNotFoundError(f"DuckDB catalog does not exist: {self.database_path}")

    def _dated_view(
        self,
        view: str,
        start: date | None,
        end: date | None,
        filters: dict[str, object] | None = None,
    ) -> pd.DataFrame:
        date_column = self._DATE_COLUMNS[view]
        clauses: list[str] = []
        parameters: list[object] = []
        if start is not None:
            clauses.append(f'"{date_column}" >= ?')
            parameters.append(start)
        if end is not None:
            clauses.append(f'"{date_column}" <= ?')
            parameters.append(end)
        for column, value in (filters or {}).items():
            if isinstance(value, (list, tuple, set, frozenset)):
                values = list(value)
                if not values:
                    return pd.DataFrame()
                clauses.append(f'"{column}" IN ({", ".join("?" for _ in values)})')
                parameters.extend(values)
            else:
                clauses.append(f'"{column}" = ?')
                parameters.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = f'SELECT * FROM "{view}"{where} ORDER BY "{date_column}"'
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            return connection.execute(query, parameters).fetchdf()

    def _require_view(self, view: str) -> None:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            exists = connection.execute(
                "SELECT COUNT(*) FROM information_schema.views "
                "WHERE table_schema = 'main' AND table_name = ?",
                [view],
            ).fetchone()[0]
        if not exists:
            if view == "sector_vol_daily":
                raise FileNotFoundError(
                    "sector_vol_daily is BLOCKED: reliable PIT/snapshot sector membership is unavailable"
                )
            raise FileNotFoundError(f"DuckDB view is not published: {view}")

    def _enforce_universe_scope(self, universe_name: str) -> None:
        status_path = self.database_path.parent.parent / "metadata" / "database_status.json"
        if not status_path.exists():
            return
        status = json.loads(status_path.read_text(encoding="utf-8"))
        scope = str(status.get("universe_scope") or "")
        current_names = {"CURRENT_SURVIVORS", "SH_SZ_CURRENT_SURVIVORS"}
        full_names = {"ALL_A", "SH_SZ_ALL_A"}
        if scope == "CURRENT_UNIVERSE_ONLY" and universe_name not in current_names:
            raise ValueError(
                "This database is CURRENT_UNIVERSE_ONLY; use CURRENT_SURVIVORS or "
                "SH_SZ_CURRENT_SURVIVORS"
            )
        if scope == "FULL_HISTORY" and universe_name not in full_names:
            raise ValueError("Use ALL_A or SH_SZ_ALL_A for a FULL_HISTORY database")

    def get_daily_bar(
        self, codes: Iterable[str], start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        return self._dated_view("daily_bar", start, end, {"stock_code": list(codes)})

    def get_index_daily(
        self, codes: Iterable[str], start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        return self._dated_view("index_daily", start, end, {"index_code": list(codes)})

    def get_index_bar(
        self, codes: Iterable[str], start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        return self.get_index_daily(codes, start, end)

    def get_future_daily(
        self, codes: Iterable[str], start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        return self._dated_view("future_daily", start, end, {"contract_code": list(codes)})

    def get_future_contracts(
        self,
        products: Iterable[str] | None = None,
        active_on: date | None = None,
    ) -> pd.DataFrame:
        clauses: list[str] = []
        parameters: list[object] = []
        product_list = list(products or [])
        if product_list:
            clauses.append(f'product IN ({", ".join("?" for _ in product_list)})')
            parameters.extend(product_list)
        if active_on is not None:
            clauses.extend(["(list_date IS NULL OR list_date <= ?)", "(expire_date IS NULL OR expire_date >= ?)"])
            parameters.extend([active_on, active_on])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            return connection.execute(f"SELECT * FROM future_contracts{where} ORDER BY product, contract_code", parameters).fetchdf()

    def get_future_main(
        self,
        products: Iterable[str],
        mapping_type: str,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        if mapping_type not in {"EOD_OBSERVED", "NEXT_TRADE_DAY"}:
            raise ValueError("mapping_type must be EOD_OBSERVED or NEXT_TRADE_DAY")
        clauses = ["mapping_type = ?"]
        parameters: list[object] = [mapping_type]
        product_list = list(products)
        if not product_list:
            return pd.DataFrame()
        clauses.append(f'product IN ({", ".join("?" for _ in product_list)})')
        parameters.extend(product_list)
        if start is not None:
            clauses.append("effective_trade_date >= ?")
            parameters.append(start)
        if end is not None:
            clauses.append("effective_trade_date <= ?")
            parameters.append(end)
        query = (
            "SELECT * FROM future_main_mapping WHERE "
            + " AND ".join(clauses)
            + " ORDER BY effective_trade_date, product"
        )
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            return connection.execute(query, parameters).fetchdf()

    def get_future_basis(
        self,
        products: Iterable[str],
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        return self._dated_view("future_basis_daily", start, end, {"product": list(products)})

    def get_universe(self, universe_name: str, trade_date: date) -> pd.DataFrame:
        return self._dated_view(
            "historical_universe", trade_date, trade_date, {"universe_name": universe_name, "eligible_flag": True}
        )

    def get_current_stock_list(self, as_of: date | None = None) -> pd.DataFrame:
        self._require_view("current_stock_list")
        if as_of is None:
            with duckdb.connect(str(self.database_path), read_only=True) as connection:
                as_of = connection.execute("SELECT MAX(as_of_date) FROM current_stock_list").fetchone()[0]
        return self._dated_view("current_stock_list", as_of, as_of)

    def get_delisted_stock_list(self) -> pd.DataFrame:
        self._require_view("delisted_stock_list")
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            return connection.execute(
                "SELECT * FROM delisted_stock_list ORDER BY delist_date, stock_code"
            ).fetchdf()

    def get_index_membership(
        self, index_codes: Iterable[str] | None = None, as_of: date | None = None
    ) -> pd.DataFrame:
        self._require_view("index_membership_snapshot_daily")
        if as_of is None:
            with duckdb.connect(str(self.database_path), read_only=True) as connection:
                as_of = connection.execute(
                    "SELECT MAX(snapshot_date) FROM index_membership_snapshot_daily"
                ).fetchone()[0]
        return self._dated_view(
            "index_membership_snapshot_daily",
            as_of,
            as_of,
            {"index_code": list(index_codes)} if index_codes is not None else None,
        )

    def get_sector_membership(
        self,
        sector_type: str = "SW1",
        sector_codes: Iterable[str] | None = None,
        as_of: date | None = None,
    ) -> pd.DataFrame:
        self._require_view("sector_membership_snapshot_daily")
        if as_of is None:
            with duckdb.connect(str(self.database_path), read_only=True) as connection:
                as_of = connection.execute(
                    "SELECT MAX(snapshot_date) FROM sector_membership_snapshot_daily"
                ).fetchone()[0]
        filters: dict[str, object] = {"sector_type": sector_type}
        if sector_codes is not None:
            filters["sector_code"] = list(sector_codes)
        return self._dated_view("sector_membership_snapshot_daily", as_of, as_of, filters)

    def get_stock_volatility(
        self,
        codes: Iterable[str],
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        self._require_view("stock_vol_daily")
        return self._dated_view("stock_vol_daily", start, end, {"stock_code": list(codes)})

    def get_market_volatility(
        self,
        universe_name: str = "ALL_A",
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        self._enforce_universe_scope(universe_name)
        self._require_view("market_vol_daily")
        return self._dated_view("market_vol_daily", start, end, {"universe_name": universe_name})

    def get_index_volatility(
        self,
        codes: Iterable[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        self._require_view("index_vol_daily")
        filters = {"index_code": list(codes)} if codes is not None else None
        return self._dated_view("index_vol_daily", start, end, filters)

    def get_sector_volatility(
        self,
        sector_type: str,
        sector_codes: Iterable[str] | None = None,
        universe_name: str = "ALL_A",
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        self._enforce_universe_scope(universe_name)
        self._require_view("sector_vol_daily")
        filters: dict[str, object] = {
            "sector_type": sector_type,
            "universe_name": universe_name,
        }
        if sector_codes is not None:
            filters["sector_code"] = list(sector_codes)
        return self._dated_view("sector_vol_daily", start, end, filters)

    def get_financial_pit(
        self,
        codes: Iterable[str],
        as_of: date,
        tables: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        code_list = list(codes)
        if not code_list:
            return pd.DataFrame()
        clauses = [f'stock_code IN ({", ".join("?" for _ in code_list)})', "available_date <= ?"]
        parameters: list[object] = [*code_list, as_of]
        table_list = list(tables or [])
        if table_list:
            clauses.append(f'table_name IN ({", ".join("?" for _ in table_list)})')
            parameters.extend(table_list)
        where = " AND ".join(clauses)
        query = f"""
            WITH eligible AS (
                SELECT * FROM financial_pit WHERE {where}
            ),
            snapshot_versions AS (
                SELECT DISTINCT stock_code, table_name, report_period,
                    snapshot_version_key, available_date, announce_date
                FROM eligible
                WHERE table_name IN ('Top10Holder', 'Top10FlowHolder')
            ),
            latest_snapshots AS (
                SELECT * EXCLUDE (_snapshot_version)
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY stock_code, table_name, report_period
                        ORDER BY available_date DESC, announce_date DESC, snapshot_version_key DESC
                    ) AS _snapshot_version
                    FROM snapshot_versions
                )
                WHERE _snapshot_version = 1
            ),
            snapshot_rows AS (
                SELECT eligible.*
                FROM eligible
                INNER JOIN latest_snapshots USING (
                    stock_code, table_name, report_period, snapshot_version_key
                )
                WHERE eligible.table_name IN ('Top10Holder', 'Top10FlowHolder')
            ),
            single_rows AS (
                SELECT * EXCLUDE (_pit_version)
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY logical_record_key
                        ORDER BY available_date DESC, announce_date DESC, _ingested_at DESC
                    ) AS _pit_version
                    FROM eligible
                    WHERE table_name NOT IN ('Top10Holder', 'Top10FlowHolder')
                )
                WHERE _pit_version = 1
            )
            SELECT * FROM snapshot_rows
            UNION ALL BY NAME
            SELECT * FROM single_rows
            ORDER BY stock_code, table_name, report_period
        """
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            return connection.execute(query, parameters).fetchdf()
