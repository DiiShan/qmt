from __future__ import annotations

import json
from pathlib import Path

from .atomic import atomic_write_json
from .models import utc_now


class CheckpointStore:
    def __init__(self, data_root: Path) -> None:
        self.root = data_root / "metadata" / "checkpoints"

    def _path(self, dataset: str) -> Path:
        return self.root / f"{dataset}.json"

    def load(self, dataset: str) -> dict:
        path = self._path(dataset)
        if not path.exists():
            return {"dataset": dataset, "completed_batches": {}, "updated_at": None}
        return json.loads(path.read_text(encoding="utf-8"))

    def is_complete(self, dataset: str, batch_id: str, fingerprint: str) -> bool:
        completed = self.load(dataset).get("completed_batches", {})
        return completed.get(batch_id, {}).get("fingerprint") == fingerprint

    def mark_complete(self, dataset: str, batch_id: str, fingerprint: str, run_ids: list[str]) -> None:
        checkpoint = self.load(dataset)
        checkpoint.setdefault("completed_batches", {})[batch_id] = {
            "fingerprint": fingerprint,
            "run_ids": run_ids,
            "completed_at": utc_now(),
        }
        checkpoint["updated_at"] = utc_now()
        atomic_write_json(self._path(dataset), checkpoint)

    def reset(self, dataset: str) -> None:
        path = self._path(dataset)
        if path.exists():
            path.unlink()
