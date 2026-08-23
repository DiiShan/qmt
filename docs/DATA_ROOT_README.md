# QMT 本地数据库目录说明

> 数据根目录：`E:\qmt_data`  
> 本说明基于 2026-08-23 初始化结果。数据库当前状态为
> `READY_CURRENT_UNIVERSE_ONLY`，不包含已退市 A 股，不能用于无幸存者偏差的全市场历史回测。

## 1. 使用前先看这里

先检查 `metadata/database_status.json`：

- `state` 必须以 `READY_` 开头；
- 当前 `universe_scope` 为 `CURRENT_UNIVERSE_ONLY`；
- 当前 `accepted_for_unbiased_backtest` 为 `false`；
- 写入过程中如果状态为 `INITIALIZING_*`，不要把数据库当作完整版本使用。

不要手工修改 `raw`、`processed`、`derived`、`metadata/manifests` 中的文件。
DuckDB 查询层只读取 active manifest 指向的 Parquet 文件；目录中“看起来存在”的文件不一定属于当前活动版本。

### 两个存储位置不是同一个东西

- `D:\software\program\兴业证券SMT-Q-2.0.8.0-test\userdata_mini\datadir` 是
  **MiniQMT/XtData 上游缓存**。`download_history_data()`、`download_financial_data2()` 等接口先把券商行情源数据
  下载到这里，XtData 再从这里返回 DataFrame。它可以被重新下载，不是策略的稳定查询接口。
- `E:\qmt_data` 是本项目构建的 **研究数据库**。它把读取到的数据转换为有 manifest、质量标记、
  Processed/Derived 层和 DuckDB 视图的持久化数据，是策略和 AI 工具应该访问的位置。

数据流是 `券商行情源 → D 盘 MiniQMT 缓存 → XtData → E 盘 Parquet/DuckDB`。
把数据库放到 E 盘不会自动改变 MiniQMT 客户端自身的缓存位置；两者都存在是正常设计。
已经落入 E 盘活动 Parquet 的数据可由 DuckDB 独立查询，但后续下载和更新仍需要 MiniQMT 缓存与客户端。

## 2. 顶层目录

```text
E:\qmt_data\
├─ raw\          # 原始层：尽量保留 XtData 返回形态
├─ processed\    # 标准层：字段规范化、类型转换和质量校验后的数据
├─ derived\      # 派生层：历史样本空间、期货主力映射、基差等
├─ database\     # DuckDB Catalog/View；不复制全部 Parquet 数据
├─ metadata\     # 状态、manifest、checkpoint、容量审计等控制信息
├─ staging\      # 原子发布临时区；成功发布后通常接近空目录
├─ quarantine\   # 已隔离的中断/异常文件，不属于当前活动数据库
└─ README.md      # 本说明
```

### `raw/`：原始层

保存从 MiniQMT/XtData 读取后、进入标准化处理前的数据。主要数据集：

- `stock_daily`：A 股日线原始数据；
- `index_daily`：指数日线原始数据；
- `future_daily`：中金所合约日线原始数据；
- `financial`：八类财务表的原始数据；
- `corporate_action`：分红/复权因子原始数据，目前仍标记为
  `RAW_ONLY_PENDING_FACTOR_SEMANTICS_VALIDATION`。

典型结构：

```text
raw\stock_daily\run_id=<运行标识>\
├─ data.parquet
└─ SUCCESS
```

`data.parquet` 是 Zstd 压缩的列式数据；`SUCCESS` 表示该运行目录已完整发布。

### `processed/`：标准层

保存可直接用于查询、校验和派生计算的标准化数据。主要数据集：

- `stock_daily`：标准股票日线；
- `index_daily`：标准指数日线；
- `future_daily`：标准期货日线；
- `financial`：带 `announce_date`、`available_date` 等时点字段的财务数据；
- `security_master`：证券主表；
- `future_contract_master`：期货合约主表；
- `trade_calendar`：交易日历。

Raw 与 Processed 同时保留是有意设计：Raw 用于追溯，Processed 用于稳定研究接口。

### `derived/`：派生层

- `historical_universe`：每日股票样本空间。当前名称为 `CURRENT_SURVIVORS`，只包含现在仍上市的股票；
- `future_main_mapping`：期货主力合约映射；
- `future_basis_daily`：期货相对现货指数的基差。

### `database/`：DuckDB 查询入口

`database/qmt.duckdb` 主要保存 Catalog、View 和刷新日志。实际大数据仍在 Parquet 中，
因此 DuckDB 文件很小是正常现象，不代表数据库为空。

主要视图包括：

- `daily_bar`
- `index_daily`
- `future_daily`
- `security_master`
- `future_contracts`
- `trade_calendar`
- `financial_pit`
- `historical_universe`
- `future_main_mapping`
- `future_basis_daily`

视图会依据活动 manifest 对多次追加运行按业务主键去重。

### `metadata/`：控制面

- `database_status.json`：数据库状态和范围标签；
- `manifests/<layer>/<dataset>/active.json`：当前活动版本及其 Parquet 文件列表；
- `manifests/<layer>/<dataset>/<run_id>.json`：历史发布记录；
- `checkpoints/`：行情批次完成记录，用于中断续跑；
- `storage_audit.json`：容量审计结果（存在时）；
- `project.lock`：单写者锁，只应在初始化或更新进程运行时存在。

### `staging/`：临时发布区

新批次先写入 staging，写完 Parquet 和 `SUCCESS` 后再原子移动到正式层。
程序异常时可以留下临时文件，但它们不会自动进入活动 manifest。

### `quarantine/`：隔离区

保存人工中断或异常运行留下、已经从活动路径移出的文件。当前隔离内容来自旧版逐股发布的
corporate-action 初始化，约 68.6 MiB。它不参与 DuckDB 查询，也不计入活动清单。

不要仅凭目录名直接删除；应先确认 `metadata/manifests/**/active.json` 没有引用其中任何文件。

## 3. 当前数据覆盖

| 数据 | 当前结果 |
|---|---:|
| 当前上市 A 股证券数 | 5,556 |
| 股票日线 | 16,350,700 行 |
| 股票日线日期 | 2011-01-04 ～ 2026-08-21 |
| 财务 Raw/Processed 活动行数 | 各 5,806,480 行 |
| 财务 PIT 查询视图 | 1,384,430 行 |
| 历史样本空间 | 13,498,712 行 |
| 指数日线 | 18,990 行，5 个指数 |
| 期货日线物理记录 | 1,692 行，12 个合约；含上市前空占位行，暂不可用于正式回测 |
| 期货物理日期 | 2026-01-19 ～ 2026-08-21；不等于每个合约的真实交易期 |
| corporate action | 45,965 行，56 个批次 |

## 4. 为什么计划约 10–20 GB，实际只有约 1.4 GiB

原计划中的 10–20 GB 是保守的工程容量预算，不是数据库必须达到的大小。计划原文也明确：
“这是工程预算，不是对 QMT 实际压缩率的承诺；必须在真实数据落盘后报告实际大小。”

2026-08-23 的实际占用为：

| 位置/数据集 | 实际占用 |
|---|---:|
| `raw/financial` | 442.51 MiB |
| `processed/financial` | 399.66 MiB |
| `raw/stock_daily` | 262.08 MiB |
| `processed/stock_daily` | 254.50 MiB |
| `derived/historical_universe` | 11.18 MiB |
| 其他活动数据与 metadata | 约 5 MiB |
| `quarantine/`（不参与查询） | 68.63 MiB |
| `E:\qmt_data` 合计 | 约 1.412 GiB |

偏差来源：

1. **Parquet + Zstd 压缩效果远好于预算假设。** 股票日线每层有 1,635 万行，
   但 Raw 和 Processed 分别只约 262 MiB、255 MiB；代码、日期和数值列重复度高，列式压缩非常有效。
2. **DuckDB 不复制 Parquet。** `qmt.duckdb` 约 0.5 MiB，只保存视图和元数据；
   原预算给 DuckDB/Catalog 预留了最多 2 GB。
3. **当前是临时 `CURRENT_UNIVERSE_ONLY` 库。** 已退市 A 股尚未纳入，完整历史库会更大。
4. **期货历史范围尚未达到原计划。** MiniQMT 当前只发现 12 个可用中金所合约，
   分别是 `IC/IF/IH` 的 `2608/2609/2612/2703`，没有 IM，也没有更早历史合约。
   XtData 还为合约上市前日期返回了空价格、零成交占位行。因此当前期货、主力和基差视图
   只能用于诊断，不能用于正式策略回测。
5. **MiniQMT 自身缓存不在 E 盘数据库目录。** 当前缓存位于
   `D:\software\program\兴业证券SMT-Q-2.0.8.0-test\userdata_mini\datadir`，约 3.511 GiB。
   `E:\qmt_data` 与该缓存合计约 4.923 GiB，但二者职责不同，不能简单合并为数据库文件大小。
6. **v1 没有分钟、Tick、盘口和逐笔数据。** 当前主要是日频数据；这些高频数据才会快速消耗数十 GB。

因此，1.4 GiB 本身不是“日线漏下载”的证据：活动 manifest 已验证，DuckDB 中股票日线确有
1,635 万行并覆盖 2011-01-04 至 2026-08-21。不过，退市 A 股和完整历史期货仍是明确的数据范围缺口，
应继续保留在数据质量与风险报告中。

## 5. 常用命令

在项目代码目录运行：

```powershell
# 每日收盘后更新
python scripts/update_database.py --config config/data_config.yaml

# 校验所有活动 manifest
python scripts/validate_database.py --config config/data_config.yaml

# 容量审计
python scripts/storage_audit.py --config config/data_config.yaml
```

项目仓库：<https://github.com/DiiShan/qmt>

面向 AI 策略编程的完整调用方式见仓库 `docs/DATA_ACCESS_GUIDE.md`，数据目录中同步副本为
`E:\qmt_data\DATA_ACCESS_GUIDE.md`。

