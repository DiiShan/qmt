# Codex Plan: MiniQMT Python API capability validation

## Mission

在运行并登录 MiniQMT 的 Windows 机器上，用本仓库的 `qmt_api_probe.py` 实测 `xtquant.xtdata`，回答三个问题：

1. Python 是否能稳定连接 MiniQMT？
2. 当前账号/客户端实际暴露哪些数据类型和周期？
3. 哪些数据可以实际取得，哪些受权限、交易时段、合约代码或本地缓存限制？

不要仅根据文档或 `hasattr()` 判断“可用”。**最终结论必须来自真实运行结果。**

---

## Constraints

- 必须在 MiniQMT 已启动、已登录的本机执行。
- 不要使用 GitHub Actions 验证 MiniQMT 连接；云端 runner 无法访问本地客户端。
- 不执行下单、撤单或其他交易写操作。本任务只测试 `xtdata` 行情/基础数据 API。
- 不把账号、资金账号、密码、券商 token、MiniQMT 私有配置、客户端 DLL/二进制包提交到 GitHub。
- 不把迅投提供的 `xtquant` 包本体重新分发到本仓库。
- 原始 `reports/` 默认不提交；先人工/程序检查本机路径等信息，再将去敏后的结论写入 `CAPABILITY_MATRIX.md`。

---

## Phase 0 — Static validation

在仓库根目录：

```powershell
python -m py_compile qmt_api_probe.py
python qmt_api_probe.py --help
```

验收：

- 文件能编译。
- CLI help 正常。
- 不触发任何交易 API。

若失败，先修复代码并记录原因。

---

## Phase 1 — Environment and MiniQMT connection

确认 MiniQMT 已登录，然后运行：

```powershell
python qmt_api_probe.py
```

重点检查：

- `import xtquant.xtdata` = PASS
- `get_instrument_detail(stock)` = PASS
- `get_period_list` 返回非空列表

判断：

- import 失败：Python 环境未找到正确的 `xtquant`，不是行情权限问题。
- import 成功但 `get_instrument_detail` 连接类报错：优先检查 MiniQMT 是否运行/登录、版本和连接。
- `get_instrument_detail` 返回有效字典：可视为 Python -> xtdata -> MiniQMT 的基础链路已建立。

若基础连接失败，不继续宣布后续数据能力结论；先解决连接。

---

## Phase 2 — Runtime inventory

保存 `get_period_list()` 的实际返回值，并与官方常见类别对照。

### Level 1

重点：

- `tick`
- `1m`
- `5m`
- `15m`
- `30m`
- `1h`
- `1d`
- `1w`
- `1mon`
- `1q`
- `1hy`
- `1y`

### Level 2

重点：

- `l2quote`
- `l2quoteaux`
- `l2order`
- `l2transaction`
- `l2orderqueue`

### 投研/特色数据

记录运行时实际出现的项目，例如：

- `warehousereceipt`
- `futureholderrank`
- `interactiveqa`
- `transactioncount1m`
- `transactioncount1d`
- `delistchangebond`
- `replacechangebond`
- `specialtreatment`
- `northfinancechange1m`
- `northfinancechange1d`
- `dividendplaninfo`
- `historycontract`
- `optionhistorycontract`
- `historymaincontract`
- `stoppricedata`
- `snapshotindex`

注意：**出现在 `get_period_list()` 只能证明当前运行时认识该 period，不等于账号已经获得数据权限。**

---

## Phase 3 — Level 1 historical data

先看无下载模式报告中的：

- 1d
- 1m
- 5m
- tick
- 15m / 30m / 1h
- 1w / 1mon / 1q / 1hy / 1y

如果 1d/1m/5m 为 EMPTY，再运行：

```powershell
python qmt_api_probe.py --download
```

`--download` 仅用一个测试股票、有限历史窗口补充数据。

验收：

- `download_history_data(1d)` 成功后，`get_market_data_ex(1d)` 应有非空结果。
- 1m、5m 同理。
- 更高周期若依赖基础周期合成，应在基础数据存在后复测。

不要因为首次本地缓存为空就标记 API 为不可用。

---

## Phase 4 — Real-time data and subscriptions

测试：

- `get_full_tick(stock)`
- `get_full_kline(1m)`（若当前版本存在）
- `subscribe_quote(tick)`

验收：

- `subscribe_quote` 返回订阅号 > 0，说明订阅请求被接受。
- 如果在非交易时间运行，没有新 callback 不视为失败。

至少安排一次 **A 股正常交易时段** 的复测，用于确认实时数据会更新。

交易时段复测建议：

```powershell
python qmt_api_probe.py
```

并观察 `get_full_tick` / L2 结果与时间戳是否更新。

---

## Phase 5 — Reference and fundamental datasets

依次评估：

### 合约与市场元数据

- `get_instrument_detail`
- `get_sector_list`
- `get_stock_list_in_sector`
- `get_holidays`
- `get_trading_calendar`
- `get_trading_dates`

### 财务数据

- `download_financial_data`（仅 `--download`）
- `get_financial_data`
- Balance
- Income
- CashFlow
- Pershareindex

### 公司行为

- `get_divid_factors`

### IPO

- `get_ipo_info`

### ETF

- `download_etf_info`（仅 `--download`）
- `get_etf_info`
- ETF 合约基础信息

验收：每一类在 `CAPABILITY_MATRIX.md` 中标记状态、证据和限制。

---

## Phase 6 — Convertible bonds, options and futures

这些品种需要当前有效代码。不要使用随时间失效的硬编码期权/期货合约。

找到当前有效代码后运行：

```powershell
python qmt_api_probe.py --download `
  --cb <可转债代码> `
  --option-code <当前有效期权合约> `
  --future-code <当前有效期货合约>
```

测试：

- 可转债：`get_cb_info`
- 期权：`get_instrument_detail`、`get_option_detail_data`、1d 行情
- 期货：`get_instrument_detail`、1d 行情

记录“代码无效/已到期”和“API/权限不可用”的区别。

---

## Phase 7 — Level 2 entitlement test

测试：

- l2quote
- l2quoteaux
- l2order
- l2transaction
- l2orderqueue

规则：

- 明确出现权限/授权/VIP 错误 -> `NO_PERMISSION`
- API 本身不存在或 period 不支持 -> `UNSUPPORTED`
- 调用成功且有数据 -> `PASS`
- 调用成功但休市为空 -> `EMPTY (inconclusive)`，不能推断无权限

**必须在正常交易时段再测一次 L2，才能给出高置信度权限结论。**

---

## Phase 8 — Special/research periods

从 `get_period_list()` 读取实际列表。

对每个特色 period：

1. 确认其需要的标的/市场/参数结构。
2. 选择适合的代表代码。
3. 运行最小数据请求。
4. 记录 PASS / EMPTY / NO_PERMISSION / UNSUPPORTED / ERROR。

不要用普通 A 股代码盲测期货仓单等 schema 不匹配的数据，然后据此宣布“不支持”。

---

## Phase 9 — Produce capability matrix

根据最新报告更新 `CAPABILITY_MATRIX.md`。

每一项必须包含：

- 数据类别
- API / period
- 测试代码
- 状态
- 是否要求 `--download`
- 是否要求交易时段
- 是否可能要求 L2/VIP/投研权限
- 证据摘要
- 下一步

状态只允许：

- `PASS`
- `EMPTY`
- `NO_PERMISSION`
- `UNSUPPORTED`
- `ERROR`
- `SKIP`
- `NOT_TESTED`

---

## Phase 10 — Final acceptance criteria

任务完成时，应能明确回答：

1. 当前 Python 环境是否能导入 xtquant？
2. 是否能通过 MiniQMT 获取 `000001.SZ` 基础信息？
3. 1d / 1m / 5m 历史数据是否能下载并读取？
4. tick / full tick / subscribe_quote 是否可用？
5. 更高 K 线周期哪些可用？
6. 财务数据哪些表可用？
7. 板块、交易日历、除权、IPO、ETF 是否可用？
8. 可转债、期权、期货是否已实测？
9. Level 2 各类别的真实权限状态是什么？
10. `get_period_list()` 发现了哪些投研/特色数据，哪些已进一步验证？

提交前运行：

```powershell
python -m py_compile qmt_api_probe.py
git diff --check
```

最终提交应主要包含：

- 测试脚本修复（若有）
- 更新后的 `CAPABILITY_MATRIX.md`
- 必要的文档说明

原始 `reports/` 默认保持本地，不提交未经检查的环境路径或其他机器信息。
