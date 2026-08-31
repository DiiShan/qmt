from __future__ import annotations

from bisect import bisect_left, bisect_right, insort
from math import ceil, sqrt
from typing import Iterable

import numpy as np
import pandas as pd

from .config import VolatilityConfig


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    valid = denominator.notna() & (denominator > 0)
    return numerator.div(denominator).where(valid).replace([np.inf, -np.inf], np.nan)


def calculate_rolling_percentile(
    values: pd.Series,
    window: int,
    min_obs: int,
) -> pd.Series:
    """Prior-only empirical CDF: fraction of prior values <= the current value."""
    if window <= 0 or min_obs <= 0 or min_obs > window:
        raise ValueError("window/min_obs must satisfy 0 < min_obs <= window")
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    result = np.full(len(numeric), np.nan, dtype=float)
    history: list[float] = []
    for index, current in enumerate(numeric):
        expired_index = index - window - 1
        if expired_index >= 0:
            expired = numeric[expired_index]
            if np.isfinite(expired):
                position = bisect_left(history, float(expired))
                if position < len(history) and history[position] == float(expired):
                    history.pop(position)
        if np.isfinite(current) and len(history) >= min_obs:
            result[index] = bisect_right(history, float(current)) / len(history)
        if np.isfinite(current):
            insort(history, float(current))
    return pd.Series(result, index=values.index, dtype="float64")


def calculate_stock_returns(
    daily: pd.DataFrame,
    universe: pd.DataFrame | None = None,
    *,
    adjusted_close_column: str = "close_adjusted",
) -> pd.DataFrame:
    """Calculate PIT stock returns on an eligible stock/date grid.

    A suspended or otherwise non-tradable row is never interpreted as a zero
    return.  On resumption, the previous price is the most recent valid traded
    adjusted close.
    """
    required_daily = {"trade_date", "stock_code", adjusted_close_column}
    if missing := required_daily - set(daily.columns):
        raise KeyError(f"daily missing: {sorted(missing)}")

    source_columns = ["trade_date", "stock_code", adjusted_close_column]
    source_columns += [column for column in ("suspend_flag", "volume") if column in daily.columns]
    source = daily[source_columns].copy()
    source["trade_date"] = pd.to_datetime(source["trade_date"], errors="coerce").dt.date
    source = source.drop_duplicates(["trade_date", "stock_code"], keep="last")

    if universe is None:
        result = source.copy()
    else:
        required_universe = {"trade_date", "stock_code"}
        if missing := required_universe - set(universe.columns):
            raise KeyError(f"universe missing: {sorted(missing)}")
        eligible = universe.copy()
        if "eligible_flag" in eligible.columns:
            eligible = eligible[eligible["eligible_flag"].fillna(False)]
        eligible["trade_date"] = pd.to_datetime(eligible["trade_date"], errors="coerce").dt.date
        eligible_columns = ["trade_date", "stock_code"]
        if "universe_name" in eligible.columns:
            eligible_columns.append("universe_name")
        result = eligible[eligible_columns].drop_duplicates().merge(
            source, on=["trade_date", "stock_code"], how="left", validate="one_to_one"
        )

    result = result.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    price = pd.to_numeric(result[adjusted_close_column], errors="coerce")
    valid = price.notna() & np.isfinite(price) & (price > 0)
    if "suspend_flag" in result.columns:
        suspend = pd.to_numeric(result["suspend_flag"], errors="coerce")
        valid &= suspend.eq(0)
    if "volume" in result.columns:
        volume = pd.to_numeric(result["volume"], errors="coerce")
        valid &= volume.gt(0)

    valid_price = price.where(valid)
    previous = valid_price.groupby(result["stock_code"], sort=False).transform(
        lambda values: values.ffill().shift(1)
    )
    valid_return = valid & previous.notna() & previous.gt(0)
    result["ret_1d"] = price.div(previous).sub(1).where(valid_return)
    result["log_ret_1d"] = np.log1p(result["ret_1d"]).where(result["ret_1d"] > -1)
    result["valid_return_flag"] = valid_return.astype(bool)
    return result


def calculate_stock_volatility(
    returns: pd.DataFrame,
    config: VolatilityConfig,
) -> pd.DataFrame:
    required = {"trade_date", "stock_code", "ret_1d", "valid_return_flag"}
    if missing := required - set(returns.columns):
        raise KeyError(f"returns missing: {sorted(missing)}")
    result = returns.copy().sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    grouped_return = result.groupby("stock_code", sort=False)["ret_1d"]
    annualizer = sqrt(config.annualization_days)

    for window in config.windows:
        min_obs = ceil(window * config.min_obs_ratio)
        rolling = grouped_return.rolling(window, min_periods=1)
        valid_obs = rolling.count().reset_index(level=0, drop=True)
        volatility = rolling.std(ddof=1).reset_index(level=0, drop=True) * annualizer
        result[f"valid_obs_{window}"] = valid_obs.astype("int64")
        result[f"rv{window}"] = volatility.where(valid_obs >= min_obs)

    result["rv5_rv20"] = _safe_ratio(result["rv5"], result["rv20"])
    result["rv20_rv60"] = _safe_ratio(result["rv20"], result["rv60"])

    positive_square = result["ret_1d"].clip(lower=0).pow(2)
    negative_square = result["ret_1d"].clip(upper=0).pow(2)
    min_obs20 = ceil(20 * config.min_obs_ratio)
    positive_mean = positive_square.groupby(result["stock_code"], sort=False).rolling(
        20, min_periods=min_obs20
    ).mean().reset_index(level=0, drop=True)
    negative_mean = negative_square.groupby(result["stock_code"], sort=False).rolling(
        20, min_periods=min_obs20
    ).mean().reset_index(level=0, drop=True)
    result["up_rv20"] = np.sqrt(config.annualization_days * positive_mean)
    result["down_rv20"] = np.sqrt(config.annualization_days * negative_mean)
    result["down_up_ratio"] = _safe_ratio(result["down_rv20"], result["up_rv20"])

    for window in config.percentile_windows:
        min_obs = ceil(window * config.percentile_min_obs_ratio)
        result[f"rv20_pct{window}"] = result.groupby("stock_code", sort=False, group_keys=False)[
            "rv20"
        ].apply(lambda values: calculate_rolling_percentile(values, window, min_obs))

    previous_rv20 = result.groupby("stock_code", sort=False)["rv20"].shift(1)
    previous_daily_sigma = previous_rv20 / annualizer
    result["shock_z20"] = result["ret_1d"].div(previous_daily_sigma).where(previous_daily_sigma > 0)
    result["shock_z20"] = result["shock_z20"].replace([np.inf, -np.inf], np.nan)

    output_columns = [
        "trade_date",
        "stock_code",
        "ret_1d",
        "log_ret_1d",
        "valid_return_flag",
        *[f"rv{window}" for window in config.windows],
        "rv5_rv20",
        "rv20_rv60",
        *[f"rv20_pct{window}" for window in config.percentile_windows],
        "up_rv20",
        "down_rv20",
        "down_up_ratio",
        "shock_z20",
        *[f"valid_obs_{window}" for window in config.windows],
    ]
    return result[output_columns].sort_values(["trade_date", "stock_code"]).reset_index(drop=True)


def calculate_index_volatility(
    index_daily: pd.DataFrame,
    config: VolatilityConfig,
    *,
    index_names: dict[str, str],
) -> pd.DataFrame:
    """Calculate the frozen stock-style volatility metrics from official index closes."""
    required = {"trade_date", "index_code", "close"}
    if missing := required - set(index_daily.columns):
        raise KeyError(f"index_daily missing: {sorted(missing)}")
    if not index_names:
        raise ValueError("index_names must not be empty")

    source = index_daily[index_daily["index_code"].isin(index_names)].copy()
    source["trade_date"] = pd.to_datetime(source["trade_date"], errors="coerce").dt.date
    source["close"] = pd.to_numeric(source["close"], errors="coerce")
    source = source[source["trade_date"].notna() & source["close"].gt(0)].copy()
    if "volume" in source.columns:
        source["volume"] = pd.to_numeric(source["volume"], errors="coerce")
        source = source[source["volume"].gt(0)].copy()
    source = source.sort_values(["index_code", "trade_date"]).drop_duplicates(
        ["trade_date", "index_code"], keep="last"
    )
    if source.empty:
        raise ValueError("No valid configured index closes are available")

    return_source = source[["trade_date", "index_code", "close"]].rename(
        columns={"index_code": "stock_code", "close": "close_adjusted"}
    )
    returns = calculate_stock_returns(return_source)
    result = calculate_stock_volatility(returns, config).rename(
        columns={"stock_code": "index_code"}
    )
    close = source[["trade_date", "index_code", "close"]]
    result = result.merge(close, on=["trade_date", "index_code"], how="left", validate="one_to_one")
    result.insert(2, "index_name", result["index_code"].map(index_names))
    ordered = [
        "trade_date",
        "index_code",
        "index_name",
        "close",
        *[
            column
            for column in result.columns
            if column not in {"trade_date", "index_code", "index_name", "close"}
        ],
    ]
    return result[ordered].sort_values(["trade_date", "index_code"]).reset_index(drop=True)


def calculate_implied_correlation(
    panel: pd.DataFrame,
    window: int,
    *,
    min_stock_count: int = 2,
    date_column: str = "trade_date",
    code_column: str = "stock_code",
    return_column: str = "ret_1d",
) -> tuple[float, int]:
    """Return fixed-equal-weight implied correlation for a complete W-day subset."""
    required = {date_column, code_column, return_column}
    if missing := required - set(panel.columns):
        raise KeyError(f"panel missing: {sorted(missing)}")
    dates = sorted(pd.Series(panel[date_column]).dropna().unique())
    if len(dates) < window:
        return np.nan, 0
    dates = dates[-window:]
    pivot = panel[panel[date_column].isin(dates)].pivot_table(
        index=date_column, columns=code_column, values=return_column, aggfunc="last"
    ).reindex(dates)
    values = pivot.to_numpy(dtype=float)
    return _implied_correlation_from_array(values, min_stock_count)


def _implied_correlation_from_array(
    values: np.ndarray,
    min_stock_count: int = 2,
) -> tuple[float, int]:
    complete_mask = np.isfinite(values).all(axis=0)
    values = values[:, complete_mask]
    stock_count = values.shape[1]
    if stock_count < min_stock_count:
        return np.nan, stock_count
    sigma_i = values.std(axis=0, ddof=1)
    sigma_p = values.mean(axis=1).std(ddof=1)
    weights = np.full(stock_count, 1.0 / stock_count)
    idiosyncratic = np.sum(weights**2 * sigma_i**2)
    numerator = sigma_p**2 - idiosyncratic
    denominator = np.sum(weights * sigma_i) ** 2 - idiosyncratic
    if not np.isfinite(denominator) or denominator <= 0:
        return np.nan, stock_count
    value = numerator / denominator
    return (float(value), stock_count) if np.isfinite(value) else (np.nan, stock_count)


def _rolling_volatility(values: pd.Series, window: int, config: VolatilityConfig) -> pd.Series:
    min_obs = ceil(window * config.min_obs_ratio)
    return values.rolling(window, min_periods=min_obs).std(ddof=1) * sqrt(config.annualization_days)


def _recursive_ewma(
    values: pd.Series,
    halflife: float,
    min_obs: int,
    seed: float | None,
) -> pd.Series:
    alpha = 1.0 - np.exp(np.log(0.5) / halflife)
    state = float(seed) if seed is not None and np.isfinite(seed) else np.nan
    seen = min_obs if np.isfinite(state) else 0
    output = np.full(len(values), np.nan, dtype=float)
    for index, value in enumerate(pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)):
        if not np.isfinite(value):
            continue
        state = value if not np.isfinite(state) else alpha * value + (1.0 - alpha) * state
        seen += 1
        if seen >= min_obs:
            output[index] = state
    return pd.Series(output, index=values.index, dtype="float64")


def _cross_section(group: pd.DataFrame, config: VolatilityConfig) -> pd.Series:
    returns = pd.to_numeric(group["ret_1d"], errors="coerce")
    valid_returns = returns.dropna()
    empty = pd.Series(np.nan, index=group.index, dtype="float64")
    rv5 = pd.to_numeric(group["rv5"] if "rv5" in group else empty, errors="coerce").dropna()
    rv20 = pd.to_numeric(group["rv20"], errors="coerce").dropna()
    rv60 = pd.to_numeric(group["rv60"] if "rv60" in group else empty, errors="coerce").dropna()
    pct252 = pd.to_numeric(group.get("rv20_pct252"), errors="coerce").dropna()
    shock = pd.to_numeric(group.get("shock_z20"), errors="coerce").dropna()
    eligible = len(group)
    valid_count = len(valid_returns)
    coverage = valid_count / eligible if eligible else np.nan
    low_coverage = not np.isfinite(coverage) or coverage < config.market_min_coverage_ratio

    values: dict[str, object] = {
        "eligible_stock_count": eligible,
        "valid_return_count": valid_count,
        "coverage_ratio": coverage,
        "quality_status": "LOW_COVERAGE" if low_coverage else "PASS",
        "quality_flags": "coverage_below_threshold" if low_coverage else "",
    }
    if low_coverage:
        for name in (
            "ew_ret",
            "median_stock_rv5",
            "median_stock_rv20",
            "median_stock_rv60",
            "p25_stock_rv20",
            "p75_stock_rv20",
            "p90_stock_rv20",
            "dispersion_1d",
            "highvol_breadth_80",
            "highvol_breadth_90",
            "shock_up_breadth",
            "shock_down_breadth",
            "shock_abs_breadth",
        ):
            values[name] = np.nan
        return pd.Series(values)

    values.update(
        {
            "ew_ret": valid_returns.mean() if valid_count else np.nan,
            "median_stock_rv5": rv5.median() if len(rv5) else np.nan,
            "median_stock_rv20": rv20.median() if len(rv20) else np.nan,
            "median_stock_rv60": rv60.median() if len(rv60) else np.nan,
            "p25_stock_rv20": rv20.quantile(0.25) if len(rv20) else np.nan,
            "p75_stock_rv20": rv20.quantile(0.75) if len(rv20) else np.nan,
            "p90_stock_rv20": rv20.quantile(0.90) if len(rv20) else np.nan,
            "dispersion_1d": valid_returns.std(ddof=1) if valid_count >= 2 else np.nan,
            "highvol_breadth_80": (pct252 >= 0.80).mean() if len(pct252) else np.nan,
            "highvol_breadth_90": (pct252 >= 0.90).mean() if len(pct252) else np.nan,
            "shock_up_breadth": (shock >= config.shock_threshold).mean() if len(shock) else np.nan,
            "shock_down_breadth": (shock <= -config.shock_threshold).mean() if len(shock) else np.nan,
            "shock_abs_breadth": (shock.abs() >= config.shock_threshold).mean() if len(shock) else np.nan,
        }
    )
    return pd.Series(values)


def calculate_market_volatility(
    stock_volatility: pd.DataFrame,
    config: VolatilityConfig,
    *,
    universe_name: str,
    universe_scope: str,
    ewma_seed: float | None = None,
) -> pd.DataFrame:
    required = {"trade_date", "stock_code", "ret_1d", "rv20", "rv20_pct252", "shock_z20"}
    if missing := required - set(stock_volatility.columns):
        raise KeyError(f"stock_volatility missing: {sorted(missing)}")
    stock = stock_volatility.copy().sort_values(["trade_date", "stock_code"])
    daily = stock.groupby("trade_date", sort=True).apply(
        _cross_section, config=config, include_groups=False
    ).reset_index()
    daily.insert(1, "universe_name", universe_name)
    daily.insert(2, "universe_scope", universe_scope)

    for window in (5, 20, 60):
        daily[f"ew_rv{window}"] = _rolling_volatility(daily["ew_ret"], window, config)
    daily["rv5_rv20"] = _safe_ratio(daily["ew_rv5"], daily["ew_rv20"])
    daily["rv20_rv60"] = _safe_ratio(daily["ew_rv20"], daily["ew_rv60"])
    daily["dispersion_ma5"] = daily["dispersion_1d"].rolling(
        5, min_periods=ceil(5 * config.min_obs_ratio)
    ).mean()
    daily["dispersion_ma20"] = daily["dispersion_1d"].rolling(
        20, min_periods=ceil(20 * config.min_obs_ratio)
    ).mean()
    daily["dispersion_ewma20"] = _recursive_ewma(
        daily["dispersion_1d"],
        config.ewma_halflife,
        ceil(20 * config.min_obs_ratio),
        ewma_seed,
    )

    positive = daily["ew_ret"].clip(lower=0).pow(2)
    negative = daily["ew_ret"].clip(upper=0).pow(2)
    min_obs20 = ceil(20 * config.min_obs_ratio)
    daily["up_rv20"] = np.sqrt(
        config.annualization_days * positive.rolling(20, min_periods=min_obs20).mean()
    )
    daily["down_rv20"] = np.sqrt(
        config.annualization_days * negative.rolling(20, min_periods=min_obs20).mean()
    )
    daily["down_up_ratio"] = _safe_ratio(daily["down_rv20"], daily["up_rv20"])

    dates = daily["trade_date"].tolist()
    return_panel = stock.pivot_table(
        index="trade_date", columns="stock_code", values="ret_1d", aggfunc="last"
    ).reindex(dates)
    return_values = return_panel.to_numpy(dtype=float)
    for window in config.correlation_windows:
        correlations: list[float] = []
        counts: list[int] = []
        for index, trade_date in enumerate(dates):
            if index + 1 < window:
                correlations.append(np.nan)
                counts.append(0)
                continue
            values = return_values[index - window + 1 : index + 1]
            value, count = _implied_correlation_from_array(values)
            correlations.append(value)
            counts.append(count)
        daily[f"implied_corr{window}"] = correlations
        daily[f"implied_corr{window}_stock_count"] = counts
        daily.loc[daily["quality_status"] != "PASS", f"implied_corr{window}"] = np.nan

    percentile_sources = (
        "ew_rv20",
        "median_stock_rv20",
        "dispersion_ma5",
        "highvol_breadth_80",
        "implied_corr20",
        "down_rv20",
    )
    for source in percentile_sources:
        for window in config.percentile_windows:
            min_obs = ceil(window * config.percentile_min_obs_ratio)
            daily[f"{source}_pct{window}"] = calculate_rolling_percentile(
                daily[source], window, min_obs
            )

    columns = [
        "trade_date",
        "universe_name",
        "universe_scope",
        "eligible_stock_count",
        "valid_return_count",
        "coverage_ratio",
        "ew_ret",
        "ew_rv5",
        "ew_rv20",
        "ew_rv60",
        "rv5_rv20",
        "rv20_rv60",
        "median_stock_rv5",
        "median_stock_rv20",
        "median_stock_rv60",
        "p25_stock_rv20",
        "p75_stock_rv20",
        "p90_stock_rv20",
        "dispersion_1d",
        "dispersion_ma5",
        "dispersion_ma20",
        "dispersion_ewma20",
        "highvol_breadth_80",
        "highvol_breadth_90",
        "shock_up_breadth",
        "shock_down_breadth",
        "shock_abs_breadth",
        "implied_corr20",
        "implied_corr60",
        "implied_corr20_stock_count",
        "implied_corr60_stock_count",
        "up_rv20",
        "down_rv20",
        "down_up_ratio",
        *[
            f"{source}_pct{window}"
            for source in percentile_sources
            for window in config.percentile_windows
        ],
        "quality_status",
        "quality_flags",
    ]
    return daily[columns].reset_index(drop=True)


def calculate_sector_volatility(
    stock_volatility: pd.DataFrame,
    membership: pd.DataFrame,
    config: VolatilityConfig,
    *,
    universe_name: str,
    universe_scope: str,
) -> pd.DataFrame:
    """Calculate sector metrics from exact-date PIT/snapshot membership only."""
    required = {"trade_date", "sector_type", "sector_code", "sector_name", "stock_code"}
    if missing := required - set(membership.columns):
        raise KeyError(f"membership missing: {sorted(missing)}")
    membership_columns = ["trade_date", "sector_type", "sector_code", "sector_name", "stock_code"]
    joined = membership[membership_columns].merge(
        stock_volatility, on=["trade_date", "stock_code"], how="inner"
    )
    outputs: list[pd.DataFrame] = []
    for (sector_type, sector_code, sector_name), group in joined.groupby(
        ["sector_type", "sector_code", "sector_name"], sort=True
    ):
        market = calculate_market_volatility(
            group,
            config,
            universe_name=universe_name,
            universe_scope=universe_scope,
        )
        market.insert(1, "sector_type", sector_type)
        market.insert(2, "sector_code", sector_code)
        market.insert(3, "sector_name", sector_name)
        market = market.rename(
            columns={
                "ew_rv5": "rv5",
                "ew_rv20": "rv20",
                "ew_rv60": "rv60",
                "ew_rv20_pct252": "rv20_pct252",
                "ew_rv20_pct756": "rv20_pct756",
            }
        )
        too_small = market["eligible_stock_count"] < config.sector_min_stock_count
        small_fields = [
            "median_stock_rv5",
            "median_stock_rv20",
            "median_stock_rv60",
            "dispersion_1d",
            "dispersion_ma5",
            "dispersion_ma20",
            "highvol_breadth_80",
            "implied_corr20",
            "implied_corr60",
        ]
        market.loc[too_small, small_fields] = np.nan
        market.loc[too_small, "quality_status"] = "INSUFFICIENT_MEMBERS"
        market.loc[too_small, "quality_flags"] = "sector_stock_count_below_threshold"
        outputs.append(market)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()
