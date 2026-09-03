# 流动性指标与数据需求清单

> 本文件用于直接指导后续实现、数据接入与验证。优先级分为 P0（必须）、P1（强烈建议）、P2（有价值增强）、P3（长期研究）。

## 1. P0：仅用现有 QMT 个股日线即可构建

### 1.1 个股交易活跃度

| 指标 | 推荐定义 | 所需数据 | 作用 | 优先级 |
|---|---|---|---|---|
| Amount | 日成交额 | amount | 基础交易规模 | P0 |
| ADV20 / ADV60 | rolling median/mean(amount) | amount | 交易承载能力 | P0 |
| Turnover | amount / free_float_market_cap | amount, free_float_mcap | 可比交易活跃度 | P0 |
| Turnover Z60 | zscore_60(log(turnover)) | turnover | 异常活跃识别 | P0 |
| Turnover Percentile | 横截面/时序百分位 | turnover | 标准化比较 | P0 |

### 1.2 个股价格冲击

| 指标 | 推荐定义 | 所需数据 | 作用 | 优先级 |
|---|---|---|---|---|
| Amihud 1D | abs(ret) / amount | close, pre_close, amount | 单位成交额价格冲击 | P0 |
| Amihud 20D | rolling median(Amihud 1D,20) | 同上 | 中期 price impact | P0 |
| Amihud 60D | rolling median(...,60) | 同上 | 结构性流动性 | P0 |
| Idio Amihud | abs(idio_ret) / amount | 个股收益, 市场/行业收益 | 去除共同波动后的冲击 | P1 |
| Range Impact | ((high-low)/pre_close) / turnover | high, low, pre_close, turnover | 日内价格区间冲击 | P0 |

### 1.3 下跌流动性与脆弱性

| 指标 | 推荐定义 | 所需数据 | 作用 | 优先级 |
|---|---|---|---|---|
| Downside ILLIQ | median(abs(ret)/amount \| ret<0) | close, pre_close, amount | 下跌时价格冲击 | P0 |
| Upside ILLIQ | median(abs(ret)/amount \| ret>0) | 同上 | 上涨时价格冲击 | P0 |
| Downside Ratio | downside_illiq / upside_illiq | 上述两项 | 流动性不对称 | P0 |
| Liquidity Deterioration | 当前 ILLIQ 相对历史 percentile | Amihud history | 恶化程度 | P0 |

### 1.4 可交易性 Tradability

| 指标 | 推荐定义 | 所需数据 | 作用 | 优先级 |
|---|---|---|---|---|
| Suspension Flag | 是否停牌 | trade_status / volume | 是否可交易 | P0 |
| Zero Amount Flag | amount==0 | amount | 异常交易状态 | P0 |
| One-price Limit Up | high==low==limit_up | high, low, 涨停价 | 买入可得性风险 | P0 |
| One-price Limit Down | high==low==limit_down | high, low, 跌停价 | 卖出流动性风险 | P0 |
| Limit-down Streak | 连续跌停天数 | limit status | 踩踏风险 | P0 |
| Tradability Score | 上述状态综合 | 上述数据 | 实际可交易能力 | P0 |

> 如果当前库没有历史涨跌停价，建议补充 ST/非ST、交易板块、上市日期、前收盘价，并按历史涨跌停规则正确还原。

---

## 2. P0：全市场流动性指标

### 2.1 总量与中位数

| 指标 | 所需数据 | 含义 | 优先级 |
|---|---|---|---|
| Total Market Amount | 个股 amount | 市场交易总量 | P0 |
| Market Turnover | sum(amount)/sum(free_float_mcap) | 市场整体活动度 | P0 |
| Median Turnover | 个股 turnover | 普通股票活动度 | P0 |
| Median Amihud | 个股 Amihud | 普通股票价格冲击 | P0 |
| Median Downside ILLIQ | 个股 downside_illiq | 市场下跌流动性 | P0 |

### 2.2 流动性广度 Breadth

| 指标 | 推荐定义 | 所需数据 | 优先级 |
|---|---|---|---|
| Turnover Breadth | turnover 高于自身 rolling median 的股票占比 | 个股 turnover | P0 |
| ILLIQ Breadth | ILLIQ 低于自身 rolling median 的股票占比 | 个股 Amihud | P0 |
| Liquidity Improving Breadth | 流动性改善股票占比 | 个股 liquidity delta | P0 |
| Tradability Breadth | 正常可交易股票占比 | tradability flags | P0 |
| Limit-down Breadth | 跌停/一字跌停股票占比 | limit status | P0 |

### 2.3 成交集中度与拥挤

| 指标 | 推荐定义 | 所需数据 | 优先级 |
|---|---|---|---|
| Stock HHI | sum(amount_share^2) | 个股 amount | P0 |
| Normalized HHI | 归一化 HHI | HHI, 股票数 N | P0 |
| Top10 Amount Share | 前10成交额占比 | amount | P0 |
| Top50 Amount Share | 前50成交额占比 | amount | P0 |
| Top100 Amount Share | 前100成交额占比 | amount | P0 |
| Top1% Amount Share | 前1%股票成交占比 | amount | P0 |
| Top5% Amount Share | 前5%股票成交占比 | amount | P0 |
| Hot Liquidity Share | 异常高换手股票的成交占比 | turnover_z60, amount | P0 |
| Liquidity Divergence | z(total_activity)-z(median_activity) | 市场与中位数活动度 | P0 |

### 2.4 市场复合指标

建议至少构建两个独立总分：

#### Market Liquidity Health

建议分项：

- Activity；
- Price Impact；
- Breadth；
- Tradability；
- Downside Resilience。

#### Market Liquidity Crowding

建议分项：

- Stock Concentration；
- Sector Concentration；
- Hot Liquidity Share；
- Breadth Gap；
- Fragility。

> 复合权重不应一开始写死。先输出所有底层分项，再通过历史预测能力、稳定性和可解释性确定权重。

---

## 3. P0：板块流动性指标

前提：需要**历史时点正确的行业/板块成员关系**，避免当前成分回填过去造成前视偏差。

| 指标 | 推荐定义 | 所需数据 | 优先级 |
|---|---|---|---|
| Sector Amount | sum(amount) | 个股 amount + 行业成分 | P0 |
| Sector Turnover | sector_amount / sector_ff_mcap | amount, free_float_mcap | P0 |
| Sector Median Amihud | 成分股 Amihud 中位数 | 个股 Amihud | P0 |
| Sector Liquidity Breadth | 流动性改善成分占比 | 个股指标 + 成分 | P0 |
| Sector Amount Share | sector_amount / market_amount | amount | P0 |
| Sector MCap Share | sector_ff_mcap / market_ff_mcap | free_float_mcap | P0 |
| Relative Turnover Attraction | amount_share / mcap_share | 上述两项 | P0 |
| Sector Intra-HHI | 板块内部成交份额 HHI | amount | P0 |
| Sector Top-N Share | 板块龙头成交占比 | amount | P0 |
| Sector Hot Share | 异常高换手股票成交占比 | turnover_z60, amount | P0 |
| Sector Downside Liquidity | 板块下跌冲击 | downside_illiq | P0 |
| Sector Liquidity Health | 分项复合 | 上述指标 | P0 |
| Sector Liquidity Crowding | 分项复合 | 上述指标 | P0 |

---

## 4. P1：ETF 资金流数据

### 4.1 必要数据

| 数据 | 用途 | 优先级 |
|---|---|---|
| ETF code | 标识 | P1 |
| ETF type | 宽基/行业/主题/债券等分类 | P1 |
| Daily shares outstanding | 份额变化 | P1 |
| NAV / IOPV | 申赎金额估算、折溢价 | P1 |
| Close price | 二级市场表现 | P1 |
| Amount / Volume | 二级市场交易活跃度 | P1 |
| Benchmark / tracked index | 映射市场/行业 | P1 |

### 4.2 建议指标

| 指标 | 推荐定义 | 作用 |
|---|---|---|
| ETF Net Creation | (shares_t-shares_t-1)*NAV_t | 一级净申赎代理 |
| ETF Flow % AUM | net_creation / AUM | 标准化资金流 |
| Broad ETF Flow | 宽基 ETF 汇总 | 市场级增量资金 |
| Sector ETF Flow | 行业 ETF 汇总 | 板块资金压力 |
| Theme ETF Flow | 主题 ETF 汇总 | 热点资金拥挤 |
| ETF Turnover | amount / AUM | ETF 二级活跃度 |
| Premium/Discount | price/NAV-1 | 套利/供需压力 |
| Price-Share State | 收益与份额变化组合 | 区分上涨申购/上涨赎回/下跌抄底等 |

注意：ETF 份额变化不应被简单等同于“主观多头净买入”，一级申赎还可能受套利与库存机制影响。

---

## 5. P1：融资融券数据

### 5.1 所需数据

- 个股/市场融资余额；
- 融资买入额；
- 融资偿还额；
- 融券余额/余量（若可得）；
- 历史板块映射；
- 自由流通市值；
- 市场成交额。

### 5.2 建议指标

| 指标 | 定义 | 用途 |
|---|---|---|
| Financing Net Flow | financing_buy - financing_repayment | 杠杆净流入 |
| Financing Balance Change | Δ financing_balance | 杠杆扩张/收缩 |
| Financing Intensity | financing_balance / ff_mcap | 杠杆拥挤 |
| Financing Buy Share | financing_buy / market_amount | 杠杆成交参与度 |
| Sector Financing Flow | 行业融资净流入 | 板块杠杆资金 |
| Sector Financing Concentration | 行业/个股集中度 | leveraged crowding |

---

## 6. P1：Funding Liquidity / 银行间资金面

### 6.1 推荐原始数据

- 央行 7 天逆回购利率 OMO7；
- DR001；
- DR007；
- R001；
- R007；
- GC001；
- GC007；
- 1Y NCD；
- Repo 成交量；
- Overnight Repo 占比；
- OMO 投放/到期/净投放；
- MLF 操作；
- 买断式逆回购；
- 政府债发行/缴款（如可得）。

### 6.2 推荐指标

| 指标 | 作用 | 优先级 |
|---|---|---|
| DR007 - OMO7 | 银行体系资金相对政策中枢松紧 | P1 |
| R007 - DR007 | 银行与非银流动性分层 | P1 |
| GC007 - DR007 | 交易所与银行间资金摩擦 | P1 |
| R007 - R001 | 期限结构压力 | P1 |
| DR007 - DR001 | 银行间期限结构 | P1 |
| NCD1Y - OMO7 | 中期银行负债压力 | P1 |
| Repo Volume | 融资活动规模 | P1 |
| Overnight Repo Ratio | 短久期融资依赖 | P1 |
| Funding Stress Score | 上述指标标准化复合 | P1 |

**原则：Funding Stress Score 单独保存，不直接混入 Market Liquidity Health。**

重点验证：Funding Stress 是否领先未来 1/5/10/20 日股票市场流动性恶化。

---

## 7. P2：场外公募基金数据

### 7.1 所需数据

- 基金代码；
- 基金类型；
- 基金总份额/AUM；
- 单位净值；
- 基金收益；
- 股票仓位；
- 行业配置；
- 持仓数据；
- 新基金发行规模。

### 7.2 建议指标

| 指标 | 定义/思路 | 用途 |
|---|---|---|
| Estimated Net Flow | AUM_t - AUM_t-1*(1+r_t) | 剔除净值涨跌后的申赎估计 |
| Equity Flow | net_flow * equity_exposure | 股票方向资金流 |
| Sector Fund Flow | sum(flow_f * exposure_f * sector_weight_fg) | 行业潜在买卖压力 |
| Fund Flow Momentum | rolling sum/net flow zscore | 中期资金趋势 |
| Fund Redemption Stress | 大额赎回异常值 | 潜在被动卖压 |

由于公开场外基金数据频率通常较低，建议作为**中低频增强变量**，不作为日度核心流动性指标。

---

## 8. P2：股指期货与期权

### 股指期货

所需数据：

- IF/IH/IC/IM 主力及各合约价格；
- volume；
- open interest；
- basis；
- expiry；
- 持仓结构（如可得）。

建议指标：

- OI change；
- volume/OI；
- annualized basis；
- basis stress；
- futures leverage regime。

### 期权

所需数据：

- IV；
- skew；
- term structure；
- put/call；
- OI；
- volume。

建议指标：

- IV level；
- downside skew；
- short-dated vol stress；
- put OI concentration；
- gamma/hedging pressure proxies。

这些更适合做风险需求和杠杆状态增强，而不是直接定义现货交易流动性。

---

## 9. P2：权益供给与资金吸收

### 所需数据

- IPO 融资额；
- 定增/配股；
- 可转债等权益相关融资；
- 大股东减持；
- 解禁规模；
- 回购；
- 增持。

### 推荐指标

`Net Equity Liquidity = Fund Inflow - IPO - SEO - Reduction - Unlock Selling + Buyback`

可按：

- 全市场；
- 行业；
- 风格；
- 大小盘；

分别汇总。

---

## 10. P3：宏观资金与居民资产配置

长期可研究：

- 居民新增存款；
- 非银存款；
- 银行理财规模；
- 保险资金运用；
- 公募总规模；
- 新增证券账户；
- 两市投资者活跃度；
- 货币基金规模；
- M1/M2 等。

这些变量适合解释**中长期大类资产资金水位**，频率与传导链条较长，不建议优先纳入日度交易流动性系统。

---

## 11. 建议的数据优先级

### P0：必须完成

1. OHLCV + amount；
2. 前收盘价；
3. 自由流通市值/自由流通股本；
4. 历史交易状态；
5. 历史涨跌停状态；
6. 历史行业/板块成员；
7. 上市/退市状态。

### P1：强烈建议接入

1. ETF 日度份额 + NAV + 价格 + 成交；
2. 融资融券日度数据；
3. DR/R/GC/OMO/NCD/Repo。

### P2：值得构建

1. 场外公募资金流；
2. 股指期货；
3. 期权；
4. IPO/增发/减持/解禁/回购；
5. 新基金发行。

### P3：研究增强

1. 居民存款；
2. 银行理财；
3. 保险资金；
4. 新增账户等。

---

## 12. 建议的最终输出表

### stock_liquidity_daily

建议字段：

```text
trade_date
symbol
amount
adv20
adv60
turnover
turnover_z60
amihud_1d
amihud_20
amihud_60
idio_amihud_20
range_impact_20
downside_illiq_20
upside_illiq_20
downside_ratio
suspension_flag
one_price_limit_up_flag
one_price_limit_down_flag
tradability_score
liquidity_health
liquidity_xs_pct
liquidity_ts_pct
```

### market_liquidity_daily

```text
trade_date
total_amount
market_turnover
median_turnover
median_amihud
median_downside_illiq
turnover_breadth
illiq_breadth
tradability_breadth
limit_down_breadth
stock_hhi
normalized_hhi
top10_amount_share
top50_amount_share
top100_amount_share
top1pct_amount_share
top5pct_amount_share
hot_liquidity_share
liquidity_divergence
liquidity_health
liquidity_crowding
health_pct_252
crowding_pct_252
health_pct_756
crowding_pct_756
```

### sector_liquidity_daily

```text
trade_date
sector_id
sector_name
sector_amount
sector_turnover
median_amihud
liquidity_breadth
market_amount_share
market_ff_mcap_share
relative_turnover_attraction
intra_sector_hhi
top5_stock_amount_share
hot_share
downside_liquidity
liquidity_health
liquidity_crowding
```

### funding_liquidity_daily

```text
trade_date
omo7
dr001
dr007
r001
r007
gc001
gc007
ncd_1y
dr007_omo_spread
r007_dr007_spread
gc007_dr007_spread
dr_term_spread
r_term_spread
repo_volume
overnight_repo_ratio
omo_net_injection
funding_stress_score
```

### capital_flow_daily

```text
trade_date
broad_etf_net_creation
sector_etf_net_creation
theme_etf_net_creation
financing_balance
financing_balance_change
financing_net_flow
financing_buy_share
futures_oi
futures_basis
public_fund_estimated_flow
net_equity_supply
```

---

## 13. 实现时必须处理的数据问题

1. **存活偏差**：历史市场必须包含退市股票；
2. **行业前视偏差**：历史行业成员必须使用当时成分；
3. **涨跌停制度变化**：主板、创业板、科创板、北交所规则不同；
4. **ST 历史状态**：不能使用当前 ST 状态回填历史；
5. **自由流通市值口径**：保持长期一致；
6. **成交额单位**：Amihud 必须固定单位；
7. **复权问题**：收益口径与价格字段需统一；
8. **停牌/零成交**：不能当成普通低成交日直接参与均值；
9. **新股上市期**：上市初期建议单独处理；
10. **极端值**：使用 winsorize/robust zscore/percentile；
11. **板块样本数**：小行业需要最小样本门槛；
12. **时间序列标准化**：至少保留 252D 与 756D percentile。

---

## 14. 验证指标是否“值得保留”的标准

每个指标至少应验证：

1. 是否领先未来 5/10/20 日 realized volatility；
2. 是否领先未来最大回撤；
3. 是否领先未来跌停广度；
4. 是否领先 future Amihud deterioration；
5. 是否对大盘/小盘/微盘均稳健；
6. 牛市/熊市是否存在明显非对称；
7. 是否只是成交额/波动率的重复表达；
8. 加入已有波动率/拥挤度体系后是否仍有增量信息；
9. 是否具有足够稳定的历史分位和可解释性；
10. 是否存在明显数据泄露或前视偏差。

如果一个指标无法提供增量信息，就不应仅因为“看起来专业”而保留。

---

## 15. 第一阶段建议真正实现的最小集合

如果要快速形成可用 V1，优先实现以下 15 项：

1. Turnover；
2. ADV20；
3. Amihud20；
4. Range Impact20；
5. Downside ILLIQ20；
6. Downside Ratio；
7. Tradability Score；
8. Market Median Turnover；
9. Liquidity Breadth；
10. Stock HHI；
11. Top5% Amount Share；
12. Hot Liquidity Share；
13. Liquidity Divergence；
14. Sector Relative Turnover Attraction；
15. Sector Intra-HHI。

在此基础上再构造：

- Market Liquidity Health；
- Market Liquidity Crowding；
- Sector Liquidity Health；
- Sector Liquidity Crowding。

这是最值得先交给 Codex 实现和回测的一组指标。
