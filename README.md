# QMT / MiniQMT Python API Probe

用于在**已启动并登录 MiniQMT 的 Windows 机器**上检测 `xtquant.xtdata` Python API 是否可用，并生成数据能力矩阵。

> 本仓库不包含、不重新分发迅投提供的 `xtquant`、DLL、客户端文件或账号信息。请使用你本机 QMT / MiniQMT 安装环境中获授权的 `xtquant`。

## 项目总体规划

本仓库将从当前的 QMT 数据能力审计继续建设为完整的本地量化研究系统：

```text
QMT / MiniQMT
    ↓
Raw Parquet
    ↓
Processed Parquet
    ↓
DuckDB
    ↓
Factor / Strategy / Backtest / Risk
```

完整路线图见 [`量化系统总体规划.md`](量化系统总体规划.md)。当前可直接交给 Codex 执行的数据库建设方案见 [`本地数据库构建计划.md`](本地数据库构建计划.md)，其中已经冻结 v1 数据范围、历史区间、Raw/Processed/DuckDB 职责、期货主链与基差设计、容量预算和验收标准。

执行级、经过独立 Review 收敛的计划见 [`本地数据库构建计划_codex.md`](本地数据库构建计划_codex.md)。数据库 v1 代码位于 `src/qmt_local_data/`，默认数据根目录为 `E:\qmt_data`；可在本地配置中修改，但源码不硬编码其他机器路径。

第一阶段优先建设 **全 A 股日线 + 财务八表 + 复权/状态/交易日历 + 主要指数 + CFFEX 股指期货实际合约 + 本地 DuckDB/Parquet 数据底座**，分钟、tick、期权和实时能力后置到策略确有需要时再扩展。

## 本地数据库 v1 首轮实现

代码已经实现：

- 不可变 Raw/Processed/Derived Parquet run；
- 原子 active manifest、SHA-256、lineage 与 checkpoint；
- 单写者锁和容量守卫；
- XtData 日线、财务、交易日历、证券/合约资料适配；
- 财务公告日后的首个交易日 PIT 可见性；
- EOD 与下一交易日两种主力映射；
- 股指期货自然日单利年化基差；
- DuckDB 去重 views；
- 离线单元/集成测试以及 MiniQMT 实机 Preflight。

当前代码是计划的可运行基础与各数据层实现，**不代表 v1 数据已经全量建成**。
2026-08-23 的实机 Preflight 已确认当前 A 股和过期 CFFEX 合约日线可读，但
MiniQMT 当前未能发现退市 A 股候选，因此 Phase 0 Gate 仍为 `BLOCKED`；程序按计划
拒绝启动全量初始化，不能用当前股票列表回填历史。去敏结论见
[`docs/PREFLIGHT_REPORT.md`](docs/PREFLIGHT_REPORT.md)。

安装开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

先执行 Phase 0，不要直接全量下载：

```powershell
python scripts/preflight_database.py --config config/data_config.yaml
```

首次验证历史退市证券和过期 CFFEX 合约：

```powershell
python scripts/preflight_database.py --config config/data_config.yaml `
  --download-history-contracts --allow-sample-download
```

不带确认参数的初始化是 dry run；只有 Preflight 五项 Gate 全部 PASS 后，才能显式启动全量：

```powershell
python scripts/init_database.py --config config/data_config.yaml
python scripts/init_database.py --config config/data_config.yaml --confirm-full-download
```

完整命令、失败恢复与安全边界见 [`docs/RUNBOOK.md`](docs/RUNBOOK.md)，字段契约见 [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md)。

## 当前 QMT 数据权限基线

精简、可直接用于数据库和策略边界判断的权限清单见 [`qmt权限清单.md`](qmt权限清单.md)。

该清单按以下口径区分当前数据能力：

- ✅ 已确认可用：已取得至少 1 个有效数据样本；
- ❌ 明确无权限：服务端明确返回权限拒绝；
- ⛔ 当前环境不可用：当前 Python/MiniQMT handler、period、edition 或 schema 无法提供；
- ⚠️ 权限未知：没有有效样本，也没有明确权限拒绝；
- ⏳ 未测试：当前阶段无合法代表样本或暂不需要。

当前已确认的数据足以启动 **全 A 股日频量化数据库、财务 Point-in-Time、因子、选股、日频回测、风险指标和组合分析**。Level 2、订单流、商品衍生品、海外市场和实时 callback 不作为第一阶段数据库建设的阻塞条件。

## 目标

1. 验证 Python -> `xtquant` -> MiniQMT 的连接链路。
2. 按[迅投 XtData 官方主文档](https://dict.thinktrader.net/nativeApi/xtdata.html)逐项覆盖主接口区的 43 个函数入口，并以 manifest 覆盖官网版本记录扩展能力；不再宣称扩展接口存在固定且完整的“7 项”总数。
3. 探测数据类别是否可用：
   - 合约基础信息
   - 交易日历 / 节假日 / 板块
   - Level 1 日线、分钟线、tick、最新快照
   - 实时订阅（订阅受理与新鲜 callback 分开判定）
   - 官方列出的 8 张财务表
   - 除权除息因子
   - 新股申购信息
   - ETF 申赎信息
   - 可转债信息（可选代码）
   - 上证、深证证券期权及中金所股指期权
   - 股指期货行情（可选代码）
   - 上期所、大商所、郑商所、上期能源、广期所商品期货和商品期权（运行时可见时自动选择当前有效配对合约）
   - 订单流 `orderflow1m` 与历史 ST 专用 helper
   - Level 2 行情类型（权限/交易时段敏感）
4. 将结果区分为 `PASS / EMPTY / NO_PERMISSION / UNSUPPORTED / ERROR / SKIP`，避免把“休市无实时数据”误判成“无权限”。
5. 输出 JSON 与 Markdown 报告；每项均记录适用资产/市场域、API 是否存在、权限判断、是否有返回值、实际返回字段及是否取得有效样本。
6. 范围严格限于 XtData 数据能力，以及直接影响数据 API 的 MiniQMT/xtquant handler、版本和 schema 兼容性。

官方运行逻辑：`xtdata` 与 MiniQMT 建立连接，由 MiniQMT 处理行情请求；能获取的数据范围与 MiniQMT 一致。历史数据不足时需要先下载/补充数据。

官方参考：
- https://dict.thinktrader.net/nativeApi/xtdata.html
- https://dict.thinktrader.net/nativeApi/code_examples.html
- https://dict.thinktrader.net/nativeApi/download_xtquant

## 快速开始

### 1. 前置条件

- Windows
- MiniQMT 已启动并登录
- 当前 Python 可以 `from xtquant import xtdata`
- 建议在 MiniQMT 所在机器运行，不要在 GitHub Actions 上运行（云端 CI 无法连接你的本地 MiniQMT）

### 2. 基础探测（不主动下载大批数据）

```powershell
python qmt_api_probe_minimal.py
```

### 3. 允许补充少量测试数据

```powershell
python qmt_api_probe_minimal.py --download `
  --miniqmt-dir '<MiniQMT安装目录>'
```

默认测试标的为 `000001.SZ`，历史窗口默认为近 7 天。

### 4. 增加其他品种

```powershell
python qmt_api_probe_minimal.py --download `
  --stock 000001.SZ `
  --etf 510300.SH `
  --cb 113000.SH `
  --option-code <你的有效期权代码> `
  --future-code <你的有效期货代码>
```

期权、期货代码会随合约到期变化，因此脚本不硬编码一个可能已失效的合约。脚本自动从运行时板块发现深证证券期权和中金所股指期权；未传入商品合约参数时，则从 MiniQMT 可见的上期所、大商所、郑商所、上期能源和广期所板块中，按到期日、主力标志和近期成交量各选择一组有效商品期货及对应商品期权。运行时没有相应板块或有效合约时记为 `NOT_TESTED`，不会伪造代码。

也可以重复传入参数覆盖自动选择：

```powershell
python qmt_api_probe_minimal.py --download `
  --commodity-future-code au2610.SF `
  --commodity-option-code au2610C1000.SF
```

对每个金融或商品衍生品，脚本检查合约资料、合约类型、日线、一分钟、tick、完整快照和订阅/取消；期权另检查期权专用资料。

### 5. 输出

审核意见中的数据 P0/P1 专项补测使用：

```powershell
python qmt_api_probe_minimal.py --review-p0-p1-only --download
```

该模式覆盖客户端版本、版本记录新增 XtData API、ETF、可转债、北交所、指数、五个商品期货市场、深证/中金所期权、订单流、历史 ST、特色 period 与真实订阅回调证据。所有实时订阅都使用 `count=0`；正订阅号仅表示受理，只有 callback 的 `time/stime` 通过相对订阅开始时间的新鲜度校验才证明实时数据可用。

默认生成：

```text
reports/qmt_api_official_<timestamp>.json
reports/qmt_api_official_<timestamp>.md
```

报告会记录：

- Python / xtquant 环境
- MiniQMT 基础连接测试
- `get_period_list()` 返回的实际周期
- 每项测试的适用域 `domain_zh`、中文用途说明 `description_zh`、官方前置版本/权限 `official_prerequisite`、实际字段 `returned_fields`，以及 `status`、`api_available`、`permission`、`has_return_value`、`has_valid_sample`、订阅/回调两层证据、耗时、摘要及异常信息
- 对“无数据”和“无权限”的保守判断

报告状态仅使用 `PASS / EMPTY / NO_PERMISSION / UNSUPPORTED / ERROR / SKIP / NOT_TESTED`。其中 `SKIP` 表示接口已纳入完整性检查，但因会修改本地板块、属于阻塞接收循环、需要用户提供研究公式，或是超出“一类数据一个样本”的批量下载而未执行。

## 给 Codex 的执行任务

权限审计 / API 能力补测步骤见 [`CODEX_PLAN.md`](CODEX_PLAN.md)。

数据库正式建设步骤见 [`本地数据库构建计划.md`](本地数据库构建计划.md)。

最重要的验收标准：Codex 必须在**你实际登录 MiniQMT 的机器**运行脚本，再根据生成的 JSON/Markdown 报告更新数据能力矩阵；不能仅靠静态阅读代码宣布某项权限可用。

公开、去敏的完整审计结论见 [`qmt权限-20260823版本.md`](qmt权限-20260823版本.md)。
