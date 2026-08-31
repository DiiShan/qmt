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

`security_master.delist_date_quality` 记录退市日来源质量。只有 XtData 返回实机确认的
`10001011/10001111/10011011/10011111/10111111` 哨兵值时，标准化层才令
`delist_date=NULL` 并标记 `INVALID_SENTINEL_IGNORED`。其他早于上市日的可解析日期原样
保留，并由 `listing_interval` 质量门禁阻断。

## 财务 PIT

财务数据至少包含：

```text
stock_code, table_name, source_record_key, logical_record_key, snapshot_version_key,
report_period, announce_date,
available_date, pit_quality, source_run_id, _ingested_at
```

仅有公告日期时，`available_date` 是公告日后的首个交易日。`announce_date` 缺失的记录默认不进入 PIT 查询。
`source_record_key` 区分公告版本中的明细；`logical_record_key` 区分同一业务明细；
`snapshot_version_key` 标识整份公告快照。Top10Holder 和 Top10FlowHolder 使用报告期内的
`rank` 区分明细，但 PIT 查询先选择最新整份公告快照再返回其中全部 rank，避免把不同公告
拼成一个不存在的混合快照。

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

## 数据库接受状态

`metadata/database_status.json` 是研究使用前必须检查的状态文件：

- `READY_FULL_HISTORY`：只有 Phase 0 完整 Gate PASS 后才可用于无偏历史全市场回测；
- `READY_CURRENT_UNIVERSE_ONLY`：只含初始化时仍可发现的股票，存在幸存者偏差；
- `INITIALIZING_*`：初始化未完成，不得作为稳定研究输入。

临时模式的历史股票池固定命名为 `CURRENT_SURVIVORS`，不能命名为 `ALL_A`。

## 波动率 Derived V1

`stock_vol_daily` 主键为 `trade_date, stock_code`。收益严格使用已验证累计复权因子生成的
adjusted close，并按最近一个有效交易收盘价计算简单收益；停牌、无成交、无有效价格时
`ret_1d=NULL`。股票 RV 使用 5/10/20/60/120 个市场交易日窗口、`ddof=1`、`sqrt(252)`
年化和 80% 最小有效样本。`rv20_pct252/756` 是不含当日的 prior-only 经验分位，
`shock_z20` 的分母使用前一日 `rv20`。

`market_vol_daily` 主键为 `trade_date, universe_name`，包含 Plan 冻结的 5/20/60 等权市场
RV、`median_stock_rv5/20/60`、个股 RV20 横截面分位、dispersion、high-vol/shock breadth、up/down RV 和
`implied_corr20/60`。相关性只使用 t 日 eligible 且 W 日窗口收益完整的股票，保持固定等权；
实际参与数量记录在 `implied_corr20_stock_count` 和 `implied_corr60_stock_count`。

同一数据集按 `universe_name` 分开发布全范围和沪深范围。当前存续库使用
`CURRENT_SURVIVORS` 与 `SH_SZ_CURRENT_SURVIVORS`；完整历史库使用 `ALL_A` 与
`SH_SZ_ALL_A`。沪深范围只保留代码后缀 `.SH`、`.SZ` 的 eligible 股票，并继续继承真实
`universe_scope`。

`index_vol_daily` 主键为 `trade_date, index_code`，覆盖上证50、沪深300、中证500、
中证1000、科创50和创业板。核心字段为 `index_name, close, ret_1d, log_ret_1d,
valid_return_flag, rv5/10/20/60/120, rv5_rv20, rv20_rv60, rv20_pct252/756,
up_rv20, down_rv20, down_up_ratio, shock_z20, valid_obs_*`。它使用官方指数收盘点位，
不应用股票复权因子。

当前数据库只能发布 `CURRENT_SURVIVORS / CURRENT_UNIVERSE_ONLY` 及对应沪深子集。`sector_vol_daily` 的
名称和计算接口已保留，但没有可靠 PIT/snapshot membership 时不注册、不发布。

## 参考证券与成分快照

| 数据集 | 业务键 | 含义 |
|---|---|---|
| `current_stock_list` | `as_of_date, stock_code` | 采集日确认的沪深京当前股票；交易所正式退市优先于 QMT 当前板块，且必须有上市日期。 |
| `delisted_stock_list` | `stock_code` | 上交所、深交所官方终止上市 A 股列表，包含上市日和终止上市日。北交所历史退市源尚未闭环。 |
| `security_master` | `stock_code` | 当前与退市证券的统一生命周期主表，增加 `listing_status/reference_source/reference_as_of_date`。 |
| `index_membership_snapshot_daily` | `snapshot_date, index_code, stock_code` | 六个宽基指数的 QMT 权重快照。 |
| `sector_membership_snapshot_daily` | `snapshot_date, sector_type, sector_code, stock_code` | 申万一级行业成员快照，限定在校正后的当前股票列表。 |

两个 membership 数据集首批记录的 `membership_quality` 均为
`OBSERVED_SNAPSHOT_ONLY`。它们只证明采集日观察到的真实成员，不能倒填为采集日前的历史成员，
也不会解除历史 `sector_vol_daily` 的 PIT 门禁。

所有波动率 manifest 必须记录直接 `input_runs`、volatility config hash、`rule_version`、
`factor_version` 和 `universe_scope`。`index_vol_daily` 不需要 `factor_version`，但必须记录
直接 `index_daily/trade_calendar` lineage、配置 hash、`price_basis=official_index_close` 和
`rule_version`。低 coverage 日期保留计数和质量标记，聚合指标为 NULL。
