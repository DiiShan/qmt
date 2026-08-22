# MiniQMT / xtdata Capability Matrix

> 由本机实际运行 `qmt_api_probe.py` 后更新。初始化状态为 `NOT_TESTED`，不要仅凭文档改成 PASS。

| Category | API / period | Representative code | Status | Download needed | Trading-hours sensitive | Permission-sensitive | Evidence / next step |
|---|---|---|---|---|---|---|---|
| Connection | `import xtquant.xtdata` | - | NOT_TESTED | No | No | No | Run probe locally |
| Connection | `get_instrument_detail` | `000001.SZ` | NOT_TESTED | No | No | Low | Basic MiniQMT link test |
| Inventory | `get_period_list` | - | NOT_TESTED | No | No | Medium | Save actual returned periods |
| Calendar | `get_holidays` | - | NOT_TESTED | Maybe | No | Low | Run probe |
| Calendar | `get_trading_calendar` | `SH` | NOT_TESTED | Maybe | No | Low | Run probe |
| Calendar | `get_trading_dates` | `SH` | NOT_TESTED | No | No | Low | Run probe |
| Metadata | `get_sector_list` | - | NOT_TESTED | Maybe | No | Low | `--download` may refresh sector metadata |
| Metadata | `get_stock_list_in_sector` | runtime-selected sector | NOT_TESTED | Maybe | No | Low | Run after sector metadata exists |
| L1 history | `1d` | `000001.SZ` | NOT_TESTED | Usually | No | Low | Run no-download, then `--download` if EMPTY |
| L1 history | `1m` | `000001.SZ` | NOT_TESTED | Usually | No | Low | Same |
| L1 history | `5m` | `000001.SZ` | NOT_TESTED | Usually | No | Low | Same |
| L1 period | `15m` | `000001.SZ` | NOT_TESTED | Base data | No | Low | May be synthesized |
| L1 period | `30m` | `000001.SZ` | NOT_TESTED | Base data | No | Low | May be synthesized |
| L1 period | `1h` | `000001.SZ` | NOT_TESTED | Base data | No | Low | May be synthesized |
| L1 period | `1w` | `000001.SZ` | NOT_TESTED | 1d base | No | Low | May be synthesized |
| L1 period | `1mon` | `000001.SZ` | NOT_TESTED | 1d base | No | Low | May be synthesized |
| L1 period | `1q` | `000001.SZ` | NOT_TESTED | 1d base | No | Low | May be synthesized |
| L1 period | `1hy` | `000001.SZ` | NOT_TESTED | 1d base | No | Low | May be synthesized |
| L1 period | `1y` | `000001.SZ` | NOT_TESTED | 1d base | No | Low | May be synthesized |
| Tick | `get_market_data_ex(tick)` | `000001.SZ` | NOT_TESTED | Cache dependent | Yes for freshness | Low | Historical/local tick may be empty |
| Realtime | `get_full_tick` | `000001.SZ` | NOT_TESTED | No | Yes for freshness | Low | Test snapshot |
| Realtime | `get_full_kline(1m)` | `000001.SZ` | NOT_TESTED | No | Yes | Low | Version-dependent API |
| Realtime | `subscribe_quote(tick)` | `000001.SZ` | NOT_TESTED | No | Yes for callback | Low | Subscription id > 0 proves acceptance |
| Corporate action | `get_divid_factors` | `000001.SZ` | NOT_TESTED | No | No | Low | Run probe |
| Financial | `Balance` | `000001.SZ` | NOT_TESTED | Usually | No | Medium | Run `--download` if empty |
| Financial | `Income` | `000001.SZ` | NOT_TESTED | Usually | No | Medium | Same |
| Financial | `CashFlow` | `000001.SZ` | NOT_TESTED | Usually | No | Medium | Same |
| Financial | `Pershareindex` | `000001.SZ` | NOT_TESTED | Usually | No | Medium | Same |
| IPO | `get_ipo_info` | - | NOT_TESTED | No | No | Medium | Run probe |
| ETF | `get_etf_info` | `510300.SH` | NOT_TESTED | Maybe | No | Medium | `--download` can refresh ETF info |
| Convertible bond | `get_cb_info` | current CB code | NOT_TESTED | Maybe | No | Medium | Supply `--cb` |
| Option | `get_option_detail_data` | current option contract | NOT_TESTED | Maybe | No | Medium | Supply `--option-code` |
| Option | `1d` market data | current option contract | NOT_TESTED | Maybe | No | Medium | Supply `--option-code` |
| Futures | `get_instrument_detail` | current futures contract | NOT_TESTED | No | No | Medium | Supply `--future-code` |
| Futures | `1d` market data | current futures contract | NOT_TESTED | Maybe | No | Medium | Supply `--future-code` |
| Level 2 | `l2quote` | `000001.SZ` | NOT_TESTED | No historical guarantee | **Yes** | **High** | Must rerun in trading session |
| Level 2 | `l2quoteaux` | `000001.SZ` | NOT_TESTED | No historical guarantee | **Yes** | **High** | Same |
| Level 2 | `l2order` | `000001.SZ` | NOT_TESTED | No historical guarantee | **Yes** | **High** | Same |
| Level 2 | `l2transaction` | `000001.SZ` | NOT_TESTED | No historical guarantee | **Yes** | **High** | Same |
| Level 2 | `l2orderqueue` | `000001.SZ` | NOT_TESTED | No historical guarantee | **Yes** | **High** | Same |
| Research | `warehousereceipt` | schema-specific | NOT_TESTED | Varies | Varies | High | First check `get_period_list()` |
| Research | `futureholderrank` | schema-specific | NOT_TESTED | Varies | Varies | High | First check runtime inventory |
| Research | `interactiveqa` | schema-specific | NOT_TESTED | Varies | No | High | First check runtime inventory |
| Research | `transactioncount1m/1d` | schema-specific | NOT_TESTED | Varies | Varies | High | First check runtime inventory |
| Research | `northfinancechange1m/1d` | schema-specific | NOT_TESTED | Varies | Varies | High | First check runtime inventory |
| Research | `snapshotindex` | schema-specific | NOT_TESTED | Varies | Varies | High | First check runtime inventory |
| Research | other discovered periods | runtime-specific | NOT_TESTED | Varies | Varies | High | Add rows after first probe |

## Status definitions

- `PASS`: representative call returned valid usable data, or subscription returned a valid id.
- `EMPTY`: call completed but returned no data; reason still unresolved.
- `NO_PERMISSION`: explicit entitlement/permission failure.
- `UNSUPPORTED`: API or period is unsupported by the installed runtime.
- `ERROR`: unexpected failure requiring investigation.
- `SKIP`: intentionally not probed because prerequisites/code were missing.
- `NOT_TESTED`: no real local execution evidence yet.
