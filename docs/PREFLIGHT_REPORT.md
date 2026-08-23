# QMT 本地数据库 Phase 0 实机预检报告

> 运行日期：2026-08-23（Asia/Shanghai）
>
> 数据根目录：`E:\qmt_data`
>
> xtquant：`xtquant_250807`
>
> 结论：`BLOCKED`，未启动全量初始化

相关数据质量、回测风险、暂缓决定与风险关闭标准见
[`DATA_QUALITY_AND_RISK_REPORT.md`](DATA_QUALITY_AND_RISK_REPORT.md)。

## 去敏结果

| 检查 | 状态 | 证据 |
|---|---|---|
| 当前 A 股日线 | PASS | `000001.SZ` 读取到有效日线 |
| 历史合约元数据下载命令 | PASS | `download_history_contracts(incrementally=True)` 正常完成 |
| 退市 A 股发现 | EMPTY | 运行时历史日期板块查询没有返回相对当前列表的历史代码差集 |
| 退市 A 股日线 | BLOCKED | 没有运行时发现的合法候选；未硬编码或伪造代码 |
| 过期 CFFEX 合约发现 | PASS | 运行时发现 3 个候选，样本为 `IC2608.IF` |
| 过期 CFFEX 日线 | PASS | 样本包含 OHLC、结算价、成交量和持仓量 |

实机返回的结算价字段名为 `settelementPrice`（上游拼写如此），转换层已兼容并标准化为
`settlement`，且由合成测试固定该映射。

## Gate 与处置

计划要求五项硬门槛全部 PASS。当前“退市 A 股发现”和“退市 A 股日线”未通过，因此：

- `init --confirm-full-download` 必须非零退出；
- 不得用当前证券列表代替历史证券全集；
- 允许继续开发、测试 Raw/Processed/Derived、DuckDB 和 Research API；
- 待找到 MiniQMT 可验证的历史退市证券发现入口或补齐合法元数据后，重新执行 Phase 0；
- 只有新报告五项全部 PASS 后才能启动全量下载。

完整原始 JSON/Markdown 报告保存在本机 `E:\qmt_data\metadata\preflight`，不提交 GitHub，
以避免提交运行时路径和环境细节。
