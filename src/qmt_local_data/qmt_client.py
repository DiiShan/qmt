from __future__ import annotations

import importlib
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Protocol


class MarketDataSource(Protocol):
    source_version: str | None

    def instrument_detail(self, code: str) -> dict[str, Any]: ...

    def market_data(
        self, codes: list[str], period: str, start: str = "", end: str = "", count: int = -1
    ) -> Any: ...

    def trading_dates(self, market: str, start: str, end: str, count: int = -1) -> list[Any]: ...


class XtDataClient:
    """Thin, lazy wrapper around the installed ``xtquant.xtdata`` module."""

    def __init__(self, xtdata_module: Any | None = None) -> None:
        if xtdata_module is None:
            xtquant = importlib.import_module("xtquant")
            xtdata_module = importlib.import_module("xtquant.xtdata")
            self.source_version = str(getattr(xtquant, "__version__", None) or getattr(xtquant, "version", None) or "unknown")
        else:
            self.source_version = str(getattr(xtdata_module, "__version__", "test-double"))
        self.xtdata = xtdata_module

    def instrument_detail(self, code: str) -> dict[str, Any]:
        value = self.xtdata.get_instrument_detail(code, True)
        return value if isinstance(value, dict) else {}

    def instrument_type(self, code: str) -> dict[str, bool]:
        getter = getattr(self.xtdata, "get_instrument_type", None)
        if getter is None:
            raise RuntimeError("XtData get_instrument_type is required for stock-universe discovery")
        value = getter(code)
        return value if isinstance(value, dict) else {}

    @property
    def data_dir(self) -> Path | None:
        getter = getattr(self.xtdata, "get_data_dir", None)
        if getter is None:
            return None
        try:
            value = getter()
            return Path(value) if value else None
        except Exception:
            return None

    def market_data(
        self, codes: list[str], period: str, start: str = "", end: str = "", count: int = -1
    ) -> Any:
        return self.xtdata.get_market_data_ex(
            field_list=[],
            stock_list=codes,
            period=period,
            start_time=start,
            end_time=end,
            count=count,
            dividend_type="none",
            fill_data=True,
        )

    def download_market_data(self, code: str, period: str, start: str, end: str = "") -> None:
        self.xtdata.download_history_data(code, period=period, start_time=start, end_time=end)

    def download_history_contracts(self, incrementally: bool = True) -> None:
        self.xtdata.download_history_contracts(incrementally=incrementally)

    def download_index_weights(self) -> None:
        self.xtdata.download_index_weight()

    def index_weights(self, index_code: str) -> dict[str, float]:
        value = self.xtdata.get_index_weight(index_code) or {}
        return {str(code): float(weight) for code, weight in value.items()}

    def sector_list(self) -> list[str]:
        return [str(value) for value in (self.xtdata.get_sector_list() or [])]

    def sector_codes(self, sector: str, as_of: str | None = None) -> list[str]:
        if as_of:
            values = self.xtdata.get_stock_list_in_sector(sector, real_timetag=as_of)
        else:
            values = self.xtdata.get_stock_list_in_sector(sector)
        return [str(value) for value in (values or [])]

    def discover_codes(self, sectors: Iterable[str], suffixes: Iterable[str] = ()) -> list[str]:
        suffixes = tuple(suffixes)
        result: set[str] = set()
        for sector in sectors:
            try:
                codes = self.sector_codes(sector)
            except Exception:
                continue
            result.update(code for code in codes if not suffixes or code.endswith(suffixes))
        return sorted(result)

    def discover_stock_codes(self, sectors: Iterable[str], suffixes: Iterable[str]) -> list[str]:
        """Return only contracts that XtData explicitly classifies as stocks.

        Some broker sector files include broad-market index contracts in an A-share
        sector.  Suffix filtering alone cannot distinguish those contracts from BSE
        stocks because both use ``.BJ``.
        """
        candidates = self.discover_codes(sectors, suffixes)
        return sorted(code for code in candidates if self.instrument_type(code).get("stock") is True)

    def instrument_details(self, codes: Iterable[str]) -> dict[str, dict[str, Any]]:
        return {code: detail for code in codes if (detail := self.instrument_detail(code))}

    def trading_dates(self, market: str, start: str, end: str, count: int = -1) -> list[Any]:
        return list(self.xtdata.get_trading_dates(market, start_time=start, end_time=end, count=count) or [])

    def dividend_factors(self, code: str, start: str, end: str) -> Any:
        return self.xtdata.get_divid_factors(code, start_time=start, end_time=end)

    def download_financial(self, codes: list[str], tables: list[str], start: str = "", end: str = "") -> None:
        if hasattr(self.xtdata, "download_financial_data2"):
            self.xtdata.download_financial_data2(codes, tables, start_time=start, end_time=end)
        else:
            self.xtdata.download_financial_data(codes, tables)

    def financial_data(
        self,
        codes: list[str],
        tables: list[str],
        start: str = "",
        end: str = "",
        report_type: str = "report_time",
    ) -> Any:
        return self.xtdata.get_financial_data(
            codes, tables, start_time=start, end_time=end, report_type=report_type
        )

    def discover_historical_candidates(self, products: Iterable[str]) -> tuple[list[str], list[str]]:
        """Return delisted-stock and expired-CFFEX candidates using only runtime-discovered codes."""
        today = date.today().strftime("%Y%m%d")
        sectors = self.sector_list()
        stock_sectors = [sector for sector in sectors if "A股" in sector and any(token in sector for token in ("沪深", "沪深京"))]
        current_stocks = set(self.discover_stock_codes(stock_sectors, (".SH", ".SZ", ".BJ")))
        historical_stocks: set[str] = set()
        for sector in stock_sectors:
            for as_of in ("20150105", "20180102", "20200102", "20240102"):
                try:
                    historical_stocks.update(self.sector_codes(sector, as_of=as_of))
                except Exception:
                    continue

        futures = self.discover_cffex_contracts(products)
        delisted: list[str] = []
        for code in sorted(historical_stocks - current_stocks):
            if not re.match(r"^\d{6}\.(SH|SZ|BJ)$", code, re.IGNORECASE):
                continue
            try:
                if self.instrument_type(code).get("stock") is not True:
                    continue
                detail = self.instrument_detail(code)
            except Exception:
                continue
            if detail:
                delisted.append(code)

        expired: list[str] = []
        for code in futures:
            try:
                detail = self.instrument_detail(code)
            except Exception:
                continue
            expiry = str(detail.get("ExpireDate") or "").replace("-", "")[:8]
            if expiry and expiry != "0" and expiry < today:
                expired.append(code)
        return sorted(set(delisted)), sorted(set(expired))

    def discover_cffex_contracts(self, products: Iterable[str]) -> list[str]:
        """Return every runtime-visible real IF/IH/IC/IM contract, regardless of expiry."""
        sectors = self.sector_list()
        derivative_sectors = [
            sector
            for sector in sectors
            if any(token in sector for token in ("退市", "历史", "过期", "中金所", "股指期货"))
        ]
        derivative_codes = self.discover_codes(derivative_sectors or sectors)
        product_pattern = re.compile(rf"^({'|'.join(re.escape(value) for value in products)})\d{{4}}\.IF$", re.IGNORECASE)
        return sorted({code for code in derivative_codes if product_pattern.match(code)})

    def disconnect(self) -> None:
        if hasattr(self.xtdata, "disconnect"):
            self.xtdata.disconnect()
