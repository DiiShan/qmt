from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from _bootstrap import bootstrap

bootstrap()

from qmt_local_data.config import load_config
from qmt_local_data.maintenance import build_maintenance_plan, run_database_update


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-click QMT local database maintenance")
    parser.add_argument("--config", type=Path, default=Path("config/data_config.yaml"))
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also refresh financial/corporate actions, adjustment factors, universe, and all volatility datasets",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the automatically selected ranges without downloading or writing data",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        config = load_config(args.config)
        payload = build_maintenance_plan(config, args.as_of, full=args.full).to_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    result = run_database_update(args.config, as_of=args.as_of, full=args.full)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
