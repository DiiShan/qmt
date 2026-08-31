# QMT 本地数据库数据调用说明书

> 面向对象：编写因子、选股、回测、绩效分析和风险分析程序的 AI 工具与开发者。  
> 数据目录：`E:\qmt_data`  
> DuckDB 入口：`E:\qmt_data\database\qmt.duckdb`  
> 当前状态：`READY_CURRENT_UNIVERSE_ONLY`。

## 1. 强制使用约束

每个策略程序在运行前必须读取 `E:\qmt_data\metadata\database_status.json`，并执行以下判断：

1. `state` 必须以 `READY_` 开头；
2. 当前 `universe_scope` 是 `CURRENT_UNIVERSE_ONLY`；
3. 当前 `accepted_for_unbiased_backtest` 是 `false`；
4. 股票池只能使用 `CURRENT_SURVIVORS`，不得把它改名或解释为 `ALL_A`；
5. 当前库不包含退市 A 股，不得用于声称“无幸存者偏差”的历史全市场回测；
6. `daily_bar` 是不复权日线；`corporate_action` 仍是 Raw-only，不能直接乘用；已验证的生产
   因子是 Derived `adjust_factor`，版本为 `xtdata_dr_cumprod_v1`；
7. 当前 CFFEX 合约库不完整，`future_daily`、`future_main_mapping`、`future_basis_daily`
   暂不得用于正式期货策略回测，详见第 8 节。

推荐的数据链路：

```text
策略/因子代码
    ↓
ResearchData Python API 或 DuckDB 只读 SQL
    ↓
qmt.duckdb 中的去重视图
    ↓
active manifest 指向的 Processed / Derived Parquet
```

策略程序不应直接读取 MiniQMT 缓存，也不应绕过视图扫描所有历史 run 目录。

## 2. Python 环境

项目要求 Python 3.11 或更高版本。建议一次性以 editable 模式安装：

```powershell
python -m pip install -e D:\project\codex\investment\qmt\qmt-api-probe
```

之后可从任意策略项目导入：

```python
from qmt_local_data.research import ResearchData

data = ResearchData(r"E:\qmt_data\database\qmt.duckdb")
```

如果不安装项目包，也可以只安装 `duckdb` 和 `pandas`，使用第 5 节的只读 SQL。

## 3. 标准启动模板

```python
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from qmt_local_data.research import ResearchData


DATA_ROOT = Path(r"E:\qmt_data")
STATUS_PATH = DATA_ROOT / "metadata" / "database_status.json"
DATABASE_PATH = DATA_ROOT / "database" / "qmt.duckdb"

status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
if not str(status.get("state", "")).startswith("READY_"):
    raise RuntimeError(f"Database is not ready: {status}")
if status.get("universe_scope") != "CURRENT_UNIVERSE_ONLY":
    raise RuntimeError(f"Unexpected universe scope: {status}")
if status.get("accepted_for_unbiased_backtest") is not False:
    raise RuntimeError(f"Invalid acceptance flag: {status}")

data = ResearchData(DATABASE_PATH)

bars = data.get_daily_bar(
    ["000001.SZ", "600000.SH"],
    start=date(2024, 1, 1),
    end=date(2024, 12, 31),
)
universe = data.get_universe("CURRENT_SURVIVORS", date(2024, 6, 28))
financial = data.get_financial_pit(
    ["000001.SZ", "600000.SH"],
    as_of=date(2024, 6, 28),
    tables=["Balance", "Income", "CashFlow"],
)
```

## 4. `ResearchData` API

| 方法 | 用途 | 关键参数/限制 |
|---|---|---|
| `get_daily_bar(codes, start, end)` | 股票日线 | 代码格式如 `000001.SZ`；价格未复权 |
| `get_index_daily(codes, start, end)` | 指数日线 | 代码格式如 `000300.SH` |
| `get_index_bar(...)` | 指数日线别名 | 与 `get_index_daily` 相同 |
| `get_universe(name, trade_date)` | 指定日股票池 | 当前只允许 `CURRENT_SURVIVORS` |
| `get_stock_volatility(codes, start, end)` | 个股波动率期限结构 | 只有 validated adjust factor 构建后才存在 |
| `get_market_volatility(universe_name, start, end)` | 全市场波动状态 | 当前必须显式使用 `CURRENT_SURVIVORS` |
| `get_index_volatility(codes, start, end)` | 六个宽基指数波动率 | 独立 `index_vol_daily`；不使用股票复权因子 |
| `get_sector_volatility(...)` | 板块波动率 | 可靠 PIT/snapshot membership 上线前明确报 BLOCKED |
| `get_financial_pit(codes, as_of, tables)` | 截至某日可知的最新财务记录 | 强制 `available_date <= as_of` |
| `get_future_contracts(products, active_on)` | 期货合约主表 | 当前仅诊断使用 |
| `get_future_daily(codes, start, end)` | 期货日线 | 当前仅诊断使用，必须再做生命周期/非空过滤 |
| `get_future_main(products, mapping_type, start, end)` | 主力映射 | 当前禁止正式回测；`mapping_type` 必须显式指定 |
| `get_future_basis(products, start, end)` | 期货基差 | 当前禁止正式回测 |

所有日期参数使用 `datetime.date`。空代码列表返回空 DataFrame。

### 沪深 A 股每日成交额

当前 `index_daily` 已包含：

- `000002.SH`：上证 A 股指数；
- `399107.SZ`：深证 A 指。

两个指数的 `amount` 按交易日相加，可作为沪深 A 股每日成交额。市场通常所说的“成交量
达到多少万亿元”实际指成交额，应优先使用 `amount`；`volume` 是成交数量，不能与成交额混用。

```sql
SELECT
    trade_date,
    SUM(amount) AS sh_sz_a_share_amount,
    SUM(volume) AS sh_sz_a_share_volume
FROM index_daily
WHERE index_code IN ('000002.SH', '399107.SZ')
GROUP BY trade_date
HAVING COUNT(DISTINCT index_code) = 2
ORDER BY trade_date;
```

`HAVING` 条件用于防止某日只存在一个市场的数据却被误报为完整沪深合计。该口径不含北交所；
沪深京全 A 应从经过历史成员校验的股票池逐股汇总，当前库仍受退市证券历史覆盖限制。

### 财务 PIT 示例

```python
from datetime import date

pit = data.get_financial_pit(
    ["000001.SZ"],
    as_of=date(2023, 8, 31),
    tables=["Balance", "Income", "PershareIndex"],
)
```

不要用 `report_period <= 回测日` 代替 PIT 条件。报告期结束并不代表信息已经公开；
策略应使用 `available_date`，该逻辑已经封装在 `get_financial_pit()` 中。

## 5. DuckDB 只读 SQL

```python
from datetime import date

import duckdb


connection = duckdb.connect(
    r"E:\qmt_data\database\qmt.duckdb",
    read_only=True,
)
bars = connection.execute(
    """
    SELECT trade_date, stock_code, open, high, low, close, volume, amount
    FROM daily_bar
    WHERE stock_code IN (?, ?)
      AND trade_date BETWEEN ? AND ?
    ORDER BY stock_code, trade_date
    """,
    ["000001.SZ", "600000.SH", date(2024, 1, 1), date(2024, 12, 31)],
).fetchdf()
```

查询可用视图和字段：

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'main' AND table_type = 'VIEW'
ORDER BY table_name;

DESCRIBE daily_bar;
DESCRIBE financial_pit;
```

AI 生成的稳定策略代码应显式列出所需字段，不要长期依赖 `SELECT *`，尤其是财务表的上游字段可能扩展。

### 日线与股票池联接

```sql
SELECT b.trade_date, b.stock_code, b.close, b.volume
FROM daily_bar AS b
JOIN historical_universe AS u
  ON b.trade_date = u.trade_date
 AND b.stock_code = u.stock_code
WHERE u.universe_name = 'CURRENT_SURVIVORS'
  AND u.eligible_flag
  AND b.trade_date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31';
```

注意：该查询仍有幸存者偏差，因为 `CURRENT_SURVIVORS` 不包含后来已经退市的公司。

## 6. DuckDB 视图契约

| 视图 | 业务主键 | 用途 |
|---|---|---|
| `daily_bar` | `trade_date, stock_code` | 股票日线 |
| `index_daily` | `trade_date, index_code` | 指数日线 |
| `future_daily` | `trade_date, contract_code` | 真实期货合约日线，当前不完整 |
| `security_master` | `stock_code` | 当前股票证券主表 |
| `future_contracts` | `contract_code` | 期货合约主表，当前不完整 |
| `trade_calendar` | `market, trade_date` | 交易日历 |
| `financial_pit` | `source_record_key` | 具有可得日期的财务记录 |
| `historical_universe` | `universe_name, trade_date, stock_code` | 每日股票池 |
| `future_main_mapping` | `mapping_type, effective_trade_date, product` | 主力合约映射，当前禁用 |
| `future_basis_daily` | `trade_date, contract_code` | 股指期货基差，当前禁用 |
| `stock_vol_daily` | `trade_date, stock_code` | 个股复权收益与多期限波动率 |
| `market_vol_daily` | `trade_date, universe_name` | 全范围及沪深 A 股双口径市场波动率 |
| `index_vol_daily` | `trade_date, index_code` | 六个宽基指数多期限波动率 |

DuckDB 视图按业务主键选择 `_ingested_at` 最新的活动记录。策略不需要自行对多次更新去重。

## 7. 股票策略的关键边界

- 当前有效股票日线覆盖 2011-01-04 至 2026-08-21，共 5,554 只当前上市股票；
- 不包含已退市股票，因此历史截面选股和组合回测存在幸存者偏差；
- `daily_bar` 为不复权价格，不要把长期收益直接解释为含分红总回报；
- 停牌、零成交和缺失价格必须由策略显式处理；
- 使用财务因子时必须走 `get_financial_pit()` 或等价的 `available_date <= as_of` SQL；
- 不要直接使用 Raw 财务公告，也不要按当前最新公告覆盖历史当时可知版本；
- 回测成交信号应至少滞后一根已完整收盘的日线，避免使用当日收盘后才可知的信息在同日成交。

## 8. CFFEX 期货数据现状

`CFFEX` 是 China Financial Futures Exchange，即中国金融期货交易所（中金所）。
本项目计划覆盖四类股指期货：

- `IF`：沪深 300 股指期货；
- `IH`：上证 50 股指期货；
- `IC`：中证 500 股指期货；
- `IM`：中证 1000 股指期货。

XtData 代码如 `IC2608.IF`：`IC` 是品种，`26` 是 2026 年，`08` 是交割月份，末尾 `.IF`
是 XtData 的中金所市场后缀。

2026-08-23 实机的“中金所”板块只返回以下 12 个合约：

```text
IC2608.IF  IC2609.IF  IC2612.IF  IC2703.IF
IF2608.IF  IF2609.IF  IF2612.IF  IF2703.IF
IH2608.IF  IH2609.IF  IH2612.IF  IH2703.IF
```

没有 IM，也没有 2010 年以来的大量已到期合约。这个板块表现为“当前/近期合约快照”，
不是历史合约主表。当前发现代码只读取运行时板块并按 `IF/IH/IC/IM + 四位年月 + .IF`
过滤；上游没有暴露旧合约，就无法枚举并下载完整历史。

此外，XtData 日线读取当前使用 `fill_data=True`。诊断发现每个合约都返回 2026-01-19 至
2026-08-21 的 141 个交易日；对尚未上市的日期，价格是 NULL、成交量和持仓量为 0、结算价为 0。
这些是占位行，不是真实交易记录。当前派生主力映射没有把 `list_date <= trade_date` 和有效价格
作为候选硬条件，因此相关主力/基差视图不得用于正式回测。

修复并验收完整期货库至少需要：

1. 取得可重复生成的 IF/IH/IC/IM 历史真实合约主表；
2. 验证每个合约的上市日、到期日和乘数；
3. 逐合约下载其生命周期内的日线；
4. 对期货禁用填充，或在标准层强制过滤生命周期外、价格为空和零占位记录；
5. 重新生成主力映射和基差；
6. 抽查每个品种至少一次正常换月，并确认 `NEXT_TRADE_DAY` 不使用未来信息。

## 9. 给 AI 工具的任务模板

把下面内容附在策略编程任务中：

```text
数据入口：E:\qmt_data\database\qmt.duckdb，只读访问。
先读取 E:\qmt_data\metadata\database_status.json；非 READY 状态立即停止。
当前 universe_scope=CURRENT_UNIVERSE_ONLY，存在幸存者偏差，不得声称无偏全市场回测。
股票池名称只能使用 CURRENT_SURVIVORS。
股票价格为不复权日线；corporate_action 尚不可直接用于复权。

### 波动率接口

真实库已于 2026-08-27 完成复权因子验证和 Derived 构建：

```python
from datetime import date
from qmt_local_data import ResearchData

data = ResearchData(r"E:\qmt_data\database\qmt.duckdb")
stock = data.get_stock_volatility(["000001.SZ"], date(2024, 1, 1), date(2024, 12, 31))
market = data.get_market_volatility(
    "CURRENT_SURVIVORS", date(2024, 1, 1), date(2024, 12, 31)
)
```

不得在当前库省略 market 的 universe 参数；默认 `ALL_A` 会因 scope 不一致而明确失败。
需要沪深 A 股独立口径时使用 `SH_SZ_CURRENT_SURVIVORS`；它仍继承当前存续股票的
幸存者偏差，不等于完整历史沪深 A 股。

宽基指数示例：

```python
indexes = data.get_index_volatility(
    ["000016.SH", "000300.SH", "000905.SH", "000852.SH", "000688.SH", "399006.SZ"],
    date(2024, 1, 1),
    date(2024, 12, 31),
)
```
`sector_vol_daily` 当前没有 active view，不能用当前板块成分回填历史。

### 证券清单和成分快照

```python
from qmt_local_data.research import ResearchData

data = ResearchData(r"E:\qmt_data\database\qmt.duckdb")
current = data.get_current_stock_list()
delisted = data.get_delisted_stock_list()
hs300 = data.get_index_membership(["000300.SH"])
sw1 = data.get_sector_membership("SW1")
```

不传 `as_of` 时，快照 API 返回数据库内最新采集日。请求早于首个采集日的成分历史不会自动
使用最新成员替代；2026-08-30 以前的指数/行业历史成分仍属于数据源缺口。
财务数据必须通过 financial_pit 且满足 available_date <= 决策日。
期货库当前不完整，禁止使用 future_daily/future_main_mapping/future_basis_daily 形成正式策略结论。
所有 SQL 显式列字段并使用参数绑定；不要直接扫描 raw/processed/derived 的全部 run 目录。
```

## 10. 更新与验证

在代码仓库目录运行：

```powershell
python scripts/update_database.py --config config/data_config.yaml --dry-run
python scripts/update_database.py --config config/data_config.yaml
python scripts/validate_database.py --config config/data_config.yaml
python scripts/storage_audit.py --config config/data_config.yaml
```

需要连同财务、公司行动、复权因子、历史股票池和波动率 Derived 一并重建时，使用
`python scripts/update_database.py --config config/data_config.yaml --full`。完整模式耗时和磁盘
占用显著高于日常核心更新。

更新是追加发布；DuckDB 活动视图负责按业务主键选择最新版本。不要在更新进程运行时启动另一个写入进程。

