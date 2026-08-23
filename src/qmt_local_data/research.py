from __future__ import annotations

from collections.abc import Iterable
from datetime import date
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
        query = f"""
            SELECT * EXCLUDE (_pit_version)
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY stock_code, table_name, report_period
                    ORDER BY available_date DESC, announce_date DESC, _ingested_at DESC
                ) AS _pit_version
                FROM financial_pit
                WHERE {" AND ".join(clauses)}
            )
            WHERE _pit_version = 1
            ORDER BY stock_code, table_name, report_period
        """
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            return connection.execute(query, parameters).fetchdf()
