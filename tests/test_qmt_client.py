from __future__ import annotations

from qmt_local_data.qmt_client import XtDataClient


class FakeXtData:
    __version__ = "fake"

    @staticmethod
    def get_sector_list():
        return ["沪深A股", "中金所"]

    @staticmethod
    def get_stock_list_in_sector(sector, real_timetag=None):
        if sector == "沪深A股":
            return ["000001.SZ", "600001.SH"] if real_timetag else ["000001.SZ"]
        if sector == "中金所":
            return ["IF2001.IF", "IF2609.IF", "IF2612.IF"]
        return []

    @staticmethod
    def get_instrument_detail(code, complete):
        expiry = {
            "IF2001.IF": "20200117",
            "IF2609.IF": "20260918",
            "IF2612.IF": "20261218",
        }.get(code, "")
        return {"ExpireDate": expiry, "InstrumentName": code}


def test_expired_gate_discovery_is_separate_from_complete_cffex_universe() -> None:
    client = XtDataClient(FakeXtData())
    delisted, expired = client.discover_historical_candidates(["IF"])
    all_contracts = client.discover_cffex_contracts(["IF"])

    assert delisted == ["600001.SH"]
    assert expired == ["IF2001.IF"]
    assert all_contracts == ["IF2001.IF", "IF2609.IF", "IF2612.IF"]
