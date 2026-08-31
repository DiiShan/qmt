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
from .pipeline import DatabaseBuilder, load_database_status, market_universe_names
from .preflight import (
    PreflightRunner,
    enforce_current_universe_preflight,
    enforce_preflight,
)
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
    init.add_argument(
        "--allow-current-universe-only",
        action="store_true",
        help="Explicitly build a survivorship-biased temporary database when only delisted-stock checks fail",
    )

    update = sub.add_parser("update", parents=[common])
    update.add_argument("--codes", nargs="+")
    update.add_argument("--start", type=_date, required=True)
    update.add_argument("--end", type=_date, default=date.today())
    update.add_argument("--download", action="store_true")
    update.add_argument("--asset", choices=("stock", "index"), default="stock")

    sub.add_parser("validate", parents=[common])
    sub.add_parser("storage-audit", parents=[common])
    sub.add_parser("refresh-catalog", parents=[common])
    sub.add_parser(
        "build-universe",
        parents=[common],
        help="Rebuild the database-scope historical universe from security lifecycle dates",
    )
    reference = sub.add_parser(
        "update-reference-data",
        parents=[common],
        help="Update official stock lists and observed QMT index/sector membership snapshots",
    )
    reference.add_argument("--as-of", type=_date, default=date.today())
    volatility = sub.add_parser("build-volatility", parents=[common])
    range_group = volatility.add_mutually_exclusive_group(required=True)
    range_group.add_argument("--start", type=_date)
    range_group.add_argument("--rebuild-from", type=_date)
    volatility.add_argument("--end", type=_date, default=date.today())
    market_volatility = sub.add_parser("build-market-volatility", parents=[common])
    market_range = market_volatility.add_mutually_exclusive_group(required=True)
    market_range.add_argument("--start", type=_date)
    market_range.add_argument("--rebuild-from", type=_date)
    market_volatility.add_argument("--end", type=_date, default=date.today())
    index_volatility = sub.add_parser("build-index-volatility", parents=[common])
    index_range = index_volatility.add_mutually_exclusive_group(required=True)
    index_range.add_argument("--start", type=_date)
    index_range.add_argument("--rebuild-from", type=_date)
    index_volatility.add_argument("--end", type=_date, default=date.today())
    dashboard = sub.add_parser(
        "dashboard",
        parents=[common],
        help="Launch the read-only market, sector, and index volatility dashboard",
    )
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8501)
    adjustment = sub.add_parser(
        "build-adjust-factor",
        parents=[common],
        help="Audit XtData dr semantics and optionally publish validated adjust_factor",
    )
    adjustment.add_argument(
        "--factor-version",
        default="xtdata_dr_cumprod_v1",
    )
    adjustment.add_argument(
        "--audit-output",
        type=Path,
        default=Path("reports/adjust_factor_audit.json"),
    )
    adjustment.add_argument("--publish", action="store_true")
    return parser


def _run_init(args: argparse.Namespace, config, client: XtDataClient) -> int:
    if not args.confirm_full_download:
        print("Dry run only. Pass --confirm-full-download to execute full initialization.")
        print(json.dumps({
            "data_root": str(config.data_root),
            "start": str(args.start or config.project.history_start),
            "end": str(args.end),
            "universe_scope": "CURRENT_UNIVERSE_ONLY" if args.allow_current_universe_only else "FULL_HISTORY",
        }, ensure_ascii=False))
        return 0
    report = PreflightRunner(config, client).run(download_history_contracts=False, allow_sample_download=False)
    if args.allow_current_universe_only:
        enforce_current_universe_preflight(report)
        universe_scope = "CURRENT_UNIVERSE_ONLY"
        universe_name = "CURRENT_SURVIVORS"
    else:
        enforce_preflight(report)
        universe_scope = "FULL_HISTORY"
        universe_name = "ALL_A"
    builder = DatabaseBuilder(config, client, universe_scope=universe_scope)
    start = args.start or config.project.history_start
    end = args.end
    with ProjectLock(config.data_root):
        builder.write_database_status(f"INITIALIZING_{universe_scope}", report.gate_passed)
        builder.build_trade_calendar("SH", start, end)
        current_codes = client.discover_codes(config.markets.stock_sectors, config.markets.stock_suffixes)
        delisted, _ = client.discover_historical_candidates(config.futures.products)
        futures = client.discover_cffex_contracts(config.futures.products)
        stock_codes = sorted(set(current_codes) | (set() if args.allow_current_universe_only else set(delisted)))
        builder.build_security_master(stock_codes, asset="stock")
        builder.build_universe(universe_name)
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
        status = builder.write_database_status(f"READY_{universe_scope}", report.gate_passed)
        print(json.dumps({
            "state": f"READY_{universe_scope}",
            "stock_count": len(stock_codes),
            "future_contract_count": len(futures),
            "database_status": str(status),
        }, ensure_ascii=False))
    return 0


def _existing_database_scope(config) -> str:
    status = load_database_status(config.data_root)
    if status is None:
        raise QmtLocalDataError("Database status is missing; run an initialization command before update")
    state = str(status.get("state") or "")
    scope = str(status.get("universe_scope") or "")
    if not state.startswith("READY_"):
        raise QmtLocalDataError(f"Database is not ready for update: {state or 'UNKNOWN'}")
    expected_state = f"READY_{scope}"
    if state != expected_state:
        raise QmtLocalDataError(f"Database state/scope mismatch: state={state}, scope={scope}")
    if scope not in {"FULL_HISTORY", "CURRENT_UNIVERSE_ONLY"}:
        raise QmtLocalDataError(f"Unsupported database universe scope: {scope}")
    accepted = bool(status.get("accepted_for_unbiased_backtest"))
    if scope == "CURRENT_UNIVERSE_ONLY" and accepted:
        raise QmtLocalDataError("CURRENT_UNIVERSE_ONLY status cannot be accepted for unbiased backtest")
    return scope


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if (
            args.command == "init"
            and args.allow_current_universe_only
            and not args.confirm_full_download
        ):
            raise QmtLocalDataError(
                "--allow-current-universe-only requires --confirm-full-download"
            )
        if args.command == "storage-audit":
            guard = StorageGuard(config.data_root, config.storage)
            print(json.dumps(guard.snapshot().to_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "dashboard":
            from .dashboard import launch_dashboard

            return launch_dashboard(args.config, host=args.host, port=args.port)
        if args.command == "build-adjust-factor":
            from .adjustment import audit_xtdata_adjustment_factors

            scope = _existing_database_scope(config)
            result = audit_xtdata_adjustment_factors(
                config,
                factor_version=args.factor_version,
            )
            args.audit_output.parent.mkdir(parents=True, exist_ok=True)
            args.audit_output.write_text(
                json.dumps(result.report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            run_id = None
            if args.publish:
                builder = DatabaseBuilder(config, object(), universe_scope=scope)
                with ProjectLock(config.data_root):
                    run_id = builder.publish_validated_adjust_factor(
                        result.factors,
                        factor_version=args.factor_version,
                        validation_evidence=result.evidence,
                    )
            print(
                json.dumps(
                    {
                        "status": result.report["status"],
                        "audit_output": str(args.audit_output.resolve()),
                        "factor_rows": len(result.factors),
                        "adjust_factor_run": run_id,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "validate":
            store = ManifestStore(config.data_root, config.project.compression)
            errors: list[str] = []
            for layer, dataset in [
                ("processed", "security_master"),
                ("processed", "current_stock_list"),
                ("processed", "delisted_stock_list"),
                ("processed", "index_membership_snapshot_daily"),
                ("processed", "sector_membership_snapshot_daily"),
                ("processed", "trade_calendar"),
                ("processed", "stock_daily"),
                ("processed", "index_daily"),
                ("processed", "future_daily"),
                ("derived", "future_main_mapping"),
                ("derived", "future_basis_daily"),
                ("derived", "adjust_factor"),
                ("derived", "stock_vol_daily"),
                ("derived", "market_vol_daily"),
                ("derived", "index_vol_daily"),
            ]:
                manifest = store.load_active(layer, dataset)
                if manifest:
                    errors.extend(store.verify_active(layer, dataset))
                    if dataset in {"stock_vol_daily", "market_vol_daily", "index_vol_daily"}:
                        if not manifest.input_runs:
                            errors.append(f"{dataset}: input_runs is empty")
                        if not manifest.config_hash:
                            errors.append(f"{dataset}: config_hash is missing")
                        for key in ("rule_version", "universe_scope"):
                            if not manifest.metadata.get(key):
                                errors.append(f"{dataset}: metadata.{key} is missing")
                        if dataset in {"stock_vol_daily", "market_vol_daily"} and not manifest.metadata.get(
                            "factor_version"
                        ):
                            errors.append(f"{dataset}: metadata.factor_version is missing")
            index_manifest = store.load_active("derived", "index_vol_daily")
            if config.volatility.index_universe and index_manifest is None:
                errors.append("index_vol_daily: active manifest is missing")
            market_manifest = store.load_active("derived", "market_vol_daily")
            status = load_database_status(config.data_root) or {}
            scope = str(status.get("universe_scope") or "")
            if market_manifest is not None and scope in {"FULL_HISTORY", "CURRENT_UNIVERSE_ONLY"}:
                expected_names = set(market_universe_names(scope))
                actual_names = set(
                    market_manifest.metadata.get("universe_names")
                    or [market_manifest.metadata.get("universe_name")]
                )
                if not expected_names <= actual_names:
                    errors.append(
                        "market_vol_daily: missing required market scopes "
                        f"{sorted(expected_names - actual_names)}"
                    )
            try:
                _existing_database_scope(config)
            except QmtLocalDataError as exc:
                errors.append(str(exc))
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 2
            print("All discovered active manifests verified.")
            return 0

        if args.command in {
            "refresh-catalog",
            "build-universe",
            "build-volatility",
            "build-market-volatility",
            "build-index-volatility",
        }:
            scope = _existing_database_scope(config)
            builder = DatabaseBuilder(config, object(), universe_scope=scope)
            if args.command == "refresh-catalog":
                print(json.dumps(builder.refresh_catalog(), ensure_ascii=False))
                return 0
            if args.command == "build-universe":
                universe_name = (
                    "ALL_A" if scope == "FULL_HISTORY" else "CURRENT_SURVIVORS"
                )
                with ProjectLock(config.data_root):
                    run_id = builder.build_universe(universe_name)
                    created = builder.refresh_catalog()
                print(
                    json.dumps(
                        {"historical_universe_run": run_id, "universe_name": universe_name, "catalog_views": created},
                        ensure_ascii=False,
                    )
                )
                return 0
            effective_start = args.rebuild_from or args.start
            if effective_start > args.end:
                raise QmtLocalDataError("Volatility start/rebuild-from must not be after end")
            # Fail read-only prerequisites before acquiring the project lock;
            # the builder rechecks them inside the locked publication path.
            if args.command in {"build-volatility", "build-market-volatility"}:
                builder.check_volatility_prerequisites()
            if args.command in {"build-volatility", "build-index-volatility"}:
                builder.check_index_volatility_prerequisites()
            with ProjectLock(config.data_root):
                if args.command == "build-index-volatility":
                    index_run = builder.build_index_volatility(
                        effective_start,
                        args.end,
                        rebuild_from=args.rebuild_from,
                    )
                    stock_run = None
                    market_run = None
                elif args.command == "build-market-volatility":
                    market_run = builder.build_market_volatility(
                        effective_start,
                        args.end,
                        rebuild_from=args.rebuild_from,
                    )
                    stock_run = None
                    index_run = None
                else:
                    stock_run, market_run, index_run = builder.build_volatility_derived(
                        effective_start,
                        args.end,
                        rebuild_from=args.rebuild_from,
                    )
                created = builder.refresh_catalog()
            print(
                json.dumps(
                    {
                        "stock_vol_daily_run": stock_run,
                        "market_vol_daily_run": market_run,
                        "index_vol_daily_run": index_run,
                        "catalog_views": created,
                    },
                    ensure_ascii=False,
                )
            )
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
            universe_scope = (
                _existing_database_scope(config)
                if args.command in {"update", "update-reference-data"}
                else "FULL_HISTORY"
            )
            builder = DatabaseBuilder(config, client, universe_scope=universe_scope)
            if args.command == "update-reference-data":
                with ProjectLock(config.data_root):
                    runs = builder.update_reference_data(args.as_of)
                    views = builder.refresh_catalog()
                    builder.write_storage_audit()
                print(json.dumps({"runs": runs, "catalog_views": views}, ensure_ascii=False))
                return 0
            if args.command == "update":
                if args.asset == "index":
                    codes = args.codes or list(config.markets.indexes)
                else:
                    codes = args.codes or client.discover_codes(
                        config.markets.stock_sectors, config.markets.stock_suffixes
                    )
                with ProjectLock(config.data_root):
                    builder.ingest_market(codes, args.asset, args.start, args.end, download=args.download)
                    builder.refresh_catalog()
                    builder.write_storage_audit()
                return 0
        finally:
            client.disconnect()
    except (QmtLocalDataError, ValueError, KeyError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
