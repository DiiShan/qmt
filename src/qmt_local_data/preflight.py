from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .atomic import atomic_write_json
from .config import DataConfig
from .errors import CapabilityGateError
from .models import utc_now
from .qmt_client import XtDataClient
from .transforms import normalize_market_data


@dataclass(frozen=True)
class CapabilityResult:
    name: str
    status: str
    sample_code: str | None
    rows: int
    fields: list[str]
    detail: str


@dataclass
class PreflightReport:
    generated_at: str
    source_version: str | None
    download_history_contracts_requested: bool
    results: list[CapabilityResult]

    @property
    def gate_passed(self) -> bool:
        required = {
            "current_a_share_daily",
            "delisted_a_share_discovery",
            "delisted_a_share_daily",
            "expired_cffex_discovery",
            "expired_cffex_daily",
        }
        passed = {result.name for result in self.results if result.status == "PASS"}
        return required <= passed

    @property
    def current_universe_gate_passed(self) -> bool:
        """Reduced gate for an explicitly labelled survivorship-biased temporary database."""
        required = {
            "current_a_share_daily",
            "expired_cffex_discovery",
            "expired_cffex_daily",
        }
        passed = {result.name for result in self.results if result.status == "PASS"}
        return required <= passed

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "source_version": self.source_version,
            "download_history_contracts_requested": self.download_history_contracts_requested,
            "gate_passed": self.gate_passed,
            "results": [asdict(result) for result in self.results],
        }


class PreflightRunner:
    def __init__(self, config: DataConfig, client: XtDataClient) -> None:
        self.config = config
        self.client = client

    def _bar_result(self, name: str, code: str, asset: str, allow_download: bool) -> CapabilityResult:
        start = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
        try:
            raw = self.client.market_data([code], "1d", start=start, count=1)
            frame = normalize_market_data(raw, asset)
            if frame.empty and allow_download:
                self.client.download_market_data(code, "1d", start=self.config.project.history_start.strftime("%Y%m%d"))
                raw = self.client.market_data([code], "1d", start="", count=1)
                frame = normalize_market_data(raw, asset)
            status = "PASS" if not frame.empty else "EMPTY"
            return CapabilityResult(name, status, code, len(frame), list(frame.columns), "valid row required")
        except Exception as exc:
            return CapabilityResult(name, "ERROR", code, 0, [], f"{type(exc).__name__}: {exc}")

    def run(self, download_history_contracts: bool = False, allow_sample_download: bool = False) -> PreflightReport:
        results: list[CapabilityResult] = []
        current = self._bar_result("current_a_share_daily", "000001.SZ", "stock", allow_sample_download)
        results.append(current)

        if download_history_contracts:
            try:
                self.client.download_history_contracts(incrementally=True)
                results.append(CapabilityResult("download_history_contracts", "PASS", None, 0, [], "command completed"))
            except Exception as exc:
                results.append(
                    CapabilityResult("download_history_contracts", "ERROR", None, 0, [], f"{type(exc).__name__}: {exc}")
                )

        try:
            delisted, expired = self.client.discover_historical_candidates(self.config.futures.products)
        except Exception as exc:
            delisted, expired = [], []
            results.append(CapabilityResult("historical_discovery", "ERROR", None, 0, [], f"{type(exc).__name__}: {exc}"))

        results.append(
            CapabilityResult(
                "delisted_a_share_discovery",
                "PASS" if delisted else "EMPTY",
                delisted[0] if delisted else None,
                len(delisted),
                [],
                "runtime-discovered only",
            )
        )
        if delisted:
            results.append(self._bar_result("delisted_a_share_daily", delisted[0], "stock", allow_sample_download))
        else:
            results.append(CapabilityResult("delisted_a_share_daily", "BLOCKED", None, 0, [], "no candidate"))

        results.append(
            CapabilityResult(
                "expired_cffex_discovery",
                "PASS" if expired else "EMPTY",
                expired[0] if expired else None,
                len(expired),
                [],
                "runtime-discovered only",
            )
        )
        if expired:
            future_result = self._bar_result("expired_cffex_daily", expired[0], "future", allow_sample_download)
            required = {"settlement", "open_interest", "volume"}
            if future_result.status == "PASS" and not required <= set(future_result.fields):
                future_result = CapabilityResult(
                    future_result.name,
                    "ERROR",
                    future_result.sample_code,
                    future_result.rows,
                    future_result.fields,
                    f"missing fields: {sorted(required - set(future_result.fields))}",
                )
            results.append(future_result)
        else:
            results.append(CapabilityResult("expired_cffex_daily", "BLOCKED", None, 0, [], "no candidate"))

        return PreflightReport(
            generated_at=utc_now(),
            source_version=self.client.source_version,
            download_history_contracts_requested=download_history_contracts,
            results=results,
        )

    def write(self, report: PreflightReport, output_dir: Path | None = None) -> tuple[Path, Path]:
        output_dir = output_dir or self.config.data_root / "metadata" / "preflight"
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = report.generated_at.replace(":", "").replace("+", "_")
        json_path = output_dir / f"preflight_{stamp}.json"
        markdown_path = output_dir / f"preflight_{stamp}.md"
        atomic_write_json(json_path, report.to_dict())
        lines = [
            "# QMT Database Preflight",
            "",
            f"- Generated: {report.generated_at}",
            f"- Source version: {report.source_version}",
            f"- Gate: {'PASS' if report.gate_passed else 'BLOCKED'}",
            "",
            "| Check | Status | Sample | Rows | Detail |",
            "|---|---|---|---:|---|",
        ]
        for item in report.results:
            detail = item.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {item.name} | {item.status} | {item.sample_code or ''} | {item.rows} | {detail} |")
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return json_path, markdown_path


def enforce_preflight(report: PreflightReport) -> None:
    if not report.gate_passed:
        raise CapabilityGateError("Phase 0 gate is BLOCKED; do not start full initialization")


def enforce_current_universe_preflight(report: PreflightReport) -> None:
    if not report.current_universe_gate_passed:
        raise CapabilityGateError(
            "Current-universe gate is BLOCKED; current stock and expired CFFEX samples must pass"
        )
