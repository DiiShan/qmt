# MiniQMT / xtdata Capability Matrix

> 2026-08-23 使用 `qmt_api_probe_minimal.py` 在兴业证券 MiniQMT 实机验证；
> Python 3.13.5 / xtquant 250807.1.2。每类只以 1 个有效样本作为 PASS 证据。
> 已按迅投官网 XtData 主文档补齐安全只读接口、8 张财务表及明确的 SKIP 项；
> 完整报告另含 API 可用性、权限、返回值和有效样本字段。

| Category | API / period | Representative code | Status | Download needed | Trading-hours sensitive | Permission-sensitive | Evidence / next step |
|---|---|---|---|---|---|---|---|
| Connection | `import xtquant.xtdata` | - | PASS | No | No | No | Imported from the installed xtquant 250807.1.2 package |
| Connection | `get_instrument_detail` | `000001.SZ` | PASS | No | No | Low | Returned a non-empty instrument object over the local MiniQMT connection |
| Connection | `get_instrument_type` | `000001.SZ` | PASS | No | No | Low | Returned `stock: true` |
| Inventory | `get_period_list` | - | UNSUPPORTED | No | No | Medium | Client returned ErrorID 300000: `function not realize` |
| Calendar | `get_holidays` | - | EMPTY | Attempted | No | Low | Empty before/after supplement; `download_holiday_data` is unsupported by this client |
| Calendar | `get_trading_calendar` | `SH` | UNSUPPORTED | No | No | Low | Client returned ErrorID 300000: `function not realize` |
| Calendar | `get_trading_dates` | `SH` | PASS | No | No | Low | Returned one trading-date timestamp |
| Metadata | `get_sector_list` | - | PASS | No | No | Low | Returned one of 853 local sectors |
| Metadata | `get_stock_list_in_sector` | runtime-selected sector | PASS | No | No | Low | Returned one constituent from the first runtime sector |
| L1 history | `1d` | `000001.SZ` | PASS | Yes, 7-day window | No | Low | Returned the 2026-08-21 bar after minimal supplement |
| L1 history | `1m` | `000001.SZ` | PASS | Yes, 7-day window | No | Low | Returned one 2026-08-21 minute bar |
| L1 history | `5m` | `000001.SZ` | PASS | Yes, 7-day window | No | Low | Returned one 2026-08-21 five-minute bar |
| L1 period | `15m` | `000001.SZ` | PASS | Base data | No | Low | Returned one synthesized/retrieved bar |
| L1 period | `30m` | `000001.SZ` | PASS | Base data | No | Low | Returned one synthesized/retrieved bar |
| L1 period | `1h` | `000001.SZ` | PASS | Base data | No | Low | Returned one synthesized/retrieved bar |
| L1 period | `1w` | `000001.SZ` | PASS | 1d base | No | Low | Returned one weekly bar |
| L1 period | `1mon` | `000001.SZ` | PASS | 1d base | No | Low | Returned one monthly bar |
| L1 period | `1q` | `000001.SZ` | PASS | 1d base | No | Low | Returned one quarterly bar |
| L1 period | `1hy` | `000001.SZ` | PASS | 1d base | No | Low | Returned one half-year bar |
| L1 period | `1y` | `000001.SZ` | PASS | 1d base | No | Low | Returned one yearly bar |
| Tick | `get_market_data_ex(tick)` | `000001.SZ` | PASS | Yes, 7-day window | Yes for freshness | Low | Returned the last 2026-08-21 tick |
| L1 API | `get_market_data(1d)` | `000001.SZ` | PASS | Existing cache | No | Low | Official primary cache-read API returned one bar |
| L1 API | `get_local_data(1d)` | `000001.SZ` | PASS | Existing cache | No | Low | Official local-file API returned one bar |
| Realtime | `get_full_tick` | `000001.SZ` | PASS | No | Yes for freshness | Low | Returned the latest cached snapshot |
| Realtime | `get_full_kline(1m)` | `000001.SZ` | UNSUPPORTED | No | Yes | Low | Client returned ErrorID 300000: `function not realize` |
| Realtime | `subscribe_quote(tick)` | `000001.SZ` | PASS | No | Yes for callback | Low | Returned subscription id 1, then immediately unsubscribed |
| Realtime | `subscribe_whole_quote` | `000001.SZ` | PASS | No | Yes for callback | Low | One-code full-push subscription returned id 2, then immediately unsubscribed |
| Corporate action | `get_divid_factors` | `000001.SZ` | PASS | No | No | Low | Returned one dividend-factor row |
| Financial | `Balance` | `000001.SZ` | PASS | Yes | No | Medium | Returned one row after one-symbol compatibility download |
| Financial | `Income` | `000001.SZ` | PASS | Yes | No | Medium | Returned one row after one-symbol compatibility download |
| Financial | `CashFlow` | `000001.SZ` | PASS | Yes | No | Medium | Returned one row after one-symbol compatibility download |
| Financial | `Capital` | `000001.SZ` | PASS | Yes | No | Medium | Returned one capital-structure row |
| Financial | `HolderNum` | `000001.SZ` | PASS | Yes | No | Medium | Returned one shareholder-count row |
| Financial | `Top10Holder` | `000001.SZ` | PASS | Yes | No | Medium | Returned one top-ten-holder row |
| Financial | `Top10FlowHolder` | `000001.SZ` | PASS | Yes | No | Medium | Returned one top-ten-floating-holder row |
| Financial | `PershareIndex` | `000001.SZ` | PASS | Yes | No | Medium | Returned one per-share-index row |
| Index | `get_index_weight` | `000300.SH` | EMPTY | Not downloaded | No | Low | Local index-weight cache is empty; bulk refresh intentionally skipped |
| IPO | `get_ipo_info` | - | UNSUPPORTED | No | No | Medium | Client returned ErrorID 200005: handler not found |
| ETF | `get_etf_info` | `510300.SH` | UNSUPPORTED | No | No | Medium | ETF instrument detail passed, but this API returned ErrorID 300000 |
| Convertible bond | `get_cb_info` | `123071.SZ` | EMPTY | Yes, metadata | No | Medium | Instrument detail passed; metadata download plus 11 valid-code retries stayed empty |
| Option | `get_option_detail_data` | `10011948.SHO` | ERROR | No | No | Medium | Instrument detail passed; wrapper raised TypeError because a client field was missing |
| Option | `1d / 1m` market data | `10011948.SHO` | PASS | Yes, 7-day window | No | Medium | Both daily and minute samples returned |
| Option | `tick` history | `10011948.SHO` | EMPTY | Not downloaded | Yes for freshness | Medium | No historical tick returned in the 7-day window |
| Option | `get_full_tick` | `10011948.SHO` | PASS | No | Yes for freshness | Medium | Returned the latest cached option snapshot |
| Option | `subscribe_quote` | `10011948.SHO` | PASS | No | Yes for callback | Medium | Subscription accepted and immediately cancelled |
| Futures | `get_instrument_detail` | `IF2609.IF` | PASS | No | No | Medium | Returned current CFFEX contract detail; expiry 2026-09-18 |
| Futures | `1d / 1m` market data | `IF2609.IF` | PASS | Yes, 7-day window | No | Medium | Both daily and minute samples returned |
| Futures | `tick / get_full_tick` | `IF2609.IF` | EMPTY | No | Yes for freshness | Medium | No historical tick or cached full snapshot returned outside trading hours |
| Futures | `subscribe_quote` | `IF2609.IF` | PASS | No | Yes for callback | Medium | Subscription accepted and immediately cancelled |
| Commodity future | Contract discovery/detail | `al2611.SF / c2701.DF / MA701.ZF` | PASS | No | No | Medium | Found valid paired contracts for SHFE, DCE and CZCE; instrument detail returned for all three |
| Commodity future | `1d / 1m / tick / get_full_tick` | same three | EMPTY | Yes, 7-day 1d/1m | Yes for snapshot | **High** | All reads stayed empty after minimal downloads; no explicit permission error, so entitlement remains unknown |
| Commodity future | `subscribe_quote` | same three | PASS | No | Yes for callback | **High** | All three subscriptions returned positive ids and were immediately cancelled; this does not prove data delivery |
| Commodity option | Contract discovery/detail | `al2611C24000.SF / c2701-C-2040.DF / MA701C2600.ZF` | PASS | No | No | Medium | Valid matching options discovered for SHFE, DCE and CZCE; instrument detail returned for all three |
| Commodity option | `get_option_detail_data` | same three | ERROR | No | No | Medium | Installed wrapper raised the same missing-field TypeError for all three |
| Commodity option | `1d / 1m / tick / get_full_tick` | same three | EMPTY | Yes, 7-day 1d/1m | Yes for snapshot | **High** | All reads stayed empty after minimal downloads; no explicit permission error, so entitlement remains unknown |
| Commodity option | `subscribe_quote` | same three | PASS | No | Yes for callback | **High** | All three subscriptions returned positive ids and were immediately cancelled; no callback sample was required |
| Level 2 | `l2quote` | `000001.SZ` | NO_PERMISSION | No historical guarantee | **Yes** | **High** | Brief subscription returned explicit `no level2 permission`, meta 1010 |
| Level 2 | `l2quoteaux` | `000001.SZ` | NO_PERMISSION | No historical guarantee | **Yes** | **High** | Explicit permission error, meta 1011 |
| Level 2 | `l2order` | `000001.SZ` | NO_PERMISSION | No historical guarantee | **Yes** | **High** | Explicit permission error, meta 1802 |
| Level 2 | `l2transaction` | `000001.SZ` | NO_PERMISSION | No historical guarantee | **Yes** | **High** | Explicit permission error, meta 1801 |
| Level 2 | `l2orderqueue` | `000001.SZ` | NO_PERMISSION | No historical guarantee | **Yes** | **High** | Explicit permission error, meta 1804 |
| Level 2 extension | `subscribe_l2thousand` | `000001.SZ` | NO_PERMISSION | No | **Yes** | **High** | Explicit permission error, meta 1803 |
| Level 2 extension | `get_l2thousand_queue` | `000001.SZ` | UNSUPPORTED | No | **Yes** | **High** | Client returned ErrorID 300000 |
| Level 2 extension | `subscribe_l2thousand_queue` | `000001.SZ` | UNSUPPORTED | No | **Yes** | **High** | Client returned invalid period |
| Trading time | `get_trading_time` / installed `get_trading_period` | `000001.SZ` | UNSUPPORTED | No | No | Low | Official name absent; installed alias returned ErrorID 300000 |
| Connection helper | `reconnect` | - | SKIP | No | No | Low | Installed but not called because it would change the active connection |
| Research | `warehousereceipt` | schema-specific | NOT_TESTED | Varies | Varies | High | Runtime inventory unavailable because `get_period_list` is unsupported |
| Research | `futureholderrank` | schema-specific | NOT_TESTED | Varies | Varies | High | Runtime inventory unavailable; no blind A-share probe performed |
| Research | `interactiveqa` | schema-specific | NOT_TESTED | Varies | No | High | Runtime inventory unavailable; schema not guessed |
| Research | `transactioncount1m/1d` | schema-specific | NOT_TESTED | Varies | Varies | High | Runtime inventory unavailable; schema not guessed |
| Research | `northfinancechange1m/1d` | schema-specific | NOT_TESTED | Varies | Varies | High | Runtime inventory unavailable; schema not guessed |
| Research | `snapshotindex` | schema-specific | NOT_TESTED | Varies | Varies | High | Runtime inventory unavailable; schema not guessed |
| Research | other discovered periods | runtime-specific | NOT_TESTED | Varies | Varies | High | No periods could be enumerated on this client |

## Status definitions

- `PASS`: representative call returned valid usable data, or subscription returned a valid id.
- `EMPTY`: call completed but returned no data; reason still unresolved.
- `NO_PERMISSION`: explicit entitlement/permission failure.
- `UNSUPPORTED`: API or period is unsupported by the installed runtime.
- `ERROR`: unexpected failure requiring investigation.
- `SKIP`: intentionally not probed because prerequisites/code were missing.
- `NOT_TESTED`: no real local execution evidence yet.
