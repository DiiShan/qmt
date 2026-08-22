# Codex Plan: MiniQMT Python API capability validation

## Mission

在 MiniQMT 已启动并登录的 Windows 本机，用 `qmt_api_probe.py` 实测 `xtquant.xtdata`，回答：

1. Python 是否能连接 MiniQMT？
2. 当前环境有哪些数据类别可调用？
3. 每类数据是否能成功取得至少 1 笔有效样本？

最终目标是建立“数据类别是否可行”的能力矩阵，**不是下载完整数据集、验证数据完整性、做性能压测或批量采集。**

## 核心测试原则：每类数据只测试 1 笔

这是本任务的最高优先级约束：

- 每一种数据类别，只需要取得 **1 笔 / 1 行 / 1 个有效对象 / 1 次成功订阅** 即可证明该类数据“可行”。
- 历史行情调用统一优先使用 `count=1`；不要为了测试能力而下载大段历史数据。
- 实时行情只读取 1 个标的的 1 次快照；订阅接口只需证明订阅成功，随后立即取消订阅。
- 财务数据每张需要验证的表只需取得 1 条有效记录。
- 板块、交易日历、合约信息、ETF、IPO、可转债、期权、期货等，只需取得 1 个有效返回样本。
- Level 2 每一种类别只取 1 笔数据即可；不要持续订阅或保存大量逐笔数据。
- 投研/特色数据同样遵守“一类一笔”。先确认 period/接口存在，再用合适标的取 1 个有效样本。
- 若某接口必须先下载本地数据，只下载能够支撑 1 笔验证结果的最小数据范围。
- 不做全市场扫描、不做全品种批量下载、不做长时间实时监听、不做吞吐量/延迟性能测试。

### PASS 的定义

满足以下任意一种即可：

- API 返回至少 1 条有效数据；
- API 返回至少 1 个有效对象/字典；
- 列表类 API 返回至少 1 个有效元素；
- 实时订阅返回有效订阅号；
- 下载接口成功完成，且后续读取至少 1 条有效数据。

一旦某数据类别达到 PASS，**立即停止继续获取该类别更多数据。**

## 安全与范围约束

- MiniQMT 必须运行并已登录。
- 不使用 GitHub Actions 验证 MiniQMT；云端 runner 无法访问本机客户端。
- 只测试 `xtquant.xtdata` 数据能力，不执行下单、撤单或任何交易写操作。
- 不提交账号、资金账号、密码、token、本机 MiniQMT 私有配置、DLL 或迅投 `xtquant` 包本体。
- 原始 `reports/` 默认不提交；只把去敏后的能力结论更新到 `CAPABILITY_MATRIX.md`。

## Phase 0 — 静态验证

```powershell
python -m py_compile qmt_api_probe.py
python qmt_api_probe.py --help
```

如果脚本中用于能力验证的数据读取仍使用 `count=5`、`count=10` 等，应先改为 `count=1`，除非接口本身不支持该参数。

## Phase 1 — Python / MiniQMT 连接

```powershell
python qmt_api_probe.py
```

验证：

- `import xtquant.xtdata`
- `get_instrument_detail("000001.SZ")` 返回 1 个有效对象
- `get_period_list()` 返回非空结果

只要基础链路成功即可，不做重复连接压力测试。

## Phase 2 — 数据类别最小可行性测试

### L1 历史行情

对每种需要验证的周期只取 1 根/1 笔：

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

首选：

```python
count=1
```

若本地历史缓存为空，再执行最小 `download_history_data()` 补充，然后只读取 1 条验证。

### 实时行情

只测试 1 个标的：

- `get_full_tick(["000001.SZ"])`：取得 1 个快照即可 PASS。
- `get_full_kline(..., count=1)`：取得 1 根即可 PASS。
- `subscribe_quote()`：获得有效订阅号即证明请求可行，随后立即 `unsubscribe_quote()`。

非交易时间没有新 callback 不视为权限失败。

### 基础/参考数据

每类只取 1 个有效返回：

- 股票/合约信息
- 板块列表
- 板块成分
- 节假日
- 交易日历/交易日期
- 除权除息因子
- IPO
- ETF 信息

### 财务数据

对需要验证的表分别只确认存在至少 1 条有效记录：

- Balance
- Income
- CashFlow
- Pershareindex

如果需要 `download_financial_data()`，仅补充最小测试标的数据；不要批量下载全市场财务数据。

### 可转债 / 期权 / 期货

使用当前有效的 1 个代表合约即可：

- 可转债：1 个代码、1 个有效返回
- 期权：1 个当前有效合约、1 条数据
- 期货：1 个当前有效合约、1 条数据

不要为了覆盖品种而扫描全部合约。

### Level 2

分别验证：

- l2quote
- l2quoteaux
- l2order
- l2transaction
- l2orderqueue

每类只需要 1 笔有效数据即可 PASS。调用时使用最小 `count=1`（若该接口支持）。

判断规则：

- 有 1 笔有效数据 → `PASS`
- 明确权限/授权/VIP 错误 → `NO_PERMISSION`
- API/period 不存在 → `UNSUPPORTED`
- 休市时调用成功但为空 → `EMPTY`，结论暂不确定；交易时段只复测到取得 1 笔或确认权限错误为止

### 投研/特色数据

以 `get_period_list()` 的实际返回为入口。对每一种准备验证的特色类别：

1. 找到一个 schema 匹配的代表标的；
2. 请求最小样本；
3. 得到 1 笔有效数据即 PASS；
4. 立即停止该类别的进一步采集。

不要用错误品种代码测试后就判断“不支持”。

## Phase 3 — 结果矩阵

更新 `CAPABILITY_MATRIX.md`。每类只记录是否可行，不要求记录大量样本。

状态限定为：

- `PASS`
- `EMPTY`
- `NO_PERMISSION`
- `UNSUPPORTED`
- `ERROR`
- `SKIP`
- `NOT_TESTED`

每项至少记录：

- 数据类别
- API / period
- 测试标的
- 状态
- 1 笔样本是否成功
- 是否需要下载
- 是否要求交易时段/特殊权限
- 简短证据或错误信息

**不要把获取了多少行作为测试成绩；一旦有 1 条有效数据，能力验证即完成。**

## Final acceptance

最终需要明确回答：

1. Python → xtquant → MiniQMT 是否连通？
2. 每一类 L1 行情是否能取得 1 笔？
3. 实时快照/订阅是否可行？
4. 基础信息、日历、板块、除权、IPO、ETF 是否各能取得 1 个样本？
5. 财务表是否各能取得至少 1 条？
6. 可转债、期权、期货是否各完成 1 个代表样本测试？
7. Level 2 每类是否能取得 1 笔，或明确属于无权限/不支持？
8. 特色数据中哪些已通过 1 笔样本证明可行？

提交前：

```powershell
python -m py_compile qmt_api_probe.py
git diff --check
```

最终提交主要包含：

- 必要的测试脚本修改（尤其确保 `count=1`）
- 更新后的 `CAPABILITY_MATRIX.md`
- 必要的文档说明

测试目的始终是 **feasibility / capability check（可行性验证）**，不是数据采集任务。
