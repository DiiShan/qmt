from __future__ import annotations

import pandas as pd

from qmt_local_data.preflight import PreflightRunner


class FakePreflightClient:
    source_version = "fake"

    def market_data(self, codes, period, start="", end="", count=-1):
        code = codes[0]
        columns = {
            "open": [1], "high": [2], "low": [1], "close": [2], "volume": [3], "amount": [4]
        }
        if code.startswith("IF"):
            columns.update({"settlementPrice": [2], "openInterest": [5]})
        return {code: pd.DataFrame(columns, index=pd.Index(["20200102"], name="time"))}

    def discover_historical_candidates(self, products):
        return ["600001.SH"], ["IF2001.IF"]

    def download_history_contracts(self, incrementally=True):
        return None

    def download_market_data(self, code, period, start, end=""):
        return None


def test_preflight_gate_passes_only_with_all_five_capabilities(data_config) -> None:
    report = PreflightRunner(data_config, FakePreflightClient()).run()
    assert report.gate_passed
    assert {result.name for result in report.results if result.status == "PASS"} >= {
        "current_a_share_daily",
        "delisted_a_share_discovery",
        "delisted_a_share_daily",
        "expired_cffex_discovery",
        "expired_cffex_daily",
    }
