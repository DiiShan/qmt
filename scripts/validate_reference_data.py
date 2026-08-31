from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from qmt_local_data.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/data_config.yaml"))
    args = parser.parse_args()
    config = load_config(args.config)
    database = config.data_root / "database" / "qmt.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        current = connection.execute(
            "SELECT COUNT(*), COUNT_IF(list_date IS NULL), MIN(as_of_date), MAX(as_of_date) "
            "FROM current_stock_list"
        ).fetchone()
        delisted = connection.execute(
            "SELECT COUNT(*), COUNT_IF(list_date IS NULL), COUNT_IF(delist_date IS NULL), "
            "MIN(delist_date), MAX(delist_date) FROM delisted_stock_list"
        ).fetchone()
        master = connection.execute(
            "SELECT COUNT(*), COUNT_IF(listing_status = 'CURRENT'), "
            "COUNT_IF(listing_status = 'DELISTED'), COUNT_IF(list_date IS NULL) FROM security_master"
        ).fetchone()
        indexes = connection.execute(
            "SELECT index_code, index_name, COUNT(*), ROUND(SUM(weight), 6) "
            "FROM index_membership_snapshot_daily GROUP BY 1, 2 ORDER BY 1"
        ).fetchall()
        sectors = connection.execute(
            "SELECT COUNT(DISTINCT sector_code), COUNT(*), COUNT(DISTINCT stock_code) "
            "FROM sector_membership_snapshot_daily"
        ).fetchone()
        universe = connection.execute(
            "SELECT universe_name, COUNT(DISTINCT stock_code), MIN(trade_date), MAX(trade_date) "
            "FROM historical_universe GROUP BY 1"
        ).fetchall()
        overlaps = connection.execute(
            "SELECT COUNT(*) FROM current_stock_list c "
            "INNER JOIN delisted_stock_list d USING (stock_code)"
        ).fetchone()[0]
        current_not_master = connection.execute(
            "SELECT COUNT(*) FROM current_stock_list c LEFT JOIN security_master m USING (stock_code) "
            "WHERE m.stock_code IS NULL OR m.listing_status <> 'CURRENT'"
        ).fetchone()[0]
        missing_list_dates = connection.execute(
            "SELECT stock_code, stock_name, exchange, source FROM current_stock_list "
            "WHERE list_date IS NULL ORDER BY stock_code"
        ).fetchall()
        universe_before_listing = connection.execute(
            "SELECT COUNT(*) FROM historical_universe u "
            "INNER JOIN security_master m USING (stock_code) "
            "WHERE u.eligible_flag AND u.trade_date < m.list_date"
        ).fetchone()[0]
        sector_not_current = connection.execute(
            "SELECT COUNT(*) FROM sector_membership_snapshot_daily s "
            "LEFT JOIN current_stock_list c ON s.snapshot_date = c.as_of_date "
            "AND s.stock_code = c.stock_code WHERE c.stock_code IS NULL"
        ).fetchone()[0]
        latest_market = connection.execute(
            "SELECT universe_name, trade_date, eligible_stock_count, valid_return_count "
            "FROM market_vol_daily QUALIFY ROW_NUMBER() OVER "
            "(PARTITION BY universe_name ORDER BY trade_date DESC) = 1 ORDER BY universe_name"
        ).fetchall()
    payload = {
        "current_stock_list": {
            "rows": current[0], "missing_list_date": current[1],
            "min_as_of": current[2], "max_as_of": current[3],
        },
        "delisted_stock_list": {
            "rows": delisted[0], "missing_list_date": delisted[1],
            "missing_delist_date": delisted[2], "min_delist_date": delisted[3],
            "max_delist_date": delisted[4],
        },
        "security_master": {
            "rows": master[0], "current": master[1], "delisted": master[2],
            "missing_list_date": master[3],
        },
        "index_membership": indexes,
        "sector_membership": {
            "sectors": sectors[0], "rows": sectors[1], "stocks": sectors[2],
        },
        "historical_universe": universe,
        "cross_checks": {
            "current_delisted_overlap": overlaps,
            "current_missing_or_noncurrent_in_master": current_not_master,
            "missing_current_list_dates": missing_list_dates,
            "universe_before_listing": universe_before_listing,
            "sector_members_not_in_current_snapshot": sector_not_current,
        },
        "latest_market_volatility": latest_market,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
