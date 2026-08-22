#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe xtquant.xtdata capabilities against a locally logged-in MiniQMT.

Run this on the Windows machine where MiniQMT is running. The script is read-only
except when --download is supplied, in which case it asks MiniQMT to supplement
small amounts of market/metadata/financial data for the test symbols.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class ProbeResult:
    name: str
    category: str
    status: str
    elapsed_ms: int
    summary: str = ""
    error: str = ""
    note: str = ""


RESULTS: list[ProbeResult] = []
DISCOVERED_PERIODS: list[str] = []


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, bytes)):
        return len(value) == 0
    if isinstance(value, (list, tuple, set, dict)):
        if len(value) == 0:
            return True
        if isinstance(value, dict):
            # Nested API results may contain a code mapped to an empty DataFrame.
            return all(is_empty(v) for v in value.values())
        return False
    empty = getattr(value, "empty", None)
    if isinstance(empty, bool):
        return empty
    try:
        return len(value) == 0
    except Exception:
        return False


def summarize(value: Any, limit: int = 600) -> str:
    try:
        if value is None:
            text = "None"
        elif isinstance(value, dict):
            keys = list(value.keys())
            text = f"dict(len={len(value)}, keys={keys[:12]})"
            # Add shape/length clues for the first few values.
            details = []
            for key in keys[:4]:
                val = value[key]
                shape = getattr(val, "shape", None)
                if shape is not None:
                    details.append(f"{key}:shape={shape}")
                else:
                    try:
                        details.append(f"{key}:len={len(val)}")
                    except Exception:
                        details.append(f"{key}:{type(val).__name__}")
            if details:
                text += " | " + ", ".join(details)
        elif isinstance(value, (list, tuple, set)):
            seq = list(value)
            text = f"{type(value).__name__}(len={len(seq)}, sample={seq[:12]})"
        else:
            shape = getattr(value, "shape", None)
            if shape is not None:
                text = f"{type(value).__name__}(shape={shape})"
            else:
                text = repr(value)
    except Exception as exc:
        text = f"<summary failed: {exc!r}>"
    return text[:limit]


def classify_exception(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    permission_words = [
        "no permission", "permission denied", "unauthorized", "forbidden",
        "权限", "无权限", "未授权", "level2", "level 2", "vip",
    ]
    unsupported_words = [
        "has no attribute", "not supported", "unsupported", "不支持",
        "不存在该接口", "unknown period", "invalid period",
    ]
    if any(word in text for word in permission_words):
        return "NO_PERMISSION"
    if any(word in text for word in unsupported_words):
        return "UNSUPPORTED"
    return "ERROR"


def record(
    name: str,
    category: str,
    status: str,
    started: float,
    value: Any = None,
    error: str = "",
    note: str = "",
) -> Any:
    result = ProbeResult(
        name=name,
        category=category,
        status=status,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        summary=summarize(value) if value is not None else "",
        error=error[:1000],
        note=note,
    )
    RESULTS.append(result)
    print(f"[{result.status:13}] {category:18} {name} - {result.summary or result.error or result.note}")
    return value


def probe(
    name: str,
    category: str,
    fn: Callable[[], Any],
    *,
    empty_status: str = "EMPTY",
    note: str = "",
    validator: Optional[Callable[[Any], bool]] = None,
) -> Any:
    started = time.perf_counter()
    try:
        value = fn()
        if validator is not None:
            ok = validator(value)
            status = "PASS" if ok else empty_status
        else:
            status = empty_status if is_empty(value) else "PASS"
        return record(name, category, status, started, value=value, note=note)
    except Exception as exc:
        return record(
            name,
            category,
            classify_exception(exc),
            started,
            error=f"{type(exc).__name__}: {exc}",
            note=note,
        )


def skip(name: str, category: str, note: str) -> None:
    started = time.perf_counter()
    record(name, category, "SKIP", started, note=note)


def download_history(xtdata: Any, code: str, period: str, start_date: str) -> Any:
    return xtdata.download_history_data(
        code,
        period=period,
        start_time=start_date,
        end_time="",
        incrementally=None,
    )


def market_data(xtdata: Any, code: str, period: str, start_date: str, count: int = 10) -> Any:
    return xtdata.get_market_data_ex(
        field_list=[],
        stock_list=[code],
        period=period,
        start_time=start_date,
        end_time="",
        count=count,
        dividend_type="none",
        fill_data=True,
    )


def subscribe_once(xtdata: Any, code: str, period: str = "tick") -> Any:
    seq = xtdata.subscribe_quote(code, period=period, count=0, callback=None)
    try:
        return seq
    finally:
        if isinstance(seq, int) and seq > 0 and hasattr(xtdata, "unsubscribe_quote"):
            xtdata.unsubscribe_quote(seq)


def option_detail(xtdata: Any, code: str) -> Any:
    return xtdata.get_option_detail_data(code)


def generate_markdown(meta: dict[str, Any], results: list[ProbeResult]) -> str:
    lines = [
        "# MiniQMT Python API capability report",
        "",
        f"- Generated: `{meta['generated_at']}`",
        f"- Host: `{meta['platform']}`",
        f"- Python: `{meta['python']}`",
        f"- Stock: `{meta['args']['stock']}`",
        f"- Download mode: `{meta['args']['download']}`",
        "",
        "## Status meaning",
        "",
        "- **PASS**: API returned a non-empty/valid result, or a subscription id > 0.",
        "- **EMPTY**: call succeeded but returned no data. This is not automatically a permission failure.",
        "- **NO_PERMISSION**: exception text strongly indicates an entitlement/permission problem.",
        "- **UNSUPPORTED**: current xtquant version does not expose/support the API/period.",
        "- **ERROR**: unexpected error; inspect MiniQMT state, parameters and versions.",
        "- **SKIP**: intentionally not tested (usually missing an appropriate contract code).",
        "",
        "## Discovered periods",
        "",
        "`" + ", ".join(meta.get("discovered_periods", [])) + "`",
        "",
        "## Capability matrix",
        "",
        "| Category | Test | Status | ms | Summary / error |",
        "|---|---|---:|---:|---|",
    ]
    for item in results:
        detail = item.summary or item.error or item.note
        detail = detail.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {item.category} | {item.name} | **{item.status}** | {item.elapsed_ms} | {detail} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation notes",
            "",
            "1. MiniQMT must be running and logged in on the same machine for connection-dependent calls.",
            "2. Historical Level 1 data may require a prior download. Re-run with `--download` when an L1 test is EMPTY.",
            "3. Level 2 is real-time oriented and permission-sensitive. EMPTY outside trading hours is inconclusive; rerun during a trading session.",
            "4. `get_period_list()` is the strongest runtime inventory of periods exposed by the installed xtquant/MiniQMT combination.",
            "5. Do not infer that a discovered period is licensed until a representative call returns usable data.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe MiniQMT xtdata API capabilities")
    parser.add_argument("--stock", default="000001.SZ", help="A-share test code")
    parser.add_argument("--etf", default="510300.SH", help="ETF test code")
    parser.add_argument("--cb", default="", help="Convertible bond test code (optional)")
    parser.add_argument("--option-code", default="", help="Current valid option contract (optional)")
    parser.add_argument("--future-code", default="", help="Current valid futures contract (optional)")
    parser.add_argument("--days", type=int, default=45, help="History download lookback days")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Allow small metadata/history/financial supplement downloads",
    )
    parser.add_argument("--output-dir", default="reports", help="Report output directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    start_date = (datetime.now() - timedelta(days=max(args.days, 7))).strftime("%Y%m%d")
    today = datetime.now().strftime("%Y%m%d")

    # Import test is separate so a missing xtquant creates a useful report instead of a traceback.
    started = time.perf_counter()
    try:
        import xtquant  # type: ignore
        from xtquant import xtdata  # type: ignore
        import_value = {
            "xtquant_file": getattr(xtquant, "__file__", ""),
            "xtquant_version": getattr(xtquant, "__version__", "unknown"),
        }
        record("import xtquant.xtdata", "environment", "PASS", started, value=import_value)
    except Exception as exc:
        record(
            "import xtquant.xtdata",
            "environment",
            classify_exception(exc),
            started,
            error=f"{type(exc).__name__}: {exc}",
        )
        meta = {
            "generated_at": generated_at,
            "python": sys.version,
            "platform": platform.platform(),
            "args": vars(args),
            "discovered_periods": [],
        }
        return write_reports(meta, args.output_dir)

    # Connection/base contract tests.
    probe(
        "get_instrument_detail(stock)",
        "connection",
        lambda: xtdata.get_instrument_detail(args.stock, True),
        note="A non-empty contract dictionary is a strong basic connection test.",
    )

    periods = probe("get_period_list", "inventory", lambda: xtdata.get_period_list())
    if isinstance(periods, (list, tuple)):
        DISCOVERED_PERIODS.extend(str(p) for p in periods)

    # Calendar and static information.
    probe("get_holidays", "calendar", lambda: xtdata.get_holidays())
    probe(
        "get_trading_calendar(SH)",
        "calendar",
        lambda: xtdata.get_trading_calendar("SH", start_time=start_date, end_time=today),
    )
    probe(
        "get_trading_dates(SH)",
        "calendar",
        lambda: xtdata.get_trading_dates("SH", start_time=start_date, end_time=today, count=-1),
    )

    if args.download:
        probe(
            "download_sector_data",
            "metadata",
            lambda: (xtdata.download_sector_data(), {"downloaded": True})[1],
            empty_status="PASS",
        )
    sectors = probe("get_sector_list", "metadata", lambda: xtdata.get_sector_list())
    if isinstance(sectors, list) and sectors:
        preferred = next(
            (s for s in sectors if s in {"沪深A股", "沪深京A股", "上证A股", "深证A股"}),
            sectors[0],
        )
        probe(
            f"get_stock_list_in_sector({preferred})",
            "metadata",
            lambda sector=preferred: xtdata.get_stock_list_in_sector(sector),
        )

    # Level 1 historical market data.
    for period in ("1d", "1m", "5m"):
        if args.download:
            probe(
                f"download_history_data({period})",
                "l1_history",
                lambda p=period: (download_history(xtdata, args.stock, p, start_date), {"downloaded": p})[1],
                empty_status="PASS",
            )
        probe(
            f"get_market_data_ex({period})",
            "l1_history",
            lambda p=period: market_data(xtdata, args.stock, p, start_date),
            note="If EMPTY, rerun with --download before treating this as unavailable.",
        )

    # Derived/higher periods; 1d download above is usually sufficient as local source.
    for period in ("15m", "30m", "1h", "1w", "1mon", "1q", "1hy", "1y"):
        probe(
            f"get_market_data_ex({period})",
            "l1_periods",
            lambda p=period: market_data(xtdata, args.stock, p, start_date, count=5),
            note="Some periods are synthesized from base periods; EMPTY can mean missing local base data.",
        )

    # Tick, snapshot and subscription.
    probe(
        "get_market_data_ex(tick)",
        "l1_tick",
        lambda: market_data(xtdata, args.stock, "tick", start_date, count=10),
        note="Historical tick availability depends on locally cached/downloaded data.",
    )
    probe("get_full_tick(stock)", "realtime", lambda: xtdata.get_full_tick([args.stock]))
    if hasattr(xtdata, "get_full_kline"):
        probe(
            "get_full_kline(1m)",
            "realtime",
            lambda: xtdata.get_full_kline([], [args.stock], period="1m", count=1),
        )
    else:
        skip("get_full_kline(1m)", "realtime", "API not present in this xtquant version")
    probe(
        "subscribe_quote(tick)",
        "realtime",
        lambda: subscribe_once(xtdata, args.stock, "tick"),
        validator=lambda seq: isinstance(seq, int) and seq > 0,
        empty_status="ERROR",
        note="A subscription id > 0 proves subscription acceptance; it does not prove a live callback while market is closed.",
    )

    # Corporate actions and finance.
    probe(
        "get_divid_factors",
        "corporate_action",
        lambda: xtdata.get_divid_factors(args.stock, start_time="20200101", end_time=today),
    )
    if args.download:
        probe(
            "download_financial_data",
            "financial",
            lambda: (
                xtdata.download_financial_data(
                    [args.stock], ["Balance", "Income", "CashFlow", "Pershareindex"]
                ),
                {"downloaded": True},
            )[1],
            empty_status="PASS",
        )
    probe(
        "get_financial_data",
        "financial",
        lambda: xtdata.get_financial_data(
            [args.stock], ["Balance", "Income", "CashFlow", "Pershareindex"], start_time="20200101"
        ),
        note="If EMPTY, rerun with --download.",
    )

    # Other market/reference datasets.
    probe("get_ipo_info", "ipo", lambda: xtdata.get_ipo_info("", ""))
    if args.download and hasattr(xtdata, "download_etf_info"):
        probe(
            "download_etf_info",
            "etf",
            lambda: (xtdata.download_etf_info(), {"downloaded": True})[1],
            empty_status="PASS",
        )
    if hasattr(xtdata, "get_etf_info"):
        probe("get_etf_info", "etf", lambda: xtdata.get_etf_info())
    else:
        skip("get_etf_info", "etf", "API not present in this xtquant version")
    probe("get_instrument_detail(etf)", "etf", lambda: xtdata.get_instrument_detail(args.etf, True))

    if args.cb:
        if args.download and hasattr(xtdata, "download_cb_data"):
            probe(
                "download_cb_data",
                "convertible_bond",
                lambda: (xtdata.download_cb_data(), {"downloaded": True})[1],
                empty_status="PASS",
            )
        probe("get_cb_info", "convertible_bond", lambda: xtdata.get_cb_info(args.cb))
    else:
        skip("get_cb_info", "convertible_bond", "Pass --cb with a current convertible-bond code")

    if args.option_code:
        probe(
            "get_instrument_detail(option)",
            "option",
            lambda: xtdata.get_instrument_detail(args.option_code, True),
        )
        if hasattr(xtdata, "get_option_detail_data"):
            probe("get_option_detail_data", "option", lambda: option_detail(xtdata, args.option_code))
        probe(
            "get_market_data_ex(option,1d)",
            "option",
            lambda: market_data(xtdata, args.option_code, "1d", start_date, count=5),
        )
    else:
        skip("option APIs", "option", "Pass --option-code with a current valid option contract")

    if args.future_code:
        probe(
            "get_instrument_detail(future)",
            "future",
            lambda: xtdata.get_instrument_detail(args.future_code, True),
        )
        probe(
            "get_market_data_ex(future,1d)",
            "future",
            lambda: market_data(xtdata, args.future_code, "1d", start_date, count=5),
        )
    else:
        skip("futures APIs", "future", "Pass --future-code with a current valid futures contract")

    # Level 2: no historical persistence according to official docs. Outside trading hours,
    # EMPTY is explicitly inconclusive rather than NO_PERMISSION.
    for period in ("l2quote", "l2quoteaux", "l2order", "l2transaction", "l2orderqueue"):
        probe(
            f"get_market_data_ex({period})",
            "level2",
            lambda p=period: xtdata.get_market_data_ex(
                field_list=[], stock_list=[args.stock], period=p, count=10
            ),
            note="EMPTY outside trading hours is inconclusive. Re-run during an active session to verify entitlement.",
        )

    # Research/special periods: inventory first. Probe only safe stock-compatible examples
    # if the runtime explicitly advertises them.
    special_periods = [
        "transactioncount1m", "transactioncount1d", "specialtreatment",
        "dividendplaninfo", "stoppricedata", "snapshotindex",
        "northfinancechange1m", "northfinancechange1d",
        "warehousereceipt", "futureholderrank", "interactiveqa",
        "delistchangebond", "replacechangebond", "historycontract",
        "optionhistorycontract", "historymaincontract",
    ]
    for period in special_periods:
        if period in DISCOVERED_PERIODS:
            # We record discovery as INFO/PASS-like evidence but do not claim usable entitlement
            # without a suitable code/schema-specific request.
            started = time.perf_counter()
            record(
                f"period discovered: {period}",
                "special_periods",
                "PASS",
                started,
                value={"advertised": True},
                note="Runtime advertises the period; representative entitlement still needs a schema-appropriate probe.",
            )
        else:
            skip(
                f"period discovered: {period}",
                "special_periods",
                "Not returned by get_period_list() on this runtime",
            )

    meta = {
        "generated_at": generated_at,
        "python": sys.version,
        "platform": platform.platform(),
        "args": vars(args),
        "history_start": start_date,
        "discovered_periods": DISCOVERED_PERIODS,
    }
    return write_reports(meta, args.output_dir)


def write_reports(meta: dict[str, Any], output_dir: str) -> int:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output / f"qmt_api_probe_{stamp}.json"
    md_path = output / f"qmt_api_probe_{stamp}.md"

    payload = {
        "meta": meta,
        "results": [asdict(item) for item in RESULTS],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(generate_markdown(meta, RESULTS), encoding="utf-8")

    counts: dict[str, int] = {}
    for result in RESULTS:
        counts[result.status] = counts.get(result.status, 0) + 1
    print("\n=== Summary ===")
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    print(f"JSON report: {json_path.resolve()}")
    print(f"Markdown report: {md_path.resolve()}")

    # Non-zero only when the basic import/connection fails or there are unexpected errors.
    connection_failed = any(
        r.category in {"environment", "connection"} and r.status not in {"PASS"}
        for r in RESULTS
    )
    return 2 if connection_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
