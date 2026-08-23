from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Iterable, Iterator

import numpy as np
import pandas as pd


MARKET_COLUMN_MAP = {
    "time": "trade_date",
    "stime": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "preClose": "pre_close",
    "pre_close": "pre_close",
    "volume": "volume",
    "amount": "amount",
    "suspendFlag": "suspend_flag",
    "suspend_flag": "suspend_flag",
    "settlementPrice": "settlement",
    "settelementPrice": "settlement",
    "settlement": "settlement",
    "openInterest": "open_interest",
    "open_interest": "open_interest",
}

KNOWN_XTDATA_STOCK_EXPIRY_SENTINELS = {
    "10001011",
    "10001111",
    "10011011",
    "10011111",
    "10111111",
}


def _parse_date_series(values: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(values):
        return pd.to_datetime(values, errors="coerce").dt.date
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().any() and numeric.dropna().abs().median() > 10_000_000_000:
        return pd.to_datetime(numeric, unit="ms", errors="coerce", utc=True).dt.tz_convert("Asia/Shanghai").dt.date
    text = values.astype("string").str.replace(r"\.0$", "", regex=True)
    parsed = pd.to_datetime(text, errors="coerce")
    return parsed.dt.date


def flatten_market_data(raw: Any, code_column: str = "security_code") -> pd.DataFrame:
    """Flatten the dict-of-DataFrames returned by ``get_market_data_ex``."""
    if raw is None:
        return pd.DataFrame()
    if isinstance(raw, pd.DataFrame):
        raw = {"": raw}
    if not isinstance(raw, dict):
        raise TypeError(f"Unsupported market-data shape: {type(raw).__name__}")

    frames: list[pd.DataFrame] = []
    for code, value in raw.items():
        if value is None:
            continue
        frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
        if frame.empty:
            continue
        if not isinstance(frame.index, pd.RangeIndex):
            index_name = frame.index.name or "time"
            if index_name in frame.columns:
                index_name = "_index_time"
            frame = frame.reset_index(names=index_name)
            if "time" not in frame.columns and index_name in frame.columns:
                frame = frame.rename(columns={index_name: "time"})
        frame[code_column] = str(code)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def normalize_market_data(raw: Any, asset: str) -> pd.DataFrame:
    code_column = {"stock": "stock_code", "index": "index_code", "future": "contract_code"}[asset]
    frame = flatten_market_data(raw, code_column=code_column)
    if frame.empty:
        return frame
    frame = frame.rename(columns={key: value for key, value in MARKET_COLUMN_MAP.items() if key in frame.columns})
    if "trade_date" not in frame.columns:
        raise ValueError("Market data has no time/trade_date column")
    frame["trade_date"] = _parse_date_series(frame["trade_date"])
    frame = frame[frame["trade_date"].notna()].copy()
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "volume",
        "amount",
        "suspend_flag",
        "settlement",
        "open_interest",
    ]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    required_by_asset = {
        "stock": ["trade_date", "stock_code", "open", "high", "low", "close", "volume", "amount"],
        "index": ["trade_date", "index_code", "open", "high", "low", "close"],
        "future": ["trade_date", "contract_code", "open", "high", "low", "close", "volume", "open_interest"],
    }
    missing = set(required_by_asset[asset]) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required {asset} columns: {sorted(missing)}")
    if asset == "future":
        frame["product"] = frame["contract_code"].str.extract(r"^([A-Za-z]+)", expand=False).str.upper()
    columns = list(dict.fromkeys([*required_by_asset[asset], *[c for c in numeric_columns if c in frame.columns], "product"]))
    columns = [column for column in columns if column in frame.columns]
    return frame[columns].sort_values([code_column, "trade_date"]).reset_index(drop=True)


def normalize_instrument_details(details: dict[str, dict[str, Any]], asset: str = "stock") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for code, detail in details.items():
        if not isinstance(detail, dict) or not detail:
            continue
        if asset == "future":
            rows.append(
                {
                    "contract_code": code,
                    "product": str(detail.get("ProductID") or re.match(r"[A-Za-z]+", code).group(0)).upper(),
                    "exchange": code.rsplit(".", 1)[-1],
                    "list_date": _parse_detail_date(detail.get("CreateDate") or detail.get("OpenDate")),
                    "expire_date": _parse_detail_date(detail.get("ExpireDate") or detail.get("EndDelivDate")),
                    "multiplier": _number_or_none(detail.get("VolumeMultiple") or detail.get("Multiplier")),
                }
            )
        else:
            list_date = _parse_detail_date(detail.get("OpenDate") or detail.get("CreateDate"))
            delist_raw = detail.get("ExpireDate") or detail.get("DelistDate")
            delist_digits = re.sub(r"\D", "", str(delist_raw))[:8] if delist_raw else ""
            delist_date = _parse_detail_date(delist_raw)
            if delist_digits in KNOWN_XTDATA_STOCK_EXPIRY_SENTINELS:
                delist_date = None
                delist_quality = "INVALID_SENTINEL_IGNORED"
            elif delist_date is None:
                delist_quality = "MISSING_OR_ACTIVE"
            else:
                delist_quality = "SOURCE"
            rows.append(
                {
                    "stock_code": code,
                    "stock_name": str(detail.get("InstrumentName") or detail.get("Name") or ""),
                    "exchange": code.rsplit(".", 1)[-1],
                    "security_type": str(detail.get("InstrumentType") or detail.get("ProductID") or "STOCK"),
                    "board": str(detail.get("Board") or "UNKNOWN"),
                    "list_date": list_date,
                    "delist_date": delist_date,
                    "delist_date_quality": delist_quality,
                }
            )
    return pd.DataFrame(rows)


def _parse_detail_date(value: Any) -> date | None:
    if value in (None, "", 0, "0"):
        return None
    text = re.sub(r"\D", "", str(value))[:8]
    if len(text) != 8:
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_trading_dates(values: Iterable[Any], market: str) -> pd.DataFrame:
    series = pd.Series(list(values), dtype="object")
    dates = _parse_date_series(series).dropna().drop_duplicates().sort_values().tolist()
    frame = pd.DataFrame({"market": market, "trade_date": dates})
    frame["is_open"] = True
    frame["previous_trade_date"] = frame["trade_date"].shift(1)
    frame["next_trade_date"] = frame["trade_date"].shift(-1)
    return frame


def flatten_financial_data(raw: Any) -> pd.DataFrame:
    """Flatten common XtData financial shapes while retaining source columns."""
    rows: list[pd.DataFrame] = []
    if not isinstance(raw, dict):
        return pd.DataFrame(raw)
    for stock_code, stock_value in raw.items():
        if isinstance(stock_value, dict):
            for table, value in stock_value.items():
                frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
                if frame.empty:
                    continue
                frame["stock_code"] = str(stock_code)
                frame["table_name"] = str(table)
                frame["source_record_key"] = _financial_record_keys(frame)
                rows.append(frame)
        else:
            frame = stock_value.copy() if isinstance(stock_value, pd.DataFrame) else pd.DataFrame(stock_value)
            if not frame.empty:
                frame["stock_code"] = str(stock_code)
                frame["table_name"] = "UNKNOWN"
                frame["source_record_key"] = _financial_record_keys(frame)
                rows.append(frame)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _financial_record_keys(frame: pd.DataFrame) -> list[str]:
    candidates = [
        "stock_code",
        "table_name",
        "m_timetag",
        "m_anntime",
        "m_quarter",
        "m_stateTypeCode",
        "reportDate",
        "announceTime",
        "endDate",
        "declareDate",
        "rank",
    ]
    columns = [column for column in candidates if column in frame.columns]
    if not columns:
        raise ValueError("Financial data has no fields for a stable source record key")
    payloads = frame[columns].astype("string").fillna("<NULL>").agg("\x1f".join, axis=1)
    return [hashlib.sha256(payload.encode("utf-8")).hexdigest() for payload in payloads]


def assign_financial_availability(financial: pd.DataFrame, trading_calendar: pd.DataFrame) -> pd.DataFrame:
    result = financial.copy()
    if "table_name" not in result.columns:
        result["table_name"] = "UNKNOWN"
    report_candidates = ["report_period", "reportDate", "m_timetag", "endDate", "date"]
    announce_candidates = ["announce_date", "announceTime", "m_anntime", "declareDate", "publishDate"]
    report_col = next((name for name in report_candidates if name in result.columns), None)
    announce_col = next((name for name in announce_candidates if name in result.columns), None)
    if report_col is None or announce_col is None:
        raise ValueError("Financial data lacks report-period or announce-date fields")
    result["report_period"] = _parse_date_series(result[report_col])
    result["announce_date"] = _parse_date_series(result[announce_col])

    open_days = sorted(pd.Series(trading_calendar.loc[trading_calendar["is_open"], "trade_date"]).dropna().unique())
    open_array = np.array(open_days, dtype="datetime64[D]")

    def next_day(value: Any) -> date | None:
        if pd.isna(value) or not len(open_array):
            return None
        index = int(np.searchsorted(open_array, np.datetime64(value), side="right"))
        return pd.Timestamp(open_array[index]).date() if index < len(open_array) else None

    result["available_date"] = result["announce_date"].map(next_day)
    result["pit_quality"] = np.where(result["announce_date"].isna(), "MISSING_ANNOUNCE_DATE", "VALID")
    detail_key = pd.Series("", index=result.index, dtype="string")
    detail_tables = result["table_name"].isin(["Top10Holder", "Top10FlowHolder"])
    if detail_tables.any():
        if "rank" not in result.columns:
            raise ValueError("Top shareholder financial data lacks rank for its logical record key")
        detail_key.loc[detail_tables] = result.loc[detail_tables, "rank"].astype("string").fillna("<NULL>")

    logical_payload = (
        result["stock_code"].astype("string").fillna("<NULL>")
        + "\x1f"
        + result["table_name"].astype("string").fillna("<NULL>")
        + "\x1f"
        + result["report_period"].astype("string").fillna("<NULL>")
        + "\x1f"
        + detail_key
    )
    source_payload = logical_payload + "\x1f" + result["announce_date"].astype("string").fillna("<NULL>")
    snapshot_payload = (
        result["stock_code"].astype("string").fillna("<NULL>")
        + "\x1f"
        + result["table_name"].astype("string").fillna("<NULL>")
        + "\x1f"
        + result["report_period"].astype("string").fillna("<NULL>")
        + "\x1f"
        + result["announce_date"].astype("string").fillna("<NULL>")
    )
    result["logical_record_key"] = logical_payload.map(lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest())
    result["source_record_key"] = source_payload.map(lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest())
    result["snapshot_version_key"] = snapshot_payload.map(
        lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
    )
    return result


def iter_historical_universe(
    security_master: pd.DataFrame,
    calendar: pd.DataFrame,
    name: str = "ALL_A",
    batch_size: int = 500,
) -> Iterator[pd.DataFrame]:
    """Yield bounded universe batches instead of materializing the full cross-product."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    days = pd.Series(calendar.loc[calendar["is_open"], "trade_date"]).dropna().sort_values().tolist()
    parts: list[pd.DataFrame] = []
    for offset in range(0, len(security_master), batch_size):
        for row in security_master.iloc[offset : offset + batch_size].itertuples(index=False):
            listed = getattr(row, "list_date", None)
            delisted = getattr(row, "delist_date", None)
            eligible_days = [
                day for day in days if (listed is None or day >= listed) and (delisted is None or day <= delisted)
            ]
            if not eligible_days:
                continue
            parts.append(
                pd.DataFrame(
                    {
                        "trade_date": eligible_days,
                        "stock_code": row.stock_code,
                        "universe_name": name,
                        "eligible_flag": True,
                        "exclusion_reasons": "",
                        "rule_version": "listed_interval_v1",
                    }
                )
            )
        if parts:
            yield pd.concat(parts, ignore_index=True)
            parts = []


def build_historical_universe(security_master: pd.DataFrame, calendar: pd.DataFrame, name: str = "ALL_A") -> pd.DataFrame:
    batches = list(iter_historical_universe(security_master, calendar, name))
    return pd.concat(batches, ignore_index=True) if batches else pd.DataFrame()
