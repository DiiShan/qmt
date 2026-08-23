from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable

import pandas as pd

from .errors import QualityGateError


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    rule: str
    count: int
    detail: str


@dataclass
class QualityReport:
    dataset: str
    rows: int
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "ERROR"]

    def to_dict(self) -> dict:
        return {"dataset": self.dataset, "rows": self.rows, "issues": [asdict(issue) for issue in self.issues]}


def _require_columns(frame: pd.DataFrame, required: Iterable[str], report: QualityReport) -> bool:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        report.issues.append(QualityIssue("ERROR", "required_columns", len(missing), f"Missing: {missing}"))
        return False
    return True


def validate_daily_bars(frame: pd.DataFrame, code_column: str, dataset: str) -> QualityReport:
    report = QualityReport(dataset, len(frame))
    required = ["trade_date", code_column, "open", "high", "low", "close", "volume"]
    if not _require_columns(frame, required, report):
        return report
    duplicates = frame.duplicated(["trade_date", code_column]).sum()
    if duplicates:
        report.issues.append(QualityIssue("ERROR", "business_key_unique", int(duplicates), "Duplicate daily bars"))
    invalid_ohlc = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    ).sum()
    if invalid_ohlc:
        report.issues.append(QualityIssue("ERROR", "ohlc_bounds", int(invalid_ohlc), "Invalid OHLC relationship"))
    negative_volume = (frame["volume"] < 0).sum()
    if negative_volume:
        report.issues.append(QualityIssue("ERROR", "non_negative_volume", int(negative_volume), "Negative volume"))
    for optional in ["amount", "open_interest"]:
        if optional in frame.columns:
            count = (frame[optional] < 0).sum()
            if count:
                report.issues.append(QualityIssue("ERROR", f"non_negative_{optional}", int(count), f"Negative {optional}"))
    extreme = frame.groupby(code_column, sort=False)["close"].pct_change(fill_method=None).abs().gt(0.5).sum()
    if extreme:
        report.issues.append(QualityIssue("WARN", "extreme_close_return", int(extreme), "Absolute close return above 50%"))
    return report


def validate_security_master(frame: pd.DataFrame) -> QualityReport:
    report = QualityReport("security_master", len(frame))
    if not _require_columns(frame, ["stock_code", "list_date", "delist_date"], report):
        return report
    duplicates = frame.duplicated(["stock_code"]).sum()
    if duplicates:
        report.issues.append(QualityIssue("ERROR", "stock_code_unique", int(duplicates), "Duplicate security code"))
    invalid = (
        frame["list_date"].notna() & frame["delist_date"].notna() & (frame["delist_date"] < frame["list_date"])
    ).sum()
    if invalid:
        report.issues.append(QualityIssue("ERROR", "listing_interval", int(invalid), "delist_date before list_date"))
    return report


def validate_financial(frame: pd.DataFrame) -> QualityReport:
    report = QualityReport("financial", len(frame))
    if not _require_columns(frame, ["stock_code", "report_period", "announce_date", "available_date"], report):
        return report
    missing_announce = frame["announce_date"].isna().sum()
    if missing_announce:
        report.issues.append(
            QualityIssue("WARN", "announce_date_present", int(missing_announce), "Excluded from default PIT query")
        )
    leakage = (
        frame["available_date"].notna()
        & frame["announce_date"].notna()
        & (frame["available_date"] <= frame["announce_date"])
    ).sum()
    if leakage:
        report.issues.append(QualityIssue("ERROR", "pit_availability", int(leakage), "Availability is not after announce date"))
    return report


def enforce_quality(report: QualityReport) -> None:
    if report.errors:
        summary = "; ".join(f"{issue.rule}={issue.count}" for issue in report.errors)
        raise QualityGateError(f"{report.dataset} quality gate failed: {summary}")
