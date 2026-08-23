# Codex Plan: MiniQMT Python API capability validation

## Goal

在 MiniQMT 已启动并登录的 Windows 本机，用 `qmt_api_probe_minimal.py` 验证 `xtquant.xtdata` 数据能力。

本任务只回答一个问题：**迅投 XtData 官网主接口和版本记录扩展能力是否均已纳入检查，并且每类数据是否至少能成功取得 1 个有效样本？**

不是数据采集任务，不检查全历史完整性，不批量下载，不做性能压测。

## Highest-priority rule: one sample per category

- 每一种数据类别只测试 **1 笔 / 1 行 / 1 根K线 / 1 个对象 / 1 次成功订阅**。
- 支持 `count` 的读取统一使用 `count=1`。
- 一旦取得 1 个有效样本并标记 `PASS`，立即停止该类别继续取数。
- 若必须补充本地历史数据，只下载支撑最小验证所需的小窗口，然后读取 1 笔。
- 实时行情只测试 1 个标的；订阅成功后立即取消。
- 不扫描全市场，不批量下载，不长期订阅，不保存大量逐笔数据。
- 官方主文档中的接口即使因安全或前置条件不能执行，也必须进入报告并明确标为 `SKIP`，不能从检查清单中消失。

## Safety

- 实机只测试 `xtquant.xtdata`，不测试下单、撤单或其他交易写操作。
- 不导入、枚举、连接或测试任何交易模块；账户、资产、持仓、委托、成交和交易权限均不在范围内。
- 不提交账号、密码、token、MiniQMT 私有配置、DLL、vendor `xtquant` 包或未经去敏的本机报告。
- 不使用 GitHub Actions 测 MiniQMT，本任务必须在 MiniQMT 所在机器执行。

## Step 1 — Static check

```powershell
python -m py_compile qmt_api_probe_minimal.py
python qmt_api_probe_minimal.py --help
```

## Step 2 — Basic connection and read-only capability probe

```powershell
python qmt_api_probe_minimal.py
```

至少确认：

- `import xtquant.xtdata` 可用
- `get_instrument_detail("000001.SZ")` 返回有效对象
- `get_period_list()` 返回运行时数据类型/周期清单

如果基础连接失败，先解决连接，不对其他类别下结论。

## Step 3 — Minimal supplement only when needed

若历史/财务/板块数据因本地缓存不足而为空，再运行：

```powershell
python qmt_api_probe_minimal.py --download
```

`--download` 仍然只是为了让后续 **1 笔** 读取成功，不代表要下载完整历史。

## Data categories to verify

### L1 market data

每个周期最多取 1 笔：

- tick
- 1m
- 5m
- 15m
- 30m
- 1h
- 1d
- 1w
- 1mon
- 1q
- 1hy
- 1y

有 1 笔有效数据即 `PASS`。

### Realtime

只使用 1 个股票代码：

- `get_full_tick`：1 个快照
- `get_full_kline`：1 根
- `subscribe_quote`：收到 1 条合法 callback 后立即取消
- `subscribe_whole_quote`：只订阅 1 个代码；订阅受理与实际 callback 分开记录

休市时没有更新 callback 记为 `EMPTY / SUBSCRIBE_ACCEPTED_NO_CALLBACK`，不视为无权限，也不记为实时行情 `PASS`。

### Reference / metadata

每类只确认 1 个有效返回：

- instrument detail
- instrument type
- `get_market_data` / `get_local_data` 各取 1 笔
- sector list
- sector constituent
- holiday
- trading calendar / trading date
- dividend factor
- IPO
- ETF
- index weight

### Financial

按官方文档列出的 8 张表，每张只验证 1 条：

- Balance
- Income
- CashFlow
- Capital
- HolderNum
- Top10Holder
- Top10FlowHolder
- PershareIndex

### Official interfaces requiring an explicit SKIP decision

以下接口也必须出现在报告中：

- 研究公式接口：没有用户提供的有效公式名时标记 `SKIP`。
- 自定义板块写接口：因本任务为只读验证，标记 `SKIP`。
- `run`：阻塞接收循环不单独运行，标记 `SKIP`；订阅与取消订阅单独验证。
- 批量或等价下载接口：若超出“一类数据一个样本”或已有安全等价路径，标记 `SKIP` 并写明理由。

### Convertible bond / option / future

分别使用 1 个当前有效代表合约：

```powershell
python qmt_api_probe_minimal.py --download `
  --cb <一个当前可转债代码> `
  --option-code <一个当前有效期权> `
  --future-code <一个当前有效期货>
```

每个类别 1 个有效样本即可。

### Commodity futures / commodity options

商品衍生品至少覆盖 MiniQMT 当前可见的上期所、大商所、郑商所。每家交易所自动选择一组未到期且近期有成交的商品期货和对应商品期权；也允许通过可重复参数显式指定：

```powershell
python qmt_api_probe_minimal.py --download `
  --commodity-future-code <商品期货代码> `
  --commodity-option-code <商品期权代码>
```

每个代表合约验证：

- instrument detail
- instrument type
- 1d
- 1m
- tick
- full tick snapshot
- subscribe + immediate unsubscribe
- option detail（仅期权）

历史读取为空时仅补充单合约 7 日窗口。订阅号大于零只证明订阅被接受，不能代替有效行情样本；下载后仍为空且没有明确权限错误时保持 `EMPTY`。

### Level 2

每类只取 1 笔：

- l2quote
- l2quoteaux
- l2order
- l2transaction
- l2orderqueue

判断：

- 1 笔有效数据 → `PASS`
- 明确权限/VIP错误 → `NO_PERMISSION`
- API/period不存在 → `UNSUPPORTED`
- 休市时为空 → `EMPTY`，结论暂不确定；交易时段只复测到拿到 1 笔或得到明确权限结论为止

### Special / research data

优先使用 `get_period_list()` 实际发现的 period；当前后端不支持该接口时，仍直接测试官方已明确名称和 schema 的 period。

对准备验证的每个特色类别：

1. 确认正确 schema/市场/代表标的；
2. 请求最小样本；
3. 取得 1 笔即 `PASS`；
4. 立即停止该类别继续取数。

不要拿普通 A 股代码盲测期货仓单等不匹配数据后宣布“不支持”。

## Result status

只使用：

- `PASS`
- `EMPTY`
- `NO_PERMISSION`
- `UNSUPPORTED`
- `ERROR`
- `SKIP`
- `NOT_TESTED`

## Capability matrix

根据实机结果更新 `CAPABILITY_MATRIX.md`。每项只需记录：

- 数据类别
- API / period
- 代表标的
- 状态
- 是否成功取得 1 个样本
- 是否需要最小下载
- 是否要求交易时段/权限
- 简短证据或错误信息
- API 是否存在
- 权限判断（`SUFFICIENT / DENIED / UNKNOWN / NOT_TESTED`）
- 是否有返回值
- 是否取得有效样本
- 适用资产/市场域
- 实际返回字段清单

**不要把返回行数、下载量或覆盖年限作为测试成绩。一类数据只要拿到 1 个有效样本，可行性验证就完成。**

## Final acceptance

最终报告必须能回答：

1. Python → xtquant → MiniQMT 是否连通？
2. 每个 L1 周期是否能取 1 笔？
3. 实时快照/订阅是否可行？
4. 基础信息/日历/板块/除权/IPO/ETF 是否各能取 1 个样本？
5. 官方列出的八类财务表是否各能取 1 条？
6. 可转债/证券期权/金融期货是否各用 1 个代表合约验证？
7. Level 2 每类是否能取 1 笔，或明确是无权限/不支持？
8. 特色数据哪些已经用 1 个正确样本证明可行？
9. 官方 XtData 主文档的每个接口是否均有一条检查记录，包括明确的 `SKIP`？
10. 上期所、大商所、郑商所的商品期货及对应商品期权，是否分别覆盖静态资料、历史行情、快照和订阅？
11. 官网版本记录中的 `get_market_data_ex`、期权详情、交易时段、重连和千档行情是否已单列？
12. MiniQMT build、行情后端 build、xtquant 包版本，以及 handler/schema 兼容性是否已记录？

提交前：

```powershell
python -m py_compile qmt_api_probe_minimal.py
git diff --check
```

最终提交主要包含更新后的 `CAPABILITY_MATRIX.md` 和必要的探测脚本修复；原始 `reports/` 默认不提交。
