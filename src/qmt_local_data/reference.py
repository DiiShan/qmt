from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Iterable

import pandas as pd


_USER_AGENT = "Mozilla/5.0 (compatible; qmt-local-data/0.1; research-data-audit)"


def _get_json(url: str, params: dict[str, str], *, referer: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": _USER_AGENT, "Referer": referer},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError(f"Official reference endpoint returned {type(value).__name__}, expected object")
    return value


def _get_bytes(url: str, params: dict[str, str], *, referer: str) -> bytes:
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": _USER_AGENT, "Referer": referer},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _sse_stock_rows(status: str) -> pd.DataFrame:
    payload = _get_json(
        "https://query.sse.com.cn/commonQuery.do",
        {
            "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
            "isPagination": "true",
            "STOCK_CODE": "",
            "CSRC_CODE": "",
            "REG_PROVINCE": "",
            "STOCK_TYPE": "1,8",
            "COMPANY_STATUS": status,
            "type": "inParams",
            "pageHelp.cacheSize": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.pageSize": "10000",
            "pageHelp.pageNo": "1",
            "pageHelp.endPage": "1",
        },
        referer="https://www.sse.com.cn/assortment/stock/list/share/",
    )
    return pd.DataFrame(payload.get("result") or [])


def _normalize_sse(frame: pd.DataFrame, listing_status: str, as_of: date) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    delist_values = frame["DELIST_DATE"] if "DELIST_DATE" in frame else pd.Series(pd.NaT, index=frame.index)
    result = pd.DataFrame(
        {
            "stock_code": frame["A_STOCK_CODE"].astype("string").str.zfill(6) + ".SH",
            "stock_name": frame["SEC_NAME_CN"].fillna(frame["COMPANY_ABBR"]).astype("string"),
            "exchange": "SH",
            "list_date": pd.to_datetime(frame["LIST_DATE"], errors="coerce").dt.date,
            "delist_date": pd.to_datetime(delist_values, errors="coerce").dt.date,
        }
    )
    result["listing_status"] = listing_status
    result["as_of_date"] = as_of
    result["source"] = "SSE_OFFICIAL"
    return result[result["stock_code"].str.match(r"^\d{6}\.SH$")].reset_index(drop=True)


def _szse_report(catalog_id: str, tab_key: str) -> pd.DataFrame:
    content = _get_bytes(
        "https://www.szse.cn/api/report/ShowReport",
        {
            "SHOWTYPE": "xlsx",
            "CATALOGID": catalog_id,
            "TABKEY": tab_key,
            "random": "0.6935816432433362",
        },
        referer="https://www.szse.cn/market/product/stock/list/index.html",
    )
    return pd.read_excel(io.BytesIO(content))


def _normalize_sz_current(frame: pd.DataFrame, as_of: date) -> pd.DataFrame:
    required = {"A股代码", "A股简称", "A股上市日期"}
    if missing := required - set(frame.columns):
        raise KeyError(f"SZSE current-stock report missing: {sorted(missing)}")
    codes = frame["A股代码"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
    result = pd.DataFrame(
        {
            "stock_code": codes + ".SZ",
            "stock_name": frame["A股简称"].astype("string"),
            "exchange": "SZ",
            "list_date": pd.to_datetime(frame["A股上市日期"], errors="coerce").dt.date,
            "delist_date": pd.NaT,
            "listing_status": "CURRENT",
            "as_of_date": as_of,
            "source": "SZSE_OFFICIAL",
        }
    )
    return result[result["stock_code"].str.match(r"^(000|001|002|003|300|301)\d{3}\.SZ$")].reset_index(drop=True)


def _normalize_sz_delisted(frame: pd.DataFrame, as_of: date) -> pd.DataFrame:
    required = {"证券代码", "证券简称", "上市日期", "终止上市日期"}
    if missing := required - set(frame.columns):
        raise KeyError(f"SZSE delisted-stock report missing: {sorted(missing)}")
    codes = frame["证券代码"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
    result = pd.DataFrame(
        {
            "stock_code": codes + ".SZ",
            "stock_name": frame["证券简称"].astype("string"),
            "exchange": "SZ",
            "list_date": pd.to_datetime(frame["上市日期"], errors="coerce").dt.date,
            "delist_date": pd.to_datetime(frame["终止上市日期"], errors="coerce").dt.date,
            "listing_status": "DELISTED",
            "as_of_date": as_of,
            "source": "SZSE_OFFICIAL",
        }
    )
    return result[result["stock_code"].str.match(r"^(000|001|002|003|300|301)\d{3}\.SZ$")].reset_index(drop=True)


def load_official_sh_sz_stock_reference(as_of: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read current and delisted A-share lists from official SSE/SZSE endpoints."""
    sh_current = _normalize_sse(_sse_stock_rows("2,4,5,7,8"), "CURRENT", as_of)
    sh_delisted = _normalize_sse(_sse_stock_rows("3"), "DELISTED", as_of)
    sz_current = _normalize_sz_current(_szse_report("1110", "tab1"), as_of)
    sz_delisted = _normalize_sz_delisted(_szse_report("1793_ssgs", "tab2"), as_of)
    current = pd.concat([sh_current, sz_current], ignore_index=True).drop_duplicates("stock_code", keep="last")
    delisted = pd.concat([sh_delisted, sz_delisted], ignore_index=True).drop_duplicates("stock_code", keep="last")
    overlap = set(current["stock_code"]) & set(delisted["stock_code"])
    if overlap:
        raise ValueError(f"Official current/delisted lists overlap: {sorted(overlap)[:10]}")
    return current.sort_values("stock_code").reset_index(drop=True), delisted.sort_values("stock_code").reset_index(drop=True)


def build_current_stock_snapshot(
    qmt_codes: Iterable[str], official_current: pd.DataFrame, as_of: date
) -> pd.DataFrame:
    qmt = pd.DataFrame({"stock_code": sorted(set(qmt_codes))})
    qmt = qmt[qmt["stock_code"].str.match(r"^\d{6}\.(SH|SZ|BJ)$")]
    result = qmt.merge(official_current, on="stock_code", how="outer")
    result["exchange"] = result["exchange"].fillna(result["stock_code"].str.rsplit(".", n=1).str[-1])
    result["listing_status"] = "CURRENT"
    result["as_of_date"] = as_of
    result["source"] = result["source"].fillna("QMT_CURRENT_SECTOR")
    result["stock_name"] = result["stock_name"].fillna("")
    return result.sort_values("stock_code").reset_index(drop=True)


def build_index_membership_snapshot(
    weights: dict[str, dict[str, float]], index_names: dict[str, str], as_of: date
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index_code, index_name in index_names.items():
        for stock_code, weight in (weights.get(index_code) or {}).items():
            rows.append(
                {
                    "snapshot_date": as_of,
                    "index_code": index_code,
                    "index_name": index_name,
                    "stock_code": str(stock_code),
                    "weight": float(weight),
                    "source": "QMT_INDEX_WEIGHT",
                    "membership_quality": "OBSERVED_SNAPSHOT_ONLY",
                }
            )
    return pd.DataFrame(rows).sort_values(["index_code", "stock_code"]).reset_index(drop=True)


def build_sector_membership_snapshot(
    sector_members: dict[str, Iterable[str]], as_of: date
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sector_name, codes in sector_members.items():
        sector_type = "SW1" if sector_name.startswith("SW1") else "SOURCE_SECTOR"
        for stock_code in sorted(set(codes)):
            if not str(stock_code).endswith((".SH", ".SZ", ".BJ")):
                continue
            rows.append(
                {
                    "snapshot_date": as_of,
                    "sector_type": sector_type,
                    "sector_code": sector_name,
                    "sector_name": sector_name.removeprefix("SW1") if sector_type == "SW1" else sector_name,
                    "stock_code": str(stock_code),
                    "source": "QMT_SECTOR_SNAPSHOT",
                    "membership_quality": "OBSERVED_SNAPSHOT_ONLY",
                }
            )
    return pd.DataFrame(rows).sort_values(["sector_type", "sector_code", "stock_code"]).reset_index(drop=True)
