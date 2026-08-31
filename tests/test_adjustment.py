from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from qmt_local_data.adjustment import normalize_xtdata_dr_factors
from qmt_local_data.errors import CapabilityGateError


def test_xtdata_dr_is_cumulative_from_one_baseline() -> None:
    raw = pd.DataFrame(
        {
            "stock_code": ["A", "A", "B"],
            "index": ["20200110", "20200210", "20190101"],
            "dr": [2.0, 1.5, -2.0],
        }
    )
    first = pd.DataFrame(
        {
            "stock_code": ["A", "B", "C"],
            "first_valid_date": [date(2020, 1, 2), date(2020, 1, 2), date(2020, 1, 2)],
        }
    )

    factors, usable, classified = normalize_xtdata_dr_factors(raw, first)

    assert factors[factors["stock_code"] == "A"]["factor"].tolist() == [1.0, 2.0, 3.0]
    assert factors[factors["stock_code"] == "C"]["factor"].tolist() == [1.0]
    assert usable[["stock_code", "dr"]].values.tolist() == [["A", 2.0], ["A", 1.5]]
    ignored = classified[~classified["inside_price_history"]]
    assert ignored[["stock_code", "dr"]].values.tolist() == [["B", -2.0]]


def test_nonpositive_dr_inside_price_history_blocks_publication() -> None:
    raw = pd.DataFrame(
        {"stock_code": ["A"], "index": ["20200110"], "dr": [0.0]}
    )
    first = pd.DataFrame(
        {"stock_code": ["A"], "first_valid_date": [date(2020, 1, 2)]}
    )

    with pytest.raises(CapabilityGateError, match="inside price history"):
        normalize_xtdata_dr_factors(raw, first)
