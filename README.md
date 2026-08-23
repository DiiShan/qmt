# QMT / MiniQMT Python API Probe

用于在**已启动并登录 MiniQMT 的 Windows 机器**上检测 `xtquant.xtdata` Python API 是否可用，并生成数据能力矩阵。

> 本仓库不包含、不重新分发迅投提供的 `xtquant`、DLL、客户端文件或账号信息。请使用你本机 QMT / MiniQMT 安装环境中获授权的 `xtquant`。

## 目标

1. 验证 Python -> `xtquant` -> MiniQMT 的连接链路。
2. 按[迅投 XtData 官方主文档](https://dict.thinktrader.net/nativeApi/xtdata.html)逐项覆盖主接口区的 43 个函数入口，并补充官网版本记录中的 7 项扩展能力；不能安全执行或缺少必要前置条件的接口也进入报告，并明确标为 `SKIP`。
3. 探测数据类别是否可用：
   - 合约基础信息
   - 交易日历 / 节假日 / 板块
   - Level 1 日线、分钟线、tick、最新快照
   - 实时订阅
   - 官方列出的 8 张财务表
   - 除权除息因子
   - 新股申购信息
   - ETF 申赎信息
   - 可转债信息（可选代码）
   - 期权信息（可选代码）
   - 期货行情（可选代码）
   - 上期所、大商所、郑商所商品期货和商品期权（默认自动选择当前有效配对合约）
   - Level 2 行情类型（权限/交易时段敏感）
4. 将结果区分为 `PASS / EMPTY / NO_PERMISSION / UNSUPPORTED / ERROR / SKIP`，避免把“休市无实时数据”误判成“无权限”。
5. 输出 JSON 与 Markdown 报告；每项均记录适用资产/市场域、API 是否存在、权限判断、是否有返回值、实际返回字段及是否取得有效样本。
6. 对 XtTrader 当前安装包的公开方法、回调和核心对象字段做静态审计，但不连接资金账号、不执行交易操作。

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
python qmt_api_probe_minimal.py --download
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

期权、期货代码会随合约到期变化，因此脚本不硬编码一个可能已失效的合约。未传入商品合约参数时，脚本会从 MiniQMT 的上期所、大商所、郑商所运行时板块中，按到期日、主力标志和近期成交量各选择一组有效的商品期货及对应商品期权。

也可以重复传入参数覆盖自动选择：

```powershell
python qmt_api_probe_minimal.py --download `
  --commodity-future-code au2610.SF `
  --commodity-option-code au2610C1000.SF
```

对每个金融或商品衍生品，脚本检查合约资料、合约类型、日线、一分钟、tick、完整快照和订阅/取消；期权另检查期权专用资料。

### 5. 输出

默认生成：

```text
reports/qmt_api_official_<timestamp>.json
reports/qmt_api_official_<timestamp>.md
```

报告会记录：

- Python / xtquant 环境
- MiniQMT 基础连接测试
- `get_period_list()` 返回的实际周期
- 每项测试的适用域 `domain_zh`、中文用途说明 `description_zh`、实际字段 `returned_fields`，以及 `status`、`api_available`、`permission`、`has_return_value`、`has_valid_sample`、耗时、摘要及异常信息
- 对“无数据”和“无权限”的保守判断

报告状态仅使用 `PASS / EMPTY / NO_PERMISSION / UNSUPPORTED / ERROR / SKIP / NOT_TESTED`。其中 `SKIP` 表示接口已纳入完整性检查，但因会修改本地板块、属于阻塞接收循环、需要用户提供研究公式，或是超出“一类数据一个样本”的批量下载而未执行。

## 给 Codex 的执行任务

完整步骤见 [`CODEX_PLAN.md`](CODEX_PLAN.md)。

最重要的验收标准：Codex 必须在**你实际登录 MiniQMT 的机器**运行脚本，再根据生成的 JSON/Markdown 报告更新数据能力矩阵；不能仅靠静态阅读代码宣布某项权限可用。

公开、去敏的完整审计结论见 [`qmt权限-20260823版本.md`](qmt权限-20260823版本.md)。
