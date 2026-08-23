from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from qmt_local_data.derived import build_main_contract_mapping, calculate_future_basis


def _fixtures():
    futures = pd.DataFrame(
        {
            "trade_date": [date(2026, 8, 20)] * 2,
            "contract_code": ["IF2609.IF", "IF2612.IF"],
            "product": ["IF", "IF"],
            "close": [4010.0, 4020.0],
            "settlement": [4005.0, 4015.0],
            "open_interest": [100.0, 100.0],
            "volume": [200.0, 300.0],
        }
    )
    master = pd.DataFrame(
        {
            "contract_code": ["IF2609.IF", "IF2612.IF"],
            "expire_date": [date(2026, 9, 18), date(2026, 12, 18)],
        }
    )
    calendar = pd.DataFrame(
        {
            "trade_date": [date(2026, 8, 20), date(2026, 8, 21)],
            "next_trade_date": [date(2026, 8, 21), None],
            "is_open": [True, True],
        }
    )
    indexes = pd.DataFrame({"trade_date": [date(2026, 8, 20)], "index_code": ["000300.SH"], "close": [4000.0]})
    return futures, master, calendar, indexes


def test_main_mapping_has_eod_and_next_day_without_same_day_tradable_leakage() -> None:
    futures, master, calendar, _ = _fixtures()
    mapping = build_main_contract_mapping(futures, master, calendar)
    assert set(mapping["mapping_type"]) == {"EOD_OBSERVED", "NEXT_TRADE_DAY"}
    eod = mapping[mapping["mapping_type"] == "EOD_OBSERVED"].iloc[0]
    nxt = mapping[mapping["mapping_type"] == "NEXT_TRADE_DAY"].iloc[0]
    assert eod["contract_code"] == "IF2609.IF"  # equal OI -> earlier expiry deterministic tie-break
    assert eod["effective_trade_date"] == date(2026, 8, 20)
    assert nxt["effective_trade_date"] == date(2026, 8, 21)


def test_basis_uses_calendar_day_simple_annualization() -> None:
    futures, master, calendar, indexes = _fixtures()
    mapping = build_main_contract_mapping(futures, master, calendar)
    basis = calculate_future_basis(futures, indexes, master, mapping, {"IF": "000300.SH"})
    row = basis[basis["contract_code"] == "IF2609.IF"].iloc[0]
    assert row["basis_close"] == 10
    assert row["basis_pct"] == pytest.approx(0.0025)
    assert row["days_to_expiry"] == 29
    assert row["annualized_basis"] == pytest.approx(0.0025 * 365 / 29)
    assert bool(row["is_main_contract_eod"])
    assert not bool(row["is_main_contract_next_trade_day"])
