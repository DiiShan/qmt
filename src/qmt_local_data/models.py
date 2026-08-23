from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class FileRecord:
    relative_path: str
    rows: int
    bytes: int
    sha256: str
    component_run_id: str


@dataclass
class DatasetManifest:
    run_id: str
    dataset: str
    layer: str
    schema_version: str
    status: str
    started_at: str
    finished_at: str | None = None
    requested_start: str | None = None
    requested_end: str | None = None
    actual_min_date: str | None = None
    actual_max_date: str | None = None
    row_count: int = 0
    physical_bytes: int = 0
    files: list[FileRecord] = field(default_factory=list)
    input_runs: list[str] = field(default_factory=list)
    source: str = "xtdata"
    source_version: str | None = None
    code_commit: str | None = None
    config_hash: str | None = None
    error_summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DatasetManifest":
        data = dict(value)
        data["files"] = [FileRecord(**item) for item in data.get("files", [])]
        return cls(**data)


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")
