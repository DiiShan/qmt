from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from itertools import islice
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from .atomic import atomic_write_json
from .catalog import CatalogBuilder
from .checkpoint import CheckpointStore
from .config import DataConfig
from .derived import apply_adjustment_factor, build_main_contract_mapping, calculate_future_basis
from .errors import CapabilityGateError
from .manifest import ManifestStore
from .qmt_client import XtDataClient
from .quality import (
    enforce_quality,
    validate_daily_bars,
    validate_financial,
    validate_aggregate_volatility,
    validate_index_volatility,
    validate_security_master,
    validate_stock_volatility,
)
from .reference import (
    build_current_stock_snapshot,
    build_index_membership_snapshot,
    build_sector_membership_snapshot,
    load_official_sh_sz_stock_reference,
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
from .volatility import (
    calculate_index_volatility,
    calculate_market_volatility,
    calculate_stock_returns,
    calculate_stock_volatility,
)


def market_universe_names(universe_scope: str) -> tuple[str, str]:
    if universe_scope == "FULL_HISTORY":
        return "ALL_A", "SH_SZ_ALL_A"
    if universe_scope == "CURRENT_UNIVERSE_ONLY":
        return "CURRENT_SURVIVORS", "SH_SZ_CURRENT_SURVIVORS"
    raise ValueError(f"Unsupported universe scope: {universe_scope}")


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


@dataclass(frozen=True)
class VolatilityPrerequisites:
    universe_name: str
    universe_scope: str
    database_state: str
    factor_version: str
    sector_membership_dataset: str | None = None


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
        for batch_index, batch in enumerate(
            batched(sorted(set(codes)), self.config.ingestion.initial_batch_size), start=1
        ):
            frames: list[pd.DataFrame] = []
            included_codes: list[str] = []
            for code in batch:
                value = self.client.dividend_factors(
                    code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
                )
                frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
                if frame.empty:
                    continue
                if not isinstance(frame.index, pd.RangeIndex):
                    frame = frame.reset_index()
                frame["stock_code"] = code
                frames.append(frame)
                included_codes.append(code)
            if not frames:
                continue
            combined = pd.concat(frames, ignore_index=True, sort=False)
            manifest = self.store.publish_frame(
                "raw",
                "corporate_action",
                combined,
                "1.0",
                mode="append",
                source_version=self.client.source_version,
                metadata={
                    "batch_index": batch_index,
                    "codes": included_codes,
                    "code_count": len(included_codes),
                    "normalization_status": "RAW_ONLY_PENDING_FACTOR_SEMANTICS_VALIDATION",
                    "universe_scope": self.universe_scope,
                },
            )
            runs.append(manifest.run_id)
        return runs

    def publish_validated_adjust_factor(
        self,
        factors: pd.DataFrame,
        *,
        factor_version: str,
        validation_evidence: Iterable[dict],
    ) -> str:
        """Publish a normalized factor only after explicit, auditable validation."""
        evidence = list(validation_evidence)
        event_cases = [item for item in evidence if item.get("case_type") == "CORPORATE_ACTION"]
        no_event_cases = [item for item in evidence if item.get("case_type") == "NO_EVENT"]
        if (
            len(event_cases) < 3
            or not no_event_cases
            or any(str(item.get("status")) != "PASS" for item in evidence)
        ):
            raise CapabilityGateError(
                "Adjustment-factor validation requires three PASS corporate-action cases and one PASS no-event case"
            )
        required = {"trade_date", "stock_code", "factor"}
        if missing := required - set(factors.columns):
            raise KeyError(f"adjust_factor missing: {sorted(missing)}")
        normalized = factors[list(required)].copy()
        normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], errors="coerce").dt.date
        normalized["factor"] = pd.to_numeric(normalized["factor"], errors="coerce")
        invalid = normalized["trade_date"].isna() | normalized["factor"].isna() | normalized["factor"].le(0)
        if invalid.any() or normalized.duplicated(["trade_date", "stock_code"]).any():
            raise ValueError("Validated adjustment factors contain invalid dates/factors or duplicate keys")
        raw_manifest = self.store.load_active("raw", "corporate_action")
        if raw_manifest is None:
            raise FileNotFoundError("No active raw/corporate_action manifest")
        manifest = self.store.publish_frame(
            "derived",
            "adjust_factor",
            normalized,
            "1.0",
            mode="replace",
            input_runs=[raw_manifest.run_id],
            date_column="trade_date",
            config_hash=_fingerprint({"factor_version": factor_version, "evidence": evidence}),
            metadata={
                "normalization_status": "PRODUCTION_READY_VALIDATED_FACTOR",
                "factor_version": factor_version,
                "validation_evidence": evidence,
                "universe_scope": self.universe_scope,
            },
        )
        return manifest.run_id

    def update_reference_data(self, as_of: date) -> dict[str, str]:
        """Publish audited security lists and current membership snapshots.

        QMT's installed sector files are latest snapshots, not historical PIT files.  The
        membership datasets therefore retain ``OBSERVED_SNAPSHOT_ONLY`` metadata and must
        never be backfilled to dates before ``as_of``.
        """
        official_current, official_delisted = load_official_sh_sz_stock_reference(as_of)
        qmt_codes = self.client.discover_codes(
            self.config.markets.stock_sectors, self.config.markets.stock_suffixes
        )
        current = build_current_stock_snapshot(qmt_codes, official_current, as_of)
        official_delisted_codes = set(official_delisted["stock_code"])
        current = current[~current["stock_code"].isin(official_delisted_codes)].reset_index(drop=True)

        prior = self.store.read_active_frame("processed", "security_master", ["stock_code"])
        current = current.merge(
            prior[[column for column in prior.columns if not column.startswith("_")]],
            on="stock_code",
            how="left",
            suffixes=("", "_prior"),
        )
        for column in ("stock_name", "list_date", "exchange"):
            prior_column = f"{column}_prior"
            if prior_column in current:
                current[column] = current[column].replace("", pd.NA).fillna(current[prior_column])
        current = current[current["list_date"].notna()].reset_index(drop=True)
        current_list = current[
            ["as_of_date", "stock_code", "stock_name", "exchange", "list_date", "listing_status", "source"]
        ].copy()
        if current_list.duplicated(["as_of_date", "stock_code"]).any():
            raise ValueError("current_stock_list contains duplicate business keys")
        if current_list["list_date"].notna().any() and (
            current_list["list_date"].dropna() > as_of
        ).any():
            raise ValueError("current_stock_list contains a future list_date")
        if official_delisted["delist_date"].isna().any():
            raise ValueError("Official delisted_stock_list contains missing delist_date")
        invalid_interval = (
            official_delisted["list_date"].notna()
            & (official_delisted["delist_date"] < official_delisted["list_date"])
        )
        if invalid_interval.any():
            raise ValueError("Official delisted_stock_list contains delist_date before list_date")

        current_history = current_list
        if self.store.load_active("processed", "current_stock_list") is not None:
            previous_current = self.store.read_active_frame(
                "processed", "current_stock_list", ["as_of_date", "stock_code"]
            )
            previous_current = previous_current[
                pd.to_datetime(previous_current["as_of_date"]).dt.date != as_of
            ]
            previous_current = previous_current[
                [column for column in current_list.columns if column in previous_current.columns]
            ]
            current_history = pd.concat([previous_current, current_list], ignore_index=True)

        current_manifest = self.store.publish_frame(
            "processed",
            "current_stock_list",
            current_history,
            "1.0",
            mode="replace",
            date_column="as_of_date",
            source_version=self.client.source_version,
            metadata={
                "snapshot_quality": "OBSERVED_SNAPSHOT_ONLY",
                "sources": ["SSE_OFFICIAL", "SZSE_OFFICIAL", "QMT_CURRENT_SECTOR"],
                "includes_bj": True,
            },
        )
        delisted_manifest = self.store.publish_frame(
            "processed",
            "delisted_stock_list",
            official_delisted,
            "1.0",
            mode="replace",
            date_column="delist_date",
            source_version=self.client.source_version,
            metadata={
                "coverage": "SH_SZ_A_SHARE",
                "sources": ["SSE_OFFICIAL", "SZSE_OFFICIAL"],
                "bj_delisted_status": "SOURCE_UNAVAILABLE",
            },
        )

        master_columns = [
            "stock_code", "stock_name", "exchange", "security_type", "board",
            "list_date", "delist_date", "delist_date_quality", "listing_status",
            "reference_source", "reference_as_of_date",
        ]
        current_master = pd.DataFrame(
            {
                "stock_code": current["stock_code"],
                "stock_name": current["stock_name"],
                "exchange": current["exchange"],
                "security_type": (
                    current["security_type"].fillna("STOCK")
                    if "security_type" in current else "STOCK"
                ),
                "board": current["board"].fillna("UNKNOWN") if "board" in current else "UNKNOWN",
                "list_date": current["list_date"],
                "delist_date": pd.NaT,
                "delist_date_quality": "ACTIVE_REFERENCE",
                "listing_status": "CURRENT",
                "reference_source": current["source"],
                "reference_as_of_date": current["as_of_date"],
            }
        )
        delisted_master = official_delisted.rename(
            columns={"source": "reference_source", "as_of_date": "reference_as_of_date"}
        ).copy()
        delisted_master["security_type"] = "STOCK"
        delisted_master["board"] = "UNKNOWN"
        delisted_master["delist_date_quality"] = delisted_master["delist_date"].apply(
            lambda value: "OFFICIAL_EXCHANGE" if pd.notna(value) else "ACTIVE_OFFICIAL"
        )
        merged_master = pd.concat([current_master, delisted_master], ignore_index=True, sort=False)
        merged_master = merged_master.drop_duplicates("stock_code", keep="last")
        merged_master = merged_master[master_columns].sort_values("stock_code").reset_index(drop=True)
        enforce_quality(validate_security_master(merged_master))
        master_manifest = self.store.publish_frame(
            "processed",
            "security_master",
            merged_master,
            "1.1",
            mode="replace",
            input_runs=[current_manifest.run_id, delisted_manifest.run_id],
            source_version=self.client.source_version,
            metadata={
                "universe_scope": self.universe_scope,
                "reference_coverage": "SH_SZ_CURRENT_AND_DELISTED_PLUS_BJ_CURRENT",
                "accepted_for_unbiased_backtest": False,
            },
        )

        self.client.download_index_weights()
        index_weights = {
            code: self.client.index_weights(code) for code in self.config.volatility.index_names
        }
        index_snapshot = build_index_membership_snapshot(
            index_weights, self.config.volatility.index_names, as_of
        )
        expected_counts = {
            "000016.SH": 50,
            "000300.SH": 300,
            "000905.SH": 500,
            "000852.SH": 1000,
            "000688.SH": 50,
            "399006.SZ": 100,
        }
        actual_counts = index_snapshot.groupby("index_code")["stock_code"].nunique().to_dict()
        missing = {
            code: (expected, actual_counts.get(code, 0))
            for code, expected in expected_counts.items()
            if actual_counts.get(code, 0) != expected
        }
        if missing:
            raise ValueError(f"Index membership snapshot counts do not match contracts: {missing}")
        index_history = index_snapshot
        if self.store.load_active("processed", "index_membership_snapshot_daily") is not None:
            previous_index = self.store.read_active_frame(
                "processed",
                "index_membership_snapshot_daily",
                ["snapshot_date", "index_code", "stock_code"],
            )
            previous_index = previous_index[
                pd.to_datetime(previous_index["snapshot_date"]).dt.date != as_of
            ]
            previous_index = previous_index[
                [column for column in index_snapshot.columns if column in previous_index.columns]
            ]
            index_history = pd.concat([previous_index, index_snapshot], ignore_index=True)
        index_manifest = self.store.publish_frame(
            "processed",
            "index_membership_snapshot_daily",
            index_history,
            "1.0",
            mode="replace",
            date_column="snapshot_date",
            source_version=self.client.source_version,
            metadata={
                "membership_quality": "OBSERVED_SNAPSHOT_ONLY",
                "pit_available_from": as_of.isoformat(),
                "historical_backfill": "BLOCKED_SOURCE_UNAVAILABLE",
                "index_counts": actual_counts,
            },
        )

        sector_names = sorted(
            name for name in self.client.sector_list()
            if name.startswith("SW1") and not name.endswith("加权")
        )
        sector_members = {name: self.client.sector_codes(name) for name in sector_names}
        sector_snapshot = build_sector_membership_snapshot(sector_members, as_of)
        current_codes = set(current_list["stock_code"])
        sector_snapshot = sector_snapshot[
            sector_snapshot["stock_code"].isin(current_codes)
        ].reset_index(drop=True)
        if sector_snapshot.empty or sector_snapshot.duplicated(
            ["snapshot_date", "sector_type", "sector_code", "stock_code"]
        ).any():
            raise ValueError("Sector membership snapshot is empty or has duplicate business keys")
        sector_history = sector_snapshot
        if self.store.load_active("processed", "sector_membership_snapshot_daily") is not None:
            previous_sector = self.store.read_active_frame(
                "processed",
                "sector_membership_snapshot_daily",
                ["snapshot_date", "sector_type", "sector_code", "stock_code"],
            )
            previous_sector = previous_sector[
                pd.to_datetime(previous_sector["snapshot_date"]).dt.date != as_of
            ]
            previous_sector = previous_sector[
                [column for column in sector_snapshot.columns if column in previous_sector.columns]
            ]
            sector_history = pd.concat([previous_sector, sector_snapshot], ignore_index=True)
        sector_manifest = self.store.publish_frame(
            "processed",
            "sector_membership_snapshot_daily",
            sector_history,
            "1.0",
            mode="replace",
            date_column="snapshot_date",
            source_version=self.client.source_version,
            metadata={
                "membership_quality": "OBSERVED_SNAPSHOT_ONLY",
                "pit_available_from": as_of.isoformat(),
                "historical_backfill": "BLOCKED_SOURCE_UNAVAILABLE",
                "sector_type": "SW1",
                "sector_count": len(sector_names),
            },
        )
        return {
            "current_stock_list": current_manifest.run_id,
            "delisted_stock_list": delisted_manifest.run_id,
            "security_master": master_manifest.run_id,
            "index_membership_snapshot_daily": index_manifest.run_id,
            "sector_membership_snapshot_daily": sector_manifest.run_id,
        }

    def check_volatility_prerequisites(self, *, require_sector: bool = False) -> VolatilityPrerequisites:
        status = load_database_status(self.config.data_root)
        if status is None:
            raise CapabilityGateError("Database status is missing")
        state = str(status.get("state") or "")
        scope = str(status.get("universe_scope") or "")
        expected = f"READY_{scope}"
        if scope not in {"FULL_HISTORY", "CURRENT_UNIVERSE_ONLY"} or state != expected:
            raise CapabilityGateError(f"Database is not ready for volatility: state={state}, scope={scope}")
        if scope != self.universe_scope:
            raise CapabilityGateError(
                f"Builder/database universe scope mismatch: builder={self.universe_scope}, database={scope}"
            )
        universe_name = "ALL_A" if scope == "FULL_HISTORY" else "CURRENT_SURVIVORS"
        if scope == "FULL_HISTORY" and not bool(status.get("accepted_for_unbiased_backtest")):
            raise CapabilityGateError("FULL_HISTORY is not accepted for unbiased historical research")

        required_manifests = [
            ("processed", "stock_daily"),
            ("processed", "trade_calendar"),
            ("derived", "historical_universe"),
        ]
        for layer, dataset in required_manifests:
            if self.store.load_active(layer, dataset) is None:
                raise CapabilityGateError(f"Missing active prerequisite: {layer}/{dataset}")
        universe_manifest = self.store.load_active("derived", "historical_universe")
        if universe_manifest is None or universe_manifest.metadata.get("universe_name") != universe_name:
            raise CapabilityGateError(f"Historical universe is not published as {universe_name}")
        if universe_manifest.metadata.get("universe_scope") != scope:
            raise CapabilityGateError("Historical universe scope does not match database status")

        factor_manifest = self.store.load_active("derived", "adjust_factor")
        if factor_manifest is None:
            raw = self.store.load_active("raw", "corporate_action")
            raw_state = raw.metadata.get("normalization_status") if raw else "MISSING"
            raise CapabilityGateError(f"Validated adjust_factor is missing; raw status={raw_state}")
        if factor_manifest.metadata.get("normalization_status") != "PRODUCTION_READY_VALIDATED_FACTOR":
            raise CapabilityGateError("adjust_factor is not marked production-ready and validated")
        factor_version = str(factor_manifest.metadata.get("factor_version") or "")
        if not factor_version:
            raise CapabilityGateError("adjust_factor factor_version is missing")

        membership_dataset = None
        for candidate in ("sector_membership", "sector_membership_snapshot_daily"):
            membership = self.store.load_active("derived", candidate)
            quality = str(membership.metadata.get("membership_quality") or "") if membership else ""
            if membership and quality in {"PIT_VALIDATED", "DAILY_SNAPSHOT_VALIDATED"}:
                membership_dataset = candidate
                break
        if require_sector and membership_dataset is None:
            raise CapabilityGateError("Reliable PIT/snapshot sector membership is not available")
        return VolatilityPrerequisites(
            universe_name=universe_name,
            universe_scope=scope,
            database_state=state,
            factor_version=factor_version,
            sector_membership_dataset=membership_dataset,
        )

    def _volatility_calendar_bounds(self, start: date, end: date) -> tuple[date, list[date]]:
        calendar = self.store.read_active_frame(
            "processed", "trade_calendar", ["market", "trade_date"]
        )
        days = sorted(
            pd.Series(calendar.loc[calendar["is_open"].fillna(False), "trade_date"]).dropna().unique()
        )
        target_days = [day for day in days if start <= day <= end]
        if not target_days:
            raise ValueError(f"No market trading days in requested range: {start}..{end}")
        first_index = days.index(target_days[0])
        warmup = (
            max(self.config.volatility.windows)
            + max(self.config.volatility.percentile_windows)
            + self.config.volatility.warmup_safety_days
        )
        warmup_start = days[max(0, first_index - warmup)]
        return warmup_start, target_days

    def _calculate_stock_volatility_range(
        self,
        start: date,
        end: date,
        prerequisites: VolatilityPrerequisites,
    ) -> tuple[pd.DataFrame, pd.DataFrame, date]:
        warmup_start, _ = self._volatility_calendar_bounds(start, end)
        universe = self.store.read_active_frame(
            "derived",
            "historical_universe",
            ["universe_name", "trade_date", "stock_code"],
            columns=["trade_date", "stock_code", "universe_name", "eligible_flag"],
            date_column="trade_date",
            start=warmup_start,
            end=end,
        )
        universe = universe[universe["universe_name"] == prerequisites.universe_name]
        if universe.empty:
            raise ValueError(f"Historical universe is empty for {prerequisites.universe_name}")
        daily_columns = ["trade_date", "stock_code", "close", "suspend_flag", "volume"]
        daily = self.store.read_active_frame(
            "processed",
            "stock_daily",
            ["trade_date", "stock_code"],
            columns=daily_columns,
            date_column="trade_date",
            start=warmup_start,
            end=end,
        )
        anchors = self.store.read_active_latest_before(
            "processed",
            "stock_daily",
            business_key=["trade_date", "stock_code"],
            partition_by=["stock_code"],
            date_column="trade_date",
            before=warmup_start,
            columns=daily_columns,
            predicate="COALESCE(suspend_flag, 1) = 0 AND COALESCE(volume, 0) > 0 AND close > 0",
        )
        if not anchors.empty:
            anchors["trade_date"] = pd.to_datetime(anchors["trade_date"], errors="coerce").dt.date
        eligible_codes = set(universe["stock_code"])
        anchors = anchors[anchors["stock_code"].isin(eligible_codes)]
        if not anchors.empty:
            daily = pd.concat([anchors, daily], ignore_index=True)
            anchor_universe = anchors[["trade_date", "stock_code"]].copy()
            anchor_universe["universe_name"] = prerequisites.universe_name
            anchor_universe["eligible_flag"] = True
            universe = pd.concat([anchor_universe, universe], ignore_index=True)

        factors = self.store.read_active_frame(
            "derived",
            "adjust_factor",
            ["trade_date", "stock_code"],
            columns=["trade_date", "stock_code", "factor"],
            date_column="trade_date",
            end=end,
        )
        adjusted = apply_adjustment_factor(daily, factors, price_columns=("close",))
        eligible_daily = universe.merge(
            adjusted[["trade_date", "stock_code", "close", "close_adjusted"]],
            on=["trade_date", "stock_code"],
            how="left",
        )
        factor_denominator = eligible_daily["close"].notna() & eligible_daily["close"].gt(0)
        factor_coverage = (
            eligible_daily.loc[factor_denominator, "close_adjusted"].notna().mean()
            if factor_denominator.any()
            else 0.0
        )
        if factor_coverage < 0.99:
            raise CapabilityGateError(f"Validated factor coverage is too low: {factor_coverage:.4f}")

        returns = calculate_stock_returns(adjusted, universe)
        full = calculate_stock_volatility(returns, self.config.volatility)
        full = full[full["trade_date"] >= warmup_start].reset_index(drop=True)
        target = full[(full["trade_date"] >= start) & (full["trade_date"] <= end)].reset_index(drop=True)
        if target.empty:
            raise ValueError("Calculated stock_vol_daily target range is empty")
        return full, target, warmup_start

    def _publish_derived_range(
        self,
        dataset: str,
        frame: pd.DataFrame,
        business_key: list[str],
        *,
        start: date,
        end: date,
        rebuild_from: date | None,
        input_runs: Iterable[str],
        metadata: dict,
    ):
        active = self.store.load_active("derived", dataset)
        mode = "replace" if active is None or rebuild_from is not None else "append"
        publish = frame
        if active and rebuild_from is None and active.actual_max_date:
            active_max = date.fromisoformat(active.actual_max_date)
            if start <= active_max:
                raise ValueError(
                    f"{dataset} overlaps active data through {active_max}; use --rebuild-from"
                )
        if active and rebuild_from is not None:
            if active.actual_max_date and end < date.fromisoformat(active.actual_max_date):
                raise ValueError(
                    f"{dataset} rebuild end {end} is before active tail {active.actual_max_date}; "
                    "rebuild the complete affected tail"
                )
            prefix_end = rebuild_from - timedelta(days=1)
            prefix = self.store.read_active_frame(
                "derived",
                dataset,
                business_key,
                date_column="trade_date",
                end=prefix_end,
            )
            publish = pd.concat([prefix, frame], ignore_index=True, sort=False)
            publish = publish.sort_values("_ingested_at").drop_duplicates(business_key, keep="last") \
                if "_ingested_at" in publish.columns else publish.drop_duplicates(business_key, keep="last")
            removable = [column for column in ("source_run_id", "_ingested_at") if column in publish.columns]
            publish = publish.drop(columns=removable)
        return self.store.publish_frame(
            "derived",
            dataset,
            publish,
            "1.0",
            mode=mode,
            input_runs=input_runs,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            date_column="trade_date",
            config_hash=_fingerprint(asdict(self.config.volatility)),
            metadata=metadata,
        )

    def build_stock_volatility(
        self,
        start: date,
        end: date,
        *,
        rebuild_from: date | None = None,
    ) -> tuple[str, pd.DataFrame, date, VolatilityPrerequisites]:
        prerequisites = self.check_volatility_prerequisites()
        effective_start = rebuild_from or start
        full, target, warmup_start = self._calculate_stock_volatility_range(
            effective_start, end, prerequisites
        )
        quality = validate_stock_volatility(target, self.config.volatility.windows)
        enforce_quality(quality)
        inputs = [
            self.store.load_active(layer, dataset).run_id
            for layer, dataset in (
                ("processed", "stock_daily"),
                ("processed", "trade_calendar"),
                ("derived", "historical_universe"),
                ("derived", "adjust_factor"),
            )
        ]
        manifest = self._publish_derived_range(
            "stock_vol_daily",
            target,
            ["trade_date", "stock_code"],
            start=effective_start,
            end=end,
            rebuild_from=rebuild_from,
            input_runs=inputs,
            metadata={
                "universe_name": prerequisites.universe_name,
                "universe_scope": prerequisites.universe_scope,
                "factor_version": prerequisites.factor_version,
                "rule_version": "volatility_v1",
                "quality": quality.to_dict(),
                "warmup_start": warmup_start.isoformat(),
            },
        )
        return manifest.run_id, full, warmup_start, prerequisites

    def build_market_volatility(
        self,
        start: date,
        end: date,
        *,
        rebuild_from: date | None = None,
        stock_history: pd.DataFrame | None = None,
        warmup_start: date | None = None,
        prerequisites: VolatilityPrerequisites | None = None,
    ) -> str:
        prerequisites = prerequisites or self.check_volatility_prerequisites()
        effective_start = rebuild_from or start
        if warmup_start is None:
            warmup_start, _ = self._volatility_calendar_bounds(effective_start, end)
        if stock_history is None:
            if self.store.load_active("derived", "stock_vol_daily") is None:
                raise CapabilityGateError(
                    "stock_vol_daily must be published before market_vol_daily"
                )
            stock_history = self.store.read_active_frame(
                "derived",
                "stock_vol_daily",
                ["trade_date", "stock_code"],
                columns=[
                    "trade_date",
                    "stock_code",
                    "ret_1d",
                    "rv5",
                    "rv20",
                    "rv60",
                    "rv20_pct252",
                    "shock_z20",
                ],
                date_column="trade_date",
                start=warmup_start,
                end=end,
            )
        base_universe_name, sh_sz_universe_name = market_universe_names(
            prerequisites.universe_scope
        )
        required_universe_names = (base_universe_name, sh_sz_universe_name)
        active_market = self.store.load_active("derived", "market_vol_daily")
        if active_market is not None and rebuild_from is None:
            active_names = set(
                active_market.metadata.get("universe_names")
                or [active_market.metadata.get("universe_name")]
            )
            if not set(required_universe_names) <= active_names:
                raise ValueError(
                    "market_vol_daily lacks the SH/SZ market scope; use --rebuild-from to backfill it"
                )

        ewma_seeds: dict[str, float] = {}
        if active_market is not None:
            previous = self.store.read_active_latest_before(
                "derived",
                "market_vol_daily",
                business_key=["trade_date", "universe_name"],
                partition_by=["universe_name"],
                date_column="trade_date",
                before=warmup_start,
                columns=["trade_date", "universe_name", "dispersion_ewma20"],
            )
            ewma_seeds = {
                str(row.universe_name): float(row.dispersion_ewma20)
                for row in previous.itertuples(index=False)
                if pd.notna(row.dispersion_ewma20)
            }

        sh_sz_mask = stock_history["stock_code"].astype(str).str.endswith((".SH", ".SZ"))
        variants = (
            (base_universe_name, stock_history),
            (sh_sz_universe_name, stock_history.loc[sh_sz_mask].copy()),
        )
        full_frames: list[pd.DataFrame] = []
        for universe_name, history in variants:
            if history.empty:
                raise ValueError(f"No stock volatility rows are available for {universe_name}")
            full_frames.append(
                calculate_market_volatility(
                    history,
                    self.config.volatility,
                    universe_name=universe_name,
                    universe_scope=prerequisites.universe_scope,
                    ewma_seed=ewma_seeds.get(universe_name),
                )
            )
        full = pd.concat(full_frames, ignore_index=True).sort_values(
            ["trade_date", "universe_name"]
        )
        target = full[(full["trade_date"] >= effective_start) & (full["trade_date"] <= end)].reset_index(
            drop=True
        )
        if target.empty:
            raise ValueError("Calculated market_vol_daily target range is empty")
        quality = validate_aggregate_volatility(target, "market_vol_daily")
        enforce_quality(quality)
        stock_manifest = self.store.load_active("derived", "stock_vol_daily")
        universe_manifest = self.store.load_active("derived", "historical_universe")
        if stock_manifest is None:
            raise CapabilityGateError("stock_vol_daily must be published before market_vol_daily")
        manifest = self._publish_derived_range(
            "market_vol_daily",
            target,
            ["trade_date", "universe_name"],
            start=effective_start,
            end=end,
            rebuild_from=rebuild_from,
            input_runs=[stock_manifest.run_id, universe_manifest.run_id],
            metadata={
                "universe_name": base_universe_name,
                "universe_names": list(required_universe_names),
                "universe_scope": prerequisites.universe_scope,
                "factor_version": prerequisites.factor_version,
                "rule_version": "volatility_v1",
                "quality": quality.to_dict(),
                "warmup_start": warmup_start.isoformat(),
            },
        )
        return manifest.run_id

    def check_index_volatility_prerequisites(self) -> dict[str, str]:
        status = load_database_status(self.config.data_root)
        if status is None or not str(status.get("state") or "").startswith("READY_"):
            raise CapabilityGateError("Database is not ready for index volatility")
        for layer, dataset in (
            ("processed", "index_daily"),
            ("processed", "trade_calendar"),
        ):
            if self.store.load_active(layer, dataset) is None:
                raise CapabilityGateError(f"Missing active prerequisite: {layer}/{dataset}")
        index_names = self.config.volatility.index_names
        if not index_names:
            raise CapabilityGateError("volatility.index_universe is empty")
        missing_config = set(index_names) - set(self.config.markets.indexes)
        if missing_config:
            raise CapabilityGateError(
                f"Configured volatility indexes are missing from markets.indexes: {sorted(missing_config)}"
            )
        return index_names

    def _calculate_index_volatility_range(
        self,
        start: date,
        end: date,
    ) -> tuple[pd.DataFrame, pd.DataFrame, date]:
        index_names = self.check_index_volatility_prerequisites()
        warmup_start, _ = self._volatility_calendar_bounds(start, end)
        columns = ["trade_date", "index_code", "close", "volume"]
        daily = self.store.read_active_frame(
            "processed",
            "index_daily",
            ["trade_date", "index_code"],
            columns=columns,
            date_column="trade_date",
            start=warmup_start,
            end=end,
        )
        anchors = self.store.read_active_latest_before(
            "processed",
            "index_daily",
            business_key=["trade_date", "index_code"],
            partition_by=["index_code"],
            date_column="trade_date",
            before=warmup_start,
            columns=columns,
            predicate="close > 0 AND COALESCE(volume, 0) > 0",
        )
        if not anchors.empty:
            anchors["trade_date"] = pd.to_datetime(
                anchors["trade_date"], errors="coerce"
            ).dt.date
            daily = pd.concat([anchors, daily], ignore_index=True)
        calendar = self.store.read_active_frame(
            "processed",
            "trade_calendar",
            ["market", "trade_date"],
            columns=["market", "trade_date", "is_open"],
            date_column="trade_date",
            start=warmup_start,
            end=end,
        )
        open_dates = set(
            calendar.loc[
                (calendar["market"] == "SH") & calendar["is_open"].fillna(False),
                "trade_date",
            ]
        )
        if not anchors.empty:
            open_dates.update(anchors["trade_date"].dropna())
        daily = daily[daily["trade_date"].isin(open_dates)]
        full = calculate_index_volatility(
            daily,
            self.config.volatility,
            index_names=index_names,
        )
        target = full[
            (full["trade_date"] >= start) & (full["trade_date"] <= end)
        ].reset_index(drop=True)
        if target.empty:
            raise ValueError("Calculated index_vol_daily target range is empty")
        return full, target, warmup_start

    def build_index_volatility(
        self,
        start: date,
        end: date,
        *,
        rebuild_from: date | None = None,
    ) -> str:
        effective_start = rebuild_from or start
        _, target, warmup_start = self._calculate_index_volatility_range(
            effective_start, end
        )
        index_names = self.config.volatility.index_names
        quality = validate_index_volatility(
            target,
            self.config.volatility.windows,
            index_names,
        )
        enforce_quality(quality)
        inputs = [
            self.store.load_active(layer, dataset).run_id
            for layer, dataset in (
                ("processed", "index_daily"),
                ("processed", "trade_calendar"),
            )
        ]
        manifest = self._publish_derived_range(
            "index_vol_daily",
            target,
            ["trade_date", "index_code"],
            start=effective_start,
            end=end,
            rebuild_from=rebuild_from,
            input_runs=inputs,
            metadata={
                "index_codes": list(index_names),
                "index_names": index_names,
                "universe_scope": self.universe_scope,
                "price_basis": "official_index_close",
                "rule_version": "volatility_v1",
                "quality": quality.to_dict(),
                "warmup_start": warmup_start.isoformat(),
            },
        )
        return manifest.run_id

    def build_sector_volatility(self, *args, **kwargs) -> str:
        self.check_volatility_prerequisites(require_sector=True)
        raise CapabilityGateError("Sector publication remains disabled until a validated membership contract is registered")

    def build_volatility_derived(
        self,
        start: date,
        end: date,
        *,
        rebuild_from: date | None = None,
    ) -> tuple[str, str, str]:
        stock_run, stock_history, warmup_start, prerequisites = self.build_stock_volatility(
            start, end, rebuild_from=rebuild_from
        )
        market_run = self.build_market_volatility(
            start,
            end,
            rebuild_from=rebuild_from,
            stock_history=stock_history,
            warmup_start=warmup_start,
            prerequisites=prerequisites,
        )
        index_run = self.build_index_volatility(
            start,
            end,
            rebuild_from=rebuild_from,
        )
        return stock_run, market_run, index_run

    def build_universe(self, name: str = "ALL_A") -> str:
        if self.universe_scope == "CURRENT_UNIVERSE_ONLY" and name == "ALL_A":
            raise ValueError("CURRENT_UNIVERSE_ONLY cannot publish a universe named ALL_A")
        master = self.store.read_active_frame("processed", "security_master", ["stock_code"])
        if "listing_status" in master.columns:
            if name == "CURRENT_SURVIVORS":
                master = master[master["listing_status"].eq("CURRENT")]
            elif name == "ALL_A":
                master = master[master["listing_status"].isin(["CURRENT", "DELISTED"])]
        master = master[master["list_date"].notna()].reset_index(drop=True)
        calendar = self.store.read_active_frame("processed", "trade_calendar", ["market", "trade_date"])
        master_manifest = self.store.load_active("processed", "security_master")
        calendar_manifest = self.store.load_active("processed", "trade_calendar")
        last_manifest = None
        for index, universe in enumerate(iter_historical_universe(master, calendar, name=name), start=1):
            last_manifest = self.store.publish_frame(
                "derived",
                "historical_universe",
                universe,
                "1.0",
                mode="replace" if index == 1 else "append",
                input_runs=[master_manifest.run_id, calendar_manifest.run_id],
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
