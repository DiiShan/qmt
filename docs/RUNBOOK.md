# QMT 本地数据库运行手册

## 前置条件

- Windows；
- MiniQMT 已启动并登录；
- 当前 Python 能导入 `xtquant.xtdata`；
- 默认数据根目录为 `E:\qmt_data`；
- 正式运行前确认 QMT cache 与项目目录所在磁盘空间。

## 1. Phase 0 Preflight

先做只读/缓存读取检查：

```powershell
python scripts/preflight_database.py --config config/data_config.yaml
```

首次闭环历史退市证券和过期合约时：

```powershell
python scripts/preflight_database.py --config config/data_config.yaml `
  --download-history-contracts --allow-sample-download
```

只有五项硬门槛全部 PASS 才能执行全量初始化。命令返回 2 表示 Gate 阻断。

## 2. 初始化

不带确认参数只显示计划，不下载：

```powershell
python scripts/init_database.py --config config/data_config.yaml
```

明确确认后执行：

```powershell
python scripts/init_database.py --config config/data_config.yaml --confirm-full-download
```

### 临时当前股票池模式

当且仅当退市 A 股发现是唯一未解决的完整性缺口，且项目负责人明确接受幸存者偏差时，
可以执行：

```powershell
python scripts/init_database.py --config config/data_config.yaml `
  --confirm-full-download --allow-current-universe-only
```

该模式使用与正式库相同的 Raw/Processed/Derived/DuckDB 架构，但有以下不可绕过的标识：

- database status 为 `READY_CURRENT_UNIVERSE_ONLY`；
- manifest metadata 写入 `universe_scope=CURRENT_UNIVERSE_ONLY`；
- 股票池名称为 `CURRENT_SURVIVORS`，禁止发布为 `ALL_A`；
- `accepted_for_unbiased_backtest=false`；
- 后续补齐退市证券后，通过新 run 重建 `ALL_A`，不覆盖现有 Raw。

全量流程采用项目级单写者锁、有限证券批次、不可变 run、原子 active manifest 和 checkpoint。进程中断后重新运行同一范围会跳过 fingerprint 一致的成功批次。

## 3. 增量更新

### 3.1 推荐：一键更新

先只查看自动计算的回看区间：

```powershell
python scripts/update_database.py --config config/data_config.yaml --dry-run
```

执行日常核心更新：

```powershell
python scripts/update_database.py --config config/data_config.yaml
```

脚本按 `revision_lookback_trade_days` 自动回看交易日，依次维护交易日历、A 股日线、
`markets.indexes` 中全部指数、官方当前/退市证券参考、指数/行业成分快照，最后刷新 Catalog、
数据库状态、Manifest 校验和容量审计。`000002.SH`、`399107.SZ` 已包含在配置，因此自动更新。

需要把财务、公司行动、复权因子、历史股票池和全部波动率派生层也重建到同一截止日时：

```powershell
python scripts/update_database.py --config config/data_config.yaml --full
```

`--full` 会从项目历史起点重建大型 Derived 数据，确保当前股票池变化不会留下旧口径，但会
明显增加运行时间和不可变历史 run 的磁盘占用。CFFEX 期货三项仍因历史合约源未闭环而明确
保留为人工更新，不在一键脚本中伪装成完整更新。

维护约束：以后新增、删除或改变 `config/datasets.yaml` 中的数据集时，必须同步修改
`qmt_local_data.maintenance` 的 `DAILY_MAINTAINED_DATASETS`、`FULL_REBUILD_DATASETS` 或
`MANUAL_DATASETS` 分类。`tests/test_maintenance.py` 会在存在未分类数据集时失败。

### 3.2 底层单项命令

```powershell
python scripts/update_daily.py --config config/data_config.yaml `
  --start 2026-08-01 --end 2026-08-23 --download
```

指数行情使用同一命令的独立资产参数；未传 `--codes` 时读取 `markets.indexes`：

```powershell
python scripts/update_daily.py --config config/data_config.yaml --asset index `
  --start 2026-08-01 --end 2026-08-23 --download
```

当前配置同时维护 `000002.SH`（上证 A 股指数）和 `399107.SZ`（深证 A 指）。每日指数更新
成功后，可按交易日汇总两者的 `amount` 得到沪深 A 股成交额；完整性检查必须确认当日两只
指数均存在。

上游缺行不会自动解释为删除。重复业务主键由 DuckDB view 按 `_ingested_at` 和 `source_run_id` 选择最新已发布版本。

## 4. 验证与容量

```powershell
python scripts/validate_database.py --config config/data_config.yaml
python scripts/storage_audit.py --config config/data_config.yaml
```

## 4.1 波动率 Derived

波动率真实构建要求 active `adjust_factor` manifest 明确标记
`PRODUCTION_READY_VALIDATED_FACTOR`，带 `factor_version`、至少三个公司行动 PASS 案例和一个
无事件区间 PASS 案例。先生成只读审计报告：

```powershell
qmt-local-data build-adjust-factor --config config/data_config.yaml `
  --audit-output reports/adjust_factor_audit.json
```

审计 PASS 后才允许显式发布：

```powershell
qmt-local-data build-adjust-factor --config config/data_config.yaml `
  --factor-version xtdata_dr_cumprod_v1 `
  --audit-output reports/adjust_factor_audit.json --publish
```

该规则来自 XtData 官方等比后复权示例：每个交易日因子等于当日及以前事件 `dr` 的累计乘积。
2026-08-27 真实审计与发布记录见 `reports/adjust_factor_audit.json`。未经审计的 Raw-only 公司
行动状态会让波动率命令返回 2，且不会发布任何 volatility active manifest。

首次构建或仅追加新日期：

```powershell
qmt-local-data build-volatility --config config/data_config.yaml `
  --start 2024-01-01 --end 2026-08-27
```

该命令同时发布 `stock_vol_daily`、双口径 `market_vol_daily` 和 `index_vol_daily`。双口径为
当前/full scope 对应的全范围股票池，以及独立沪深 A 股子集。

指数波动率也可以独立构建；它不依赖股票复权因子：

```powershell
qmt-local-data build-index-volatility --config config/data_config.yaml `
  --start 2011-01-04 --end <最新交易日>
```

仅重建市场聚合（例如新增市场口径或横截面字段）时，可复用 active `stock_vol_daily`：

```powershell
qmt-local-data build-market-volatility --config config/data_config.yaml `
  --rebuild-from 2011-01-04 --end <最新交易日>
```

修订历史行情、universe 或复权因子后必须显式重建尾部：

```powershell
qmt-local-data build-volatility --config config/data_config.yaml `
  --rebuild-from 2024-01-01 --end 2026-08-27
```

普通 build 与 active 日期重叠时会拒绝执行。`--rebuild-from` 保留变更日前缀、重算其后全部
rolling/percentile/EWMA 影响并 replace active run；旧 immutable runs 不删除。

当前 `READY_CURRENT_UNIVERSE_ONLY` 生成 `CURRENT_SURVIVORS` 和它的沪深子集
`SH_SZ_CURRENT_SURVIVORS`。在退市证券闭环前禁止解释为 `ALL_A/SH_SZ_ALL_A`。
sector membership 未验证前不发布 `sector_vol_daily`。

## 更新证券清单和成分快照

```powershell
qmt-local-data update-reference-data --config config/data_config.yaml `
  --as-of 2026-08-30

qmt-local-data build-universe --config config/data_config.yaml

qmt-local-data build-volatility --config config/data_config.yaml `
  --rebuild-from 2011-01-04 --end 2026-08-21

python scripts/validate_reference_data.py --config config/data_config.yaml
qmt-local-data validate --config config/data_config.yaml
```

`update-reference-data` 从上交所、深交所官方接口更新当前/退市清单，从 MiniQMT 更新六个指数
权重和申万一级行业快照。对同一 `as_of` 重跑采用 replace 语义，允许正确删除来源修订记录。
历史指数/行业成分不能由当前快照倒填；应每天运行该命令，从首次采集日向后积累 PIT 快照。

容量阈值：目标 25 GiB、警告 30 GiB、硬停止 40 GiB。程序不自动删除 Raw、Processed 或 QMT cache。
容量预检由统一 manifest 发布路径执行，因此行情、财务、历史 universe 和 Derived 都不能
绕过硬限制；checkpoint、catalog 和容量报告写入前也会预留元数据空间。
财务下载还会在调用 XtData 前按 `financial_download_batch_reserve_mb`（默认 256 MiB）预留
空间，并自动发现 QMT cache 路径，分别检查项目盘和缓存盘的最低剩余空间。

## 5. 故障恢复

- 没有 `SUCCESS` 的 staging run 不进入 active manifest；
- checksum/文件缺失会让验证命令返回非零；
- stale lock 不能自动清理，必须检查持有者后显式处理；
- Derived 失败时从已发布 Processed 重建，不重新下载 Raw；
- 不要手工修改 `metadata/manifests/**/active.json`。

## 数据安全

GitHub 只保存代码、配置模板、schema、文档和合成测试数据。真实行情、财务数据、报告、日志、账号、Token、服务器地址与本机私有路径不得提交。
