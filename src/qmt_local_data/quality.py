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
    if "delist_date_quality" in frame.columns:
        ignored = frame["delist_date_quality"].eq("INVALID_SENTINEL_IGNORED").sum()
        if ignored:
            report.issues.append(
                QualityIssue(
                    "WARN",
                    "invalid_delist_sentinel_ignored",
                    int(ignored),
                    "Upstream expiry predates listing and was retained only as a quality flag",
                )
            )
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


def _count_outside(frame: pd.DataFrame, columns: Iterable[str], lower: float, upper: float) -> int:
    count = 0
    for column in columns:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        count += int(((values < lower) | (values > upper)).sum())
    return count


def validate_stock_volatility(
    frame: pd.DataFrame,
    windows: Iterable[int],
    source_returns: pd.DataFrame | None = None,
) -> QualityReport:
    report = QualityReport("stock_vol_daily", len(frame))
    windows = tuple(windows)
    required = [
        "trade_date",
        "stock_code",
        "ret_1d",
        "valid_return_flag",
        "rv5",
        "rv20",
        "rv60",
        *[f"valid_obs_{window}" for window in windows],
    ]
    if not _require_columns(frame, required, report):
        return report
    duplicates = frame.duplicated(["trade_date", "stock_code"]).sum()
    if duplicates:
        report.issues.append(
            QualityIssue("ERROR", "business_key_unique", int(duplicates), "Duplicate stock volatility rows")
        )
    invalid_return = (~frame["valid_return_flag"].fillna(False) & frame["ret_1d"].notna()).sum()
    if invalid_return:
        report.issues.append(
            QualityIssue("ERROR", "invalid_return_is_null", int(invalid_return), "Invalid trade has a return")
        )
    negative = 0
    for column in [name for name in frame.columns if name.startswith("rv") or name in {"up_rv20", "down_rv20"}]:
        if "_pct" in column or "_rv" in column or column in {"rv5_rv20", "rv20_rv60"}:
            continue
        negative += int((pd.to_numeric(frame[column], errors="coerce").dropna() < 0).sum())
    if negative:
        report.issues.append(QualityIssue("ERROR", "non_negative_rv", negative, "Negative realized volatility"))
    invalid_obs = 0
    for window in windows:
        column = f"valid_obs_{window}"
        values = pd.to_numeric(frame[column], errors="coerce")
        invalid_obs += int(((values < 0) | (values > window)).sum())
    if invalid_obs:
        report.issues.append(
            QualityIssue("ERROR", "valid_obs_bounds", invalid_obs, "valid_obs outside rolling window")
        )
    percentiles = [column for column in frame.columns if "_pct" in column]
    invalid_pct = _count_outside(frame, percentiles, 0, 1)
    if invalid_pct:
        report.issues.append(
            QualityIssue("ERROR", "percentile_bounds", invalid_pct, "Historical percentile outside [0,1]")
        )
    if source_returns is not None and {"trade_date", "stock_code", "valid_return_flag"} <= set(
        source_returns.columns
    ):
        invalid_keys = source_returns.loc[
            ~source_returns["valid_return_flag"].fillna(False), ["trade_date", "stock_code"]
        ]
        if not invalid_keys.empty:
            joined = invalid_keys.merge(
                frame[["trade_date", "stock_code", "ret_1d"]],
                on=["trade_date", "stock_code"],
                how="inner",
            )
            leaked = joined["ret_1d"].notna().sum()
            if leaked:
                report.issues.append(
                    QualityIssue("ERROR", "suspension_not_zero_filled", int(leaked), "Suspended return is non-null")
                )
    return report


def validate_index_volatility(
    frame: pd.DataFrame,
    windows: Iterable[int],
    expected_codes: Iterable[str],
) -> QualityReport:
    renamed = frame.rename(columns={"index_code": "stock_code"})
    report = validate_stock_volatility(renamed, windows)
    report.dataset = "index_vol_daily"
    if "index_code" not in frame.columns or "index_name" not in frame.columns:
        return report
    missing_codes = set(expected_codes) - set(frame["index_code"].dropna().astype(str))
    if missing_codes:
        report.issues.append(
            QualityIssue(
                "ERROR",
                "configured_index_coverage",
                len(missing_codes),
                f"Missing configured indexes: {sorted(missing_codes)}",
            )
        )
    missing_names = frame["index_name"].isna().sum()
    if missing_names:
        report.issues.append(
            QualityIssue("ERROR", "index_name_present", int(missing_names), "Index name is missing")
        )
    return report


def validate_aggregate_volatility(frame: pd.DataFrame, dataset: str) -> QualityReport:
    report = QualityReport(dataset, len(frame))
    key = ["trade_date", "universe_name"]
    if dataset == "sector_vol_daily":
        key = ["trade_date", "sector_type", "sector_code", "universe_name"]
    required = [*key, "eligible_stock_count", "valid_return_count", "coverage_ratio", "quality_status"]
    if not _require_columns(frame, required, report):
        return report
    duplicates = frame.duplicated(key).sum()
    if duplicates:
        report.issues.append(
            QualityIssue("ERROR", "business_key_unique", int(duplicates), f"Duplicate {dataset} rows")
        )
    bounded = [
        column
        for column in frame.columns
        if column == "coverage_ratio" or "breadth" in column or "_pct" in column
    ]
    invalid_bounded = _count_outside(frame, bounded, 0, 1)
    if invalid_bounded:
        report.issues.append(
            QualityIssue("ERROR", "bounded_metric_range", invalid_bounded, "Ratio/breadth/percentile outside [0,1]")
        )
    non_negative = [
        column
        for column in frame.columns
        if ("rv" in column or "dispersion" in column)
        and "ratio" not in column
        and "_pct" not in column
    ]
    negatives = sum(
        int((pd.to_numeric(frame[column], errors="coerce").dropna() < 0).sum())
        for column in non_negative
    )
    if negatives:
        report.issues.append(
            QualityIssue("ERROR", "non_negative_volatility", negatives, "Negative RV or dispersion")
        )
    invalid_counts = (
        (frame["eligible_stock_count"] < 0)
        | (frame["valid_return_count"] < 0)
        | (frame["valid_return_count"] > frame["eligible_stock_count"])
    ).sum()
    if invalid_counts:
        report.issues.append(
            QualityIssue("ERROR", "aggregate_counts", int(invalid_counts), "Invalid eligible/valid counts")
        )
    for window in (20, 60):
        column = f"implied_corr{window}"
        count_column = f"implied_corr{window}_stock_count"
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        severe = ((values < -1.05) | (values > 1.05)).sum()
        if severe:
            report.issues.append(
                QualityIssue("ERROR", "implied_correlation_range", int(severe), f"{column} outside tolerance")
            )
        if count_column in frame.columns:
            impossible = (frame[count_column] < 0).sum()
            if impossible:
                report.issues.append(
                    QualityIssue("ERROR", "correlation_stock_count", int(impossible), "Negative stock count")
                )
    return report


def enforce_quality(report: QualityReport) -> None:
    if report.errors:
        summary = "; ".join(f"{issue.rule}={issue.count}" for issue in report.errors)
        raise QualityGateError(f"{report.dataset} quality gate failed: {summary}")
