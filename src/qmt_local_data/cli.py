from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .config import load_config
from .errors import QmtLocalDataError
from .lock import ProjectLock
from .manifest import ManifestStore
from .pipeline import DatabaseBuilder
from .preflight import PreflightRunner, enforce_preflight
from .qmt_client import XtDataClient
from .storage_guard import StorageGuard


DEFAULT_CONFIG = Path("config/data_config.yaml")


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qmt-local-data")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    preflight = sub.add_parser("preflight", parents=[common])
    preflight.add_argument("--download-history-contracts", action="store_true")
    preflight.add_argument("--allow-sample-download", action="store_true")
    preflight.add_argument("--output-dir", type=Path)

    init = sub.add_parser("init", parents=[common])
    init.add_argument("--confirm-full-download", action="store_true")
    init.add_argument("--start", type=_date)
    init.add_argument("--end", type=_date, default=date.today())
    init.add_argument("--skip-financial", action="store_true")

    update = sub.add_parser("update", parents=[common])
    update.add_argument("--codes", nargs="+")
    update.add_argument("--start", type=_date, required=True)
    update.add_argument("--end", type=_date, default=date.today())
    update.add_argument("--download", action="store_true")

    sub.add_parser("validate", parents=[common])
    sub.add_parser("storage-audit", parents=[common])
    sub.add_parser("refresh-catalog", parents=[common])
    return parser


def _run_init(args: argparse.Namespace, config, client: XtDataClient) -> int:
    if not args.confirm_full_download:
        print("Dry run only. Pass --confirm-full-download to execute full initialization.")
        print(json.dumps({"data_root": str(config.data_root), "start": str(args.start or config.project.history_start), "end": str(args.end)}, ensure_ascii=False))
        return 0
    report = PreflightRunner(config, client).run(download_history_contracts=False, allow_sample_download=False)
    enforce_preflight(report)
    builder = DatabaseBuilder(config, client)
    start = args.start or config.project.history_start
    end = args.end
    with ProjectLock(config.data_root):
        builder.build_trade_calendar("SH", start, end)
        current_codes = client.discover_codes(config.markets.stock_sectors, config.markets.stock_suffixes)
        delisted, _ = client.discover_historical_candidates(config.futures.products)
        futures = client.discover_cffex_contracts(config.futures.products)
        stock_codes = sorted(set(current_codes) | set(delisted))
        builder.build_security_master(stock_codes, asset="stock")
        builder.build_universe()
        builder.ingest_market(stock_codes, "stock", start, end, download=True)
        builder.ingest_market(config.markets.indexes, "index", start, end, download=True)
        if futures:
            builder.build_security_master(futures, asset="future")
            builder.ingest_market(futures, "future", start, end, download=True)
        calendar = builder.store.read_active_frame("processed", "trade_calendar", ["market", "trade_date"])
        if not args.skip_financial:
            builder.ingest_financial(stock_codes, calendar, start, end, download=True)
        builder.ingest_dividend_factors(stock_codes, start, end)
        if futures:
            builder.build_futures_derived()
        builder.refresh_catalog()
        builder.write_storage_audit()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "storage-audit":
            guard = StorageGuard(config.data_root, config.storage)
            print(json.dumps(guard.snapshot().to_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate":
            store = ManifestStore(config.data_root, config.project.compression)
            errors: list[str] = []
            for layer, dataset in [
                ("processed", "security_master"),
                ("processed", "trade_calendar"),
                ("processed", "stock_daily"),
                ("processed", "index_daily"),
                ("processed", "future_daily"),
                ("derived", "future_main_mapping"),
                ("derived", "future_basis_daily"),
            ]:
                if store.load_active(layer, dataset):
                    errors.extend(store.verify_active(layer, dataset))
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 2
            print("All discovered active manifests verified.")
            return 0

        client = XtDataClient()
        try:
            if args.command == "preflight":
                runner = PreflightRunner(config, client)
                report = runner.run(args.download_history_contracts, args.allow_sample_download)
                paths = runner.write(report, args.output_dir)
                print(json.dumps({"gate_passed": report.gate_passed, "reports": [str(path) for path in paths]}, ensure_ascii=False))
                return 0 if report.gate_passed else 2
            if args.command == "init":
                return _run_init(args, config, client)
            builder = DatabaseBuilder(config, client)
            if args.command == "update":
                codes = args.codes or client.discover_codes(config.markets.stock_sectors, config.markets.stock_suffixes)
                with ProjectLock(config.data_root):
                    builder.ingest_market(codes, "stock", args.start, args.end, download=args.download)
                    builder.refresh_catalog()
                    builder.write_storage_audit()
                return 0
            if args.command == "refresh-catalog":
                print(json.dumps(builder.refresh_catalog(), ensure_ascii=False))
                return 0
        finally:
            client.disconnect()
    except (QmtLocalDataError, ValueError, KeyError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
