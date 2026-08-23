# QMT 本地数据库构建计划（Codex 收敛版）

> 文档状态：待独立 Review 收敛
>
> 版本日期：2026-08-23
>
> 依据：[`本地数据库构建计划.md`](本地数据库构建计划.md)、[`qmt权限-20260823版本.md`](qmt权限-20260823版本.md)、[`CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md)
>
> 本文只规划数据库 v1 的建设与验收，不在本轮下载全量数据或实现交易能力。

## 1. 目标、边界与决策优先级

### 1.1 v1 目标

在已登录 MiniQMT 的 Windows 主机上，建设一个可增量更新、可断点续传、可重建、可审计且不引入未来函数的本地**日频量化研究数据底座**。v1 完成后应稳定支持：

- 沪、深、北 A 股历史日线与历史股票池；
- 原始价格、可重建复权价格和可用于回测的收益序列；
- 财务八表的 Point-in-Time 查询；
- 主要宽基指数日线；
- CFFEX IF、IH、IC、IM 真实历史合约日线；
- 版本化的主力映射、连续序列和股指期货基差；
- DuckDB 统一查询入口；
- 后续因子、策略、回测和风险模块复用同一数据契约。

### 1.2 明确不在 v1 中建设

- XtTrader、下单、撤单、账户、资金或持仓；
- 全市场分钟、tick、实时全推和 Level 2；
- 期权、商品期货全市场、港股、美股和外盘；
- ETF IOPV、订单流、特色 VIP period；
- Web 服务、调度平台、分布式计算集群；
- 任何未经有效样本验证的数据域。

这些能力未来只能以新增 dataset/adapter 的方式接入，不改变 `Raw → Processed → Derived → DuckDB` 主架构。

### 1.3 决策优先级

冲突时按以下顺序决策：

1. 时间一致性和可审计性；
2. 数据正确性和可重建性；
3. 幂等、断点续传和故障恢复；
4. 存储硬限制；
5. 查询性能；
6. 开发便利性。

不得为追求覆盖率伪造缺失历史，不得把“命令被接受”当成“数据可用”，不得把当前成分回填到历史日期。

## 2. 已知事实、待验证项与硬门槛

### 2.1 当前实机已确认，可进入样本闭环

| 数据域 | 当前证据 | v1 用法 |
|---|---|---|
| 沪深 A 股、北交所股票 `1d` | PASS，有有效样本 | 股票日线 |
| 主要指数 `1d` | PASS，有有效样本 | benchmark/现货映射 |
| CFFEX 股指期货 `1d/1m` | PASS，有有效样本 | v1 只保存 `1d` |
| 财务八表 | 全部 PASS | 财务 PIT |
| `get_divid_factors` | PASS | 公司行动/复权输入 |
| `get_trading_dates` | PASS | 交易日历 |
| `get_instrument_detail` | PASS | 证券/合约静态信息 |
| 板块清单与成分 | PASS | 当前证券和合约发现的辅助入口 |

### 2.2 仍须在 Preflight 形成证据

- `download_history_contracts()` 是否能完成且能发现历史退市 A 股和过期 CFFEX 合约；
- 历史退市 A 股能否读取静态信息与至少一根历史日线；
- 过期 CFFEX 合约能否读取静态信息与至少一根历史日线；
- CFFEX 日线实际返回字段是否稳定包含结算价、成交量和持仓量；
- 财务记录中公告日期、报告期和修订记录的真实字段名、类型、时区/日期语义；
- 除权因子字段的实际含义及能否支持预期复权公式；
- QMT 缓存目录能否可靠定位、实际历史最早日期和批量下载吞吐。

### 2.3 Phase 0 硬门槛

以下五项必须全部 PASS，才允许启动股票/期货全量初始化：

1. 当前 A 股日线有效样本；
2. 历史退市 A 股发现；
3. 历史退市 A 股日线有效样本；
4. CFFEX 过期真实合约发现；
5. CFFEX 过期真实合约日线有效样本。

若 2 或 3 失败，禁止用当前股票列表代替历史证券全集；数据库建设停在样本/能力诊断阶段。若 4 或 5 失败，股票核心库可继续样本开发，但期货全量、主链和基差不得标记完成，且 v1 总体验收不通过。

## 3. 唯一标准架构

```text
MiniQMT / XtData
        │
        ▼
采集器（批次、重试、checkpoint、manifest）
        │
        ▼
Raw Parquet（不可变批次，忠实保留来源字段）
        │
        ▼
Processed Parquet（标准 schema、去重、PIT、质量规则）
        │
        ├──────────────► Derived Parquet（可删除并重建）
        │
        ▼
DuckDB（Catalog、View、小型元数据表；不复制全部大表）
        │
        ▼
Research API / Factor / Strategy / Backtest / Risk
```

### 3.1 各层职责

- **Raw**：按采集 run 落盘；已成功发布的文件不可原地修改。上游补数或修订产生新 run。
- **Processed**：规范字段、类型、主键和时间语义；对 Raw 多版本做确定性选取；可以从 Raw 重建。
- **Derived**：复权、历史 universe、主力映射、连续序列和基差；可以从 Processed 重建。
- **DuckDB**：保存 schema/catalog、views、运行与质量摘要等小表；大表默认通过 `read_parquet(..., hive_partitioning=true)` 查询。
- **Research API**：唯一面向研究代码的稳定接口；研究模块不得直接调用 XtData。

### 3.2 发布原子性

每个 dataset 的一次写入遵循：

```text
写入 staging/run_id
→ 校验文件可读、schema、行数、主键和 checksum
→ 生成 manifest
→ 原子重命名/切换 active manifest
→ 写入 SUCCESS 标记
```

没有 `SUCCESS` 的 run 不进入 Processed 或 DuckDB view。失败 run 可诊断、可安全重试，不覆盖上一个成功版本。

## 4. 仓库与数据目录

### 4.1 Git 仓库交付结构

```text
config/
  data_config.yaml
  datasets.yaml
src/qmt_local_data/
  cli.py
  config.py
  qmt_client.py
  models.py
  manifest.py
  checkpoint.py
  storage_guard.py
  discovery.py
  ingest/
  transform/
  derived/
  catalog.py
  quality.py
scripts/
  preflight_database.py
  init_database.py
  update_daily.py
  validate_database.py
  storage_audit.py
tests/
  unit/
  integration/
  fixtures/
docs/
  DATABASE_SCHEMA.md
  RUNBOOK.md
  DATA_QUALITY_REPORT.md
  STORAGE_REPORT.md
```

实现时可调整模块拆分，但公开 CLI、数据契约和交付物不得弱化。

### 4.2 本地持久化目录

```text
data/
  raw/{dataset}/ingest_date=YYYY-MM-DD/run_id=.../
  processed/{dataset}/...
  derived/{dataset}/...
  database/qmt.duckdb
  metadata/manifests/
  metadata/checkpoints/
  metadata/quality/
  logs/
  staging/
```

`data/`、真实报告、日志、缓存路径和临时文件必须进入 `.gitignore`。Git 只保存代码、配置、schema、去敏报告、小型合成 fixture 与文档。

## 5. 配置、运行标识与元数据契约

### 5.1 最小配置

```yaml
project:
  timezone: Asia/Shanghai
  history_start: 2011-01-01
  history_fallback_start: 2014-01-01
  stock_period: 1d
  compression: zstd

storage:
  target_gb: 25
  warning_gb: 30
  hard_limit_gb: 40
  future_project_ceiling_gb: 100

ingestion:
  initial_batch_size: 100
  max_retries: 3
  retry_backoff_seconds: [5, 30, 120]

futures:
  products: [IF, IH, IC, IM]
  main_rule_version: oi_then_volume_v1
```

路径不得硬编码在源代码中；MiniQMT/QMT 缓存路径通过显式配置或只读发现得到。敏感路径只保留在本地配置，公开报告去敏。

### 5.2 每次 run 必记元数据

| 字段 | 说明 |
|---|---|
| `run_id` | UUID 或等价全局唯一标识 |
| `dataset` / `schema_version` | 数据集和契约版本 |
| `source` / `source_version` | `xtdata`、客户端/包版本 |
| `requested_start/end` | 请求范围 |
| `actual_min/max_date` | 实际覆盖 |
| `started_at/finished_at` | 带时区时间 |
| `status` | `STARTED/SUCCESS/FAILED/BLOCKED` |
| `rows/files/bytes` | 产出规模 |
| `input_runs` | 转换/派生所依赖的 run |
| `code_commit` / `config_hash` | 代码和配置可追溯性 |
| `checksums` | 文件校验值 |
| `error_summary` | 失败摘要，不含隐私 |

### 5.3 Schema 演进

- schema 使用整数版本，新增可空列允许向后兼容的小版本演进；
- 删除/改名/语义变化必须升级主版本并提供迁移或全量重建步骤；
- 未知上游字段先保存在 Raw；不得静默塞入 Processed；
- DuckDB view 只指向当前被支持的 schema 版本；
- 每次转换把 `schema_version` 和来源 run 写入 manifest，不要求在每行重复保存。

## 6. 核心数据集与最小契约

所有日期在 Processed 层使用 DuckDB/Arrow `DATE`；时间戳使用带 `Asia/Shanghai` 语义的时间。价格和金额使用能避免无意二进制浮点比较的明确精度策略；具体 Decimal 精度在样本 profiling 后冻结于 `DATABASE_SCHEMA.md`。证券/合约代码保持字符串，不做数值化。

### 6.1 `security_master`

最小字段：

```text
stock_code, stock_name, exchange, security_type, board,
list_date, delist_date, source_run_id
```

主键为 `stock_code`。`delist_date` 可空；不能根据当前列表推断历史退市日。代码曾被复用或名称/分类随时间变化时，另建版本化属性表，不覆盖历史。

### 6.2 `trade_calendar`

```text
market, trade_date, is_open, previous_trade_date, next_trade_date
```

主键为 `(market, trade_date)`。v1 使用已确认可用的 `get_trading_dates` 构建；不等待不可用的 `get_trading_calendar`。

### 6.3 `stock_daily`

```text
trade_date, stock_code, open, high, low, close, pre_close,
volume, amount, suspend_flag, source_run_id
```

Processed 业务主键为 `(trade_date, stock_code)`。Raw 保留 XtData 原始字段名和值；Processed 字段映射以样本 schema 为准。`0`、空值、停牌和无成交不得在转换时混为一类。

### 6.4 公司行动与复权

```text
corporate_action:
  stock_code, effective_date, action_type, source_fields..., source_run_id

adjust_factor:
  trade_date, stock_code, factor, factor_version, source_run_id
```

Raw 保存 `get_divid_factors` 原始字段。Phase 4 先通过至少三个已知分红/送转案例验证字段含义和公式，再冻结标准化 schema。原始 OHLC 永不被复权值覆盖。复权产物带 `factor_version`，可从公司行动/因子和原始行情重建。

### 6.5 财务八表

每张表至少保留：

```text
stock_code, report_period, announce_date, source_record_key,
source_run_id, ingested_at, <table-specific fields>
```

业务唯一性以实际 schema profiling 后冻结，不能先假定只有 `(stock_code, report_period)`。同一报告期的更正/修订必须保留多版本。

PIT 可见性规则：

- 若只有 `announce_date` 而没有可靠公告时间，则该记录最早在 **公告日后的首个交易日** 可用于日频策略；
- 若以后获得可靠且有时区的盘前/盘后时间，升级 PIT 规则版本，不回写旧结果；
- 截止某研究日的查询选取 `available_date <= as_of_date` 的最新可用修订；
- `report_period` 绝不能作为可见日期；
- 缺少可靠公告日期的记录进入隔离/质量报告，默认不进入回测输入。

### 6.6 `stock_status` 与 `historical_universe`

```text
stock_status:
  trade_date, stock_code, listed_flag, suspended_flag,
  st_status, st_status_quality, source_run_id

historical_universe:
  trade_date, stock_code, universe_name, eligible_flag,
  exclusion_reasons, rule_version
```

ST 专用 helper 当前不可用，不能伪造历史 ST。可验证重建前，`st_status=UNKNOWN` 且 `st_status_quality=MISSING_SOURCE`。`historical_universe` 的 v1 基础规则只使用可靠字段；任何依赖 ST 的研究必须显式拒绝 UNKNOWN 或采用单独版本规则。

### 6.7 指数日线

```text
trade_date, index_code, open, high, low, close,
pre_close, volume, amount, source_run_id
```

范围：`000001.SH`、`000016.SH`、`000300.SH`、`000905.SH`、`000852.SH`。指数自身行情与指数权重是不同数据域；v1 不把当前为空的权重接口列为完成条件。

### 6.8 期货合约与日线

```text
future_contract_master:
  contract_code, product, exchange, list_date, expire_date,
  multiplier, source_run_id

future_daily:
  trade_date, contract_code, product, open, high, low, close,
  settlement, volume, open_interest, source_run_id
```

业务主键分别为 `contract_code` 与 `(trade_date, contract_code)`。只保存真实合约，不以 `IF00` 等连续代码代替底层真实历史。静态字段缺失时保留空值和质量标记，不凭命名规则伪造到期日或乘数。

### 6.9 主力映射、连续序列和基差

`future_main_mapping` 最小字段：

```text
trade_date, product, contract_code, selection_method,
rule_version, eligible_contract_count, source_run_id
```

`oi_then_volume_v1` 规则：

1. 候选合约必须当日有有效行情，且未到期；
2. 优先最大 `open_interest`；
3. 持仓量全部缺失/无效时用最大 `volume`；
4. 再并列时按更早到期日、最后按合约代码做确定性选择；
5. 不用未来日期数据决定当日主力；
6. 保存 `selection_method`、候选数量和规则版本。

`future_main_daily` 不生成伪造可交易价格。第一版保留被选中真实合约的原始价与换月标记；如以后提供拼接调整价格，必须是单独字段和单独规则版本。

`future_basis_daily` 最小字段：

```text
trade_date, product, contract_code, spot_code,
future_close, future_settlement, spot_close,
basis_close, basis_settlement, basis_pct,
days_to_expiry, annualized_basis,
is_main_contract, rule_version, source_run_id
```

现货映射：`IH→000016.SH`、`IF→000300.SH`、`IC→000905.SH`、`IM→000852.SH`。基差符号统一为 `future - spot`，在 schema 文档明确。`days_to_expiry <= 0`、现货价非正、任一必需价格缺失时，不计算百分比/年化值并记录质量原因。年化公式和自然日/交易日口径在实现前由测试样例冻结。

## 7. 采集、幂等与增量策略

### 7.1 通用采集流程

```text
读取 active manifest/checkpoint
→ storage precheck
→ 生成有限批次请求
→ 调用下载接口
→ 再调用读取接口验证有效数据
→ 写 Raw staging
→ Raw 校验与发布
→ 更新 checkpoint
→ 转换 Processed staging
→ 质量门禁与发布
→ 刷新 DuckDB views/metadata
→ storage postcheck
```

命令返回成功只代表请求被受理；只有复读取得有效行并通过 schema 检查才算数据 PASS。

### 7.2 初始化分批

- 股票初始 `100 stocks/batch`，样本基准后可在配置内调到 100–300；
- 不允许一次请求全市场全历史；
- 按证券批次和有限日期窗形成 checkpoint；
- 单批失败不回滚已发布成功批次；
- retry 只处理明确可重试错误，schema/权限/硬容量错误直接停止；
- 记录空返回并分类为合理空值、待重试或 blocker，不能静默跳过。

### 7.3 增量更新窗口

- 日常股票/指数/期货行情默认重拉最近若干交易日，以吸收上游修订；实际窗口经观测后配置化；
- 财务按公告/更新范围增量拉取，并定期回看最近报告期；
- 公司行动定期回看，因子变化触发受影响证券的 Derived 重建；
- Processed 使用确定性的 `source_run_id + ingested_at` 优先级处理相同业务主键的版本；
- 每次增量输出新增、更新、不变、隔离和删除候选数量；上游缺行不自动解释为删除。

### 7.4 并发与单写者

v1 采用单写者模型。写任务获取项目级锁；并发读取允许。锁包含持有者、开始时间和 run_id；只允许通过显式的 stale-lock 检查流程清理，不以进程启动时无条件删除锁文件。

## 8. 分区、文件大小与存储治理

### 8.1 格式与分区

- Parquet + ZSTD；
- 股票日线优先 `year=YYYY/bucket=NN`，bucket 为证券代码稳定哈希；
- 财务按 `table/report_year`，期货日线按 `product/year`；
- 不采用“一股票一年一个文件”；
- 目标文件大小先设为 128–512 MiB，按真实 benchmark 调整；
- 小文件压实产生新 Processed run，通过 manifest 原子切换，不原地改已发布 Raw。

具体分区方案必须通过以下两个查询基准后冻结：单证券 10 年时间序列、单交易日全市场横截面。

### 8.2 容量阈值

```text
TARGET      project persistent data <= 25 GB
WARNING     project persistent data >= 30 GB
HARD LIMIT  project persistent data >= 40 GB
CEILING     future total project <= 100 GB
```

- 批次前用“当前占用 + 本批估算 + 安全余量”检查硬限制；
- 达到 30GB 仍可完成正在验证的小批次，但必须生成异常报告并禁止扩大范围；
- 预计或实际达到 40GB，停止新增大规模 dataset，保留已成功数据并返回非零退出码；
- 不自动删除 Raw、Processed 或 QMT cache 来腾空间；
- 分别报告 `project_data_size`、`qmt_cache_size`、`staging_temp_size`、`free_disk_space`。

标准持久化只包含 Raw + Processed/Derived + DuckDB views/catalog，不生成全量 CSV 或 DuckDB 第三份行情副本。

## 9. 数据质量门禁

### 9.1 阻断发布（ERROR）

- schema 版本或必需列不匹配；
- 业务主键重复且无法按明确规则消解；
- 文件不可读或 checksum 不匹配；
- 行情存在 `high < max(open, close, low)` 或 `low > min(open, close, high)`；
- 非停牌记录价格为非正且无可信解释；
- `volume/amount/open_interest < 0`；
- 上市前或退市后出现记录且无法解释；
- 财务记录被赋予早于公告可用日的 PIT 可见性；
- Derived 引用了未发布或不同 schema 的输入 run。

### 9.2 告警但不自动篡改（WARN）

- 合理停牌/无成交；
- 某证券相对交易日历缺日；
- 极端收益/价格跳变；
- 财务缺少公告日期；
- ST 状态未知；
- 合约 multiplier/expiry 缺失；
- 主力合约异常频繁切换；
- 基差或年化基差极端值。

WARN 进入隔离表或质量报告；是否排除由明确规则决定，不能用前向填充或猜测静默修复。

### 9.3 必做抽查与对账

- 历史 universe 至少抽查 2015、2018、2020、2026 四个年份，数量应合理变化；
- 至少一只退市股票在上市期有数据、退市后无伪造数据；
- 至少三只股票手工核验复权事件前后连续性；
- 财务至少覆盖首次披露、后续修订、缺公告日期三类 fixture；
- 每个 IF/IH/IC/IM 至少抽查一次正常主力选择和一次换月；
- 基差 spot 映射、符号、到期天数和缺值路径全部有确定性测试；
- 行数、最早/最晚日期、证券数与 Raw/Processed 差异均写入报告。

## 10. 测试与验证策略

### 10.1 单元测试（不依赖 MiniQMT）

- 配置校验、路径和容量阈值；
- manifest/checkpoint 状态机和失败恢复；
- schema 映射、日期/时区和空值处理；
- 幂等去重与版本选择；
- 财务 PIT 可见性和修订选择；
- 复权公式 fixture；
- 主力选择 tie-break；
- 基差公式和异常输入；
- quality rules；
- DuckDB view SQL。

fixture 必须是合成或去敏小样本，不提交真实大数据。

### 10.2 本机集成测试（依赖已登录 MiniQMT）

- Preflight 的当前/退市股票、当前/过期期货闭环；
- 一个股票批次首次运行、断点续传、完全重跑；
- 注入中断后上次成功 run 仍可查询；
- 一张财务表和一项公司行动的 Raw→Processed→DuckDB；
- storage warning/hard limit 使用临时小阈值验证；
- `init` 后紧接 `update` 不产生业务主键重复。

### 10.3 查询基准

至少记录冷/热两次耗时和扫描字节：

```sql
-- 单证券时间序列
SELECT * FROM daily_bar
WHERE stock_code = '600519.SH'
ORDER BY trade_date;

-- 单日全市场横截面
SELECT * FROM daily_bar
WHERE trade_date = DATE '2020-06-30';
```

计划阶段不虚构固定性能 SLA。Phase 3 样本 benchmark 后，在 `RUNBOOK.md` 冻结本机基线和可接受回归范围。

## 11. 分阶段实施、交付物与 Gate

### Phase 0 — Preflight 与契约冻结

工作：实现最小能力探针，验证历史证券/合约发现、实际 schema、日期语义、缓存和空间基线；不进行全量下载。

交付：去敏 JSON/Markdown 报告、Raw 样本 schema、字段映射草案、容量/吞吐基线。

Gate：第 2.3 节五项硬门槛全部 PASS；关键字段和状态分类有证据。

### Phase 1 — 骨架、配置、运行元数据与存储守卫

工作：建立包结构、配置验证、日志、run manifest、checkpoint、单写者锁、原子发布和 storage guard。

交付：可执行 CLI 骨架及单元测试。

Gate：失败注入后可恢复；warning/hard limit 行为测试通过；敏感路径不进入 Git。

### Phase 2 — Security Master、交易日历与历史 Universe

工作：构建当前+历史证券全集、上市/退市边界和基础历史 universe。

交付：`security_master`、`trade_calendar`、`historical_universe`。

Gate：退市样本闭环；四个年份 universe 数量合理变化；无当前成分回填历史。

### Phase 3 — A 股历史日线

工作：SH/SZ/BJ，默认 2011-01-01 至当前；分批下载、Raw/Processed 发布、增量窗口与 DuckDB view。

交付：`stock_daily`、checkpoint、质量摘要、查询 benchmark。

Gate：至少一个批次完整重跑业务结果一致；实际最早日期有 metadata；两类查询通过；无未解释主键重复。

若 QMT 不能可靠覆盖 2011，先逐类记录实际最早日期；只有证据表明统一口径必要时才将研究基准回退到 2014，不伪造空缺。

### Phase 4 — 财务、公司行动、复权与状态

工作：财务八表 Raw/Processed、PIT 可见性、修订、公司行动、复权和可验证状态字段。

交付：财务 views/API、`corporate_action`、`adjust_factor`、调整价格数据集、`stock_status` 质量标记。

Gate：无公告日期的数据不会泄漏到回测；三项复权案例通过；重建结果 checksum/统计一致；ST 缺口明确可见。

### Phase 5 — 指数与 CFFEX 真实合约

工作：五个指数日线，IF/IH/IC/IM 合约主表和全部可发现真实历史合约日线。

交付：`index_daily`、`future_contract_master`、`future_daily`。

Gate：四个产品均有真实合约覆盖；过期样本可查询；结算价/持仓量/成交量质量检查通过。

### Phase 6 — 版本化 Derived

工作：主力映射、真实价格连续视图、基差、复权价格和历史 universe 重建命令。

交付：`future_main_mapping`、`future_main_daily`、`future_basis_daily`、规则版本与 lineage。

Gate：tie-break、换月、缺值、到期日和 spot 映射测试通过；无未来数据参与当日选择。

### Phase 7 — DuckDB 与稳定 Research API

工作：建立 catalog/views、小型 metadata/quality 表和稳定读取函数。

最小 API：

```text
get_daily_bar
get_universe
get_financial_pit
get_index_bar
get_future_contracts
get_future_main
get_future_basis
```

Gate：研究 API 不导入 `xtdata`；大表没有被 DuckDB 全量复制；两类查询和 PIT 查询通过。

### Phase 8 — 全量验证、容量审计和运维交付

工作：完成跨表质量检查、可重跑验证、故障恢复演练、真实容量和性能报告。

交付：`DATABASE_SCHEMA.md`、`RUNBOOK.md`、`DATA_QUALITY_REPORT.md`、`STORAGE_REPORT.md`，更新 README。

Gate：所有 v1 完成标准通过，或明确列出阻断项且不得宣称 v1 完成。

## 12. CLI 与运维契约

计划实现以下幂等命令；名称可在实现时统一，但语义不得缺失：

```powershell
python scripts/preflight_database.py --config config/data_config.yaml
python scripts/init_database.py --config config/data_config.yaml
python scripts/update_daily.py --config config/data_config.yaml --as-of YYYY-MM-DD
python scripts/validate_database.py --config config/data_config.yaml
python scripts/storage_audit.py --config config/data_config.yaml
```

- 成功返回 0；数据门禁、容量硬限制、权限/schema blocker 返回非 0；
- 支持 `--dry-run` 展示范围、批次、预估容量和将写入的 dataset；
- `--resume` 只能从成功 checkpoint 接续；
- 日志包含 run_id，但不包含账号、Token、服务器地址或其他敏感信息；
- 更新流程默认只处理配置范围，任何新增市场/周期必须先走 capability→schema→benchmark→capacity gate。

## 13. Git/PR 实施切片

数据库实现不做一个超大 PR，建议按 Gate 切片：

1. `preflight + schemas`；
2. `runtime foundation + storage guard`；
3. `security master + calendar + universe`；
4. `stock daily ingestion`；
5. `financial + corporate action + PIT`；
6. `index + CFFEX`；
7. `derived + DuckDB + research API`；
8. `full validation + runbook + reports`。

每个 PR body 必须写任务、非目标、验收标准、真实测试环境和数据影响。没有实机 MiniQMT 的 CI 只运行单元/合成集成测试；实机结果以去敏报告和 manifest 摘要为证据。

## 14. 风险登记与应对

| 风险 | 触发信号 | 应对/停止条件 |
|---|---|---|
| 历史退市证券不可发现 | Preflight 无有效样本 | 停止全量，不能用当前列表替代 |
| 过期期货不可发现/读取 | 过期样本失败 | 阻断期货和 v1 总验收 |
| 上游 schema/版本变化 | 必需字段变化或 wrapper 错误 | 隔离新 run，升级 mapping/schema 后重试 |
| 财务公告语义不足 | 公告日期缺失/异常 | 隔离记录，默认不可用于 PIT |
| ST 历史源不可用 | helper 继续 UNSUPPORTED | 保持 UNKNOWN，不构造假标签 |
| 2011 覆盖不足 | 多数据集实际最早日偏晚 | 按数据集记录；有证据后才回退研究基准 |
| 小文件过多 | 文件数/平均大小异常 | Processed 新 run 压实，Raw 不原地改 |
| QMT cache + 项目数据挤占磁盘 | free space 或预估触线 | 停止新批次，报告各层占用，不自动删除 |
| 运行中断 | 无 SUCCESS 的 staging/run | 保留上次 active，按 checkpoint 重试 |
| 上游历史修订 | 重拉窗口数据变化 | 新 Raw run + 确定性版本选择 + lineage |

## 15. v1 最终验收清单

只有以下全部满足才可宣称 v1 完成：

- [ ] Phase 0 五项硬门槛全部 PASS；
- [ ] 历史证券全集含退市样本，历史 universe 无 survivorship bias；
- [ ] SH/SZ/BJ 日线可初始化、断点续传、增量更新和幂等重跑；
- [ ] Raw 不可变，Processed/Derived 可从已发布输入重建；
- [ ] 财务八表具备有测试证据的 PIT 语义，修订不丢失；
- [ ] 原始价格不被复权覆盖，复权规则版本化并通过事件样例；
- [ ] 指数和 IF/IH/IC/IM 真实历史合约可查询；
- [ ] 主力映射和基差不使用未来信息，且可重建；
- [ ] DuckDB 大表使用 Parquet views，无默认第三份全量副本；
- [ ] Research API 不直接访问 QMT；
- [ ] 数据质量 ERROR 为零，WARN 有解释、数量和处置状态；
- [ ] 故障恢复、锁、checkpoint、原子发布经过测试；
- [ ] 输出真实覆盖、性能、容量、Top 20 大文件/目录和 QMT cache 占用；
- [ ] 项目持久化目标不超过 25GB；达到 30GB 有整改报告；不得突破 40GB 硬限制；
- [ ] README、schema、runbook、质量报告和容量报告完整且去敏；
- [ ] 新增 dataset 的 capability/schema/benchmark/capacity 审批流程可执行。

## 16. 本计划收敛标准

本文件的 Review 只判断计划是否足以指导后续实现，不提前要求数据库已经建成。计划收敛必须满足：

- 范围、非目标、架构和数据契约无关键歧义；
- 已确认能力与待验证能力明确分开；
- 每个 Phase 有交付物、Gate、失败行为和依赖顺序；
- PIT、历史 universe、复权、期货主链/基差不存在明显未来函数；
- 幂等、断点续传、原子发布、schema 演进和 lineage 有明确策略；
- 存储、质量、测试、运维、隐私和 Git 边界可验收；
- 独立 Reviewer 对当前 PR HEAD 给出 `ACCEPT`。
