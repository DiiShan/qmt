# QMT / MiniQMT Python API Probe

用于在**已启动并登录 MiniQMT 的 Windows 机器**上检测 `xtquant.xtdata` Python API 是否可用，并生成数据能力矩阵。

> 本仓库不包含、不重新分发迅投提供的 `xtquant`、DLL、客户端文件或账号信息。请使用你本机 QMT / MiniQMT 安装环境中获授权的 `xtquant`。

## 目标

1. 验证 Python -> `xtquant` -> MiniQMT 的连接链路。
2. 枚举当前客户端可见的数据周期 `get_period_list()`。
3. 探测常用数据类别是否可用：
   - 合约基础信息
   - 交易日历 / 节假日 / 板块
   - Level 1 日线、分钟线、tick、最新快照
   - 实时订阅
   - 财务报表
   - 除权除息因子
   - 新股申购信息
   - ETF 申赎信息
   - 可转债信息（可选代码）
   - 期权信息（可选代码）
   - 期货行情（可选代码）
   - Level 2 行情类型（权限/交易时段敏感）
4. 将结果区分为 `PASS / EMPTY / NO_PERMISSION / UNSUPPORTED / ERROR / SKIP`，避免把“休市无实时数据”误判成“无权限”。
5. 输出 JSON 与 Markdown 报告，供 Codex 继续分析。

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
python qmt_api_probe.py
```

### 3. 允许补充少量测试数据

```powershell
python qmt_api_probe.py --download
```

默认测试标的为 `000001.SZ`，历史窗口默认为近 45 天。

### 4. 增加其他品种

```powershell
python qmt_api_probe.py --download `
  --stock 000001.SZ `
  --etf 510300.SH `
  --cb 113000.SH `
  --option-code <你的有效期权代码> `
  --future-code <你的有效期货代码>
```

期权、期货代码会随合约到期变化，因此脚本不硬编码一个可能已失效的合约。

### 5. 输出

默认生成：

```text
reports/qmt_api_probe_<timestamp>.json
reports/qmt_api_probe_<timestamp>.md
```

报告会记录：

- Python / xtquant 环境
- MiniQMT 基础连接测试
- `get_period_list()` 返回的实际周期
- 每项测试的状态、耗时、摘要、异常信息
- 对“无数据”和“无权限”的保守判断

## 给 Codex 的执行任务

完整步骤见 [`CODEX_PLAN.md`](CODEX_PLAN.md)。

最重要的验收标准：Codex 必须在**你实际登录 MiniQMT 的机器**运行脚本，再根据生成的 JSON/Markdown 报告更新数据能力矩阵；不能仅靠静态阅读代码宣布某项权限可用。
