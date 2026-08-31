from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from .config import DataConfig
from .errors import CapabilityGateError
from .manifest import ManifestStore


OFFICIAL_XTDATA_REFERENCE = (
    "https://dict.thinktrader.net/nativeApi/code_examples.html?id=x3GDHP"
)


@dataclass(frozen=True)
class AdjustmentAuditResult:
    factors: pd.DataFrame
    evidence: tuple[dict[str, Any], ...]
    report: dict[str, Any]


def normalize_xtdata_dr_factors(
    raw: pd.DataFrame,
    first_valid_dates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build official XtData equal-ratio backward factors from event-level ``dr``.

    XtData's official example multiplies every event ``dr`` whose event date is
    not later than the quote date. A per-stock factor=1 baseline one calendar day
    before the first valid close makes that cumulative rule explicit and gives
    stocks without corporate actions full coverage.
    """
    required_raw = {"stock_code", "index", "dr"}
    required_first = {"stock_code", "first_valid_date"}
    if missing := required_raw - set(raw.columns):
        raise KeyError(f"corporate_action missing: {sorted(missing)}")
    if missing := required_first - set(first_valid_dates.columns):
        raise KeyError(f"first_valid_dates missing: {sorted(missing)}")

    first = first_valid_dates[list(required_first)].copy()
    first["first_valid_date"] = pd.to_datetime(
        first["first_valid_date"], errors="coerce"
    ).dt.date
    first = first.dropna().drop_duplicates("stock_code", keep="last")
    if first.empty:
        raise CapabilityGateError("No stocks have a valid positive close")

    events = raw.copy()
    events["event_date"] = pd.to_datetime(
        events["index"].astype(str).str.replace(r"\.0$", "", regex=True),
        format="%Y%m%d",
        errors="coerce",
    ).dt.date
    events["dr"] = pd.to_numeric(events["dr"], errors="coerce")
    if events["event_date"].isna().any():
        raise CapabilityGateError("Raw corporate_action contains invalid event dates")
    if events.duplicated(["stock_code", "event_date"]).any():
        duplicates = events.loc[
            events.duplicated(["stock_code", "event_date"], keep=False),
            ["stock_code", "event_date"],
        ]
        raise CapabilityGateError(
            f"Raw corporate_action contains duplicate stock/date events: {len(duplicates)} rows"
        )

    events = events.merge(first, on="stock_code", how="left", validate="many_to_one")
    events["inside_price_history"] = (
        events["first_valid_date"].notna()
        & (events["event_date"] >= events["first_valid_date"])
    )
    invalid_inside = events[
        events["inside_price_history"]
        & (~np.isfinite(events["dr"]) | events["dr"].le(0))
    ]
    if not invalid_inside.empty:
        sample = invalid_inside.iloc[0]
        raise CapabilityGateError(
            "Non-positive/invalid XtData dr occurs inside price history: "
            f"{sample['stock_code']}@{sample['event_date']} dr={sample['dr']}"
        )

    usable = events[events["inside_price_history"] & events["dr"].gt(0)].copy()
    usable = usable.sort_values(["stock_code", "event_date"])
    usable["factor"] = usable.groupby("stock_code", sort=False)["dr"].cumprod()
    if (~np.isfinite(usable["factor"]) | usable["factor"].le(0)).any():
        raise CapabilityGateError("Cumulative XtData factors contain non-finite/non-positive values")

    baseline = first.rename(columns={"first_valid_date": "trade_date"}).copy()
    baseline["trade_date"] = baseline["trade_date"].map(lambda value: value - timedelta(days=1))
    baseline["factor"] = 1.0
    factor_events = usable[["event_date", "stock_code", "factor"]].rename(
        columns={"event_date": "trade_date"}
    )
    factors = pd.concat(
        [baseline[["trade_date", "stock_code", "factor"]], factor_events],
        ignore_index=True,
    ).sort_values(["stock_code", "trade_date"])
    if factors.duplicated(["trade_date", "stock_code"]).any():
        raise CapabilityGateError("Normalized adjust_factor contains duplicate business keys")
    return factors.reset_index(drop=True), usable.reset_index(drop=True), events.reset_index(drop=True)


def _event_evidence(
    usable_events: pd.DataFrame,
    bars: pd.DataFrame,
    minimum_cases: int = 3,
) -> list[dict[str, Any]]:
    candidates = usable_events[usable_events["dr"] >= 1.20].sort_values(
        ["dr", "event_date"], ascending=[False, True]
    )
    cases: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        stock_bars = bars[bars["stock_code"] == event.stock_code]
        before = stock_bars[stock_bars["trade_date"] < event.event_date].tail(1)
        after = stock_bars[stock_bars["trade_date"] >= event.event_date].head(1)
        if before.empty or after.empty:
            continue
        previous = before.iloc[0]
        current = after.iloc[0]
        if current["trade_date"] != event.event_date:
            continue
        raw_return = float(current["close"] / previous["close"] - 1.0)
        adjusted_return = float(current["close"] * event.dr / previous["close"] - 1.0)
        if not (
            abs(raw_return) >= 0.20
            and abs(adjusted_return) <= 0.15
            and abs(adjusted_return) < abs(raw_return)
        ):
            continue
        cases.append(
            {
                "case": f"{event.stock_code}@{event.event_date.isoformat()}",
                "case_type": "CORPORATE_ACTION",
                "status": "PASS",
                "stock_code": event.stock_code,
                "event_date": event.event_date.isoformat(),
                "previous_trade_date": previous["trade_date"].isoformat(),
                "applied_trade_date": current["trade_date"].isoformat(),
                "dr": float(event.dr),
                "raw_return": raw_return,
                "adjusted_return": adjusted_return,
                "absolute_gap_reduction": abs(raw_return) - abs(adjusted_return),
            }
        )
        if len(cases) >= minimum_cases:
            return cases
    raise CapabilityGateError(
        f"Only {len(cases)} real corporate-action continuity cases passed; {minimum_cases} required"
    )


def _no_event_evidence(
    usable_events: pd.DataFrame,
    bars: pd.DataFrame,
    factors: pd.DataFrame,
    minimum_bars: int = 20,
) -> dict[str, Any]:
    for stock_code in bars["stock_code"].drop_duplicates():
        stock_bars = bars[bars["stock_code"] == stock_code].tail(minimum_bars).copy()
        if len(stock_bars) < minimum_bars:
            continue
        start = stock_bars["trade_date"].iloc[0]
        end = stock_bars["trade_date"].iloc[-1]
        events = usable_events[
            (usable_events["stock_code"] == stock_code)
            & (usable_events["event_date"] > start)
            & (usable_events["event_date"] <= end)
        ]
        if not events.empty:
            continue
        stock_factors = factors[factors["stock_code"] == stock_code].sort_values("trade_date")
        merge_bars = stock_bars.copy()
        merge_factors = stock_factors.copy()
        merge_bars["trade_date"] = pd.to_datetime(merge_bars["trade_date"])
        merge_factors["trade_date"] = pd.to_datetime(merge_factors["trade_date"])
        merged = pd.merge_asof(
            merge_bars.sort_values("trade_date"),
            merge_factors.sort_values("trade_date"),
            on="trade_date",
            direction="backward",
        )
        raw_returns = merged["close"].pct_change(fill_method=None)
        adjusted_returns = (merged["close"] * merged["factor"]).pct_change(fill_method=None)
        max_difference = float((raw_returns - adjusted_returns).abs().dropna().max())
        if max_difference <= 1e-12:
            return {
                "case": f"{stock_code}@{start.isoformat()}..{end.isoformat()}",
                "case_type": "NO_EVENT",
                "status": "PASS",
                "stock_code": stock_code,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "valid_bar_count": int(len(stock_bars)),
                "event_count": 0,
                "max_abs_return_difference": max_difference,
            }
    raise CapabilityGateError("No 20-valid-bar no-event continuity case could be established")


def audit_xtdata_adjustment_factors(
    config: DataConfig,
    *,
    factor_version: str,
) -> AdjustmentAuditResult:
    store = ManifestStore(config.data_root, config.project.compression)
    raw_manifest = store.load_active("raw", "corporate_action")
    if raw_manifest is None:
        raise FileNotFoundError("No active raw/corporate_action manifest")
    raw = store.read_active_frame(
        "raw", "corporate_action", ["stock_code", "index"]
    )
    database_path = config.data_root / "database" / "qmt.duckdb"
    if not database_path.exists():
        raise FileNotFoundError(f"DuckDB catalog does not exist: {database_path}")
    with duckdb.connect(str(database_path), read_only=True) as connection:
        first_valid = connection.execute(
            "SELECT stock_code, MIN(trade_date) AS first_valid_date "
            "FROM daily_bar WHERE close > 0 GROUP BY stock_code"
        ).fetchdf()

    factors, usable_events, classified_events = normalize_xtdata_dr_factors(raw, first_valid)
    candidate_codes = (
        usable_events[usable_events["dr"] >= 1.20]
        .sort_values("dr", ascending=False)["stock_code"]
        .drop_duplicates()
        .head(200)
        .tolist()
    )
    if not candidate_codes:
        raise CapabilityGateError("No material real corporate-action candidates were found")
    placeholders = ", ".join("?" for _ in candidate_codes)
    with duckdb.connect(str(database_path), read_only=True) as connection:
        bars = connection.execute(
            "SELECT trade_date, stock_code, close FROM daily_bar "
            f"WHERE stock_code IN ({placeholders}) AND close > 0 "
            "AND COALESCE(volume, 0) > 0 AND COALESCE(suspend_flag, 1) = 0 "
            "ORDER BY stock_code, trade_date",
            candidate_codes,
        ).fetchdf()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="coerce").dt.date

    event_cases = _event_evidence(usable_events, bars)
    no_event_case = _no_event_evidence(usable_events, bars, factors)
    evidence = tuple([*event_cases, no_event_case])
    ignored = classified_events[~classified_events["inside_price_history"]]
    report = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": "PASS",
        "factor_version": factor_version,
        "official_xtdata_reference": OFFICIAL_XTDATA_REFERENCE,
        "official_rule": "factor[t] = cumulative product of event dr where event_date <= t",
        "raw_manifest_run_id": raw_manifest.run_id,
        "raw_event_row_count": int(len(raw)),
        "raw_stock_count": int(raw["stock_code"].nunique()),
        "price_history_stock_count": int(first_valid["stock_code"].nunique()),
        "usable_event_row_count": int(len(usable_events)),
        "ignored_pre_price_history_event_count": int(len(ignored)),
        "normalized_factor_row_count": int(len(factors)),
        "normalized_factor_min": float(factors["factor"].min()),
        "normalized_factor_max": float(factors["factor"].max()),
        "business_key_duplicate_count": int(
            factors.duplicated(["trade_date", "stock_code"]).sum()
        ),
        "validation_evidence": list(evidence),
    }
    return AdjustmentAuditResult(factors, evidence, report)
