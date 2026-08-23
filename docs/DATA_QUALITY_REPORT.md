# Data Quality Report

> 当前文件是代码阶段的报告模板。真实全量运行后由 `validate_database.py` 和 manifest 中的 quality metadata 更新实际统计。

当前已确认的退市 A 股发现缺口、幸存者偏差风险、控制措施和关闭标准见
[`DATA_QUALITY_AND_RISK_REPORT.md`](DATA_QUALITY_AND_RISK_REPORT.md)。该风险关闭前，本文不得
被解释为全量数据库已通过质量验收。

已实现的阻断规则：

- 必需字段；
- 行情业务主键重复；
- OHLC 边界；
- volume、amount、open_interest 非负；
- security master 代码唯一和上市区间；
- 财务 `available_date` 必须晚于 `announce_date`；
- Parquet 文件大小与 SHA-256；
- active manifest 引用完整性。

已实现的告警规则：

- 单日收盘价绝对变化超过 50%；
- 财务公告日期缺失。

尚需实机全量后填充：覆盖日期、证券数、隔离记录、四个历史年份 universe 数量、复权事件人工抽查、期货换月抽查。
