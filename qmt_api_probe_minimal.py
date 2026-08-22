#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal MiniQMT/xtdata capability probe.

Policy: one valid sample is enough to mark a data category feasible.
This is NOT a bulk data downloader, completeness check, or performance test.
MiniQMT must be running and logged in on this Windows machine.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

RESULTS: list[dict[str, Any]] = []


def empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, bytes, list, tuple, set, dict)):
        if len(value) == 0:
            return True
        if isinstance(value, dict):
            return all(empty(v) for v in value.values())
        return False
    flag = getattr(value, "empty", None)
    if isinstance(flag, bool):
        return flag
    try:
        return len(value) == 0
    except Exception:
        return False


def first_sample(value: Any) -> Any:
    """Keep/report only one representative sample where practical."""
    if value is None:
        return None
    if isinstance(value, dict):
        if not value:
            return value
        key = next(iter(value))
        return {key: first_sample(value[key])}
    if isinstance(value, (list, tuple)):
        return value[:1]
    if isinstance(value, set):
        return list(value)[:1]
    if hasattr(value, "head"):
        try:
            return value.head(1)
        except Exception:
            pass
    return value


def summary(value: Any) -> str:
    value = first_sample(value)
    shape = getattr(value, "shape", None)
    if shape is not None:
        return f"{type(value).__name__}(shape={shape})"
    text = repr(value)
    return text[:500]


def classify(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(x in text for x in ["permission", "unauthorized", "forbidden", "权限", "未授权", "vip"]):
        return "NO_PERMISSION"
    if any(x in text for x in ["has no attribute", "unsupported", "not supported", "unknown period", "不支持"]):
        return "UNSUPPORTED"
    return "ERROR"


def probe(category: str, name: str, fn: Callable[[], Any], validator: Callable[[Any], bool] | None = None, note: str = "") -> Any:
    started = time.perf_counter()
    try:
        value = fn()
        ok = validator(value) if validator else not empty(value)
        status = "PASS" if ok else "EMPTY"
        item = {
            "category": category,
            "test": name,
            "status": status,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "sample": summary(value) if not empty(value) else "",
            "note": note,
        }
        RESULTS.append(item)
        print(f"[{status:13}] {category:20} {name} {item['sample'] or note}")
        return value
    except Exception as exc:
        status = classify(exc)
        item = {
            "category": category,
            "test": name,
            "status": status,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "sample": "",
            "note": f"{type(exc).__name__}: {exc}",
        }
        RESULTS.append(item)
        print(f"[{status:13}] {category:20} {name} {item['note']}")
        return None


def skip(category: str, name: str, note: str) -> None:
    RESULTS.append({"category": category, "test": name, "status": "SKIP", "elapsed_ms": 0, "sample": "", "note": note})
    print(f"[SKIP         ] {category:20} {name} {note}")


def one_market(xtdata: Any, code: str, period: str, start: str = "") -> Any:
    return xtdata.get_market_data_ex(
        field_list=[],
        stock_list=[code],
        period=period,
        start_time=start,
        end_time="",
        count=1,
        dividend_type="none",
        fill_data=True,
    )


def subscribe_once(xtdata: Any, code: str) -> Any:
    seq = xtdata.subscribe_quote(code, period="tick", count=1, callback=None)
    try:
        return seq
    finally:
        if isinstance(seq, int) and seq > 0 and hasattr(xtdata, "unsubscribe_quote"):
            xtdata.unsubscribe_quote(seq)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One-sample MiniQMT xtdata capability probe")
    p.add_argument("--stock", default="000001.SZ")
    p.add_argument("--etf", default="510300.SH")
    p.add_argument("--cb", default="")
    p.add_argument("--option-code", default="")
    p.add_argument("--future-code", default="")
    p.add_argument("--download", action="store_true", help="Allow minimal supplement downloads when local data is missing")
    p.add_argument("--output-dir", default="reports")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = datetime.now().strftime("%Y%m%d")
    # Small window only; actual feasibility reads still use count=1.
    start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")

    try:
        import xtquant  # type: ignore
        from xtquant import xtdata  # type: ignore
        probe("environment", "import xtquant.xtdata", lambda: {"path": getattr(xtquant, "__file__", "")})
    except Exception as exc:
        RESULTS.append({"category": "environment", "test": "import xtquant.xtdata", "status": classify(exc), "elapsed_ms": 0, "sample": "", "note": str(exc)})
        write_report(args.output_dir, args)
        return 2

    # Connection / runtime inventory.
    probe("connection", "get_instrument_detail(stock)", lambda: xtdata.get_instrument_detail(args.stock, True))
    periods = probe("inventory", "get_period_list", lambda: xtdata.get_period_list())

    # L1: exactly one returned bar/tick per tested period where count is supported.
    for period in ["1d", "1m", "5m", "15m", "30m", "1h", "1w", "1mon", "1q", "1hy", "1y", "tick"]:
        value = probe("l1_market", f"{period}: one sample", lambda p=period: one_market(xtdata, args.stock, p, start), note="count=1")
        if empty(value) and args.download and period in {"1d", "1m", "5m", "tick"}:
            # Minimal 7-calendar-day supplement window; read is still one sample.
            probe("l1_download", f"download {period} minimal window", lambda p=period: (xtdata.download_history_data(args.stock, period=p, start_time=start, end_time=""), {"requested": True})[1])
            probe("l1_market", f"{period}: one sample after download", lambda p=period: one_market(xtdata, args.stock, p, start), note="count=1")

    # Realtime: one symbol, one snapshot / one successful subscription.
    probe("realtime", "get_full_tick one symbol", lambda: first_sample(xtdata.get_full_tick([args.stock])))
    if hasattr(xtdata, "get_full_kline"):
        probe("realtime", "get_full_kline 1m one bar", lambda: xtdata.get_full_kline([], [args.stock], period="1m", count=1))
    else:
        skip("realtime", "get_full_kline", "API not present")
    probe("realtime", "subscribe_quote one acceptance", lambda: subscribe_once(xtdata, args.stock), validator=lambda x: isinstance(x, int) and x > 0)

    # Reference/static categories. API may internally return a list; report only first sample.
    probe("calendar", "get_holidays one sample", lambda: first_sample(xtdata.get_holidays()))
    probe("calendar", "get_trading_calendar one sample", lambda: first_sample(xtdata.get_trading_calendar("SH", start_time=start, end_time=today)))
    probe("calendar", "get_trading_dates one sample", lambda: first_sample(xtdata.get_trading_dates("SH", start_time=start, end_time=today, count=1)))

    if args.download:
        probe("metadata", "download_sector_data", lambda: (xtdata.download_sector_data(), {"requested": True})[1])
    sectors = probe("metadata", "get_sector_list one sample", lambda: first_sample(xtdata.get_sector_list()))
    if sectors:
        sector = sectors[0] if isinstance(sectors, list) else next(iter(sectors)) if isinstance(sectors, dict) else None
        if sector:
            probe("metadata", "get_stock_list_in_sector one sample", lambda: first_sample(xtdata.get_stock_list_in_sector(sector)))

    probe("corporate_action", "get_divid_factors one sample", lambda: first_sample(xtdata.get_divid_factors(args.stock, start_time="20200101", end_time=today)))

    # Financial: test each table separately; first valid sample is enough.
    financial_tables = ["Balance", "Income", "CashFlow", "Pershareindex"]
    if args.download:
        probe("financial", "download_financial_data minimal symbol", lambda: (xtdata.download_financial_data([args.stock], financial_tables), {"requested": True})[1])
    for table in financial_tables:
        probe("financial", f"{table}: one sample", lambda t=table: first_sample(xtdata.get_financial_data([args.stock], [t], start_time="20200101")))

    # IPO / ETF.
    probe("ipo", "get_ipo_info one sample", lambda: first_sample(xtdata.get_ipo_info("", "")))
    probe("etf", "ETF instrument detail one sample", lambda: xtdata.get_instrument_detail(args.etf, True))
    if hasattr(xtdata, "get_etf_info"):
        probe("etf", "get_etf_info one sample", lambda: first_sample(xtdata.get_etf_info()))
    else:
        skip("etf", "get_etf_info", "API not present")

    # Optional representative contracts: exactly one contract per category.
    if args.cb:
        probe("convertible_bond", "get_cb_info one contract", lambda: xtdata.get_cb_info(args.cb))
    else:
        skip("convertible_bond", "get_cb_info", "Pass --cb with one current valid convertible bond")

    if args.option_code:
        probe("option", "instrument detail one contract", lambda: xtdata.get_instrument_detail(args.option_code, True))
        if hasattr(xtdata, "get_option_detail_data"):
            probe("option", "option detail one contract", lambda: xtdata.get_option_detail_data(args.option_code))
        probe("option", "1d one bar", lambda: one_market(xtdata, args.option_code, "1d", start))
    else:
        skip("option", "option APIs", "Pass --option-code with one current valid option")

    if args.future_code:
        probe("future", "instrument detail one contract", lambda: xtdata.get_instrument_detail(args.future_code, True))
        probe("future", "1d one bar", lambda: one_market(xtdata, args.future_code, "1d", start))
    else:
        skip("future", "future APIs", "Pass --future-code with one current valid future")

    # L2: one record only. EMPTY outside trading hours remains inconclusive.
    for period in ["l2quote", "l2quoteaux", "l2order", "l2transaction", "l2orderqueue"]:
        probe("level2", f"{period}: one sample", lambda p=period: xtdata.get_market_data_ex(field_list=[], stock_list=[args.stock], period=p, count=1), note="count=1; EMPTY outside trading hours is inconclusive")

    # Special/research periods: inventory only here. Codex should perform one schema-appropriate
    # sample for each desired discovered category rather than blindly querying with an A-share code.
    known_special = [
        "transactioncount1m", "transactioncount1d", "specialtreatment", "dividendplaninfo",
        "stoppricedata", "snapshotindex", "northfinancechange1m", "northfinancechange1d",
        "warehousereceipt", "futureholderrank", "interactiveqa", "delistchangebond",
        "replacechangebond", "historycontract", "optionhistorycontract", "historymaincontract",
    ]
    period_set = set(periods or []) if isinstance(periods, (list, tuple, set)) else set()
    for p in known_special:
        if p in period_set:
            RESULTS.append({"category": "special_period", "test": p, "status": "NOT_TESTED", "elapsed_ms": 0, "sample": "runtime advertised", "note": "Use one schema-appropriate sample only"})

    write_report(args.output_dir, args)
    basic_fail = any(r["category"] in {"environment", "connection"} and r["status"] != "PASS" for r in RESULTS)
    return 2 if basic_fail else 0


def write_report(output_dir: str, args: argparse.Namespace) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "policy": "ONE_SAMPLE_PER_DATA_CATEGORY",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.version,
        "args": vars(args),
        "results": RESULTS,
    }
    path = out / f"qmt_api_minimal_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {path.resolve()}")
    print("Policy: one valid sample is sufficient for PASS; no bulk collection performed.")


if __name__ == "__main__":
    raise SystemExit(main())
