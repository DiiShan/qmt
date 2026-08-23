from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from itertools import islice
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from .atomic import atomic_write_json
from .catalog import CatalogBuilder
from .checkpoint import CheckpointStore
from .config import DataConfig
from .derived import build_main_contract_mapping, calculate_future_basis
from .manifest import ManifestStore
from .qmt_client import XtDataClient
from .quality import (
    enforce_quality,
    validate_daily_bars,
    validate_financial,
    validate_security_master,
)
from .storage_guard import StorageGuard
from .transforms import (
    assign_financial_availability,
    flatten_financial_data,
    flatten_market_data,
    iter_historical_universe,
    normalize_instrument_details,
    normalize_market_data,
    normalize_trading_dates,
)


def batched(values: Iterable[str], size: int) -> Iterator[list[str]]:
    iterator = iter(values)
    while batch := list(islice(iterator, size)):
        yield batch


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class BatchResult:
    batch_id: str
    codes: tuple[str, ...]
    raw_run_id: str
    processed_run_id: str
    rows: int


class DatabaseBuilder:
    def __init__(
        self,
        config: DataConfig,
        client: XtDataClient,
        universe_scope: str = "FULL_HISTORY",
    ) -> None:
        if universe_scope not in {"FULL_HISTORY", "CURRENT_UNIVERSE_ONLY"}:
            raise ValueError(f"Unsupported universe scope: {universe_scope}")
        self.config = config
        self.client = client
        self.universe_scope = universe_scope
        cache_path = config.storage.qmt_cache_path or getattr(client, "data_dir", None)
        storage_config = replace(config.storage, qmt_cache_path=cache_path)
        self.storage = StorageGuard(config.data_root, storage_config)
        self.store = ManifestStore(config.data_root, config.project.compression, self.storage)
        self.checkpoints = CheckpointStore(config.data_root)

    def build_trade_calendar(self, market: str, start: date, end: date) -> str:
        values = self.client.trading_dates(market, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        frame = normalize_trading_dates(values, market)
        if frame.empty:
            raise ValueError(f"No trading dates returned for {market}")
        manifest = self.store.publish_frame(
            "processed",
            "trade_calendar",
            frame,
            "1.0",
            mode="append",
            date_column="trade_date",
            source_version=self.client.source_version,
        )
        return manifest.run_id

    def build_security_master(self, codes: Iterable[str], asset: str = "stock") -> str:
        details = self.client.instrument_details(codes)
        frame = normalize_instrument_details(details, asset=asset)
        if frame.empty:
            raise ValueError(f"No instrument details for {asset}")
        if asset == "stock":
            enforce_quality(validate_security_master(frame))
            dataset = "security_master"
        else:
            dataset = "future_contract_master"
        manifest = self.store.publish_frame(
            "processed",
            dataset,
            frame,
            "1.0",
            mode="append",
            source_version=self.client.source_version,
            metadata={"universe_scope": self.universe_scope} if asset == "stock" else {},
        )
        return manifest.run_id

    def ingest_market(
        self,
        codes: Iterable[str],
        asset: str,
        start: date,
        end: date,
        *,
        download: bool,
        resume: bool = True,
    ) -> list[BatchResult]:
        dataset = {"stock": "stock_daily", "index": "index_daily", "future": "future_daily"}[asset]
        code_column = {"stock": "stock_code", "index": "index_code", "future": "contract_code"}[asset]
        results: list[BatchResult] = []
        for index, batch in enumerate(batched(sorted(set(codes)), self.config.ingestion.initial_batch_size), start=1):
            payload = {
                "dataset": dataset,
                "codes": batch,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "period": "1d",
            }
            fingerprint = _fingerprint(payload)
            batch_id = f"{start:%Y%m%d}-{end:%Y%m%d}-{index:05d}"
            if resume and self.checkpoints.is_complete(dataset, batch_id, fingerprint):
                continue
            self.storage.enforce(estimated_batch_bytes=max(10 * 1024 * 1024, len(batch) * 256 * 1024))
            if download:
                for code in batch:
                    self.client.download_market_data(code, "1d", start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            raw = self.client.market_data(
                batch, "1d", start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"), count=-1
            )
            raw_frame = flatten_market_data(raw, code_column=code_column)
            if raw_frame.empty:
                raise ValueError(f"Empty market batch: {batch_id}")
            raw_manifest = self.store.publish_frame(
                "raw",
                dataset,
                raw_frame,
                "1.0",
                mode="append",
                requested_start=start.isoformat(),
                requested_end=end.isoformat(),
                source_version=self.client.source_version,
                metadata={
                    "batch_id": batch_id,
                    "codes": batch,
                    **({"universe_scope": self.universe_scope} if asset == "stock" else {}),
                },
            )
            processed = normalize_market_data(raw, asset)
            quality = validate_daily_bars(processed, code_column, dataset)
            enforce_quality(quality)
            processed_manifest = self.store.publish_frame(
                "processed",
                dataset,
                processed,
                "1.0",
                mode="append",
                input_runs=[raw_manifest.run_id],
                requested_start=start.isoformat(),
                requested_end=end.isoformat(),
                date_column="trade_date",
                source_version=self.client.source_version,
                metadata={
                    "batch_id": batch_id,
                    "quality": quality.to_dict(),
                    **({"universe_scope": self.universe_scope} if asset == "stock" else {}),
                },
            )
            self.storage.enforce(64 * 1024)
            self.checkpoints.mark_complete(
                dataset, batch_id, fingerprint, [raw_manifest.run_id, processed_manifest.run_id]
            )
            results.append(
                BatchResult(batch_id, tuple(batch), raw_manifest.run_id, processed_manifest.run_id, len(processed))
            )
        return results

    def ingest_financial(
        self,
        codes: Iterable[str],
        trading_calendar: pd.DataFrame,
        start: date,
        end: date,
        *,
        download: bool,
    ) -> list[str]:
        runs: list[str] = []
        for batch in batched(sorted(set(codes)), self.config.ingestion.initial_batch_size):
            if download:
                reserve = self.config.ingestion.financial_download_batch_reserve_mb * 1024 * 1024
                self.storage.enforce(reserve)
                self.client.download_financial(
                    batch,
                    list(self.config.financial.tables),
                    start.strftime("%Y%m%d"),
                    end.strftime("%Y%m%d"),
                )
                self.storage.enforce(0)
            raw = self.client.financial_data(
                batch,
                list(self.config.financial.tables),
                start.strftime("%Y%m%d"),
                end.strftime("%Y%m%d"),
                report_type="report_time",
            )
            raw_frame = flatten_financial_data(raw)
            if raw_frame.empty:
                continue
            raw_manifest = self.store.publish_frame(
                "raw",
                "financial",
                raw_frame,
                "1.0",
                mode="append",
                source_version=self.client.source_version,
                metadata={"universe_scope": self.universe_scope},
            )
            processed = assign_financial_availability(raw_frame, trading_calendar)
            quality = validate_financial(processed)
            enforce_quality(quality)
            manifest = self.store.publish_frame(
                "processed",
                "financial",
                processed,
                "1.0",
                mode="append",
                input_runs=[raw_manifest.run_id],
                date_column="report_period",
                source_version=self.client.source_version,
                metadata={"quality": quality.to_dict(), "universe_scope": self.universe_scope},
            )
            runs.append(manifest.run_id)
        return runs

    def ingest_dividend_factors(self, codes: Iterable[str], start: date, end: date) -> list[str]:
        runs: list[str] = []
        for code in sorted(set(codes)):
            value = self.client.dividend_factors(code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
            if frame.empty:
                continue
            if not isinstance(frame.index, pd.RangeIndex):
                frame = frame.reset_index()
            frame["stock_code"] = code
            manifest = self.store.publish_frame(
                "raw",
                "corporate_action",
                frame,
                "1.0",
                mode="append",
                source_version=self.client.source_version,
                metadata={
                    "normalization_status": "RAW_ONLY_PENDING_FACTOR_SEMANTICS_VALIDATION",
                    "universe_scope": self.universe_scope,
                },
            )
            runs.append(manifest.run_id)
        return runs

    def build_universe(self, name: str = "ALL_A") -> str:
        if self.universe_scope == "CURRENT_UNIVERSE_ONLY" and name == "ALL_A":
            raise ValueError("CURRENT_UNIVERSE_ONLY cannot publish a universe named ALL_A")
        master = self.store.read_active_frame("processed", "security_master", ["stock_code"])
        calendar = self.store.read_active_frame("processed", "trade_calendar", ["market", "trade_date"])
        last_manifest = None
        for index, universe in enumerate(iter_historical_universe(master, calendar, name=name), start=1):
            last_manifest = self.store.publish_frame(
                "derived",
                "historical_universe",
                universe,
                "1.0",
                mode="replace" if index == 1 else "append",
                date_column="trade_date",
                metadata={
                    "batch_index": index,
                    "universe_name": name,
                    "universe_scope": self.universe_scope,
                    "accepted_for_unbiased_backtest": self.universe_scope == "FULL_HISTORY",
                },
            )
        if last_manifest is None:
            raise ValueError("Historical universe is empty")
        return last_manifest.run_id

    def build_futures_derived(self) -> tuple[str, str]:
        future_daily = self.store.read_active_frame(
            "processed", "future_daily", ["trade_date", "contract_code"]
        )
        contract_master = self.store.read_active_frame(
            "processed", "future_contract_master", ["contract_code"]
        )
        calendar = self.store.read_active_frame("processed", "trade_calendar", ["market", "trade_date"])
        index_daily = self.store.read_active_frame("processed", "index_daily", ["trade_date", "index_code"])
        mapping = build_main_contract_mapping(
            future_daily, contract_master, calendar, self.config.futures.main_rule_version
        )
        if mapping.empty:
            raise ValueError("Main-contract mapping is empty")
        mapping_manifest = self.store.publish_frame(
            "derived", "future_main_mapping", mapping, "1.0", mode="replace", date_column="effective_trade_date"
        )
        basis = calculate_future_basis(
            future_daily,
            index_daily,
            contract_master,
            mapping,
            self.config.futures.spot_mapping,
        )
        basis_manifest = self.store.publish_frame(
            "derived",
            "future_basis_daily",
            basis,
            "1.0",
            mode="replace",
            date_column="trade_date",
            input_runs=[mapping_manifest.run_id],
        )
        return mapping_manifest.run_id, basis_manifest.run_id

    def refresh_catalog(self) -> list[str]:
        self.storage.enforce(16 * 1024 * 1024)
        created = CatalogBuilder(self.store, self.config.data_root / "database" / "qmt.duckdb").refresh()
        self.storage.enforce(0)
        return created

    def write_storage_audit(self) -> Path:
        self.storage.enforce(64 * 1024)
        snapshot = self.storage.snapshot()
        files = []
        for path in self.config.data_root.rglob("*") if self.config.data_root.exists() else []:
            if path.is_file():
                files.append((path.stat().st_size, path.relative_to(self.config.data_root).as_posix()))
        payload = snapshot.to_dict()
        payload["top_20_files"] = [
            {"path": path, "bytes": size} for size, path in sorted(files, reverse=True)[:20]
        ]
        output = self.config.data_root / "metadata" / "storage" / "latest.json"
        atomic_write_json(output, payload)
        return output
    def write_database_status(self, state: str, phase0_gate_passed: bool) -> Path:
        self.storage.enforce(64 * 1024)
        payload = {
            "schema_version": "1.0",
            "state": state,
            "universe_scope": self.universe_scope,
            "phase0_gate_passed": phase0_gate_passed,
            "accepted_for_unbiased_backtest": (
                self.universe_scope == "FULL_HISTORY" and phase0_gate_passed
            ),
            "updated_at": pd.Timestamp.now(tz=self.config.project.timezone).isoformat(),
        }
        output = self.config.data_root / "metadata" / "database_status.json"
        atomic_write_json(output, payload)
        return output


def load_database_status(data_root: Path) -> dict | None:
    path = data_root / "metadata" / "database_status.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("database_status.json must contain a JSON object")
    return value
