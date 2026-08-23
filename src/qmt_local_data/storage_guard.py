from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from .atomic import directory_size, disk_usage
from .config import StorageConfig
from .errors import StorageLimitError

GIB = 1024**3


class StorageLevel(StrEnum):
    OK = "OK"
    TARGET_EXCEEDED = "TARGET_EXCEEDED"
    WARNING = "WARNING"
    HARD_LIMIT = "HARD_LIMIT"


@dataclass(frozen=True)
class StorageSnapshot:
    level: str
    project_data_size: int
    qmt_cache_size: int | None
    staging_temp_size: int
    free_disk_space: int
    qmt_cache_free_disk_space: int | None
    projected_bytes: int
    projected_total: int

    def to_dict(self) -> dict:
        return asdict(self)


class StorageGuard:
    def __init__(self, data_root: Path, config: StorageConfig) -> None:
        self.data_root = data_root
        self.config = config

    def snapshot(self, estimated_batch_bytes: int = 0) -> StorageSnapshot:
        project_bytes = directory_size(self.data_root) or 0
        staging_bytes = directory_size(self.data_root / "staging") or 0
        cache_bytes = directory_size(self.config.qmt_cache_path)
        free_bytes = disk_usage(self.data_root).free
        cache_free_bytes = disk_usage(self.config.qmt_cache_path).free if self.config.qmt_cache_path else None
        projected = int(max(0, estimated_batch_bytes) * self.config.batch_safety_factor)
        projected_total = project_bytes + projected
        if projected_total >= self.config.hard_limit_gb * GIB:
            level = StorageLevel.HARD_LIMIT
        elif projected_total >= self.config.warning_gb * GIB:
            level = StorageLevel.WARNING
        elif projected_total > self.config.target_gb * GIB:
            level = StorageLevel.TARGET_EXCEEDED
        else:
            level = StorageLevel.OK
        return StorageSnapshot(
            level=level,
            project_data_size=project_bytes,
            qmt_cache_size=cache_bytes,
            staging_temp_size=staging_bytes,
            free_disk_space=free_bytes,
            qmt_cache_free_disk_space=cache_free_bytes,
            projected_bytes=projected,
            projected_total=projected_total,
        )

    def enforce(self, estimated_batch_bytes: int = 0) -> StorageSnapshot:
        snapshot = self.snapshot(estimated_batch_bytes)
        if snapshot.level == StorageLevel.HARD_LIMIT:
            raise StorageLimitError("Projected project size reaches the configured hard limit")
        if snapshot.free_disk_space - snapshot.projected_bytes < self.config.minimum_free_gb * GIB:
            raise StorageLimitError("Projected batch would violate minimum free disk space")
        if (
            snapshot.qmt_cache_free_disk_space is not None
            and snapshot.qmt_cache_free_disk_space - snapshot.projected_bytes < self.config.minimum_free_gb * GIB
        ):
            raise StorageLimitError("Projected download would violate QMT cache disk minimum free space")
        return snapshot
