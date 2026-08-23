#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal MiniQMT/xtdata capability probe.

Policy: one valid sample is enough to mark a data category feasible.
This is NOT a bulk data downloader, historical completeness check, or performance test.
It lists every interface on the official XtData main documentation page,
including explicit SKIP records for unsafe or prerequisite-dependent calls.
MiniQMT must be running and logged in on this Windows machine.
"""

from __future__ import annotations

import argparse
import inspect
import importlib.metadata
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

RESULTS: list[dict[str, Any]] = []
OFFICIAL_DOC_URL = "https://dict.thinktrader.net/nativeApi/xtdata.html"
REVIEW_SCOPE_URL = "https://github.com/DiiShan/qmt/issues/1#issuecomment-5384072265"
ALLOWED_STATUSES = {"PASS", "EMPTY", "NO_PERMISSION", "UNSUPPORTED", "ERROR", "SKIP", "NOT_TESTED"}


def domain_zh(category: str, name: str) -> str:
    """Describe the asset/market domain to which a checklist item applies."""
    domains = {
        "environment": "Python / 本机运行环境",
        "connection": "所有 XtData 资产",
        "inventory": "所有行情周期与特色数据",
        "l1_market": "沪深 A 股 Level 1",
        "l1_api": "Level 1 历史行情",
        "l1_download": "Level 1 本地缓存",
        "realtime": "沪深 A 股实时行情",
        "realtime_helper": "所有实时订阅",
        "calendar": "交易所日历",
        "metadata": "证券、板块与指数",
        "corporate_action": "股票除权除息",
        "financial": "上市公司财务数据",
        "ipo": "新股 / 新债申购",
        "etf": "ETF",
        "convertible_bond": "可转债",
        "option": "沪深证券期权",
        "option_sz": "深交所证券期权",
        "index_option": "中金所金融期权",
        "future": "中金所金融期货",
        "commodity_discovery": "上期所 / 大商所 / 郑商所 / 能源中心 / 广期所",
        "commodity_future": "商品期货",
        "commodity_option": "商品期权",
        "level2": "沪深 A 股 Level 2",
        "special_period": "投研版特色数据",
        "official_formula": "投研端公式",
        "official_sector_write": "本地自定义板块",
        "official_download": "本地数据缓存",
        "official_extension": "官网版本记录中的扩展接口",
        "compatibility": "MiniQMT / xtquant 数据接口兼容性",
        "etf_market": "ETF 通用行情与 IOPV",
        "convertible_bond_market": "可转债通用行情",
        "bse_market": "北京证券交易所股票",
        "index_market": "指数通用行情",
        "market_scope": "港股 / 美股 / 外盘行情",
        "subscription_callback": "实时行情回调证据",
        "option_helper": "期权合约与标的辅助数据",
        "status_monitor": "XtData 行情连接状态",
        "orderflow": "A 股订单流增值数据",
        "historical_st": "A 股历史 ST 状态",
    }
    return domains.get(category, "XtData 通用")


def returned_fields(value: Any) -> list[str]:
    """Extract a stable field inventory without retaining additional data rows."""
    if value is None:
        return []
    columns = getattr(value, "columns", None)
    if columns is not None:
        try:
            return [str(column) for column in columns]
        except Exception:
            pass
    names = getattr(getattr(value, "dtype", None), "names", None)
    if names:
        return [str(name) for name in names]
    if isinstance(value, dict):
        if value and all(not isinstance(item, (dict, list, tuple, set)) and not hasattr(item, "columns") for item in value.values()):
            return [str(key) for key in value.keys()]
        for child in value.values():
            fields = returned_fields(child)
            if fields:
                return fields
        return [str(key) for key in value.keys()]
    if isinstance(value, (list, tuple)) and value:
        return returned_fields(value[0])
    return []


SENSITIVE_KEYS = {
    "account", "accountid", "account_id", "address", "addr", "ip", "port",
    "password", "passwd", "phone", "mobile", "token", "username", "user",
    "path", "datadir", "data_dir", "miniqmt_dir",
}


def sanitize_value(value: Any) -> Any:
    """Remove private connection/configuration values before retaining evidence."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("-", "_")
            if normalized in SENSITIVE_KEYS or any(token in normalized for token in ["account", "password", "token", "address"]):
                cleaned[key_text] = "<REDACTED>"
            else:
                cleaned[key_text] = sanitize_value(child)
        return cleaned
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item) for item in value)
    if isinstance(value, str):
        value = re.sub(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}:\d+(?!\d)", "<REDACTED_ENDPOINT>", value)
        value = re.sub(r"[A-Za-z]:\\[^\r\n]+(?:userdata|userdata_mini)[^\r\n]*", "<REDACTED_LOCAL_PATH>", value, flags=re.IGNORECASE)
    return value


def description_zh(category: str, name: str) -> str:
    """Return a plain-Chinese explanation for every report checklist item."""
    exact = {
        ("environment", "import xtquant.xtdata"): "确认当前 Python 环境能够导入 xtquant 行情模块，这是调用 MiniQMT 数据接口的前提。",
        ("connection", "get_instrument_detail(stock)"): "读取股票合约的名称、市场、交易单位等基础资料，用于验证 MiniQMT 基础连接。",
        ("connection", "get_instrument_type(stock)"): "判断指定证券属于股票、基金、债券等哪一种合约类型。",
        ("inventory", "get_period_list"): "查询当前客户端公布的行情周期和特色数据类型清单。",
        ("l1_api", "get_market_data 1d one sample"): "使用官方通用行情读取接口，从本地缓存取得一根股票日线。",
        ("l1_api", "get_local_data 1d one sample"): "绕过订阅逻辑，直接从本地行情文件取得一根股票日线。",
        ("official_download", "download_history_data 1d minimal window"): "通过单标的历史下载接口补充最小日线窗口，验证下载链路是否可用。",
        ("official_download", "download_history_data2"): "批量下载多个证券的历史行情并支持进度 callback；官网语义为同步完成后返回，本次不重复执行。",
        ("official_download", "download_history_contracts"): "下载历史或已到期合约资料；属于批量元数据操作，本次不执行。",
        ("realtime", "get_full_tick one symbol"): "读取一个证券当前可见的完整盘口快照。",
        ("realtime", "get_full_kline 1m one bar"): "读取客户端实时缓存中的最新一根一分钟 K 线。",
        ("realtime", "subscribe_quote + unsubscribe_quote"): "订阅一个证券的一档行情，确认返回有效订阅号后立即取消。",
        ("realtime", "subscribe_whole_quote one code + unsubscribe_quote"): "订阅单个证券的全推行情，确认订阅成功后立即取消。",
        ("realtime_helper", "run"): "进入 xtdata 的阻塞消息接收循环，通常用于让订阅回调持续运行。",
        ("calendar", "get_holidays one sample"): "读取一个法定节假日样本，用于交易日判断。",
        ("calendar", "download_holiday_data"): "从服务端补充或更新本地节假日数据。",
        ("calendar", "get_holidays one sample after download"): "补充节假日数据后再次读取一个样本，确认缓存是否已生效。",
        ("calendar", "get_trading_calendar one sample"): "按市场读取包含交易日属性的交易日历样本。",
        ("calendar", "get_trading_dates one sample"): "读取指定市场的一天交易日期。",
        ("metadata", "get_sector_list one sample"): "读取客户端已有板块清单中的一个板块。",
        ("official_download", "download_sector_data"): "更新本地行业、概念等板块基础资料。",
        ("metadata", "get_stock_list_in_sector one sample"): "读取某个板块中的一个成分证券。",
        ("metadata", "get_index_weight one sample"): "读取沪深 300 指数中一个成分股及其权重。",
        ("official_download", "download_index_weight"): "批量更新指数成分权重数据。",
        ("corporate_action", "get_divid_factors one sample"): "读取一个除权除息因子，用于复权价格计算。",
        ("financial", "download_financial_data2 minimal symbol"): "使用带时间范围和进度 callback 的同步接口，为单个股票补充官方八类财务报表数据。",
        ("official_download", "download_financial_data"): "旧版同步财务下载接口；本机曾出现长时间等待，本次使用同为同步语义且带进度 callback 的第二版接口。",
        ("ipo", "get_ipo_info one sample"): "读取当前新股或新债申购信息样本。",
        ("etf", "ETF instrument detail one sample"): "读取 ETF 合约基础资料，确认该 ETF 代码有效。",
        ("etf", "get_etf_info one sample"): "读取 ETF 申购赎回清单等专用信息。",
        ("official_download", "download_etf_info"): "批量更新 ETF 申购赎回基础信息。",
        ("convertible_bond", "get_cb_info one contract"): "读取一个有效可转债的转股价、转股期等专用资料。",
        ("convertible_bond", "download_cb_data metadata"): "更新本地可转债专用基础资料。",
        ("convertible_bond", "get_cb_info one contract after download"): "更新可转债资料后再次读取同一合约，确认缓存是否生效。",
        ("option", "instrument detail one contract"): "读取一个当前期权合约的基础资料，确认合约代码有效。",
        ("option", "option detail one contract"): "读取期权行权价、到期日、认购认沽方向等专用属性。",
        ("option", "1d one bar"): "读取一个当前期权合约的一根日线行情。",
        ("future", "instrument detail one contract"): "读取一个当前期货合约的基础资料，确认合约代码有效。",
        ("future", "1d one bar"): "读取一个当前期货合约的一根日线行情。",
        ("level2", "l2quote: one sample"): "读取 Level 2 十档盘口和委托队列汇总行情样本。",
        ("level2", "l2quoteaux: one sample"): "读取 Level 2 扩展盘口统计信息样本。",
        ("level2", "l2order: one sample"): "读取 Level 2 逐笔委托数据样本。",
        ("level2", "l2transaction: one sample"): "读取 Level 2 逐笔成交数据样本。",
        ("level2", "l2orderqueue: one sample"): "读取 Level 2 买卖价位委托队列明细样本。",
        ("official_formula", "subscribe_formula"): "订阅研究终端中已配置公式的实时计算结果。",
        ("official_formula", "unsubscribe_formula"): "取消此前建立的研究公式订阅。",
        ("official_formula", "call_formula"): "对指定证券调用一次已配置的研究公式。",
        ("official_formula", "generate_index_data"): "使用研究公式生成自定义指标数据。",
        ("official_formula", "call_formula_batch"): "批量调用研究终端中已配置的公式。",
        ("official_sector_write", "create_sector_folder"): "在客户端新建自定义板块文件夹，会修改本地板块配置。",
        ("official_sector_write", "create_sector"): "创建一个自定义板块，会修改本地板块配置。",
        ("official_sector_write", "add_sector"): "向自定义板块加入证券，会修改板块成分。",
        ("official_sector_write", "remove_stock_from_sector"): "从自定义板块删除证券，会修改板块成分。",
        ("official_sector_write", "remove_sector"): "删除一个自定义板块，会修改本地板块配置。",
        ("official_sector_write", "reset_sector"): "重置自定义板块的全部成分，会覆盖本地板块配置。",
        ("official_extension", "get_trading_time"): "读取指定合约的交易时段；这是官网版本记录中的接口名。",
        ("official_extension", "get_trading_period installed alias"): "调用当前安装包提供的交易时段兼容接口，读取合约交易时间段。",
        ("official_extension", "reconnect"): "重新选择或指定 MiniQMT 行情连接地址；会改变当前连接，因此仅检查安装可用性。",
        ("official_extension", "get_l2thousand_queue"): "读取 Level 2 千档委托队列数据。",
        ("official_extension", "subscribe_l2thousand + unsubscribe"): "订阅 Level 2 千档盘口数据，确认订阅后立即取消。",
        ("official_extension", "subscribe_l2thousand_queue + unsubscribe"): "订阅 Level 2 千档委托队列数据，确认订阅后立即取消。",
    }
    if (category, name) in exact:
        return exact[(category, name)]

    if category == "l1_market":
        period = name.split(":", 1)[0].removeprefix("get_market_data_ex ")
        period_names = {
            "tick": "逐笔成交/快照",
            "1m": "一分钟 K 线",
            "5m": "五分钟 K 线",
            "15m": "十五分钟 K 线",
            "30m": "三十分钟 K 线",
            "1h": "一小时 K 线",
            "1d": "日 K 线",
            "1w": "周 K 线",
            "1mon": "月 K 线",
            "1q": "季度 K 线",
            "1hy": "半年 K 线",
            "1y": "年 K 线",
        }
        return f"读取一个股票的单条{period_names.get(period, period + '周期行情')}，验证该 L1 周期是否可用。"

    if category == "financial" and name.startswith("get_financial_data "):
        table = name.removeprefix("get_financial_data ").split(":", 1)[0]
        table_names = {
            "Balance": "资产负债表",
            "Income": "利润表",
            "CashFlow": "现金流量表",
            "Capital": "股本结构表",
            "HolderNum": "股东户数表",
            "Top10Holder": "十大股东表",
            "Top10FlowHolder": "十大流通股东表",
            "PershareIndex": "每股指标表",
        }
        return f"读取单个股票的一条{table_names.get(table, table)}记录。"

    if category == "commodity_discovery":
        return f"从 MiniQMT 的{name.split(' ', 1)[0]}合约清单中选择当前有效且有成交的商品期货及对应商品期权。"

    if category in {"option", "option_sz", "index_option", "future", "commodity_future", "commodity_option"}:
        asset_names = {
            "option": "证券期权",
            "option_sz": "深市证券期权",
            "index_option": "中金所金融期权",
            "future": "金融期货",
            "commodity_future": "商品期货",
            "commodity_option": "商品期权",
        }
        asset = asset_names[category]
        code = name.split(" ", 1)[0]
        if name == "current representative contract":
            return f"从运行时合约清单选择一个未到期的当前{asset}代表代码，避免使用过期或臆造合约。"
        if name.endswith("instrument detail"):
            return f"读取 {asset} {code} 的交易所、品种、到期日、合约乘数等基础资料。"
        if name.endswith("instrument type"):
            return f"判断 {code} 是否被客户端识别为正确的{asset}类型。"
        if "get_option_detail_data" in name or name.endswith("option detail"):
            return f"读取商品或证券期权 {code} 的标的、行权价、认购认沽方向和到期日等专用属性。"
        if "1d one sample" in name:
            return f"读取 {asset} {code} 的一根历史日线，验证日频历史行情。"
        if "1m one sample" in name:
            return f"读取 {asset} {code} 的一根历史一分钟 K 线，验证日内行情。"
        if "tick one sample" in name:
            return f"读取 {asset} {code} 的一条历史 tick，验证逐笔/快照行情。"
        if "download " in name:
            period = name.rsplit(" ", 1)[-1]
            return f"为 {asset} {code} 补充最小窗口的 {period} 历史行情。"
        if name.endswith("full tick snapshot"):
            return f"读取 {asset} {code} 当前可见的完整盘口快照。"
        if name.endswith("tick callback"):
            return f"使用 count=0 订阅 {asset} {code} 的实时 tick；只有 time/stime 通过新鲜度校验才证明实时可用。"
        if name.endswith("subscribe + unsubscribe"):
            return f"订阅 {asset} {code} 的 tick 行情，确认返回有效订阅号后立即取消。"

    if category == "orderflow":
        if name.startswith("download "):
            return "为一个 A 股补充最小窗口的订单流一分钟基础数据；命令成功不等于已有订单流权限或样本。"
        if name == "orderflow1m one sample":
            return "读取一条订单流一分钟基础数据，验证当前账号能否实际取得订单流样本。"
        return "列出由订单流一分钟基础数据合成的周期；按一类一笔原则不重复读取。"

    if category == "historical_st":
        if name == "download_his_st_data":
            return "下载历史 ST 状态专用数据文件；这是独立 helper，不等同于 specialtreatment period。"
        return "读取一只历史上确有 ST 记录股票的 ST 状态起止区间。"

    if category == "special_period" and "snapshotindex" in name:
        return "按官网要求使用 count=0 先订阅 VIP 快照指标，并等待一条通过 time/stime 新鲜度校验的 callback。"

    category_explanations = {
        "compatibility": "记录或调用影响 XtData 数据可用性的客户端版本、后端 handler 与 schema 兼容性证据。",
        "etf_market": "验证 ETF 的通用历史行情、快照、实时回调或 IOPV 特色数据能否取得一个样本。",
        "convertible_bond_market": "验证当前可转债的通用历史行情、快照和实时回调，不以专用元数据接口代替行情结论。",
        "bse_market": "验证一只当前北交所股票的合约资料、历史行情、快照和实时回调。",
        "index_market": "验证指数本身的通用行情；该能力与指数成分权重是两个不同数据类别。",
        "subscription_callback": "建立最小实时订阅并等待第一条合法回调，收到后立即取消；正订阅号本身不等于实时数据可用。",
        "option_helper": "验证官方新增的期权历史合约、标的映射和合约列表辅助接口。",
        "status_monitor": "注册 XtData 行情连接状态监听；只有实际收到一条状态变化回调才形成数据样本。",
        "special_period": "按该特色 period 的适用市场读取一条数据，用于区分有数据、无权限和后端未实现。",
        "market_scope": "明确记录尚未取得服务或合法代表样本的市场，避免把未测试误写成无权限。",
        "official_extension": "验证官网版本记录新增的 XtData 只读接口是否存在、后端是否实现以及能否返回数据。",
    }
    if category in category_explanations:
        return category_explanations[category]

    return f"检查 XtData 的“{name}”能力是否存在、是否有权限以及能否返回有效样本。"


def empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, bytes, list, tuple, set, dict)):
        if len(value) == 0:
            return True
        if isinstance(value, dict):
            return all(empty(v) for v in value.values())
        return False
    flag = getattr(value, "empty", None)
    if isinstance(flag, bool):
        return flag
    try:
        return len(value) == 0
    except Exception:
        return False


def first_sample(value: Any) -> Any:
    """Keep/report only one representative sample where practical."""
    if value is None:
        return None
    if isinstance(value, dict):
        if not value:
            return value
        key = next(iter(value))
        return {key: first_sample(value[key])}
    if isinstance(value, (list, tuple)):
        return value[:1]
    if isinstance(value, set):
        return list(value)[:1]
    if hasattr(value, "head"):
        try:
            return value.head(1)
        except Exception:
            pass
    return value


def summary(value: Any) -> str:
    value = sanitize_value(first_sample(value))
    shape = getattr(value, "shape", None)
    if shape is not None:
        return f"{type(value).__name__}(shape={shape})"
    text = repr(value)
    return text[:500]


def classify(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(x in text for x in ["permission", "unauthorized", "forbidden", "权限", "未授权", "vip"]):
        return "NO_PERMISSION"
    if isinstance(exc, TypeError) and "unsupported operand type" in text:
        return "ERROR"
    if any(
        x in text
        for x in [
            "has no attribute",
            "unsupported",
            "not supported",
            "unknown period",
            "invalid period",
            "function not realize",
            "errorid\" : 300000",
            "errorid\" : 200005",
            "未找到处理函数",
            "不支持",
        ]
    ):
        return "UNSUPPORTED"
    return "ERROR"


def reason_code_for(status: str, note: str = "", value: Any = None) -> str:
    text = note.lower()
    if "function not realize" in text or "300000" in text or "未找到处理函数" in text:
        return "BACKEND_HANDLER_MISSING_OR_EDITION_UNAVAILABLE"
    if "invalid period" in text or "unknown period" in text:
        return "INVALID_PERIOD_OR_HANDLER_MISSING"
    if "has no attribute" in text or "api is absent" in text or "api not present" in text or "name is absent" in text:
        return "PY_API_ABSENT"
    if "typeerror" in text and ("nonetype" in text or "unsupported operand type" in text):
        return "CLIENT_SCHEMA_MISMATCH"
    if status == "NO_PERMISSION":
        return "ENTITLEMENT_DENIED"
    if status == "EMPTY":
        return "NO_SAMPLE_RETURNED"
    if status == "PASS":
        return "VALID_SAMPLE_RETURNED"
    if status == "SKIP":
        return "PREREQUISITE_OR_SAFETY_SKIP"
    if status == "NOT_TESTED":
        return "NOT_TESTED"
    if status == "UNSUPPORTED":
        return "CLIENT_UNSUPPORTED"
    return "CALL_ERROR"


def official_prerequisite(category: str, name: str) -> str:
    """Document official edition/data-service prerequisites separately from errors."""
    key = name.lower()
    if any(token in key for token in ["get_current_connect_sub_info", "get_all_sub_info", "get_order_rank", "get_sector_info"]):
        return "投研版"
    if any(token in key for token in ["get_transactioncount", "snapshotindex", "limitupperformance", "historymaincontract"]):
        return "VIP / 增值数据"
    if "orderflow" in key:
        return "订单流版"
    if (
        any(token in key for token in ["l2quote", "l2order", "l2transaction", "l2thousand", "thousand"])
        or re.search(r"(?:^|[^a-z0-9])l2(?:[^a-z0-9]|$)", key)
    ):
        return "Level 2"
    if "brokerqueue" in key or "broker_queue" in key:
        return "港股 Level 2"
    if category in {"official_formula"} or "formula" in key:
        return "投研版 + 已配置公式"
    if "etfiopv" in key:
        return "ETF IOPV 数据服务"
    return "普通 / 官方未注明额外版本"


def capability_metadata(status: str, has_return_value: bool, has_valid_sample: bool) -> dict[str, Any]:
    if status == "UNSUPPORTED":
        api_available: bool | None = False
    elif status in {"PASS", "EMPTY", "NO_PERMISSION"}:
        api_available = True
    else:
        api_available = None

    if status == "NO_PERMISSION":
        permission = "DENIED"
    elif status == "PASS":
        permission = "SUFFICIENT"
    elif status in {"SKIP", "NOT_TESTED"}:
        permission = "NOT_TESTED"
    else:
        permission = "UNKNOWN"

    return {
        "api_available": api_available,
        "permission": permission,
        "has_return_value": has_return_value,
        "has_valid_sample": has_valid_sample,
    }


def record(category: str, name: str, status: str, note: str, sample: str = "") -> None:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Unsupported report status: {status}")
    has_value = bool(sample)
    item = {
        "category": category,
        "test": name,
        "domain_zh": domain_zh(category, name),
        "description_zh": description_zh(category, name),
        "official_prerequisite": official_prerequisite(category, name),
        "returned_fields": [],
        "status": status,
        "elapsed_ms": 0,
        "sample": sample,
        "note": note,
        "reason_code": reason_code_for(status, note),
        **capability_metadata(status, has_value, status == "PASS"),
    }
    RESULTS.append(item)
    print(f"[{status:13}] {category:20} {name} {sample or note}")


def probe(category: str, name: str, fn: Callable[[], Any], validator: Callable[[Any], bool] | None = None, note: str = "") -> Any:
    started = time.perf_counter()
    try:
        value = fn()
        ok = validator(value) if validator else not empty(value)
        status = "PASS" if ok else "EMPTY"
        item = {
            "category": category,
            "test": name,
            "domain_zh": domain_zh(category, name),
            "description_zh": description_zh(category, name),
            "official_prerequisite": official_prerequisite(category, name),
            "returned_fields": returned_fields(value),
            "status": status,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "sample": summary(value) if not empty(value) else "",
            "note": note,
            "reason_code": reason_code_for(status, note, value),
            **capability_metadata(status, not empty(value), ok),
        }
        lowered_name = name.lower()
        is_download_command = (
            lowered_name.startswith("download ") or " download " in lowered_name
        ) and "after download" not in lowered_name
        if status == "PASS" and is_download_command:
            item["reason_code"] = "DOWNLOAD_COMMAND_ACCEPTED"
            item["permission"] = "UNKNOWN"
            item["has_valid_sample"] = False
        RESULTS.append(item)
        print(f"[{status:13}] {category:20} {name} {item['sample'] or note}")
        return value
    except Exception as exc:
        status = classify(exc)
        item = {
            "category": category,
            "test": name,
            "domain_zh": domain_zh(category, name),
            "description_zh": description_zh(category, name),
            "official_prerequisite": official_prerequisite(category, name),
            "returned_fields": [],
            "status": status,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "sample": "",
            "note": f"{type(exc).__name__}: {exc}",
            "reason_code": reason_code_for(status, f"{type(exc).__name__}: {exc}"),
            **capability_metadata(status, False, False),
        }
        if item["reason_code"] in {
            "BACKEND_HANDLER_MISSING_OR_EDITION_UNAVAILABLE",
            "INVALID_PERIOD_OR_HANDLER_MISSING",
        }:
            item["api_available"] = True
        RESULTS.append(item)
        print(f"[{status:13}] {category:20} {name} {item['note']}")
        return None


def skip(category: str, name: str, note: str) -> None:
    record(category, name, "SKIP", note)


def one_market(xtdata: Any, code: str, period: str, start: str = "") -> Any:
    return xtdata.get_market_data_ex(
        field_list=[],
        stock_list=[code],
        period=period,
        start_time=start,
        end_time="",
        count=1,
        dividend_type="none",
        fill_data=True,
    )


def one_market_legacy(xtdata: Any, code: str, period: str, start: str = "") -> Any:
    return xtdata.get_market_data(
        field_list=[],
        stock_list=[code],
        period=period,
        start_time=start,
        end_time="",
        count=1,
        dividend_type="none",
        fill_data=True,
    )


def one_local_market(xtdata: Any, code: str, period: str, start: str = "") -> Any:
    return xtdata.get_local_data(
        field_list=[],
        stock_list=[code],
        period=period,
        start_time=start,
        end_time="",
        count=1,
        dividend_type="none",
        fill_data=True,
    )


def _timestamp_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        number = int(value)
        if number >= 10**12:
            return number
        if number >= 10**9:
            return number * 1000
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            if len(text) in {14, 17} and text.startswith(("19", "20")):
                try:
                    base = int(datetime.strptime(text[:14], "%Y%m%d%H%M%S").timestamp() * 1000)
                    return base + (int(text[14:17]) if len(text) == 17 else 0)
                except ValueError:
                    return None
            if len(text) == 13:
                return int(text[:13])
            if len(text) == 10:
                return int(text) * 1000
    return None


def extract_callback_timestamp_ms(value: Any) -> int | None:
    """Find the first usable time/stime field in nested callback payloads."""
    if isinstance(value, dict):
        for key in ["time", "stime"]:
            if key in value:
                parsed = _timestamp_ms(value[key])
                if parsed is not None:
                    return parsed
        for child in value.values():
            parsed = extract_callback_timestamp_ms(child)
            if parsed is not None:
                return parsed
    elif isinstance(value, (list, tuple)):
        for child in value:
            parsed = extract_callback_timestamp_ms(child)
            if parsed is not None:
                return parsed
    return None


def subscribe_factory_until_fresh_callback(
    xtdata: Any,
    subscribe_factory: Callable[[Callable[[Any], None]], Any],
    timeout_seconds: float,
    freshness_tolerance_seconds: float,
) -> dict[str, Any]:
    """Accept only callbacks whose time/stime is fresh relative to subscription start."""
    subscribe_started_at_ms = int(time.time() * 1000)
    any_received: list[Any] = []
    fresh_received: list[Any] = []
    callback_timestamps: list[int] = []

    def on_data(data: Any) -> None:
        if empty(data):
            return
        sample = first_sample(data)
        callback_time_ms = extract_callback_timestamp_ms(sample)
        if not any_received:
            any_received.append(sample)
        if callback_time_ms is not None:
            callback_timestamps.append(callback_time_ms)
            now_ms = int(time.time() * 1000)
            lower_bound = subscribe_started_at_ms - int(max(freshness_tolerance_seconds, 0) * 1000)
            if lower_bound <= callback_time_ms <= now_ms + 60_000 and not fresh_received:
                fresh_received.append(sample)

    seq = subscribe_factory(on_data)
    result = {
        "subscription_id": seq,
        "subscription_accepted": isinstance(seq, int) and seq > 0,
        "subscribe_started_at_ms": subscribe_started_at_ms,
        "callback_received": False,
        "fresh_callback_received": False,
        "callback_time_ms": None,
        "callback_sample": None,
        "unsubscribed": False,
    }
    try:
        deadline = time.monotonic() + max(timeout_seconds, 0)
        while not fresh_received and time.monotonic() < deadline:
            time.sleep(0.05)
        result["callback_received"] = bool(any_received)
        result["fresh_callback_received"] = bool(fresh_received)
        result["callback_time_ms"] = callback_timestamps[-1] if callback_timestamps else None
        if fresh_received:
            result["callback_sample"] = sanitize_value(fresh_received[0])
        elif any_received:
            result["callback_sample"] = sanitize_value(any_received[0])
        return result
    finally:
        if isinstance(seq, int) and seq > 0 and hasattr(xtdata, "unsubscribe_quote"):
            xtdata.unsubscribe_quote(seq)
            result["unsubscribed"] = True


def subscribe_until_callback(
    xtdata: Any,
    code: str,
    period: str,
    timeout_seconds: float,
    freshness_tolerance_seconds: float,
    method_name: str = "subscribe_quote",
) -> dict[str, Any]:
    method = getattr(xtdata, method_name)
    return subscribe_factory_until_fresh_callback(
        xtdata,
        lambda callback: method(code, period=period, count=0, callback=callback),
        timeout_seconds,
        freshness_tolerance_seconds,
    )


def probe_callback_factory(
    xtdata: Any,
    category: str,
    name: str,
    subscribe_factory: Callable[[Callable[[Any], None]], Any],
    timeout_seconds: float,
    freshness_tolerance_seconds: float,
) -> Any:
    value = probe(
        category,
        name,
        lambda: subscribe_factory_until_fresh_callback(
            xtdata, subscribe_factory, timeout_seconds, freshness_tolerance_seconds
        ),
        validator=lambda result: (
            isinstance(result, dict)
            and result.get("subscription_accepted") is True
            and result.get("fresh_callback_received") is True
            and result.get("unsubscribed") is True
        ),
        note="PASS requires one fresh time/stime callback; subscription acceptance is recorded separately",
    )
    item = RESULTS[-1]
    if isinstance(value, dict):
        item["subscription_accepted"] = bool(value.get("subscription_accepted"))
        item["callback_received"] = bool(value.get("callback_received"))
        item["fresh_callback_received"] = bool(value.get("fresh_callback_received"))
        item["subscribe_started_at_ms"] = value.get("subscribe_started_at_ms")
        item["callback_time_ms"] = value.get("callback_time_ms")
        item["unsubscribed"] = bool(value.get("unsubscribed"))
        if item["status"] == "EMPTY" and item["subscription_accepted"]:
            if item["callback_received"] and not item["fresh_callback_received"]:
                item["reason_code"] = "SUBSCRIBE_ACCEPTED_STALE_CALLBACK_IGNORED"
                item["note"] = "Subscription accepted; callback arrived but failed time/stime freshness validation"
            else:
                item["reason_code"] = "SUBSCRIBE_ACCEPTED_NO_CALLBACK"
                item["note"] = "Subscription accepted and cancelled, but no callback arrived within the bounded wait"
    return value


def probe_callback_subscription(
    xtdata: Any,
    category: str,
    name: str,
    code: str,
    period: str,
    timeout_seconds: float,
    freshness_tolerance_seconds: float,
    method_name: str = "subscribe_quote",
) -> Any:
    return probe_callback_factory(
        xtdata,
        category,
        name,
        lambda callback: getattr(xtdata, method_name)(code, period=period, count=0, callback=callback),
        timeout_seconds,
        freshness_tolerance_seconds,
    )


def read_miniqmt_version(miniqmt_dir: str) -> dict[str, Any]:
    """Read only non-sensitive release metadata shipped with the MiniQMT client."""
    if not miniqmt_dir:
        return {
            "broker": "UNKNOWN",
            "client_family": "MiniQMT",
            "client_mode": "UNKNOWN",
            "edition": "UNKNOWN（请通过 --miniqmt-dir 显式提供客户端目录）",
        }
    root = Path(miniqmt_dir)
    version_file = root / "resource" / "version"
    result: dict[str, Any] = {
        "broker": "兴业证券",
        "client_family": "MiniQMT",
        "client_mode": "券商定制 MiniQMT",
        "edition": "UNKNOWN（普通版/投研版需券商或客户端界面确认）",
    }
    if version_file.is_file():
        text = version_file.read_text(encoding="utf-8", errors="replace")
        patterns = {
            "client_version": r"(?m)^version:\s*([^\r\n]+)",
            "revision": r"(?m)^revision:\s*([^\r\n]+)",
            "build_time": r"(?m)^buildtime:\s*([^\r\n]+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                result[key] = match.group(1).strip()
    try:
        import win32api  # type: ignore
        for label, relative in [
            ("client_executable_version", Path("bin.x64") / "XtMiniQmt.exe"),
            ("quote_backend_version", Path("bin.x64") / "miniquote.exe"),
        ]:
            info = win32api.GetFileVersionInfo(str(root / relative), "\\")
            ms, ls = info["FileVersionMS"], info["FileVersionLS"]
            result[label] = ".".join(str(part) for part in [win32api.HIWORD(ms), win32api.LOWORD(ms), win32api.HIWORD(ls), win32api.LOWORD(ls)])
    except Exception:
        result["executable_version_note"] = "Windows executable version metadata unavailable"
    return result


def method_signature(module: Any, name: str) -> dict[str, Any]:
    if not hasattr(module, name):
        return {"present": False, "signature": ""}
    try:
        signature = str(inspect.signature(getattr(module, name)))
    except Exception:
        signature = "<unavailable>"
    return {"present": True, "signature": signature}


def find_active_code(xtdata: Any, sector_names: list[str], pattern: str) -> str:
    today = datetime.now().strftime("%Y%m%d")
    for sector in sector_names:
        try:
            codes = xtdata.get_stock_list_in_sector(sector) or []
        except Exception:
            continue
        for code in codes:
            if not re.match(pattern, str(code), flags=re.IGNORECASE):
                continue
            try:
                detail = xtdata.get_instrument_detail(code, True)
            except Exception:
                continue
            if not isinstance(detail, dict) or not detail:
                continue
            expiry = str(detail.get("ExpireDate") or detail.get("EndDelivDate") or "")
            if not expiry or expiry == "0" or expiry >= today:
                return str(code)
    return ""


def find_active_option_code(xtdata: Any, sector_names: list[str], pattern: str) -> str:
    today = datetime.now().strftime("%Y%m%d")
    for sector in sector_names:
        try:
            codes = xtdata.get_stock_list_in_sector(sector) or []
        except Exception:
            continue
        candidates: list[tuple[float, str]] = []
        for code in codes:
            if not re.match(pattern, str(code), flags=re.IGNORECASE):
                continue
            try:
                detail = xtdata.get_instrument_detail(code, True)
            except Exception:
                continue
            if not isinstance(detail, dict) or detail.get("OptionType", -1) not in {0, 1}:
                continue
            expiry = str(detail.get("ExpireDate") or "")
            if expiry and expiry != "0" and expiry < today:
                continue
            candidates.append((float(detail.get("LastVolume") or 0), str(code)))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
    return ""


def probe_market_domain(
    xtdata: Any,
    category: str,
    code: str,
    start: str,
    timeout_seconds: float,
    freshness_tolerance_seconds: float,
    include_detail: bool = True,
    allow_download: bool = False,
) -> None:
    if include_detail:
        probe(category, f"{code} instrument detail", lambda: xtdata.get_instrument_detail(code, True))
    for period in ["1d", "1m", "tick"]:
        value = probe(category, f"{code} {period} one sample", lambda p=period: one_market(xtdata, code, p, start), note="count=1")
        if empty(value) and allow_download:
            probe(
                category,
                f"{code} download {period} minimal window",
                lambda p=period: (xtdata.download_history_data(code, period=p, start_time=start, end_time=""), {"requested": True})[1],
                validator=lambda result: isinstance(result, dict) and result.get("requested") is True,
                note="COMMAND_ACCEPTED only; the following read determines data capability",
            )
            RESULTS[-1]["reason_code"] = "DOWNLOAD_COMMAND_ACCEPTED"
            probe(category, f"{code} {period} one sample after download", lambda p=period: one_market(xtdata, code, p, start), note="count=1")
    probe(category, f"{code} full tick snapshot", lambda: first_sample(xtdata.get_full_tick([code])))
    probe_callback_subscription(
        xtdata,
        category,
        f"{code} tick callback",
        code,
        "tick",
        timeout_seconds,
        freshness_tolerance_seconds,
    )


def download_financial_minimal(xtdata: Any, code: str, tables: list[str]) -> dict[str, Any]:
    """Use the range/progress-capable entrypoint when available.

    Official documentation describes both download variants as synchronous.
    This broker build previously behaved differently for the legacy entrypoint,
    so the probe records that local behavior without generalizing API semantics.
    """
    if hasattr(xtdata, "download_financial_data2"):
        xtdata.download_financial_data2([code], tables)
        return {"requested": True, "api": "download_financial_data2"}
    xtdata.download_financial_data([code], tables)
    return {"requested": True, "api": "download_financial_data"}


def level2_one_with_subscription(xtdata: Any, code: str, period: str) -> dict[str, Any]:
    """Read one L2 sample, subscribing briefly only when the direct read is empty."""
    data = xtdata.get_market_data_ex(field_list=[], stock_list=[code], period=period, count=1)
    if not empty(data):
        return {"subscription_id": None, "sample": data}

    seq = xtdata.subscribe_quote(code, period=period, count=0, callback=None)
    try:
        if isinstance(seq, int) and seq > 0:
            time.sleep(1)
            data = xtdata.get_market_data_ex(field_list=[], stock_list=[code], period=period, count=1)
        return {"subscription_id": seq, "sample": data}
    finally:
        if isinstance(seq, int) and seq > 0 and hasattr(xtdata, "unsubscribe_quote"):
            xtdata.unsubscribe_quote(seq)


def discover_commodity_contracts(xtdata: Any, today: str) -> dict[str, dict[str, str]]:
    """Select one active, liquid future and matching option per visible commodity exchange."""
    markets = {
        "SHFE": (["上期所", "上期所期权"], r"^[a-z]{1,3}\d{4}\.SF$", ".SF"),
        "DCE": (["大商所", "大商所期权"], r"^[a-z]{1,3}\d{4}\.DF$", ".DF"),
        "CZCE": (["郑商所", "郑商所期权"], r"^[A-Z]{1,3}\d{3}\.ZF$", ".ZF"),
        "INE": (["能源中心", "上期能源", "能源中心期权"], r"^[a-z]{1,3}\d{4}\.INE$", ".INE"),
        "GFEX": (["广期所", "广州期货交易所", "广期所期权"], r"^[a-z]{1,3}\d{4}\.GF$", ".GF"),
    }
    selected: dict[str, dict[str, str]] = {}

    def detail(code: str) -> dict[str, Any]:
        try:
            value = xtdata.get_instrument_detail(code, True)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def active(value: dict[str, Any]) -> bool:
        expiry = str(value.get("ExpireDate") or value.get("EndDelivDate") or "")
        return bool(value) and (not expiry or expiry == "0" or expiry >= today)

    for market, (sector_names, future_pattern, suffix) in markets.items():
        codes: list[str] = []
        for sector in sector_names:
            try:
                codes.extend(xtdata.get_stock_list_in_sector(sector) or [])
            except Exception:
                continue
        codes = list(dict.fromkeys(codes))
        future_candidates: list[tuple[float, str, dict[str, Any]]] = []
        for code in codes:
            if not re.match(future_pattern, code):
                continue
            value = detail(code)
            if active(value) and value.get("OptionType", -1) == -1:
                volume = float(value.get("LastVolume") or 0)
                main_bonus = 1_000_000_000 if value.get("MainContract") == 1 else 0
                future_candidates.append((main_bonus + volume, code, value))
        if not future_candidates:
            continue

        if market == "SHFE":
            option_code_pattern = re.compile(r"^([a-z]{1,3}\d{4})[CP]\d+\.SF$")
        elif market == "DCE":
            option_code_pattern = re.compile(r"^([a-z]{1,3}\d{4})-[CP]-\d+\.DF$")
        elif market == "CZCE":
            option_code_pattern = re.compile(r"^([A-Z]{1,3}\d{3})[CP]\d+\.ZF$")
        elif market == "INE":
            option_code_pattern = re.compile(r"^([a-z]{1,3}\d{4})-?[CP]-?\d+\.INE$", re.IGNORECASE)
        else:
            option_code_pattern = re.compile(r"^([a-z]{1,3}\d{4})-?[CP]-?\d+\.GF$", re.IGNORECASE)

        option_groups: dict[str, list[str]] = {}
        for code in codes:
            match = option_code_pattern.match(code)
            if match:
                option_groups.setdefault(match.group(1), []).append(code)

        # Prefer a liquid future that still has at least one unexpired matching
        # option. This keeps each exchange's future/option validation paired.
        paired: tuple[str, str] | None = None
        for _, future_code, _ in sorted(future_candidates, key=lambda item: item[0], reverse=True):
            underlying = future_code.removesuffix(suffix)
            option_candidates: list[tuple[float, str]] = []
            for option_code in option_groups.get(underlying, []):
                value = detail(option_code)
                if active(value) and value.get("OptionType", -1) in {0, 1}:
                    option_candidates.append((float(value.get("LastVolume") or 0), option_code))
            if option_candidates:
                paired = (future_code, max(option_candidates, key=lambda item: item[0])[1])
                break

        if paired:
            selected[market] = {"future": paired[0], "option": paired[1]}
        else:
            selected[market] = {"future": max(future_candidates, key=lambda item: item[0])[1]}
    return selected


def probe_derivative_contract(
    xtdata: Any,
    category: str,
    code: str,
    start: str,
    allow_download: bool,
    is_option: bool,
    callback_timeout: float = 0,
    freshness_tolerance_seconds: float = 5,
) -> None:
    """Cover static, historical, snapshot and subscription paths for one derivative."""
    probe(category, f"{code} instrument detail", lambda: xtdata.get_instrument_detail(code, True))
    probe(category, f"{code} instrument type", lambda: xtdata.get_instrument_type(code))
    if is_option and hasattr(xtdata, "get_option_detail_data"):
        probe(category, f"{code} get_option_detail_data", lambda: xtdata.get_option_detail_data(code))

    for period in ["1d", "1m", "tick"]:
        value = probe(
            category,
            f"{code} {period} one sample",
            lambda p=period: one_market(xtdata, code, p, start),
            note="count=1",
        )
        if empty(value) and allow_download and period in {"1d", "1m", "tick"}:
            probe(
                category,
                f"{code} download {period}",
                lambda p=period: (xtdata.download_history_data(code, period=p, start_time=start, end_time=""), {"requested": True})[1],
            )
            probe(
                category,
                f"{code} {period} one sample after download",
                lambda p=period: one_market(xtdata, code, p, start),
                note="count=1",
            )

    probe(category, f"{code} full tick snapshot", lambda: first_sample(xtdata.get_full_tick([code])))
    probe_callback_subscription(
        xtdata,
        category,
        f"{code} tick callback",
        code,
        "tick",
        callback_timeout,
        freshness_tolerance_seconds,
    )


def run_review_p0_p1(xtquant: Any, xtdata: Any, args: argparse.Namespace, start: str, today: str) -> None:
    """Run only the data-related P0/P1 supplements requested by the review."""
    version_value = read_miniqmt_version(args.miniqmt_dir)
    version_value["python_version"] = sys.version.split()[0]
    version_value["xtquant_package"] = getattr(xtquant, "__version__", "UNKNOWN")
    try:
        version_value["xtquant_distribution"] = importlib.metadata.version("xtquant")
    except importlib.metadata.PackageNotFoundError:
        version_value["xtquant_distribution"] = "UNKNOWN"
    record(
        "compatibility",
        "MiniQMT and xtquant version inventory",
        "PASS",
        "Read from the installed client release metadata and Python package",
        sample=json.dumps(sanitize_value(version_value), ensure_ascii=False, sort_keys=True),
    )
    RESULTS[-1]["returned_fields"] = list(version_value.keys())
    probe("connection", "get_instrument_detail(stock)", lambda: xtdata.get_instrument_detail(args.stock, True))
    probe("inventory", "get_period_list", lambda: xtdata.get_period_list())

    extension_signatures = [
        "get_current_connect_sub_info", "get_all_sub_info", "get_order_rank", "get_transactioncount",
        "get_sector_info", "get_tabular_data", "get_formula_result", "get_trading_contract_list",
        "get_trading_period", "get_all_trading_periods", "get_all_kline_trading_periods",
        "subscribe_quote2", "get_his_option_list", "get_his_option_list_batch", "get_option_undl_data",
        "get_option_list", "watch_quote_server_status", "watch_xtquant_status", "get_broker_queue_data",
        "download_his_st_data", "get_his_st_data",
    ]
    probe(
        "compatibility",
        "P1 XtData Python surface and signatures",
        lambda: {name: method_signature(xtdata, name) for name in extension_signatures},
        validator=lambda value: isinstance(value, dict) and all(item.get("present") for item in value.values()),
    )

    for method_name, call in [
        ("get_current_connect_sub_info", lambda: xtdata.get_current_connect_sub_info()),
        ("get_all_sub_info", lambda: xtdata.get_all_sub_info()),
        ("get_transactioncount", lambda: xtdata.get_transactioncount([args.stock])),
        ("get_sector_info", lambda: first_sample(xtdata.get_sector_info("沪深A股"))),
        ("get_tabular_data", lambda: first_sample(xtdata.get_tabular_data([], [args.stock], "1d", start, today, 1))),
        ("get_trading_period", lambda: xtdata.get_trading_period(args.stock)),
        ("get_all_trading_periods", lambda: first_sample(xtdata.get_all_trading_periods())),
        ("get_all_kline_trading_periods", lambda: first_sample(xtdata.get_all_kline_trading_periods())),
    ]:
        if hasattr(xtdata, method_name):
            probe("official_extension", method_name, call)
        else:
            record("official_extension", method_name, "UNSUPPORTED", "API is absent from the installed Python package")

    # These two helpers require data created by a formula subscription or a
    # concrete thousand-order record. Do not fabricate identifiers/order fields.
    for method_name, prerequisite in [
        ("get_formula_result", "Requires a request id returned by a configured research formula"),
        ("get_order_rank", "Requires one real L2 thousand-order record; this account has no usable thousand-order sample"),
    ]:
        if hasattr(xtdata, method_name):
            record("official_extension", method_name, "NOT_TESTED", prerequisite, sample=json.dumps(method_signature(xtdata, method_name)))
            RESULTS[-1]["api_available"] = True
            RESULTS[-1]["reason_code"] = "PREREQUISITE_DATA_UNAVAILABLE"
        else:
            record("official_extension", method_name, "UNSUPPORTED", "API is absent from the installed Python package")

    if hasattr(xtdata, "get_full_kline"):
        probe("compatibility", "get_full_kline 1m handler/config check", lambda: xtdata.get_full_kline([], [args.stock], period="1m", count=1))
    else:
        record("compatibility", "get_full_kline 1m handler/config check", "UNSUPPORTED", "API is absent from the installed Python package")

    if hasattr(xtdata, "subscribe_quote2"):
        probe_callback_subscription(
            xtdata, "subscription_callback", "subscribe_quote2 stock tick callback",
            args.stock, "tick", args.callback_timeout, args.freshness_tolerance, method_name="subscribe_quote2",
        )
    else:
        record("subscription_callback", "subscribe_quote2", "UNSUPPORTED", "API is absent from the installed Python package")

    # ETF, convertible bond, BSE stock and index are distinct data domains.
    probe_market_domain(xtdata, "etf_market", args.etf, start, args.callback_timeout, args.freshness_tolerance, allow_download=args.download)
    for period in ["etfiopv1m", "etfiopv1d"]:
        probe("etf_market", f"{args.etf} {period} one sample", lambda p=period: one_market(xtdata, args.etf, p, start), note="count=1")

    cb_code = args.cb or find_active_code(xtdata, ["沪深转债", "上证转债", "深证转债"], r"^(?:11|12)\d{4}\.(?:SH|SZ)$")
    if cb_code:
        record("convertible_bond_market", "current representative contract", "PASS", "Discovered from current runtime sector metadata", sample=cb_code)
        probe_market_domain(xtdata, "convertible_bond_market", cb_code, start, args.callback_timeout, args.freshness_tolerance, allow_download=args.download)
    else:
        record("convertible_bond_market", "current representative contract", "NOT_TESTED", "No current convertible bond could be discovered")

    bse_code = args.bse_code or find_active_code(xtdata, ["京市A股", "沪深京A股"], r"^\d{6}\.BJ$")
    if bse_code:
        record("bse_market", "current representative stock", "PASS", "Discovered from current runtime sector metadata", sample=bse_code)
        probe_market_domain(xtdata, "bse_market", bse_code, start, args.callback_timeout, args.freshness_tolerance, allow_download=args.download)
    else:
        record("bse_market", "current representative stock", "NOT_TESTED", "No current BSE stock could be discovered")

    index_daily = probe("index_market", f"{args.index_code} 1d one sample", lambda: one_market(xtdata, args.index_code, "1d", start), note="count=1")
    if empty(index_daily) and args.download:
        probe(
            "index_market", f"{args.index_code} download 1d minimal window",
            lambda: (xtdata.download_history_data(args.index_code, period="1d", start_time=start, end_time=""), {"requested": True})[1],
            validator=lambda result: isinstance(result, dict) and result.get("requested") is True,
            note="COMMAND_ACCEPTED only; the following read determines data capability",
        )
        RESULTS[-1]["reason_code"] = "DOWNLOAD_COMMAND_ACCEPTED"
        probe("index_market", f"{args.index_code} 1d one sample after download", lambda: one_market(xtdata, args.index_code, "1d", start), note="count=1")
    probe("index_market", f"{args.index_code} full tick snapshot", lambda: first_sample(xtdata.get_full_tick([args.index_code])))

    # Option helper series uses the ETF underlying and one date/window only.
    option_calls = [
        ("get_his_option_list", lambda: first_sample(xtdata.get_his_option_list(args.etf, today))),
        ("get_his_option_list_batch", lambda: first_sample(xtdata.get_his_option_list_batch(args.etf, start, today))),
        ("get_option_undl_data", lambda: first_sample(xtdata.get_option_undl_data(args.etf))),
        ("get_option_list", lambda: first_sample(xtdata.get_option_list(args.etf, today))),
    ]
    for method_name, call in option_calls:
        if hasattr(xtdata, method_name):
            probe("option_helper", method_name, call)
        else:
            record("option_helper", method_name, "UNSUPPORTED", "API is absent from the installed Python package")

    sz_option = args.sz_option_code or find_active_option_code(xtdata, ["深证期权"], r"^\d+\.SZO$")
    if sz_option:
        record("option_sz", "current representative contract", "PASS", "Discovered from 深证期权 runtime metadata", sample=sz_option)
        probe_derivative_contract(
            xtdata, "option_sz", sz_option, start, args.download, True,
            args.callback_timeout, args.freshness_tolerance,
        )
    else:
        record("option_sz", "current representative contract", "NOT_TESTED", "No current Shenzhen option could be discovered")

    index_option = args.index_option_code or find_active_option_code(
        xtdata, ["中金所"], r"^(?:IO|MO|HO|TSO|TFO|TLO).*\.IF$"
    )
    if index_option:
        record("index_option", "current representative contract", "PASS", "Discovered from 中金所 runtime metadata", sample=index_option)
        probe_derivative_contract(
            xtdata, "index_option", index_option, start, args.download, True,
            args.callback_timeout, args.freshness_tolerance,
        )
    else:
        record("index_option", "current representative contract", "NOT_TESTED", "No current CFFEX option could be discovered")

    future_code = args.future_code or find_active_code(xtdata, ["中金所"], r"^(?:IF|IH|IC|IM)\d{4}\.IF$")
    if future_code and hasattr(xtdata, "get_trading_contract_list"):
        probe("official_extension", "get_trading_contract_list", lambda: first_sample(xtdata.get_trading_contract_list(future_code)))
        probe_callback_subscription(
            xtdata, "subscription_callback", f"index future {future_code} tick callback",
            future_code, "tick", args.callback_timeout, args.freshness_tolerance,
        )
    elif not future_code:
        record("official_extension", "get_trading_contract_list", "NOT_TESTED", "No current financial future could be discovered")
    else:
        record("official_extension", "get_trading_contract_list", "UNSUPPORTED", "API is absent from the installed Python package")

    discovered = discover_commodity_contracts(xtdata, today)
    for market in ["SHFE", "DCE", "CZCE", "INE", "GFEX"]:
        contracts = discovered.get(market, {})
        for asset_name, code in [("commodity future", contracts.get("future", "")), ("commodity option", contracts.get("option", ""))]:
            test_name = f"{market} {asset_name} {code or 'not-discovered'} tick callback"
            if code:
                if market in {"INE", "GFEX"}:
                    probe_derivative_contract(
                        xtdata,
                        "commodity_option" if asset_name.endswith("option") else "commodity_future",
                        code,
                        start,
                        args.download,
                        asset_name.endswith("option"),
                        args.callback_timeout,
                        args.freshness_tolerance,
                    )
                else:
                    probe_callback_subscription(
                        xtdata, "subscription_callback", test_name, code, "tick",
                        args.callback_timeout, args.freshness_tolerance,
                    )
            else:
                record(
                    "subscription_callback",
                    test_name,
                    "NOT_TESTED",
                    "No current representative contract is visible in the MiniQMT runtime sectors; no fabricated code was used",
                )

    # Read-only status watchers: PASS requires a real status callback, not merely registration.
    for method_name in ["watch_quote_server_status", "watch_xtquant_status"]:
        if not hasattr(xtdata, method_name):
            record("status_monitor", method_name, "UNSUPPORTED", "API is absent from the installed Python package")
            continue
        events: list[Any] = []
        def on_status(info: Any, target: list[Any] = events) -> None:
            if not target and not empty(info):
                target.append(sanitize_value(first_sample(info)))
        try:
            getattr(xtdata, method_name)(on_status)
            deadline = time.monotonic() + min(max(args.callback_timeout, 0), 1.0)
            while not events and time.monotonic() < deadline:
                time.sleep(0.05)
            if events:
                record("status_monitor", method_name, "PASS", "Received one sanitized connection-status callback", sample=summary(events[0]))
            else:
                record("status_monitor", method_name, "EMPTY", "Watcher registered, but no connection state change occurred during the bounded wait")
                RESULTS[-1]["api_available"] = True
                RESULTS[-1]["reason_code"] = "WATCH_REGISTERED_NO_STATE_CHANGE"
        except Exception as exc:
            status = classify(exc)
            record("status_monitor", method_name, status, f"{type(exc).__name__}: {exc}")

    # Known P1 periods are queried directly because get_period_list may be unavailable.
    period_targets = [
        ("announcement", args.stock), ("limitupperformance", args.stock),
        ("hktdetails", args.hk_code), ("hktstatistics", args.hk_code),
        ("stoppricedata", args.stock),
        ("delistchangebond", cb_code or "XXXXXX.SH"),
        ("replacechangebond", cb_code or "XXXXXX.SH"),
        ("historymaincontract", "IF00.IF"),
        ("optionhistorycontract", "XXXXXX.SHO"),
    ]
    for period, code in period_targets:
        value = probe("special_period", f"{period} one sample", lambda p=period, c=code: one_market(xtdata, c, p, start), note=f"schema target={code}; count=1")
        if RESULTS[-1]["status"] == "EMPTY" and args.download:
            probe(
                "special_period",
                f"download {period} minimal window",
                lambda p=period, c=code: (xtdata.download_history_data(c, period=p, start_time=start, end_time=""), {"requested": True})[1],
                validator=lambda result: isinstance(result, dict) and result.get("requested") is True,
                note="COMMAND_ACCEPTED only; the following read determines data capability",
            )
            RESULTS[-1]["reason_code"] = "DOWNLOAD_COMMAND_ACCEPTED"
            probe("special_period", f"{period} one sample after download", lambda p=period, c=code: one_market(xtdata, c, p, start), note=f"schema target={code}; count=1")

    # Order-flow edition: only the 1m base period is downloaded/read; longer
    # periods are derived and are listed without redundant retrieval.
    if args.download:
        probe(
            "orderflow",
            "download orderflow1m minimal window",
            lambda: (xtdata.download_history_data(args.stock, period="orderflow1m", start_time=start, end_time=""), {"requested": True})[1],
            validator=lambda result: isinstance(result, dict) and result.get("requested") is True,
            note="Official prerequisite: 订单流版; command acceptance does not prove entitlement",
        )
        if RESULTS[-1]["status"] == "PASS":
            RESULTS[-1]["reason_code"] = "DOWNLOAD_COMMAND_ACCEPTED"
    probe("orderflow", "orderflow1m one sample", lambda: one_market(xtdata, args.stock, "orderflow1m", start), note="count=1; official prerequisite: 订单流版")
    for derived_period in ["orderflow5m", "orderflow15m", "orderflow30m", "orderflow1h", "orderflow1d"]:
        record("orderflow", derived_period, "NOT_TESTED", "Derived from orderflow1m; not redundantly retrieved under the one-sample policy")

    # Historical ST helper is distinct from the specialtreatment period.
    if hasattr(xtdata, "download_his_st_data"):
        if args.download:
            probe("historical_st", "download_his_st_data", lambda: xtdata.download_his_st_data())
        else:
            skip("historical_st", "download_his_st_data", "Pass --download to request the official ST history file")
    else:
        record("historical_st", "download_his_st_data", "UNSUPPORTED", "API is absent from the installed Python package")
    if hasattr(xtdata, "get_his_st_data"):
        probe("historical_st", f"get_his_st_data {args.st_code}", lambda: xtdata.get_his_st_data(args.st_code))
    else:
        record("historical_st", "get_his_st_data", "UNSUPPORTED", "API is absent from the installed Python package")

    # snapshotindex is VIP and officially requires a live subscription first.
    probe_callback_subscription(
        xtdata,
        "special_period",
        "snapshotindex fresh callback",
        args.stock,
        "snapshotindex",
        args.callback_timeout,
        args.freshness_tolerance,
    )

    if hasattr(xtdata, "get_l2thousand_queue"):
        probe("official_extension", "get_l2thousand_queue", lambda: xtdata.get_l2thousand_queue(args.stock))
    else:
        record("official_extension", "get_l2thousand_queue", "UNSUPPORTED", "API is absent from the installed Python package")
    if hasattr(xtdata, "get_broker_queue_data"):
        probe("special_period", "get_broker_queue_data one sample", lambda: xtdata.get_broker_queue_data([args.hk_code], count=1))
        probe("special_period", "brokerqueue one sample", lambda: one_market(xtdata, args.hk_code, "brokerqueue", start))
    else:
        record("special_period", "get_broker_queue_data", "UNSUPPORTED", "API is absent from the installed Python package")

    # Review asks for explicit scope statements; no representative codes/service proof was supplied.
    for market_name in [
        "非 ETF 基金 / LOF", "普通债券 / 固定收益证券", "回购品种", "板块指数 BKZS",
        "港股通用 Level 1", "港股 Level 2", "美股行情", "外盘行情",
    ]:
        record("market_scope", market_name, "NOT_TESTED", "No purchase/service declaration and no schema-validated representative test was available in this P0/P1 supplement")

    handler_items = [
        item for item in RESULTS
        if item.get("reason_code") == "BACKEND_HANDLER_MISSING_OR_EDITION_UNAVAILABLE"
    ]
    premium_handler_items = [
        item for item in handler_items
        if item.get("official_prerequisite") != "普通 / 官方未注明额外版本"
    ]
    standard_handler_items = [item for item in handler_items if item not in premium_handler_items]
    schema_mismatch = sum(1 for item in RESULTS if item.get("reason_code") == "CLIENT_SCHEMA_MISMATCH")
    record(
        "compatibility",
        "Python package versus MiniQMT backend assessment",
        "ERROR" if standard_handler_items or schema_mismatch else "PASS",
        "Compatibility is not fully confirmed: premium handler failures may reflect edition/entitlement, while standard handler or schema failures are stronger mismatch evidence"
        if handler_items or schema_mismatch
        else "No handler/schema mismatch was observed in this supplement",
        sample=json.dumps({
            "handler_missing_or_edition_unavailable": len(handler_items),
            "premium_or_edition_prerequisite": len(premium_handler_items),
            "standard_handler_missing": len(standard_handler_items),
            "client_schema_mismatch": schema_mismatch,
        }),
    )
    RESULTS[-1]["reason_code"] = "CLIENT_VERSION_OR_SCHEMA_MISMATCH_SUSPECTED" if standard_handler_items or schema_mismatch else "COMPATIBILITY_CONFIRMED"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One-sample MiniQMT xtdata capability probe")
    p.add_argument("--stock", default="000001.SZ")
    p.add_argument("--etf", default="510300.SH")
    p.add_argument("--index-code", default="000300.SH")
    p.add_argument("--bse-code", default="", help="Current BSE stock; auto-discovers from 京市A股 when omitted")
    p.add_argument("--hk-code", default="00700.HK")
    p.add_argument("--cb", default="")
    p.add_argument("--option-code", default="")
    p.add_argument("--sz-option-code", default="", help="Current Shenzhen stock-option code; auto-discovers when omitted")
    p.add_argument("--index-option-code", default="", help="Current CFFEX option code; auto-discovers when omitted")
    p.add_argument("--future-code", default="")
    p.add_argument("--st-code", default="600198.SH", help="A stock with known historical ST periods for get_his_st_data")
    p.add_argument(
        "--commodity-future-code",
        action="append",
        default=[],
        help="Commodity future code; repeat for multiple exchanges. Auto-discovers SHFE/DCE/CZCE/INE/GFEX when omitted.",
    )
    p.add_argument(
        "--commodity-option-code",
        action="append",
        default=[],
        help="Commodity option code; repeat for multiple exchanges. Auto-discovers SHFE/DCE/CZCE/INE/GFEX when omitted.",
    )
    p.add_argument("--download", action="store_true", help="Allow minimal supplement downloads when local data is missing")
    p.add_argument("--callback-timeout", type=float, default=3.0, help="Seconds to wait for the first callback per realtime category")
    p.add_argument("--freshness-tolerance", type=float, default=5.0, help="Allowed seconds before subscription start for callback time/stime freshness")
    p.add_argument("--miniqmt-dir", default="", help="MiniQMT installation directory; pass explicitly when version/build evidence is required")
    p.add_argument("--review-p0-p1-only", action="store_true", help="Run only data-related P0/P1 supplements from the 20260823 review")
    p.add_argument("--output-dir", default="reports")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = datetime.now().strftime("%Y%m%d")
    # Small window only; actual feasibility reads still use count=1.
    start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")

    try:
        import xtquant  # type: ignore
        from xtquant import xtdata  # type: ignore
        probe("environment", "import xtquant.xtdata", lambda: {"path": getattr(xtquant, "__file__", "")})
    except Exception as exc:
        record("environment", "import xtquant.xtdata", classify(exc), str(exc))
        write_report(args.output_dir, args)
        return 2

    if args.review_p0_p1_only:
        run_review_p0_p1(xtquant, xtdata, args, start, today)
        write_report(args.output_dir, args)
        basic_fail = any(item["category"] in {"environment", "connection"} and item["status"] != "PASS" for item in RESULTS)
        if hasattr(xtdata, "disconnect"):
            try:
                xtdata.disconnect()
            except Exception as exc:
                print(f"Warning: xtdata disconnect failed: {type(exc).__name__}: {exc}")
        return 2 if basic_fail else 0

    # Connection / runtime inventory.
    probe("connection", "get_instrument_detail(stock)", lambda: xtdata.get_instrument_detail(args.stock, True))
    probe("connection", "get_instrument_type(stock)", lambda: xtdata.get_instrument_type(args.stock))
    periods = probe("inventory", "get_period_list", lambda: xtdata.get_period_list())

    # L1: exactly one returned bar/tick per tested period where count is supported.
    for period in ["1d", "1m", "5m", "15m", "30m", "1h", "1w", "1mon", "1q", "1hy", "1y", "tick"]:
        value = probe("l1_market", f"get_market_data_ex {period}: one sample", lambda p=period: one_market(xtdata, args.stock, p, start), note="count=1")
        if empty(value) and args.download and period in {"1d", "1m", "5m", "tick"}:
            # Minimal 7-calendar-day supplement window; read is still one sample.
            probe("l1_download", f"download {period} minimal window", lambda p=period: (xtdata.download_history_data(args.stock, period=p, start_time=start, end_time=""), {"requested": True})[1])
            probe("l1_market", f"get_market_data_ex {period}: one sample after download", lambda p=period: one_market(xtdata, args.stock, p, start), note="count=1")

    # Official primary/local read APIs use the same one-symbol, one-row policy.
    probe("l1_api", "get_market_data 1d one sample", lambda: one_market_legacy(xtdata, args.stock, "1d", start), note="count=1")
    probe("l1_api", "get_local_data 1d one sample", lambda: one_local_market(xtdata, args.stock, "1d", start), note="count=1")
    if args.download:
        probe(
            "official_download",
            "download_history_data 1d minimal window",
            lambda: (xtdata.download_history_data(args.stock, period="1d", start_time=start, end_time=""), {"requested": True})[1],
        )
    else:
        skip("official_download", "download_history_data", "Pass --download to verify the minimal one-symbol download path")
    skip("official_download", "download_history_data2", "Batch alternative not duplicated under the one-sample policy")
    skip("official_download", "download_history_contracts", "Bulk expired-contract metadata download is outside the minimal safety scope")

    # Realtime: one symbol, one snapshot / one successful subscription.
    probe("realtime", "get_full_tick one symbol", lambda: first_sample(xtdata.get_full_tick([args.stock])))
    if hasattr(xtdata, "get_full_kline"):
        probe("realtime", "get_full_kline 1m one bar", lambda: xtdata.get_full_kline([], [args.stock], period="1m", count=1))
    else:
        skip("realtime", "get_full_kline", "API not present")
    probe_callback_subscription(
        xtdata,
        "realtime",
        "subscribe_quote tick callback",
        args.stock,
        "tick",
        args.callback_timeout,
        args.freshness_tolerance,
    )
    if hasattr(xtdata, "subscribe_whole_quote"):
        probe_callback_factory(
            xtdata,
            "realtime",
            "subscribe_whole_quote one-code fresh callback",
            lambda callback: xtdata.subscribe_whole_quote([args.stock], callback=callback),
            args.callback_timeout,
            args.freshness_tolerance,
        )
    else:
        record("realtime", "subscribe_whole_quote", "UNSUPPORTED", "API not present in the installed xtquant package")
    skip("realtime_helper", "run", "Blocking receive-loop helper; subscription acceptance and cleanup were tested directly")

    # Interfaces referenced by the official XtData version history but not all
    # represented as standalone entries in the main interface table.
    if hasattr(xtdata, "get_trading_time"):
        probe("official_extension", "get_trading_time", lambda: xtdata.get_trading_time(args.stock))
    else:
        record("official_extension", "get_trading_time", "UNSUPPORTED", "Officially referenced name is absent from this installed package")
    if hasattr(xtdata, "get_trading_period"):
        probe("official_extension", "get_trading_period installed alias", lambda: xtdata.get_trading_period(args.stock))
    else:
        record("official_extension", "get_trading_period installed alias", "UNSUPPORTED", "Installed compatibility alias is absent")

    skip("official_extension", "reconnect", "Installed API would change the active MiniQMT connection; static availability only")
    RESULTS[-1]["api_available"] = hasattr(xtdata, "reconnect")

    if hasattr(xtdata, "get_l2thousand_queue"):
        probe("official_extension", "get_l2thousand_queue", lambda: xtdata.get_l2thousand_queue(args.stock))
    else:
        record("official_extension", "get_l2thousand_queue", "UNSUPPORTED", "API is absent from the installed package")
    for method_name in ["subscribe_l2thousand", "subscribe_l2thousand_queue"]:
        if hasattr(xtdata, method_name):
            probe_callback_factory(
                xtdata,
                "official_extension",
                f"{method_name} fresh callback",
                lambda callback, m=method_name: getattr(xtdata, m)(args.stock, callback=callback),
                args.callback_timeout,
                args.freshness_tolerance,
            )
        else:
            record("official_extension", method_name, "UNSUPPORTED", "API is absent from the installed package")

    # Reference/static categories. API may internally return a list; report only first sample.
    holidays = probe("calendar", "get_holidays one sample", lambda: first_sample(xtdata.get_holidays()))
    if empty(holidays) and args.download and hasattr(xtdata, "download_holiday_data"):
        probe("calendar", "download_holiday_data", lambda: (xtdata.download_holiday_data(), {"requested": True})[1])
        probe("calendar", "get_holidays one sample after download", lambda: first_sample(xtdata.get_holidays()))
    probe("calendar", "get_trading_calendar one sample", lambda: first_sample(xtdata.get_trading_calendar("SH", start_time=start, end_time=today)))
    probe("calendar", "get_trading_dates one sample", lambda: first_sample(xtdata.get_trading_dates("SH", start_time=start, end_time=today, count=1)))

    sectors = probe("metadata", "get_sector_list one sample", lambda: first_sample(xtdata.get_sector_list()))
    if empty(sectors) and args.download:
        probe("metadata", "download_sector_data", lambda: (xtdata.download_sector_data(), {"requested": True})[1])
        sectors = probe("metadata", "get_sector_list one sample after download", lambda: first_sample(xtdata.get_sector_list()))
    elif not empty(sectors):
        skip("official_download", "download_sector_data", "Existing sector metadata is usable; previous direct refresh did not return and was not repeated")
    else:
        skip("official_download", "download_sector_data", "Pass --download only when sector metadata is empty")
    if sectors:
        sector = sectors[0] if isinstance(sectors, list) else next(iter(sectors)) if isinstance(sectors, dict) else None
        if sector:
            probe("metadata", "get_stock_list_in_sector one sample", lambda: first_sample(xtdata.get_stock_list_in_sector(sector)))

    probe("metadata", "get_index_weight one sample", lambda: first_sample(xtdata.get_index_weight("000300.SH")))
    skip("official_download", "download_index_weight", "All-index synchronous refresh is outside the one-sample safety scope")

    probe("corporate_action", "get_divid_factors one sample", lambda: first_sample(xtdata.get_divid_factors(args.stock, start_time="20200101", end_time=today)))

    # Financial: test each table separately; first valid sample is enough.
    financial_tables = [
        "Balance",
        "Income",
        "CashFlow",
        "Capital",
        "HolderNum",
        "Top10Holder",
        "Top10FlowHolder",
        "PershareIndex",
    ]
    if args.download:
        financial_download_name = "download_financial_data2" if hasattr(xtdata, "download_financial_data2") else "download_financial_data"
        probe(
            "financial",
            f"{financial_download_name} minimal symbol",
            lambda: download_financial_minimal(xtdata, args.stock, financial_tables),
        )
    for table in financial_tables:
        probe("financial", f"get_financial_data {table}: one sample", lambda t=table: first_sample(xtdata.get_financial_data([args.stock], [t], start_time="20200101")))
    skip("official_download", "download_financial_data", "Legacy synchronous entrypoint previously waited indefinitely on this client; compatible download_financial_data2 was used")

    # IPO / ETF.
    probe("ipo", "get_ipo_info one sample", lambda: first_sample(xtdata.get_ipo_info("", "")))
    probe("etf", "ETF instrument detail one sample", lambda: xtdata.get_instrument_detail(args.etf, True))
    if hasattr(xtdata, "get_etf_info"):
        probe("etf", "get_etf_info one sample", lambda: first_sample(xtdata.get_etf_info()))
    else:
        record("etf", "get_etf_info", "UNSUPPORTED", "API not present")
    skip("official_download", "download_etf_info", "All-ETF synchronous download not run after the client rejected get_etf_info")

    # Optional representative contracts: one current contract per category.
    if args.cb:
        cb_info = probe("convertible_bond", "get_cb_info one contract", lambda: xtdata.get_cb_info(args.cb))
        if empty(cb_info) and args.download and hasattr(xtdata, "download_cb_data"):
            probe("convertible_bond", "download_cb_data metadata", lambda: (xtdata.download_cb_data(), {"requested": True})[1])
            probe("convertible_bond", "get_cb_info one contract after download", lambda: xtdata.get_cb_info(args.cb))
    else:
        skip("convertible_bond", "get_cb_info", "Pass --cb with one current valid convertible bond")

    if args.option_code:
        probe_derivative_contract(xtdata, "option", args.option_code, start, args.download, is_option=True, callback_timeout=args.callback_timeout, freshness_tolerance_seconds=args.freshness_tolerance)
    else:
        skip("option", "option APIs", "Pass --option-code with one current valid option")

    sz_option = args.sz_option_code or find_active_option_code(xtdata, ["深证期权"], r"^\d+\.SZO$")
    if sz_option:
        probe_derivative_contract(xtdata, "option_sz", sz_option, start, args.download, True, args.callback_timeout, args.freshness_tolerance)
    else:
        record("option_sz", "current representative contract", "NOT_TESTED", "No current Shenzhen option could be discovered")

    index_option = args.index_option_code or find_active_option_code(xtdata, ["中金所"], r"^(?:IO|MO|HO|TSO|TFO|TLO).*\.IF$")
    if index_option:
        probe_derivative_contract(xtdata, "index_option", index_option, start, args.download, True, args.callback_timeout, args.freshness_tolerance)
    else:
        record("index_option", "current representative contract", "NOT_TESTED", "No current CFFEX option could be discovered")

    if args.future_code:
        probe_derivative_contract(xtdata, "future", args.future_code, start, args.download, is_option=False, callback_timeout=args.callback_timeout, freshness_tolerance_seconds=args.freshness_tolerance)
    else:
        skip("future", "future APIs", "Pass --future-code with one current valid future")

    # Commodity derivatives: when codes are not supplied, select one active
    # future and matching option for each visible commodity exchange.
    commodity_futures = list(args.commodity_future_code)
    commodity_options = list(args.commodity_option_code)
    if not commodity_futures and not commodity_options:
        discovered = discover_commodity_contracts(xtdata, today)
        for market in ["SHFE", "DCE", "CZCE", "INE", "GFEX"]:
            contracts = discovered.get(market, {})
            if contracts:
                record(
                    "commodity_discovery",
                    f"{market} current contracts",
                    "PASS",
                    "Selected from the runtime sector list using expiry, main-contract flag and recent volume",
                    sample=json.dumps(contracts, ensure_ascii=False),
                )
                if contracts.get("future"):
                    commodity_futures.append(contracts["future"])
                if contracts.get("option"):
                    commodity_options.append(contracts["option"])
            else:
                record(
                    "commodity_discovery",
                    f"{market} current contracts",
                    "EMPTY",
                    "No active matching commodity future/option pair was discovered",
                )

    if commodity_futures:
        for code in commodity_futures:
            probe_derivative_contract(xtdata, "commodity_future", code, start, args.download, is_option=False, callback_timeout=args.callback_timeout, freshness_tolerance_seconds=args.freshness_tolerance)
    else:
        skip("commodity_future", "commodity future APIs", "No current commodity future code was supplied or discovered")

    if commodity_options:
        for code in commodity_options:
            probe_derivative_contract(xtdata, "commodity_option", code, start, args.download, is_option=True, callback_timeout=args.callback_timeout, freshness_tolerance_seconds=args.freshness_tolerance)
    else:
        skip("commodity_option", "commodity option APIs", "No current commodity option code was supplied or discovered")

    # L2: one record only. EMPTY outside trading hours remains inconclusive.
    for period in ["l2quote", "l2quoteaux", "l2order", "l2transaction", "l2orderqueue"]:
        probe(
            "level2",
            f"{period}: one sample",
            lambda p=period: level2_one_with_subscription(xtdata, args.stock, p),
            validator=lambda x: isinstance(x, dict) and not empty(x.get("sample")),
            note="count=1; direct read then one brief subscription; EMPTY outside trading hours is inconclusive",
        )

    if args.download:
        probe(
            "orderflow",
            "download orderflow1m minimal window",
            lambda: (xtdata.download_history_data(args.stock, period="orderflow1m", start_time=start, end_time=""), {"requested": True})[1],
            validator=lambda result: isinstance(result, dict) and result.get("requested") is True,
            note="Official prerequisite: 订单流版; command acceptance does not prove entitlement",
        )
        if RESULTS[-1]["status"] == "PASS":
            RESULTS[-1]["reason_code"] = "DOWNLOAD_COMMAND_ACCEPTED"
    probe("orderflow", "orderflow1m one sample", lambda: one_market(xtdata, args.stock, "orderflow1m", start), note="count=1; official prerequisite: 订单流版")
    for derived_period in ["orderflow5m", "orderflow15m", "orderflow30m", "orderflow1h", "orderflow1d"]:
        record("orderflow", derived_period, "NOT_TESTED", "Derived from orderflow1m; not redundantly retrieved under the one-sample policy")

    if hasattr(xtdata, "download_his_st_data"):
        if args.download:
            probe("historical_st", "download_his_st_data", lambda: xtdata.download_his_st_data())
        else:
            skip("historical_st", "download_his_st_data", "Pass --download to request the official ST history file")
    else:
        record("historical_st", "download_his_st_data", "UNSUPPORTED", "API is absent from the installed Python package")
    if hasattr(xtdata, "get_his_st_data"):
        probe("historical_st", f"get_his_st_data {args.st_code}", lambda: xtdata.get_his_st_data(args.st_code))
    else:
        record("historical_st", "get_his_st_data", "UNSUPPORTED", "API is absent from the installed Python package")

    probe_callback_subscription(
        xtdata,
        "special_period",
        "snapshotindex fresh callback",
        args.stock,
        "snapshotindex",
        args.callback_timeout,
        args.freshness_tolerance,
    )

    # Special/research periods: inventory only here. Codex should perform one schema-appropriate
    # sample for each desired discovered category rather than blindly querying with an A-share code.
    known_special = [
        "transactioncount1m", "transactioncount1d", "specialtreatment", "dividendplaninfo",
        "stoppricedata", "snapshotindex", "northfinancechange1m", "northfinancechange1d",
        "warehousereceipt", "futureholderrank", "interactiveqa", "delistchangebond",
        "replacechangebond", "historycontract", "optionhistorycontract", "historymaincontract",
    ]
    period_set = set(periods or []) if isinstance(periods, (list, tuple, set)) else set()
    for p in known_special:
        if p in period_set:
            record("special_period", p, "NOT_TESTED", "Use one schema-appropriate sample only", sample="runtime advertised")

    # Officially documented helpers requiring a configured research formula or
    # mutating local sector state are listed for coverage but intentionally not called.
    for name in ["subscribe_formula", "unsubscribe_formula", "call_formula", "generate_index_data"]:
        skip("official_formula", name, "Requires a configured research-terminal formula; no formula name was supplied")
    if hasattr(xtdata, "call_formula_batch"):
        skip("official_formula", "call_formula_batch", "Requires configured research-terminal formulas")
    else:
        record("official_formula", "call_formula_batch", "UNSUPPORTED", "Documented API is absent from the installed xtquant package")

    for name in [
        "create_sector_folder",
        "create_sector",
        "add_sector",
        "remove_stock_from_sector",
        "remove_sector",
        "reset_sector",
    ]:
        skip("official_sector_write", name, "Mutates local sector state; excluded by the read-only safety policy")

    write_report(args.output_dir, args)
    basic_fail = any(r["category"] in {"environment", "connection"} and r["status"] != "PASS" for r in RESULTS)
    if hasattr(xtdata, "disconnect"):
        try:
            xtdata.disconnect()
        except Exception as exc:
            print(f"Warning: xtdata disconnect failed: {type(exc).__name__}: {exc}")
    return 2 if basic_fail else 0


def write_report(output_dir: str, args: argparse.Namespace) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    status_counts: dict[str, int] = {}
    category_status_counts: dict[str, dict[str, int]] = {}
    for item in RESULTS:
        status = item["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        category = item["category"]
        category_counts = category_status_counts.setdefault(category, {})
        category_counts[status] = category_counts.get(status, 0) + 1

    report_summary = {
        "official_main_api_entries": 43,
        "official_version_extension_entries": None,
        "extension_coverage_note": "Version-history extensions are manifest-based; no false fixed total is claimed",
        "total_items": len(RESULTS),
        "status_counts": status_counts,
        "items_with_return_value": sum(1 for item in RESULTS if item.get("has_return_value")),
        "items_with_valid_sample": sum(1 for item in RESULTS if item.get("has_valid_sample")),
        "permission_denied_items": sum(1 for item in RESULTS if item.get("permission") == "DENIED"),
        "subscriptions_accepted": sum(1 for item in RESULTS if item.get("subscription_accepted")),
        "callbacks_received": sum(1 for item in RESULTS if item.get("callback_received")),
        "fresh_callbacks_received": sum(1 for item in RESULTS if item.get("fresh_callback_received")),
        "category_status_counts": category_status_counts,
    }
    payload = {
        "policy": "ONE_SAMPLE_PER_DATA_CATEGORY",
        "scope": "XTDATA_DATA_CAPABILITIES_ONLY",
        "coverage": "REVIEW_P0_P1_DATA_SUPPLEMENT" if args.review_p0_p1_only else "CORE_XTDATA_PLUS_MANIFESTED_VERSION_EXTENSIONS_AND_ASSET_DOMAINS",
        "official_document": OFFICIAL_DOC_URL,
        "review_scope": REVIEW_SCOPE_URL,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.version,
        "args": sanitize_value(vars(args)),
        "summary": report_summary,
        "results": RESULTS,
    }
    json_path = out / f"qmt_api_official_{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def md_cell(value: Any, limit: int = 220) -> str:
        text = str(value if value is not None else "")
        text = text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
        return text[:limit]

    lines = [
        "# MiniQMT / XtData 数据能力报告",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Official documentation: {OFFICIAL_DOC_URL}",
        f"- Scope: XtData data capabilities only; review P0/P1 supplement={args.review_p0_p1_only}",
        f"- Policy: one valid sample per data category; unsafe writes are listed as SKIP",
        f"- Official main API entries: {report_summary['official_main_api_entries']}",
        f"- Version-history extensions: manifest-based, no fixed complete total claimed",
        f"- Total checklist items: {report_summary['total_items']}",
        f"- Status counts: {json.dumps(status_counts, ensure_ascii=False, sort_keys=True)}",
        f"- Valid samples: {report_summary['items_with_valid_sample']}",
        f"- Permission denied: {report_summary['permission_denied_items']}",
        f"- Subscriptions accepted: {report_summary['subscriptions_accepted']}",
        f"- Actual callbacks received: {report_summary['callbacks_received']}",
        f"- Fresh callbacks accepted as PASS: {report_summary['fresh_callbacks_received']}",
        "- Note: API-call PASS count is not a count of independently usable data permissions",
        "",
        "## 分类状态汇总",
        "",
        "| 类别 | PASS | EMPTY | NO_PERMISSION | UNSUPPORTED | ERROR | SKIP | NOT_TESTED |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for category, counts in category_status_counts.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    category,
                    str(counts.get("PASS", 0)),
                    str(counts.get("EMPTY", 0)),
                    str(counts.get("NO_PERMISSION", 0)),
                    str(counts.get("UNSUPPORTED", 0)),
                    str(counts.get("ERROR", 0)),
                    str(counts.get("SKIP", 0)),
                    str(counts.get("NOT_TESTED", 0)),
                ]
            )
            + " |"
        )
    lines.extend(
        [
        "",
        "## 逐项结果",
        "",
        "| 类别 | 适用资产 / 市场域 | 接口 / 检查项 | 中文说明 | 官方前置条件 | 状态 | 原因码 | API 可用 | 权限 | 有返回值 | 有效样本 | 订阅受理 | 任意回调 | 新鲜回调 | 实际返回字段 | 证据 |",
        "|---|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for item in RESULTS:
        api_available = item.get("api_available")
        api_text = "YES" if api_available is True else "NO" if api_available is False else "UNKNOWN"
        evidence = item.get("sample") or item.get("note") or ""
        fields = item.get("returned_fields") or []
        field_text = f"{len(fields)} 个：" + ", ".join(str(field) for field in fields) if fields else "无 / 未返回"
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(item.get("category")),
                    md_cell(item.get("domain_zh")),
                    md_cell(item.get("test")),
                    md_cell(item.get("description_zh"), limit=300),
                    md_cell(item.get("official_prerequisite")),
                    md_cell(item.get("status")),
                    md_cell(item.get("reason_code")),
                    api_text,
                    md_cell(item.get("permission")),
                    "YES" if item.get("has_return_value") else "NO",
                    "YES" if item.get("has_valid_sample") else "NO",
                    "YES" if item.get("subscription_accepted") else "NO",
                    "YES" if item.get("callback_received") else "NO",
                    "YES" if item.get("fresh_callback_received") else "NO",
                    md_cell(field_text, limit=320),
                    md_cell(evidence),
                ]
            )
            + " |"
        )
    md_path = out / f"qmt_api_official_{stamp}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nJSON report: {json_path.resolve()}")
    print(f"Markdown report: {md_path.resolve()}")
    print("Policy: one valid sample is sufficient for PASS; no bulk collection performed.")


if __name__ == "__main__":
    raise SystemExit(main())
