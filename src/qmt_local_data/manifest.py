from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .atomic import atomic_publish_directory, atomic_write_json, sha256_file
from .models import DatasetManifest, FileRecord, RunStatus, utc_now

PublishMode = Literal["append", "replace"]


def new_run_id() -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    return f"{stamp}-{uuid.uuid4().hex[:12]}"


class ManifestStore:
    """Publishes immutable Parquet components and atomically advances active metadata."""

    def __init__(self, data_root: Path, compression: str = "zstd") -> None:
        self.data_root = data_root
        self.compression = compression

    def _metadata_dir(self, layer: str, dataset: str) -> Path:
        return self.data_root / "metadata" / "manifests" / layer / dataset

    def active_path(self, layer: str, dataset: str) -> Path:
        return self._metadata_dir(layer, dataset) / "active.json"

    def load_active(self, layer: str, dataset: str) -> DatasetManifest | None:
        path = self.active_path(layer, dataset)
        if not path.exists():
            return None
        return DatasetManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def publish_frame(
        self,
        layer: str,
        dataset: str,
        frame: pd.DataFrame,
        schema_version: str,
        *,
        mode: PublishMode = "append",
        run_id: str | None = None,
        input_runs: Iterable[str] = (),
        requested_start: str | None = None,
        requested_end: str | None = None,
        date_column: str | None = None,
        source_version: str | None = None,
        code_commit: str | None = None,
        config_hash: str | None = None,
        metadata: dict | None = None,
    ) -> DatasetManifest:
        if frame.empty:
            raise ValueError(f"Refusing to publish empty dataset: {layer}/{dataset}")
        if mode not in {"append", "replace"}:
            raise ValueError(f"Unsupported publish mode: {mode}")

        run_id = run_id or new_run_id()
        previous = self.load_active(layer, dataset)
        started = utc_now()
        staging = self.data_root / "staging" / layer / dataset / run_id
        final = self.data_root / layer / dataset / f"run_id={run_id}"
        staging.mkdir(parents=True, exist_ok=False)

        publish_frame = frame.copy()
        if "source_run_id" not in publish_frame.columns:
            publish_frame["source_run_id"] = run_id
        if "_ingested_at" not in publish_frame.columns:
            publish_frame["_ingested_at"] = started

        parquet_path = staging / "data.parquet"
        try:
            table = pa.Table.from_pandas(publish_frame, preserve_index=False)
            pq.write_table(table, parquet_path, compression=self.compression)
            verification = pq.read_metadata(parquet_path)
            if verification.num_rows != len(publish_frame):
                raise RuntimeError("Parquet row-count verification failed")
            record = FileRecord(
                relative_path=final.joinpath("data.parquet").relative_to(self.data_root).as_posix(),
                rows=len(publish_frame),
                bytes=parquet_path.stat().st_size,
                sha256=sha256_file(parquet_path),
                component_run_id=run_id,
            )
            # A component is complete before it can become reachable from active.json.
            # Writing this in staging also makes the directory rename publish it atomically.
            (staging / "SUCCESS").write_text(run_id, encoding="utf-8")
            atomic_publish_directory(staging, final)
        except Exception:
            failure = DatasetManifest(
                run_id=run_id,
                dataset=dataset,
                layer=layer,
                schema_version=schema_version,
                status=RunStatus.FAILED,
                started_at=started,
                finished_at=utc_now(),
                error_summary="Publication failed before active manifest switch",
            )
            atomic_write_json(self._metadata_dir(layer, dataset) / f"{run_id}.failed.json", failure.to_dict())
            raise

        prior_files = previous.files if previous and mode == "append" else []
        lineage = list(dict.fromkeys([*(previous.input_runs if previous and mode == "append" else []), *input_runs]))
        if previous and mode == "append":
            lineage.append(previous.run_id)

        minimum = maximum = None
        if date_column and date_column in publish_frame.columns:
            dates = pd.to_datetime(publish_frame[date_column], errors="coerce").dropna()
            if not dates.empty:
                minimum = dates.min().date().isoformat()
                maximum = dates.max().date().isoformat()
        if previous and mode == "append":
            minimum = min(value for value in (previous.actual_min_date, minimum) if value is not None) \
                if previous.actual_min_date or minimum else None
            maximum = max(value for value in (previous.actual_max_date, maximum) if value is not None) \
                if previous.actual_max_date or maximum else None

        files = [*prior_files, record]
        manifest = DatasetManifest(
            run_id=run_id,
            dataset=dataset,
            layer=layer,
            schema_version=schema_version,
            status=RunStatus.SUCCESS,
            started_at=started,
            finished_at=utc_now(),
            requested_start=requested_start,
            requested_end=requested_end,
            actual_min_date=minimum,
            actual_max_date=maximum,
            row_count=sum(item.rows for item in files),
            physical_bytes=sum(item.bytes for item in files),
            files=files,
            input_runs=list(dict.fromkeys(lineage)),
            source_version=source_version,
            code_commit=code_commit,
            config_hash=config_hash,
            metadata=metadata or {},
        )
        metadata_dir = self._metadata_dir(layer, dataset)
        atomic_write_json(metadata_dir / f"{run_id}.json", manifest.to_dict())
        atomic_write_json(self.active_path(layer, dataset), manifest.to_dict())
        return manifest

    def absolute_files(self, manifest: DatasetManifest) -> list[Path]:
        paths = [self.data_root / record.relative_path for record in manifest.files]
        missing = [str(path) for path in paths if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Active manifest references missing files: {missing}")
        return paths

    def read_active_frame(
        self,
        layer: str,
        dataset: str,
        business_key: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        manifest = self.load_active(layer, dataset)
        if manifest is None:
            raise FileNotFoundError(f"No active manifest for {layer}/{dataset}")
        frames = [pd.read_parquet(path) for path in self.absolute_files(manifest)]
        combined = pd.concat(frames, ignore_index=True)
        keys = list(business_key or [])
        if keys:
            missing = set(keys) - set(combined.columns)
            if missing:
                raise KeyError(f"Business-key columns missing: {sorted(missing)}")
            combined = combined.sort_values("_ingested_at").drop_duplicates(keys, keep="last")
        return combined.reset_index(drop=True)

    def verify_active(self, layer: str, dataset: str) -> list[str]:
        manifest = self.load_active(layer, dataset)
        if manifest is None:
            return [f"No active manifest for {layer}/{dataset}"]
        errors: list[str] = []
        for record in manifest.files:
            path = self.data_root / record.relative_path
            if not path.exists():
                errors.append(f"Missing file: {path}")
                continue
            if path.stat().st_size != record.bytes:
                errors.append(f"Size mismatch: {path}")
            if sha256_file(path) != record.sha256:
                errors.append(f"Checksum mismatch: {path}")
        return errors
