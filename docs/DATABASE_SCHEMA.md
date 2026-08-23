# QMT 本地数据库 Schema v1

> Schema 版本使用 `MAJOR.MINOR`。下列为 `1.0` 最小稳定契约；Raw 层额外保留 XtData 原始字段。

## 行情与基础数据

| Dataset | 业务主键 | 核心字段 |
|---|---|---|
| `security_master` | `stock_code` | 名称、交易所、类型、板块、上市日、退市日 |
| `trade_calendar` | `market, trade_date` | 是否开市、上一/下一交易日 |
| `stock_daily` | `trade_date, stock_code` | OHLC、pre_close、volume、amount、suspend_flag |
| `index_daily` | `trade_date, index_code` | OHLC、pre_close、volume、amount |
| `future_contract_master` | `contract_code` | product、exchange、list/expire date、multiplier |
| `future_daily` | `trade_date, contract_code` | OHLC、settlement、volume、open_interest |

每个 Processed/Derived row 还包含 `source_run_id` 与 `_ingested_at`。DuckDB view 按业务主键选择最新已发布版本；物理 Parquet run 不原地修改。

## 财务 PIT

财务数据至少包含：

```text
stock_code, table_name, source_record_key, logical_record_key, report_period, announce_date,
available_date, pit_quality, source_run_id, _ingested_at
```

仅有公告日期时，`available_date` 是公告日后的首个交易日。`announce_date` 缺失的记录默认不进入 PIT 查询。
`source_record_key` 区分公告版本；`logical_record_key` 区分同一业务明细。Top10Holder 和
Top10FlowHolder 使用报告期内的 `rank` 区分十条明细，PIT 查询按逻辑明细淘汰旧修订，
不会把同一报告期压缩为一行。

研究代码应通过 `ResearchData.get_financial_pit(codes, as_of)` 读取；该接口只返回
`available_date <= as_of` 的最新公告版本，避免直接扫描全历史财务表造成未来函数。

## 期货主力

`future_main_mapping` 主键：

```text
mapping_type, effective_trade_date, product
```

- `EOD_OBSERVED`：T 日收盘后才可见；禁止用于 T 日成交决策。
- `NEXT_TRADE_DAY`：T 日 EOD 结果在下一交易日生效；用于可交易日频序列。

选取规则 `oi_then_volume_v1`：最大持仓量；全部持仓量无效时使用最大成交量；并列时先选更早到期日，再按合约代码排序。

## 股指期货基差

```text
basis_close       = future_close - spot_close
basis_settlement  = future_settlement - spot_close
basis_pct         = basis_close / spot_close
days_to_expiry    = expire_date - trade_date  # 自然日
annualized_basis  = basis_pct * 365 / days_to_expiry
```

这是自然日、365 天、单利年化。到期天数非正、现货价非正或必需价格缺失时结果为 NULL。

## 研究查询接口

`qmt_local_data.ResearchData` 提供 `get_daily_bar`、`get_index_daily`、
`get_future_daily`、`get_future_main`、`get_future_basis`、`get_universe` 和
`get_financial_pit`。`get_future_main` 强制调用者明确指定 `EOD_OBSERVED` 或
`NEXT_TRADE_DAY`，不提供有歧义的默认值。
