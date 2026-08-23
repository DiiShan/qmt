from __future__ import annotations

import numpy as np
import pandas as pd


def build_main_contract_mapping(
    future_daily: pd.DataFrame,
    contract_master: pd.DataFrame,
    trading_calendar: pd.DataFrame,
    rule_version: str = "oi_then_volume_v1",
) -> pd.DataFrame:
    required_daily = {"trade_date", "contract_code", "product", "open_interest", "volume"}
    required_master = {"contract_code", "expire_date"}
    if missing := required_daily - set(future_daily.columns):
        raise KeyError(f"future_daily missing: {sorted(missing)}")
    if missing := required_master - set(contract_master.columns):
        raise KeyError(f"contract_master missing: {sorted(missing)}")

    candidates = future_daily.merge(contract_master[["contract_code", "expire_date"]], on="contract_code", how="left")
    candidates = candidates[
        candidates["expire_date"].notna() & (candidates["expire_date"] > candidates["trade_date"])
    ].copy()
    if candidates.empty:
        return pd.DataFrame()
    candidates["_oi_valid"] = candidates["open_interest"].notna() & (candidates["open_interest"] >= 0)
    candidates["_volume_valid"] = candidates["volume"].notna() & (candidates["volume"] >= 0)

    selected: list[dict] = []
    for (trade_date, product), group in candidates.groupby(["trade_date", "product"], sort=True):
        if group["_oi_valid"].any():
            pool = group[group["_oi_valid"]]
            best_value = pool["open_interest"].max()
            pool = pool[pool["open_interest"] == best_value]
            method = "MAX_OPEN_INTEREST"
        elif group["_volume_valid"].any():
            pool = group[group["_volume_valid"]]
            best_value = pool["volume"].max()
            pool = pool[pool["volume"] == best_value]
            method = "MAX_VOLUME_FALLBACK"
        else:
            continue
        winner = pool.sort_values(["expire_date", "contract_code"]).iloc[0]
        selected.append(
            {
                "mapping_type": "EOD_OBSERVED",
                "observation_trade_date": trade_date,
                "effective_trade_date": trade_date,
                "product": product,
                "contract_code": winner["contract_code"],
                "selection_method": method,
                "rule_version": rule_version,
                "eligible_contract_count": len(group),
            }
        )
    eod = pd.DataFrame(selected)
    if eod.empty:
        return eod

    calendar = trading_calendar.loc[trading_calendar["is_open"], ["trade_date", "next_trade_date"]].drop_duplicates("trade_date")
    next_day = eod.merge(calendar, left_on="observation_trade_date", right_on="trade_date", how="left")
    next_day = next_day[next_day["next_trade_date"].notna()].copy()
    next_day["mapping_type"] = "NEXT_TRADE_DAY"
    next_day["effective_trade_date"] = next_day["next_trade_date"]
    next_day = next_day[eod.columns]
    return pd.concat([eod, next_day], ignore_index=True).sort_values(
        ["effective_trade_date", "product", "mapping_type"]
    ).reset_index(drop=True)


def calculate_future_basis(
    future_daily: pd.DataFrame,
    index_daily: pd.DataFrame,
    contract_master: pd.DataFrame,
    main_mapping: pd.DataFrame,
    spot_mapping: dict[str, str],
    rule_version: str = "basis_calendar_simple_v1",
) -> pd.DataFrame:
    futures = future_daily.merge(contract_master[["contract_code", "expire_date"]], on="contract_code", how="left")
    futures["spot_code"] = futures["product"].map(spot_mapping)
    indexes = index_daily[["trade_date", "index_code", "close"]].rename(
        columns={"index_code": "spot_code", "close": "spot_close"}
    )
    result = futures.merge(indexes, on=["trade_date", "spot_code"], how="left")
    result["future_close"] = result["close"]
    result["future_settlement"] = result.get("settlement")
    valid_spot = result["spot_close"].notna() & (result["spot_close"] > 0)
    result["basis_close"] = np.where(valid_spot, result["future_close"] - result["spot_close"], np.nan)
    result["basis_settlement"] = np.where(
        valid_spot & result["future_settlement"].notna(), result["future_settlement"] - result["spot_close"], np.nan
    )
    result["basis_pct"] = np.where(valid_spot, result["basis_close"] / result["spot_close"], np.nan)
    result["days_to_expiry"] = (
        pd.to_datetime(result["expire_date"]) - pd.to_datetime(result["trade_date"])
    ).dt.days
    valid_annual = valid_spot & (result["days_to_expiry"] > 0) & result["basis_pct"].notna()
    result["annualized_basis"] = np.where(
        valid_annual, result["basis_pct"] * 365.0 / result["days_to_expiry"], np.nan
    )

    eod = main_mapping[main_mapping["mapping_type"] == "EOD_OBSERVED"][
        ["effective_trade_date", "product", "contract_code"]
    ].rename(columns={"effective_trade_date": "trade_date"})
    nxt = main_mapping[main_mapping["mapping_type"] == "NEXT_TRADE_DAY"][
        ["effective_trade_date", "product", "contract_code"]
    ].rename(columns={"effective_trade_date": "trade_date"})
    eod_keys = pd.MultiIndex.from_frame(eod[["trade_date", "product", "contract_code"]])
    next_keys = pd.MultiIndex.from_frame(nxt[["trade_date", "product", "contract_code"]])
    result_keys = pd.MultiIndex.from_frame(result[["trade_date", "product", "contract_code"]])
    result["is_main_contract_eod"] = result_keys.isin(eod_keys)
    result["is_main_contract_next_trade_day"] = result_keys.isin(next_keys)
    result["rule_version"] = rule_version
    columns = [
        "trade_date",
        "product",
        "contract_code",
        "spot_code",
        "future_close",
        "future_settlement",
        "spot_close",
        "basis_close",
        "basis_settlement",
        "basis_pct",
        "days_to_expiry",
        "annualized_basis",
        "is_main_contract_eod",
        "is_main_contract_next_trade_day",
        "rule_version",
    ]
    return result[columns].sort_values(["trade_date", "product", "contract_code"]).reset_index(drop=True)


def apply_adjustment_factor(
    daily: pd.DataFrame,
    factors: pd.DataFrame,
    price_columns: tuple[str, ...] = ("open", "high", "low", "close", "pre_close"),
) -> pd.DataFrame:
    """Apply a validated cumulative factor; raw XtData events must be normalized first."""
    required = {"trade_date", "stock_code", "factor"}
    if missing := required - set(factors.columns):
        raise KeyError(f"adjust_factor missing: {sorted(missing)}")
    result = daily.merge(factors[list(required)], on=["trade_date", "stock_code"], how="left")
    result["factor"] = result.groupby("stock_code")["factor"].ffill()
    for column in price_columns:
        if column in result.columns:
            result[f"{column}_adjusted"] = result[column] * result["factor"]
    return result
