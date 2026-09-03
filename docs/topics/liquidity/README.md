# A股全市场流动性专题

> 目标：基于现有 QMT 个股日线数据，构建可用于全市场、板块、个股观察的专业流动性体系，并将银行间资金面、ETF/基金申赎、融资融券等外部数据作为增强层。

## 1. 核心结论

不要把“流动性”压成一个指标。建议至少拆成四层：

1. **Liquidity Health（交易流动性健康度）**：股票是否容易交易、价格冲击是否低、市场是否具有足够交易承载能力。
2. **Liquidity Crowding（流动性拥挤度）**：流动性是否越来越集中到少数股票/板块。
3. **Funding Liquidity（资金面/融资流动性）**：金融机构与交易者获取资金的成本和难度。
4. **Flow Pressure（资金流压力）**：ETF、公募、融资资金等实际/潜在买卖压力。

其中 **Liquidity Health + Liquidity Crowding 应以 QMT 个股日线数据为核心独立构建**；Funding Liquidity 和 Flow Pressure 是解释层、增强层，不建议直接混进交易流动性的定义。

一个关键判断：

> **成交额高 ≠ 市场流动性健康。**

如果总成交额很高，但绝大多数股票成交萎缩、成交集中在少数热门板块/龙头，且普通股票价格冲击上升，则属于“表面活跃、内部拥挤”的脆弱流动性状态。

---

## 2. 流动性的四个层级

### 2.1 Market Liquidity：交易流动性

关注：

- 交易活跃度；
- 价格冲击；
- 可交易性；
- 下跌时流动性；
- 流动性广度。

QMT 日线数据已经能够覆盖大部分核心指标。

### 2.2 Funding Liquidity：融资流动性

关注：

- DR001 / DR007；
- R001 / R007；
- GC001 / GC007；
- 央行 7 天逆回购利率；
- 同业存单利率；
- Repo 成交量、隔夜占比；
- 央行 OMO / MLF / 买断式逆回购等。

核心机制：

`资金成本上升 -> 杠杆能力下降 -> 风险预算下降 -> 流动性供给下降 -> 价格冲击上升`

因此银行间资金利率值得分析，但它们属于**市场流动性的解释变量/领先变量**，不应和 Amihud、换手率等直接混成一个原始指标。

### 2.3 Banking / Macro Liquidity：银行体系与宏观流动性

关注央行操作、财政缴税、政府债发行缴款、银行超储等金融体系“水位”。

作用更偏宏观状态识别，而非直接测量一只股票是否好交易。

### 2.4 Flow Liquidity：资金流

包括：

- ETF 一级申赎/份额变化；
- ETF 二级成交与折溢价；
- 公募基金申购赎回；
- 融资融券；
- 股指期货/期权；
- 新基金发行；
- IPO、增发、减持、解禁、回购等权益供需。

这层回答的是“谁在拿钱买/卖”，而不是“资产本身是否容易交易”。

---

## 3. 个股 Liquidity Health

建议核心维度：

### 3.1 Turnover

优先使用：

`turnover = amount / free_float_market_cap`

比单纯成交额更可比。

### 3.2 Amihud Price Impact

基础定义：

`ILLIQ = abs(return) / amount`

建议使用滚动中位数（如 20D/60D），并统一成交额单位。

增强版可使用市场/行业残差收益：

`idio_illiq = abs(idiosyncratic_return) / amount`

用于降低市场整体涨跌对 price impact 测量的污染。

### 3.3 Range Impact

例如：

`range_impact = ((high - low) / pre_close) / turnover`

用于衡量日内价格区间相对于交易活跃度的冲击程度。

### 3.4 Tradability

A 股必须单独处理：

- 停牌；
- 零成交；
- 一字涨停；
- 一字跌停；
- 连续跌停。

尤其要关注**卖出流动性**，不能因为历史 ADV 很高就认为跌停状态仍然流动性很好。

### 3.5 Downside Liquidity

分别计算上涨和下跌日的价格冲击：

`ILLIQ_down = median(abs(ret)/amount | ret < 0)`

`ILLIQ_up = median(abs(ret)/amount | ret > 0)`

`downside_ratio = ILLIQ_down / ILLIQ_up`

当 downside_ratio 显著升高时，说明上涨时流动性正常，但下跌时流动性快速恶化，市场/个股具有脆弱性。

---

## 4. 标准化原则

不建议直接平均原始指标。统一流程建议：

`Raw -> Winsorize -> Log/Transform -> Standardize -> Percentile`

至少同时保存：

1. **Cross-sectional percentile**：今天谁比谁更流动；
2. **Time-series percentile**：今天相对自身历史处于什么位置。

推荐多尺度：

- Fast：5D；
- Medium：20D；
- Structural：60D；
- Regime：252D / 756D percentile。

不要把 20 日窗口当作唯一标准。

---

## 5. 全市场 Liquidity Health

核心建议不是只看总成交额，而是同时看：

- Median Turnover；
- Median Amihud；
- Liquidity Breadth；
- Tradability Breadth；
- Downside Liquidity；
- 流动性恶化股票占比。

第一版复合框架可写成：

`Market Liquidity Health = Impact + Activity + Breadth + Tradability + Resilience`

具体权重必须通过历史验证确定，不应视为固定经济规律。

---

## 6. Liquidity Breadth

这是市场层非常重要的指标。

示例：

`turnover_breadth = count(turnover_i > own_median_60_i) / valid_stock_count`

`illiq_breadth = count(illiq_i < own_median_60_i) / valid_stock_count`

典型警报：

`Total Market Amount ↑↑` 但 `Liquidity Breadth ↓↓`

意味着总量活跃，但资金越来越集中。

---

## 7. Liquidity Crowding

建议单独构建，不与 Health 混为一谈。

### 7.1 成交集中度

股票成交份额：

`share_i = amount_i / sum(amount)`

指标：

- HHI；
- Normalized HHI；
- Top10 / Top50 / Top100 amount share；
- Top1% / Top5% / Top10% amount share。

### 7.2 Hot Liquidity Share

定义异常换手：

`hotness_i = zscore_60(log(turnover_i))`

例如 hotness > 1.5 定义为热点股票：

`hot_liquidity_share = sum(amount_i for hot stocks) / total_amount`

### 7.3 Breadth Divergence

同时比较：

- 全市场总活动度；
- 中位数股票活动度。

可定义：

`liquidity_divergence = z(total_activity) - z(median_activity)`

高值代表“加权意义市场很热，但普通股票并不活跃”。

### 7.4 Fragility

可使用：

- downside Amihud；
- 一字跌停比例；
- median price impact；
- liquidity deterioration breadth。

最终形成独立的 `Liquidity Crowding Score (0-100)`，优先用历史 percentile 表示状态。

---

## 8. 市场 2×2 状态矩阵

|  | Crowding 低 | Crowding 高 |
|---|---|---|
| Liquidity Health 高 | 健康、全面活跃 | 拥挤牛市/热门行情 |
| Liquidity Health 低 | 全面缩量 | 高危：集中 + 脆弱 + 潜在踩踏 |

最值得监控的状态：

`Liquidity Health ↓ + Liquidity Crowding ↑`

---

## 9. 板块流动性

板块应复用 Market Liquidity Health，同时增加板块吸引力与板块内部集中度。

### 9.1 Relative Turnover Attraction（RTA）

`amount_share_g = sector_amount / market_amount`

`mcap_share_g = sector_free_float_mcap / market_free_float_mcap`

`RTA_g = amount_share_g / mcap_share_g`

RTA > 1 表示该板块获得了高于其自由流通市值权重的交易流动性。

### 9.2 Sector Crowding

建议综合：

- RTA；
- sector intra-HHI；
- sector top-N amount share；
- hot share；
- breadth narrowness；
- downside liquidity deterioration。

需要区分：

1. **流动性扩散**：多数成分股同时改善；
2. **流动性拥挤**：板块成交主要集中在极少数龙头。

---

## 10. 为什么分析二级市场流动性要看银行利率/利差

因为很多交易者和流动性提供者依赖融资、回购和杠杆。

值得观察：

- DR007 - OMO7；
- R007 - DR007；
- GC007 - DR007；
- R007 - R001；
- DR007 - DR001；
- 1Y NCD - OMO7；
- Repo 成交量；
- 隔夜 Repo 占比。

但这些属于 **Funding Liquidity Regime**。

建议研究的是：

`P(Market Liquidity deterioration in t+N | Funding Stress rises at t)`

而不是直接把 DR007 加进股票 Liquidity Score。

---

## 11. ETF / 公募申赎是否值得加入

### ETF：高优先级

ETF 日度份额变化非常值得接入：

`ETF net creation ≈ (shares_t - shares_t-1) * NAV_t`

结合：

- ETF 收益；
- 二级市场成交额；
- 折溢价；
- 份额变化；
- ETF 类型（宽基/行业/主题）。

可构建行业/主题资金流压力。

### 场外公募：值得，但频率较低

如果有基金规模与收益，可估算：

`net_flow ≈ AUM_t - AUM_t-1 * (1 + fund_return_t)`

再结合股票仓位与行业配置映射到市场/板块。

公开数据频率通常低于 ETF，因此更适合中低频增强，而不是核心日度指标。

---

## 12. 融资融券

高优先级增强数据。

核心：

`margin_net_flow = financing_buy - financing_repayment`

`margin_intensity = financing_balance / free_float_mcap`

以及：

- financing balance change；
- financing buy / market amount；
- sector margin concentration。

这类指标可衡量 leveraged liquidity / leveraged crowding。

---

## 13. 权益资金供需

除了“资金流入”，还应观察股票供给：

`Net Equity Liquidity ≈ Fund Inflow - IPO - SEO - Reduction - Unlock Selling + Buyback`

包括：

- IPO；
- 定增/配股；
- 大股东减持；
- 解禁；
- 回购；
- 重要股东增持。

---

## 14. 建议输出的核心数据库

### stock_liquidity_daily

- turnover / turnover_z60；
- adv20 / adv60；
- amihud20 / amihud60；
- idio_amihud20；
- range_impact20；
- downside_illiq20；
- upside_illiq20；
- downside_ratio；
- tradability20；
- liquidity_health；
- liquidity_xs_pct；
- liquidity_ts_pct。

### market_liquidity_daily

- total_amount；
- market_turnover；
- median_turnover；
- median_amihud；
- turnover_breadth；
- liquidity_breadth；
- tradability_breadth；
- stock_hhi；
- top1pct/top5pct amount share；
- hot_liquidity_share；
- liquidity_divergence；
- liquidity_health；
- liquidity_crowding；
- rolling percentiles。

### sector_liquidity_daily

- sector amount / turnover；
- liquidity_health；
- liquidity_breadth；
- market_amount_share；
- market_cap_share；
- relative_turnover_attraction；
- intra_sector_hhi；
- top-N stock share；
- hot_share；
- downside_liquidity；
- sector_liquidity_crowding。

### funding_liquidity_daily

- OMO7；
- DR001 / DR007；
- R001 / R007；
- GC001 / GC007；
- 关键 spreads；
- NCD；
- Repo volume；
- overnight repo ratio；
- 央行操作量。

### capital_flow_daily

- ETF net creation；
- broad ETF flow；
- sector ETF flow；
- financing balance；
- financing net flow；
- futures OI / basis；
- 其他可获得资金流。

---

## 15. 与现有波动率、拥挤度体系的关系

建议最终形成三个并列核心风险状态：

1. **Volatility**
2. **Crowding**
3. **Liquidity**

并进一步研究：

`Market Fragility = f(Volatility, Crowding, Liquidity)`

其中最值得警惕的组合通常是：

`Crowding ↑ + Liquidity ↓ + Volatility ↑`

单独任何一个指标，都不如三者联合状态有决策价值。

---

## 16. 实施顺序

### Phase 1：仅使用现有 QMT 日线数据

优先完成：

- Turnover；
- Amihud；
- Range Impact；
- Downside Liquidity；
- Tradability；
- Liquidity Breadth；
- HHI / Top Share；
- Hot Liquidity Share；
- RTA；
- Market/Sector Liquidity Health；
- Market/Sector Liquidity Crowding。

### Phase 2：外部高价值数据

接入：

- ETF 日度份额与 NAV；
- 融资融券；
- DR/R/GC/OMO/NCD。

### Phase 3：中低频与结构数据

接入：

- 公募基金申赎/规模；
- 新基金发行；
- IPO/增发/减持/解禁/回购；
- 股指期货/期权；
- 居民/理财/保险等大类资产资金数据。

### Phase 4：历史验证

必须验证指标是否对以下变量有领先关系：

- future volatility；
- future max drawdown；
- future liquidity deterioration；
- crash / limit-down breadth；
- trend continuation / reversal。

指标权重、窗口和阈值均应由历史验证决定。

---

## 17. 推荐的研究原则

1. Health 与 Crowding 分开；
2. 交易流动性与资金面分开；
3. 总量指标与横截面广度同时看；
4. 上涨流动性与下跌流动性分开；
5. 股票、板块、市场使用同一底层指标体系；
6. 使用多尺度而非单一 20 日窗口；
7. 所有复合分数必须保留底层分项，便于解释；
8. 先验证信息含量，再冻结权重和阈值。
