from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from qmt_local_data.config import DataConfig, load_config
from qmt_local_data.research import ResearchData


MARKET_CORE_METRICS: dict[str, str] = {
    "ew_rv5": "全市场等权收益 5 日实现波动率",
    "ew_rv20": "全市场等权收益 20 日实现波动率",
    "ew_rv60": "全市场等权收益 60 日实现波动率",
    "median_stock_rv5": "个股 5 日波动率中位数",
    "median_stock_rv20": "个股 20 日波动率中位数",
    "median_stock_rv60": "个股 60 日波动率中位数",
    "dispersion_ma5": "个股收益离散度 5 日均值",
    "dispersion_ma20": "个股收益离散度 20 日均值",
    "highvol_breadth_80": "高波动个股占比（历史分位 ≥ 80%）",
    "highvol_breadth_90": "极高波动个股占比（历史分位 ≥ 90%）",
    "shock_abs_breadth": "绝对波动冲击个股占比",
    "implied_corr20": "20 日隐含平均相关性",
    "implied_corr60": "60 日隐含平均相关性",
    "down_up_ratio": "下行/上行 20 日波动率比值",
    "coverage_ratio": "有效收益覆盖率",
}

SECTOR_CORE_METRICS: dict[str, str] = {
    "rv5": "板块 5 日实现波动率",
    "rv20": "板块 20 日实现波动率",
    "rv60": "板块 60 日实现波动率",
    "rv20_pct252": "板块 20 日波动率 252 日历史分位",
    "rv20_pct756": "板块 20 日波动率 756 日历史分位",
    "median_stock_rv5": "板块内个股 5 日波动率中位数",
    "median_stock_rv20": "板块内个股 20 日波动率中位数",
    "median_stock_rv60": "板块内个股 60 日波动率中位数",
    "dispersion_ma5": "板块内收益离散度 5 日均值",
    "dispersion_ma20": "板块内收益离散度 20 日均值",
    "highvol_breadth_80": "板块内高波动个股占比",
    "shock_abs_breadth": "板块内绝对冲击个股占比",
    "implied_corr20": "板块 20 日隐含平均相关性",
    "implied_corr60": "板块 60 日隐含平均相关性",
    "down_up_ratio": "板块下行/上行波动率比值",
    "coverage_ratio": "板块有效收益覆盖率",
}

PERCENT_COLUMNS = {
    "coverage_ratio",
    "highvol_breadth_80",
    "highvol_breadth_90",
    "shock_up_breadth",
    "shock_down_breadth",
    "shock_abs_breadth",
}


@dataclass(frozen=True)
class DashboardState:
    config_path: Path
    config: DataConfig
    database_path: Path
    status: dict[str, Any]
    universe_name: str

    @property
    def universe_scope(self) -> str:
        return str(self.status.get("universe_scope") or "UNKNOWN")


class DashboardRepository:
    """Small read-only query facade used by the Streamlit dashboard and tests."""

    def __init__(self, config_path: str | Path) -> None:
        resolved = Path(config_path).resolve()
        config = load_config(resolved)
        database_path = config.data_root / "database" / "qmt.duckdb"
        status_path = config.data_root / "metadata" / "database_status.json"
        status = (
            json.loads(status_path.read_text(encoding="utf-8"))
            if status_path.exists()
            else {}
        )
        scope = str(status.get("universe_scope") or "")
        universe_name = "CURRENT_SURVIVORS" if scope == "CURRENT_UNIVERSE_ONLY" else "ALL_A"
        self.state = DashboardState(resolved, config, database_path, status, universe_name)

    def database_exists(self) -> bool:
        return self.state.database_path.exists()

    def has_view(self, view: str) -> bool:
        if not self.database_exists():
            return False
        with duckdb.connect(str(self.state.database_path), read_only=True) as connection:
            return bool(
                connection.execute(
                    "SELECT COUNT(*) FROM information_schema.views "
                    "WHERE table_schema = 'main' AND table_name = ?",
                    [view],
                ).fetchone()[0]
            )

    def date_bounds(self, view: str) -> tuple[date, date] | None:
        if not self.has_view(view):
            return None
        with duckdb.connect(str(self.state.database_path), read_only=True) as connection:
            row = connection.execute(
                f'SELECT MIN(trade_date), MAX(trade_date) FROM "{view}"'
            ).fetchone()
        if not row or row[0] is None or row[1] is None:
            return None
        return _as_date(row[0]), _as_date(row[1])

    def market_universes(self) -> list[str]:
        if not self.has_view("market_vol_daily"):
            return []
        with duckdb.connect(str(self.state.database_path), read_only=True) as connection:
            rows = connection.execute(
                "SELECT DISTINCT universe_name FROM market_vol_daily ORDER BY universe_name"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def market_data(self, universe_name: str, start: date, end: date) -> pd.DataFrame:
        research = ResearchData(self.state.database_path)
        return research.get_market_volatility(universe_name, start, end)

    def index_catalog(self) -> pd.DataFrame:
        if not self.has_view("index_vol_daily"):
            return pd.DataFrame(columns=["index_code", "index_name"])
        with duckdb.connect(str(self.state.database_path), read_only=True) as connection:
            return connection.execute(
                "SELECT DISTINCT index_code, index_name FROM index_vol_daily "
                "ORDER BY index_code"
            ).fetchdf()

    def index_data(self, codes: list[str], start: date, end: date) -> pd.DataFrame:
        research = ResearchData(self.state.database_path)
        return research.get_index_volatility(codes, start, end)

    def sector_types(self) -> list[str]:
        if not self.has_view("sector_vol_daily"):
            return []
        with duckdb.connect(str(self.state.database_path), read_only=True) as connection:
            rows = connection.execute(
                "SELECT DISTINCT sector_type FROM sector_vol_daily ORDER BY sector_type"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def sectors(self, sector_type: str) -> pd.DataFrame:
        if not self.has_view("sector_vol_daily"):
            return pd.DataFrame(columns=["sector_code", "sector_name"])
        with duckdb.connect(str(self.state.database_path), read_only=True) as connection:
            return connection.execute(
                "SELECT DISTINCT sector_code, sector_name FROM sector_vol_daily "
                "WHERE sector_type = ? ORDER BY sector_name, sector_code",
                [sector_type],
            ).fetchdf()

    def sector_data(
        self,
        sector_type: str,
        sector_codes: list[str],
        start: date,
        end: date,
    ) -> pd.DataFrame:
        research = ResearchData(self.state.database_path)
        return research.get_sector_volatility(
            sector_type,
            sector_codes,
            self.state.universe_name,
            start,
            end,
        )


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value))


def _default_date_range(bounds: tuple[date, date]) -> tuple[date, date]:
    earliest, latest = bounds
    return max(earliest, latest - timedelta(days=3 * 366)), latest


def _numeric_metric_options(frame: pd.DataFrame, labels: dict[str, str]) -> list[str]:
    excluded = {
        "trade_date",
        "sector_code",
        "sector_name",
        "sector_type",
        "universe_name",
        "universe_scope",
        "quality_status",
        "quality_flags",
    }
    numeric = [
        column
        for column in frame.columns
        if column not in excluded and pd.api.types.is_numeric_dtype(frame[column])
    ]
    return sorted(numeric, key=lambda name: (name not in labels, labels.get(name, name)))


def _format_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return "—"
    number = float(value)
    if column in PERCENT_COLUMNS or "_pct" in column:
        return f"{number:.1%}"
    if column.startswith("rv") or "_rv" in column or "dispersion" in column:
        return f"{number:.2%}"
    if "count" in column:
        return f"{number:,.0f}"
    return f"{number:.3f}"


def _parse_script_config(argv: list[str]) -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", type=Path, default=Path("config/data_config.yaml"))
    args, _ = parser.parse_known_args(argv)
    return args.config


def launch_dashboard(config_path: str | Path, *, host: str, port: int) -> int:
    """Start Streamlit without importing it during normal library use."""
    if not 1 <= port <= 65535:
        raise ValueError("Dashboard port must be between 1 and 65535")
    from streamlit.web import cli as streamlit_cli

    script = Path(__file__).resolve()
    previous = sys.argv
    sys.argv = [
        "streamlit",
        "run",
        str(script),
        "--server.address",
        host,
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--",
        "--config",
        str(Path(config_path).resolve()),
    ]
    try:
        return int(streamlit_cli.main() or 0)
    finally:
        sys.argv = previous


def render_dashboard(config_path: str | Path) -> None:
    import plotly.express as px
    import plotly.graph_objects as go
    import streamlit as st

    st.set_page_config(page_title="QMT 波动率监测", page_icon="📈", layout="wide")
    repository = DashboardRepository(config_path)
    state = repository.state

    st.title("全市场、板块与宽基指数波动率监测")
    status_name = str(state.status.get("state") or "STATUS_MISSING")
    st.caption(
        f"数据库：{state.database_path}　｜　状态：{status_name}　｜　"
        f"股票池：{state.universe_name}"
    )
    if state.universe_scope == "CURRENT_UNIVERSE_ONLY":
        st.warning(
            "当前数据仅覆盖 CURRENT_SURVIVORS，存在幸存者偏差；界面不会将其标记为 ALL_A。",
            icon="⚠️",
        )

    market_tab, sector_tab, index_tab, status_tab = st.tabs(
        ["全市场", "板块", "宽基指数", "数据状态"]
    )
    with market_tab:
        _render_market(repository, st, px, go)
    with sector_tab:
        _render_sector(repository, st, px)
    with index_tab:
        _render_index(repository, st, px)
    with status_tab:
        _render_status(repository, st)


def _render_market(repository: DashboardRepository, st: Any, px: Any, go: Any) -> None:
    bounds = repository.date_bounds("market_vol_daily")
    if bounds is None:
        st.error("尚未发布 market_vol_daily，当前不能展示真实全市场波动率。")
        st.code(
            "qmt-local-data build-volatility --config config/data_config.yaml "
            "--start YYYY-MM-DD --end YYYY-MM-DD",
            language="powershell",
        )
        st.caption("必须先通过复权因子验证门禁；界面不会用未复权价格伪造指标。")
        return

    default_start, default_end = _default_date_range(bounds)
    universes = repository.market_universes()
    universe_labels = {
        "CURRENT_SURVIVORS": "沪深京 A 股（当前存续股票）",
        "SH_SZ_CURRENT_SURVIVORS": "沪深 A 股（当前存续股票）",
        "ALL_A": "沪深京 A 股（完整历史）",
        "SH_SZ_ALL_A": "沪深 A 股（完整历史）",
    }
    universe_name = st.selectbox(
        "市场统计口径",
        universes,
        format_func=lambda name: f"{universe_labels.get(name, name)} · {name}",
    )
    chosen = st.date_input(
        "全市场日期范围",
        value=(default_start, default_end),
        min_value=bounds[0],
        max_value=bounds[1],
        key="market_dates",
    )
    if not isinstance(chosen, (tuple, list)) or len(chosen) != 2:
        st.info("请选择开始和结束日期。")
        return
    frame = repository.market_data(
        universe_name, _as_date(chosen[0]), _as_date(chosen[1])
    )
    if frame.empty:
        st.info("所选日期范围没有全市场数据。")
        return
    frame = frame.sort_values("trade_date")
    latest = frame.iloc[-1]
    as_of = _as_date(latest["trade_date"])
    cards = st.columns(6)
    card_metrics = [
        ("ew_rv20", "市场 RV20"),
        ("ew_rv20_pct252", "RV20 历史分位"),
        ("highvol_breadth_80", "高波动广度"),
        ("implied_corr20", "隐含相关性 20"),
        ("dispersion_ma5", "收益离散度 MA5"),
        ("coverage_ratio", "有效覆盖率"),
    ]
    for column, label in card_metrics:
        cards[card_metrics.index((column, label))].metric(
            label,
            _format_value(column, latest.get(column)),
        )
    st.caption(f"最新交易日：{as_of.isoformat()}　｜　质量状态：{latest.get('quality_status', 'UNKNOWN')}")

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _line_figure(px, frame, ["ew_rv5", "ew_rv20", "ew_rv60"], MARKET_CORE_METRICS,
                         "全市场波动率期限结构", "年化波动率"),
            width="stretch",
        )
    with right:
        st.plotly_chart(_distribution_figure(go, frame), width="stretch")

    left, right = st.columns(2)
    with left:
        breadth_columns = [
            "highvol_breadth_80",
            "highvol_breadth_90",
            "shock_up_breadth",
            "shock_down_breadth",
            "shock_abs_breadth",
        ]
        st.plotly_chart(
            _line_figure(px, frame, breadth_columns, MARKET_CORE_METRICS,
                         "波动率广度与冲击广度", "股票占比"),
            width="stretch",
        )
    with right:
        st.plotly_chart(
            _line_figure(px, frame, ["implied_corr20", "implied_corr60"], MARKET_CORE_METRICS,
                         "隐含平均相关性", "相关系数"),
            width="stretch",
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            _line_figure(px, frame, ["dispersion_ma5", "dispersion_ma20", "dispersion_ewma20"],
                         MARKET_CORE_METRICS, "个股收益离散度", "日收益标准差"),
            width="stretch",
        )
    with right:
        st.plotly_chart(
            _line_figure(px, frame, ["up_rv20", "down_rv20", "down_up_ratio"],
                         MARKET_CORE_METRICS, "上行与下行波动", "波动率 / 比值"),
            width="stretch",
        )

    st.subheader("全部指标浏览")
    options = _numeric_metric_options(frame, MARKET_CORE_METRICS)
    default = [name for name in ("rv5_rv20", "rv20_rv60") if name in options]
    selected = st.multiselect(
        "选择任意已发布数值字段",
        options,
        default=default,
        format_func=lambda name: f"{MARKET_CORE_METRICS.get(name, name)} · {name}",
    )
    if selected:
        st.plotly_chart(
            _line_figure(px, frame, selected, MARKET_CORE_METRICS, "自选指标", "指标值"),
            width="stretch",
        )
    with st.expander("查看全市场明细数据"):
        st.dataframe(frame, width="stretch", hide_index=True)


def _render_sector(repository: DashboardRepository, st: Any, px: Any) -> None:
    bounds = repository.date_bounds("sector_vol_daily")
    if bounds is None:
        st.warning("板块页面已实现，但真实 sector_vol_daily 尚未发布。", icon="⛔")
        st.markdown(
            "需要先提供可靠的历史 PIT 行业成员或逐日真实快照。当前成分不能回填历史，"
            "因此本页面保持门禁状态，不展示伪造板块曲线。"
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"前置条件": "sector membership", "当前状态": "BLOCKED", "通过要求": "PIT 或逐日真实 snapshot"},
                    {"前置条件": "sector_vol_daily manifest", "当前状态": "未发布", "通过要求": "质量门通过后注册 active view"},
                    {"前置条件": "universe scope", "当前状态": repository.state.universe_scope, "通过要求": "逐行保留真实 scope"},
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        return

    sector_types = repository.sector_types()
    if not sector_types:
        st.info("sector_vol_daily 中没有可用的 sector_type。")
        return
    sector_type = st.selectbox("板块分类", sector_types)
    catalog = repository.sectors(sector_type)
    labels = {
        str(row.sector_code): f"{row.sector_name} · {row.sector_code}"
        for row in catalog.itertuples(index=False)
    }
    codes = list(labels)
    chosen_codes = st.multiselect(
        "选择板块（建议不超过 8 个）",
        codes,
        default=codes[: min(5, len(codes))],
        format_func=lambda code: labels.get(code, code),
    )
    default_start, default_end = _default_date_range(bounds)
    chosen_dates = st.date_input(
        "板块日期范围",
        value=(default_start, default_end),
        min_value=bounds[0],
        max_value=bounds[1],
        key="sector_dates",
    )
    if not chosen_codes or not isinstance(chosen_dates, (tuple, list)) or len(chosen_dates) != 2:
        st.info("请选择至少一个板块和完整日期范围。")
        return
    frame = repository.sector_data(
        sector_type,
        chosen_codes,
        _as_date(chosen_dates[0]),
        _as_date(chosen_dates[1]),
    )
    if frame.empty:
        st.info("所选板块和日期范围没有数据。")
        return
    frame = frame.sort_values(["trade_date", "sector_name"])
    latest_date = frame["trade_date"].max()
    latest = frame.loc[frame["trade_date"] == latest_date].copy()
    ranking_columns = [
        column
        for column in [
            "sector_name",
            "sector_code",
            "rv20",
            "rv20_pct252",
            "highvol_breadth_80",
            "implied_corr20",
            "down_up_ratio",
            "eligible_stock_count",
            "coverage_ratio",
            "quality_status",
        ]
        if column in latest.columns
    ]
    st.subheader(f"最新板块截面 · {_as_date(latest_date).isoformat()}")
    st.dataframe(
        latest[ranking_columns].sort_values("rv20", ascending=False, na_position="last"),
        width="stretch",
        hide_index=True,
    )

    themes = [
        ("rv20", "板块 20 日实现波动率", "年化波动率"),
        ("rv20_pct252", "板块波动率历史分位", "历史分位"),
        ("highvol_breadth_80", "板块内高波动广度", "股票占比"),
        ("implied_corr20", "板块隐含平均相关性", "相关系数"),
        ("dispersion_ma5", "板块内收益离散度", "日收益标准差"),
        ("down_up_ratio", "板块下行/上行波动率", "比值"),
    ]
    for offset in range(0, len(themes), 2):
        columns = st.columns(2)
        for column, theme in zip(columns, themes[offset : offset + 2]):
            metric, title, y_title = theme
            if metric not in frame.columns:
                continue
            with column:
                figure = px.line(
                    frame,
                    x="trade_date",
                    y=metric,
                    color="sector_name",
                    title=title,
                    labels={"trade_date": "交易日", metric: y_title, "sector_name": "板块"},
                )
                figure.update_layout(hovermode="x unified", legend_title_text="板块")
                st.plotly_chart(figure, width="stretch")

    st.subheader("板块全部指标浏览")
    options = _numeric_metric_options(frame, SECTOR_CORE_METRICS)
    selected_metric = st.selectbox(
        "选择任意已发布数值字段",
        options,
        format_func=lambda name: f"{SECTOR_CORE_METRICS.get(name, name)} · {name}",
    )
    figure = px.line(
        frame,
        x="trade_date",
        y=selected_metric,
        color="sector_name",
        title=SECTOR_CORE_METRICS.get(selected_metric, selected_metric),
        labels={"trade_date": "交易日", selected_metric: "指标值", "sector_name": "板块"},
    )
    figure.update_layout(hovermode="x unified", legend_title_text="板块")
    st.plotly_chart(figure, width="stretch")
    with st.expander("查看板块明细数据"):
        st.dataframe(frame, width="stretch", hide_index=True)


def _render_index(repository: DashboardRepository, st: Any, px: Any) -> None:
    bounds = repository.date_bounds("index_vol_daily")
    if bounds is None:
        st.warning("尚未发布 index_vol_daily。", icon="⛔")
        st.code(
            "qmt-local-data build-index-volatility --config config/data_config.yaml "
            "--start YYYY-MM-DD --end YYYY-MM-DD",
            language="powershell",
        )
        st.caption("该数据集使用官方指数收盘点位，不依赖股票复权因子。")
        return
    catalog = repository.index_catalog()
    labels = {
        str(row.index_code): f"{row.index_name} · {row.index_code}"
        for row in catalog.itertuples(index=False)
    }
    codes = list(labels)
    selected_codes = st.multiselect(
        "选择宽基指数",
        codes,
        default=codes,
        format_func=lambda code: labels.get(code, code),
    )
    default_start, default_end = _default_date_range(bounds)
    chosen = st.date_input(
        "指数日期范围",
        value=(default_start, default_end),
        min_value=bounds[0],
        max_value=bounds[1],
        key="index_dates",
    )
    if not selected_codes or not isinstance(chosen, (tuple, list)) or len(chosen) != 2:
        st.info("请选择至少一个指数和完整日期范围。")
        return
    frame = repository.index_data(
        selected_codes, _as_date(chosen[0]), _as_date(chosen[1])
    ).sort_values(["trade_date", "index_code"])
    if frame.empty:
        st.info("所选指数和日期范围没有数据。")
        return
    latest_date = frame["trade_date"].max()
    latest = frame[frame["trade_date"] == latest_date]
    columns = [
        name
        for name in (
            "index_name",
            "index_code",
            "close",
            "rv5",
            "rv20",
            "rv60",
            "rv20_pct252",
            "down_up_ratio",
            "shock_z20",
        )
        if name in latest.columns
    ]
    st.subheader(f"最新指数截面 · {_as_date(latest_date).isoformat()}")
    st.dataframe(latest[columns], width="stretch", hide_index=True)

    themes = [
        ("rv20", "指数 20 日实现波动率", "年化波动率"),
        ("rv20_pct252", "指数 RV20 的 252 日历史分位", "历史分位"),
        ("rv5_rv20", "指数短中期波动率比值", "比值"),
        ("down_up_ratio", "指数下行/上行波动率", "比值"),
    ]
    for offset in range(0, len(themes), 2):
        chart_columns = st.columns(2)
        for chart_column, (metric, title, unit) in zip(
            chart_columns, themes[offset : offset + 2]
        ):
            if metric not in frame.columns:
                continue
            with chart_column:
                figure = px.line(
                    frame,
                    x="trade_date",
                    y=metric,
                    color="index_name",
                    title=title,
                    labels={"trade_date": "交易日", metric: unit, "index_name": "指数"},
                )
                figure.update_layout(hovermode="x unified", legend_title_text="指数")
                st.plotly_chart(figure, width="stretch")

    options = _numeric_metric_options(frame, {})
    selected_metric = st.selectbox("指数全部指标浏览", options)
    figure = px.line(
        frame,
        x="trade_date",
        y=selected_metric,
        color="index_name",
        title=selected_metric,
        labels={"trade_date": "交易日", selected_metric: "指标值", "index_name": "指数"},
    )
    figure.update_layout(hovermode="x unified", legend_title_text="指数")
    st.plotly_chart(figure, width="stretch")
    with st.expander("查看指数明细数据"):
        st.dataframe(frame, width="stretch", hide_index=True)


def _render_status(repository: DashboardRepository, st: Any) -> None:
    state = repository.state
    rows = [
        {"项目": "数据库文件", "状态": "存在" if repository.database_exists() else "缺失", "详情": str(state.database_path)},
        {"项目": "数据库状态", "状态": str(state.status.get("state") or "缺失"), "详情": state.universe_scope},
        {"项目": "全市场指标", "状态": "READY" if repository.has_view("market_vol_daily") else "BLOCKED", "详情": "market_vol_daily"},
        {"项目": "板块指标", "状态": "READY" if repository.has_view("sector_vol_daily") else "BLOCKED", "详情": "sector_vol_daily"},
        {"项目": "宽基指数指标", "状态": "READY" if repository.has_view("index_vol_daily") else "BLOCKED", "详情": "index_vol_daily"},
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption("仪表盘全程以只读方式访问 DuckDB，不会写入或切换 active manifest。")
    with st.expander("查看 database_status.json"):
        st.json(state.status or {"error": "database_status.json 不存在"})


def _line_figure(
    px: Any,
    frame: pd.DataFrame,
    columns: list[str],
    labels: dict[str, str],
    title: str,
    y_title: str,
) -> Any:
    available = [column for column in columns if column in frame.columns]
    long = frame.melt(
        id_vars="trade_date",
        value_vars=available,
        var_name="metric",
        value_name="value",
    )
    long["指标"] = long["metric"].map(lambda name: labels.get(name, name))
    figure = px.line(
        long,
        x="trade_date",
        y="value",
        color="指标",
        title=title,
        labels={"trade_date": "交易日", "value": y_title},
    )
    figure.update_layout(hovermode="x unified", legend_title_text="指标")
    return figure


def _distribution_figure(go: Any, frame: pd.DataFrame) -> Any:
    figure = go.Figure()
    x = frame["trade_date"]
    figure.add_trace(
        go.Scatter(x=x, y=frame["p75_stock_rv20"], mode="lines", line={"width": 0},
                   name="P75", hovertemplate="P75 %{y:.2%}<extra></extra>")
    )
    figure.add_trace(
        go.Scatter(x=x, y=frame["p25_stock_rv20"], mode="lines", fill="tonexty",
                   line={"width": 0}, name="P25–P75", hovertemplate="P25 %{y:.2%}<extra></extra>")
    )
    for column, label in (
        ("median_stock_rv5", "RV5 中位数"),
        ("median_stock_rv20", "RV20 中位数"),
        ("median_stock_rv60", "RV60 中位数"),
    ):
        if column in frame.columns:
            figure.add_trace(
                go.Scatter(
                    x=x,
                    y=frame[column],
                    mode="lines",
                    name=label,
                    hovertemplate=f"{label} %{{y:.2%}}<extra></extra>",
                )
            )
    figure.add_trace(
        go.Scatter(x=x, y=frame["p90_stock_rv20"], mode="lines", name="P90",
                   hovertemplate="P90 %{y:.2%}<extra></extra>")
    )
    figure.update_layout(
        title="个股波动率横截面分布",
        xaxis_title="交易日",
        yaxis_title="年化波动率",
        hovermode="x unified",
        legend_title_text="分布统计",
    )
    return figure


if __name__ == "__main__":
    render_dashboard(_parse_script_config(sys.argv[1:]))
