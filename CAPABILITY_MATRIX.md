# MiniQMT / XtData 数据能力矩阵

> 2026-08-23 兴业证券 MiniQMT 实机结果。范围仅限数据能力；一类数据只保留一个有效样本。完整逐项中文说明见 [`qmt权限-20260823版本.md`](qmt权限-20260823版本.md)。

| 类别 | API / period | 中文解释 | 代表代码 | 状态 | API/handler | 权限 | 返回/样本 | 下载/时段与证据 |
|---|---|---|---|---|---|---|---|---|
| 环境 | Python → XtData | 验证 Python 能导入并连接 MiniQMT 行情后端。 | `000001.SZ` | PASS | 可用 | SUFFICIENT | 有/有效 | Python 3.13.5、xtquant 250807.1.2。 |
| 兼容性 | 客户端 build | 记录直接影响数据 API 的客户端与行情后端版本。 | - | PASS | 可读 | UNKNOWN | 有/有效 | MiniQMT 2.0.8.0 revision 634931；miniquote 1.0.0.10881。 |
| 兼容性 | 包/后端评估 | 判断 Python surface 与 MiniQMT handler/schema 是否配套。 | - | ERROR | 部分兼容 | UNKNOWN | 有/无 | 22 条 handler-missing 证据、2 条 option schema mismatch。 |
| 周期清单 | `get_period_list` | 枚举运行时行情周期和特色数据。 | - | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| A 股 L1 | `1d/1m/5m/15m/30m/1h/1w/1mon/1q/1hy/1y/tick` | 读取股票各周期的一根 K 线或一条 tick。 | `000001.SZ` | PASS | 可用 | SUFFICIENT | 有/有效 | 历史缓存不足时使用 7 日最小下载。 |
| A 股快照 | `get_full_tick` | 读取当前缓存中的完整盘口快照。 | `000001.SZ` | PASS | 可用 | SUFFICIENT | 有/有效 | 休市快照不等于实时 callback。 |
| A 股实时 | `subscribe_quote` / `subscribe_quote2` | 订阅 tick，只有收到一次 callback 才算实时 PASS。 | `000001.SZ` | EMPTY | 订阅受理 | UNKNOWN | 有/无 | 正订阅号已取消；休市无 callback。 |
| K 线全推 | `get_full_kline` | 读取当日全推 K 线缓存。 | `000001.SZ` | UNSUPPORTED | 后端缺失/配置未知 | UNKNOWN | 无 | ErrorID 300000；K 线全推开关未知。 |
| ETF 通用行情 | `1d/1m/tick` | 验证 ETF 通用历史行情。 | `510300.SH` | PASS | 可用 | SUFFICIENT | 有/有效 | 三类均在最小下载后取得一笔。 |
| ETF 快照 | `get_full_tick` | 读取 ETF 缓存快照。 | `510300.SH` | PASS | 可用 | SUFFICIENT | 有/有效 | 返回 20 字段 tick 对象。 |
| ETF 实时 | tick callback | 验证 ETF 实时推送。 | `510300.SH` | EMPTY | 订阅受理 | UNKNOWN | 有/无 | 休市无 callback。 |
| ETF 专用 | `get_etf_info` | 读取 ETF 申购赎回专用资料。 | `510300.SH` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| ETF IOPV | `etfiopv1m/etfiopv1d` | 读取 ETF IOPV 分钟/日频特色数据。 | `510300.SH` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | 两项均 ErrorID 300000。 |
| 可转债通用行情 | `1d/1m/tick` | 验证当前可转债通用历史行情。 | `111017.SH` | PASS | 可用 | SUFFICIENT | 有/有效 | 三类均在最小下载后取得一笔。 |
| 可转债快照 | `get_full_tick` | 读取可转债缓存快照。 | `111017.SH` | PASS | 可用 | SUFFICIENT | 有/有效 | 返回 tick 对象。 |
| 可转债实时 | tick callback | 验证可转债实时推送。 | `111017.SH` | EMPTY | 订阅受理 | UNKNOWN | 有/无 | 休市无 callback。 |
| 可转债专用 | `get_cb_info` | 读取转股价、转股期等专用元数据。 | 原代表代码 | EMPTY | 可调用 | UNKNOWN | 无 | 专用元数据为空，不影响通用行情 PASS。 |
| 北交所行情 | `1d/1m/tick` | 验证一只当前北交所股票的历史行情。 | `920238.BJ` | PASS | 可用 | SUFFICIENT | 有/有效 | 三类均在最小下载后取得一笔。 |
| 北交所快照 | `get_full_tick` | 读取北交所股票缓存快照。 | `920238.BJ` | PASS | 可用 | SUFFICIENT | 有/有效 | 返回 tick 对象。 |
| 北交所实时 | tick callback | 验证北交所实时推送。 | `920238.BJ` | EMPTY | 订阅受理 | UNKNOWN | 有/无 | 休市无 callback。 |
| 指数行情 | `1d` | 读取指数自身日线，不与指数权重混淆。 | `000300.SH` | PASS | 可用 | SUFFICIENT | 有/有效 | 最小下载后取得一根。 |
| 指数快照 | `get_full_tick` | 读取指数缓存快照。 | `000300.SH` | PASS | 可用 | SUFFICIENT | 有/有效 | 返回 tick 对象。 |
| 指数权重 | `get_index_weight` | 读取指数成分和权重。 | `000300.SH` | EMPTY | 可调用 | UNKNOWN | 无 | 本地权重缓存为空。 |
| 证券期权 | `1d/1m/full tick` | 验证证券期权历史 K 线和快照。 | `10011948.SHO` | PASS | 可用 | SUFFICIENT | 有/有效 | 历史 tick 仍为空。 |
| 期权详情 | `get_option_detail_data` | 读取行权价、到期日、认购认沽等专用字段。 | 多类期权 | ERROR | Python 存在 | UNKNOWN | 无 | `CLIENT_SCHEMA_MISMATCH`。 |
| 期权历史 helper | `get_his_option_list(_batch)` | 读取某日/区间的历史期权合约。 | `510300.SH` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 期权映射 helper | `get_option_undl_data/get_option_list` | 建立标的映射并筛选期权列表。 | `510300.SH` | ERROR | Python 存在 | UNKNOWN | 无 | 同一 option schema mismatch。 |
| 股指期货历史 | `1d/1m` | 读取中金所股指期货历史 K 线。 | `IF2609.IF` | PASS | 可用 | SUFFICIENT | 有/有效 | tick/full tick 休市为空。 |
| 股指期货实时 | tick callback | 验证当前股指期货实时推送。 | `IC2612.IF` | EMPTY | 订阅受理 | UNKNOWN | 有/无 | 休市无 callback。 |
| 商品期货 | `1d/1m/tick/full tick` | 验证三家交易所商品期货行情。 | `al2611.SF`、`c2701.DF`、`MA701.ZF` | EMPTY | 静态资料可用 | UNKNOWN | 无 | 最小下载后仍空。 |
| 商品期货实时 | tick callback | 验证三家交易所商品期货实时推送。 | 同上 | EMPTY | 订阅受理 | UNKNOWN | 有/无 | 三个正订阅号均取消；休市无 callback。 |
| 商品期权 | `1d/1m/tick/full tick` | 验证三家交易所商品期权行情。 | 三个当前合约 | EMPTY | 静态资料可用 | UNKNOWN | 无 | 最小下载后仍空。 |
| 商品期权实时 | tick callback | 验证三家交易所商品期权实时推送。 | 三个当前合约 | EMPTY | 订阅受理 | UNKNOWN | 有/无 | 三个正订阅号均取消；休市无 callback。 |
| 财务 | 八张官方财务表 | 每张表读取一条记录。 | `000001.SZ` | PASS | 可用 | SUFFICIENT | 有/有效 | 八表全部 PASS。 |
| 除权 | `get_divid_factors` | 读取一条除权除息因子。 | `000001.SZ` | PASS | 可用 | SUFFICIENT | 有/有效 | 返回 8 个字段。 |
| 交易日 | `get_trading_dates` | 读取一个市场交易日期。 | `SH` | PASS | 可用 | SUFFICIENT | 有/有效 | 返回一个时间戳。 |
| 交易日历 | `get_trading_calendar` | 读取带属性的市场日历。 | `SH` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 板块 | `get_sector_list/get_stock_list_in_sector` | 读取板块名称和一个成分。 | 本地板块 | PASS | 可用 | SUFFICIENT | 有/有效 | 也用于发现当前合约。 |
| 板块分类 | `get_sector_info` | 读取带分类信息的板块资料。 | `沪深A股` | EMPTY | 可调用 | UNKNOWN | 无 | 未返回 DataFrame 样本。 |
| 表格行情 | `get_tabular_data` | 以表格形式读取历史行情。 | `000001.SZ` | PASS | 可用 | SUFFICIENT | 有/有效 | 返回 1 行、12 列。 |
| 订阅信息 | `get_current_connect_sub_info/get_all_sub_info` | 读取当前连接和客户端订阅信息。 | - | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | 两项均 ErrorID 300000。 |
| 交易时段 | `get_trading_period/get_all_*` | 读取单合约及全市场交易时段。 | `000001.SZ` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | 三项均 ErrorID 300000。 |
| 大单统计 | `get_transactioncount` | 读取 Level 1 大单/逐笔统计镜像。 | `000001.SZ` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 行情状态 | `watch_quote_server_status` | 监听行情服务器状态变化。 | - | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | 注册即 ErrorID 300000。 |
| XtData 状态 | `watch_xtquant_status` | 监听本机 xtquant 状态变化。 | - | EMPTY | 注册成功 | UNKNOWN | 无 | 短窗口无状态变化事件。 |
| A 股 L2 | 五类常规 L2 | 十档、扩展盘口、逐笔委托/成交及队列。 | `000001.SZ` | NO_PERMISSION | 可调用 | DENIED | 无 | 服务端明确拒绝。 |
| 千档盘口 | `subscribe_l2thousand` | 订阅千档盘口。 | `000001.SZ` | NO_PERMISSION | 可调用 | DENIED | 无 | 服务端明确拒绝权限。 |
| 千档队列 | `get_l2thousand_queue` / 队列订阅 | 读取或订阅千档委托队列。 | `000001.SZ` | UNSUPPORTED | handler/period 缺失 | UNKNOWN | 无 | ErrorID 300000 或 invalid period。 |
| 港股 broker queue helper | `get_broker_queue_data` | 使用专用 helper 读取港股经纪席位队列。 | `00700.HK` | EMPTY | 可调用 | UNKNOWN | 无 | 调用完成但没有样本。 |
| 港股 broker queue period | `brokerqueue` | 使用特色 period 读取港股经纪席位队列。 | `00700.HK` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 特色公告 | `announcement` | 读取上市公司新闻公告。 | `000001.SZ` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 涨停表现 | `limitupperformance` | 读取涨跌停、连板及炸板表现。 | `000001.SZ` | EMPTY | 可调用 | UNKNOWN | 无 | 最小下载后仍空。 |
| 港股通明细 | `hktdetails` | 读取港股通持股明细。 | `00700.HK` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 港股通统计 | `hktstatistics` | 读取港股通持股统计。 | `00700.HK` | EMPTY | 可调用 | UNKNOWN | 无 | 最小下载后仍空。 |
| 涨跌停价格 | `stoppricedata` | 读取证券涨跌停价格数据。 | `000001.SZ` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 快照指标 | `snapshotindex` | 读取量比、涨速和换手等指标。 | `000001.SZ` | EMPTY | 可调用 | UNKNOWN | 无 | 最小下载后仍空。 |
| 退市转债 | `delistchangebond` | 读取退市可转债资料。 | 转债 schema | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 待发转债 | `replacechangebond` | 读取待发或替换可转债资料。 | 转债 schema | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 历史主力合约 | `historymaincontract` | 读取期货历史主力合约映射。 | `IF00.IF` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 历史期权合约 | `optionhistorycontract` | 读取历史期权合约资料。 | `XXXXXX.SHO` | UNSUPPORTED | 后端缺失 | UNKNOWN | 无 | ErrorID 300000。 |
| 港股/美股/外盘 | 通用行情 | 明确尚未验证的市场服务范围。 | - | NOT_TESTED | 未确认 | NOT_TESTED | 无 | 没有服务声明和 schema 验证样本。 |

## 状态说明

- `PASS` 必须有一个有效数据样本；命令受理会单独标注，不能代替数据结论。
- `EMPTY` 不等于无权限；休市订阅为空尤其不能下权限结论。
- `UNSUPPORTED` 需结合原因码区分 Python 方法缺失、后端 handler 缺失和 invalid period。
- 实时订阅证据拆分为“订阅受理”和“收到 callback”；本轮 11 次受理、0 次 callback。
