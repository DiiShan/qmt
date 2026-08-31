# QMT 全市场与板块波动率系统实施计划（Codex）

> 版本日期：2026-08-27  
> 执行对象：Codex  
> 仓库：`DiiShan/qmt`  
> 目标分支：`main`（执行实现时建议新建 feature branch / PR）  
> 依据：当前仓库的 `Raw → Processed → Derived → DuckDB → Research API` 架构、`docs/DATABASE_SCHEMA.md`、`config/datasets.yaml`、`src/qmt_local_data/pipeline.py`、`src/qmt_local_data/research.py`。

---

## 0. 任务目标

在现有 QMT 本地日频数据库之上，建设一个**可重建、可增量、无未来函数、可用于全市场观察和板块比较的波动率系统**。

本任务不是只实现一个 `20D historical volatility`，而是建立波动的：

1. **期限结构**：Fast / Medium / Slow（5D / 20D / 60D；个股另保留 10D / 120D）；
2. **空间结构**：Stock → Market → Sector；
3. **横截面结构**：Median Vol / Dispersion / High-vol Breadth / Shock Breadth；
4. **系统性结构**：Market RV / Downside RV / Implied Correlation；
5. **变化速度**：`RV5/RV20`、`RV20/RV60`；
6. **方向性**：Upside / Downside volatility；
7. **后续状态识别**：规则型 Market Regime；
8. **后续研究验证**：预测未来风险、条件收益和策略适用环境。

最终系统要能够回答：

- 当前全市场到底有多波动？
- 是指数/整体组合在波动，还是个股内部在剧烈分化？
- 波动是局部还是正在扩散？
- 股票是否开始同步运动，系统性风险是否抬升？
- 哪些行业/板块正在从低波动进入扩张？
- 当前波动环境是否适合某类选股策略？

---

# 1. 最高优先级原则

## 1.1 不允许未来函数

所有滚动统计、历史分位、板块成分、股票池必须只使用当时已经可见的数据。

禁止：

- 用当前存活股票回填历史全市场；
- 用当前板块成分回填历史板块；
- 用全历史均值/标准差标准化历史样本；
- 用 T+1 以后数据计算 T 日 percentile / regime；
- 用未经复权的价格直接计算跨除权日收益率。

## 1.2 不把停牌当作 0 收益

- 明确停牌/无有效成交时，当日收益设为 NULL，不填 0；
- 恢复交易后的收益允许从最近一个有效可交易收盘价计算；
- 滚动窗口按**市场交易日窗口**定义，并要求最小有效观测数，避免长期停牌股票产生“陈旧波动率”。

建议默认最小有效观测比例：80%。

```text
window=5   -> min_obs=4
window=10  -> min_obs=8
window=20  -> min_obs=16
window=60  -> min_obs=48
window=120 -> min_obs=96
```

参数放入配置，不要硬编码散落在实现中。

## 1.3 复权收益是硬门槛

`stock_daily` 原始 OHLC 不得直接用于波动率。

优先使用现有数据库已经验证并可重建的 adjustment factor / adjusted close。

若当前数据库仍处于：

```text
RAW_ONLY_PENDING_FACTOR_SEMANTICS_VALIDATION
```

则：

- 可以实现纯函数和合成测试；
- 可以实现 pipeline 接口；
- **禁止把真实历史 `stock_vol_daily` 标记为生产可用**；
- 必须先完成复权因子语义验证。

## 1.4 全市场历史必须尊重数据库状态

读取 `metadata/database_status.json`。

- `READY_FULL_HISTORY`：允许发布 `ALL_A` 历史全市场波动指标；
- `READY_CURRENT_UNIVERSE_ONLY`：只允许显式发布 `CURRENT_SURVIVORS`，必须保留幸存者偏差标签；
- 其他状态：禁止构建生产级历史波动指标。

## 1.5 板块历史成员不能臆造

当前仓库没有已确认的历史板块成员 PIT 数据契约，因此板块模块必须采用以下规则：

1. 如果能获得带有效日期的历史行业成员数据，建立正式历史 `sector_membership`；
2. 如果只能获得“当前板块成分”，只能：
   - 作为当天 snapshot；
   - 从首次 snapshot 开始向未来积累历史；
   - 不允许回填过去；
3. 对概念板块同样处理；
4. 第一版优先支持结构稳定、来源明确的行业分类，再扩展概念板块。

---

# 2. 为什么不是只用 20 日

20D 只是中频基准，不是唯一正确窗口。

统一采用：

```text
Fast   = 5D   -> 检测最近几天突然变化
Medium = 20D  -> 描述当前约一个交易月的波动环境
Slow   = 60D  -> 描述中期背景
```

个股层另外保留：

```text
10D
120D
```

核心期限结构：

```text
rv5_rv20  = rv5 / rv20
rv20_rv60 = rv20 / rv60
```

解释：

- `rv5 > rv20 > rv60`：波动加速扩张；
- `rv5 < rv20 < rv60`：波动持续冷却；
- 单独 `rv20` 高，只说明水平高，不能说明当前还在升温还是降温。

对 Dispersion 同时保留：

```text
dispersion_1d
dispersion_ma5
dispersion_ma20
dispersion_ewma20
```

不要只保存一个 `dispersion20`。

---

# 3. 统一数学定义

## 3.1 股票日收益

第一版统一使用复权后的简单收益率：

```text
ret_1d[t] = adjusted_close[t] / adjusted_close[prev_valid_trade] - 1
```

原因：

- 等权市场组合收益可以直接用简单收益横截面均值；
- 与组合方差 / implied correlation 计算保持一致；
- 日频下与 log return 差异很小，但组合解释更直接。

可选保留 `log_ret_1d = log1p(ret_1d)`，但 V1 全部指标必须统一基于 `ret_1d`，不能混用。

## 3.2 历史波动率

对窗口 `W ∈ {5,10,20,60,120}`：

```text
rv_W = sample_std(ret_1d over last W market trading days, ddof=1) * sqrt(252)
```

必须满足对应 `min_obs`，否则 NULL。

## 3.3 上行 / 下行 Realized Volatility

使用相同有效样本集合，不按正负样本数重新归一：

```text
up_rv_W   = sqrt(252 * mean(max(ret_1d, 0)^2))
down_rv_W = sqrt(252 * mean(min(ret_1d, 0)^2))
```

V1 至少保存 20D：

```text
up_rv20
down_rv20
down_up_ratio = down_rv20 / up_rv20
```

若分母为 0，则 ratio 为 NULL，不设 inf。

## 3.4 个股历史波动率分位

`rv20_pct252[t]` 定义为：

```text
当前 rv20[t]
相对于 prior 252 trading days 的 rv20 历史值的经验分位
```

注意：参考窗口**不包含当前 t**。

建议最少历史样本：126。

同理支持：

```text
rv20_pct756
```

最少历史样本可配置，默认 378。

## 3.5 Shock Z-score

```text
daily_sigma20_prev = rv20[t-1] / sqrt(252)
shock_z20[t] = ret_1d[t] / daily_sigma20_prev
```

要求：

- 使用 `t-1` 的波动率，不能把当日冲击先计入分母；
- `daily_sigma20_prev <= 0` 时为 NULL。

市场横截面：

```text
shock_up_breadth   = pct(shock_z20 >= +2)
shock_down_breadth = pct(shock_z20 <= -2)
shock_abs_breadth  = pct(abs(shock_z20) >= 2)
```

## 3.6 全市场等权收益

对交易日 t 的 PIT eligible universe 中，当日有有效收益的股票：

```text
ew_ret[t] = mean_i(ret_i,t)
```

必须保存：

```text
eligible_stock_count
valid_return_count
coverage_ratio = valid_return_count / eligible_stock_count
```

覆盖率过低时不应静默发布有效市场指标。阈值放配置，例如默认 80%。

## 3.7 Market RV

```text
ew_rv5  = std(ew_ret, 5)  * sqrt(252)
ew_rv20 = std(ew_ret, 20) * sqrt(252)
ew_rv60 = std(ew_ret, 60) * sqrt(252)
```

V1 市场主指标必须以等权版本为基准，因为它更能描述普通股票的全市场体验。

市值加权 `cw_*` 只有在存在可靠 PIT 市值/自由流通市值数据时才能增加；不得为了完成字段而使用当前市值回填历史。

## 3.8 个股波动横截面

每日对 eligible + valid 的股票计算：

```text
median_stock_rv20
p25_stock_rv20
p75_stock_rv20
p90_stock_rv20
```

核心解释：即使 Market RV 很低，Median Stock RV 很高也说明市场内部并不平静。

## 3.9 Cross-sectional Dispersion

每日：

```text
dispersion_1d[t] = sample_std_i(ret_i,t, ddof=1)
```

然后：

```text
dispersion_ma5   = rolling_mean(dispersion_1d, 5)
dispersion_ma20  = rolling_mean(dispersion_1d, 20)
dispersion_ewma20 = EWMA(dispersion_1d, halflife=20)
```

保持日收益单位，不强制年化；展示层如需要可单独乘 `sqrt(252)`，不要把 raw 与 annualized 混在同名字段。

## 3.10 High-vol Breadth

```text
highvol_breadth_80[t] = pct(rv20_pct252 >= 0.80)
highvol_breadth_90[t] = pct(rv20_pct252 >= 0.90)
```

V1 主用 `80`，同时保留 `90` 便于识别极端扩散。

## 3.11 Implied Correlation

生产指标命名必须使用：

```text
implied_corr20
implied_corr60
```

不要命名成简单 `avg_corr`，因为本指标是**波动率乘积加权的隐含平均相关性**，不是所有 Pearson pair 的算术平均。

对每个 t 和窗口 W：

1. 取 t 日 eligible universe；
2. 在 `[t-W+1, t]` 使用固定的 t 日股票集合；
3. 仅保留满足窗口有效观测要求的股票；
4. 对这一固定集合建立等权组合收益序列；
5. 计算各股票窗口标准差 `sigma_i` 和组合标准差 `sigma_p`；
6. 等权 `w_i = 1/N`；
7. 计算：

```text
numerator = sigma_p^2 - sum(w_i^2 * sigma_i^2)

denominator = (sum(w_i * sigma_i))^2 - sum(w_i^2 * sigma_i^2)

implied_corr = numerator / denominator
```

要求：

- denominator <= 0 时返回 NULL；
- 不强行 clip 到 `[0,1]`，允许负相关；
- 可对微小数值误差做容忍，但若超出理论合理区间很多必须质量告警；
- 单元测试用小规模完整 panel 直接算 pairwise correlations，验证该公式与 volatility-product weighted pairwise correlation 一致。

复杂度目标：增量日更新 O(N×W)，不要构建 5000×5000 相关矩阵。

---

# 4. V1 数据集设计

所有新数据集属于 `derived` 层，沿用现有 Manifest / immutable run / active view 机制。

## 4.1 `stock_vol_daily`

业务主键：

```text
trade_date, stock_code
```

最小字段：

```text
trade_date
stock_code
ret_1d
log_ret_1d                # optional but recommended
valid_return_flag

rv5
rv10
rv20
rv60
rv120

rv5_rv20
rv20_rv60

rv20_pct252
rv20_pct756

up_rv20
down_rv20
down_up_ratio

shock_z20

valid_obs_5
valid_obs_10
valid_obs_20
valid_obs_60
valid_obs_120
```

注意：

- 不把 sector-relative 指标硬塞进本表，因为一个股票可能同时属于多个 sector_type；
- sector-relative volatility 后续通过 `stock_vol_daily` JOIN `sector_vol_daily` 计算，或新增独立长表。

## 4.2 `market_vol_daily`

业务主键：

```text
trade_date, universe_name
```

最小字段：

```text
trade_date
universe_name
universe_scope
eligible_stock_count
valid_return_count
coverage_ratio

ew_ret

ew_rv5
ew_rv20
ew_rv60
rv5_rv20
rv20_rv60

median_stock_rv20
p25_stock_rv20
p75_stock_rv20
p90_stock_rv20

dispersion_1d
dispersion_ma5
dispersion_ma20
dispersion_ewma20

highvol_breadth_80
highvol_breadth_90
shock_up_breadth
shock_down_breadth
shock_abs_breadth

implied_corr20
implied_corr60

up_rv20
down_rv20
down_up_ratio
```

主要观察字段增加 prior-history percentile（不包含当前日）：

```text
ew_rv20_pct252
median_stock_rv20_pct252
dispersion_ma5_pct252
highvol_breadth_80_pct252
implied_corr20_pct252
down_rv20_pct252

# 有足够历史时再提供 756D 对应版本
```

## 4.3 `sector_membership`

如果获得可靠历史成员：

业务主键：

```text
sector_type, sector_code, stock_code, effective_from
```

字段：

```text
sector_type
sector_code
sector_name
stock_code
effective_from
effective_to
membership_source
membership_quality
```

如果只有当前 snapshot，不伪造成以上历史表；改用：

```text
sector_membership_snapshot_daily
```

业务主键：

```text
snapshot_date, sector_type, sector_code, stock_code
```

并明确：历史 sector metrics 只能从有真实 snapshot 的日期开始计算。

## 4.4 `sector_vol_daily`

业务主键：

```text
trade_date, sector_type, sector_code, universe_name
```

最小字段：

```text
trade_date
sector_type
sector_code
sector_name
universe_name
eligible_stock_count
valid_return_count
coverage_ratio

ew_ret
rv5
rv20
rv60
rv5_rv20
rv20_rv60

median_stock_rv20

dispersion_1d
dispersion_ma5
dispersion_ma20

highvol_breadth_80
shock_up_breadth
shock_down_breadth

implied_corr20
implied_corr60

up_rv20
down_rv20
down_up_ratio

rv20_pct252
dispersion_ma5_pct252
highvol_breadth_80_pct252
implied_corr20_pct252
```

要求：板块最小成员数可配置，默认例如 5；小于阈值时相关性和横截面统计为 NULL，并保留质量标记。

---

# 5. 配置设计

新增：

```text
config/volatility.yaml
```

建议：

```yaml
volatility:
  annualization_days: 252
  windows: [5, 10, 20, 60, 120]
  min_obs_ratio: 0.80
  percentile_windows: [252, 756]
  percentile_min_obs_ratio: 0.50
  shock_threshold: 2.0
  highvol_percentiles: [0.80, 0.90]
  ewma_halflife: 20
  market_min_coverage_ratio: 0.80
  sector_min_stock_count: 5
  primary_universe: ALL_A
  correlation_windows: [20, 60]
```

如果现有 `DataConfig` 适合统一加载，则将 volatility config 合并进 `config/data_config.yaml` 的 typed config；不要形成两套互不一致的加载方式。

同时更新 `config/datasets.yaml`：

```text
stock_vol_daily        derived  business_key=[trade_date, stock_code]
market_vol_daily       derived  business_key=[trade_date, universe_name]
sector_vol_daily       derived  business_key=[trade_date, sector_type, sector_code, universe_name]
```

只有实际实现并发布的 membership dataset 才加入 registry。

---

# 6. 代码结构与职责

建议新增：

```text
src/qmt_local_data/volatility.py
```

纯计算函数放这里，不依赖 XtData，不直接写磁盘。

至少提供：

```python
calculate_stock_returns(...)
calculate_stock_volatility(...)
calculate_rolling_percentile(...)
calculate_market_volatility(...)
calculate_sector_volatility(...)
calculate_implied_correlation(...)
```

也可以拆为：

```text
src/qmt_local_data/volatility/
  __init__.py
  stock.py
  aggregate.py
  correlation.py
  regime.py      # V2
```

但不要为了目录美观过度拆分。

现有 `src/qmt_local_data/pipeline.py` 中为 `DatabaseBuilder` 增加高层入口，例如：

```python
build_volatility_derived(...)
build_stock_volatility(...)
build_market_volatility(...)
build_sector_volatility(...)
```

原则：

- 计算逻辑保持纯函数；
- pipeline 只负责读 active inputs、调用计算、质量检查、publish frame；
- 所有 Derived 输出走现有 `ManifestStore.publish_frame()`；
- `input_runs` 必须追踪输入 active run；
- 支持 replace/backfill 与增量 append；
- 不绕开现有 storage guard / catalog / manifest 体系。

---

# 7. 增量计算设计

## 7.1 初始化回算

完整历史首次构建需要的最早输入日，不是目标开始日本身。

如果要得到目标日 `T0` 的：

- RV120；
- RV20 的 756D percentile；
- market/sector percentile；

需要加载足够 warm-up。

不要硬编码 800 天，计算：

```text
warmup = max_rv_window + max_percentile_window + safety_margin
```

例如：

```text
120 + 756 + 20 = 896 market trading days
```

实际使用交易日历向前定位。

## 7.2 每日更新

新增 CLI 子命令，推荐：

```powershell
qmt-local-data build-volatility --start YYYY-MM-DD --end YYYY-MM-DD
```

或者：

```powershell
qmt-local-data update-derived --volatility --start ... --end ...
```

以现有 CLI 风格为准。

每日执行流程：

```text
确认 database_status READY_*
→ 读取历史 universe
→ 读取 adjusted stock daily / factor inputs
→ 加载目标区间 + warmup
→ 计算 stock_vol_daily
→ 聚合 market_vol_daily
→ 若存在 PIT/snapshot sector membership，则计算 sector_vol_daily
→ quality gate
→ publish immutable derived runs
→ refresh catalog
→ verify active manifests
```

## 7.3 上游历史修订

若上游某日期被补数/更正：

- 不只重算那一天；
- 从 earliest_changed_date 开始，向后重算所有可能受 rolling window / percentile 影响的日期；
- 最安全实现是允许显式 `--rebuild-from YYYY-MM-DD`；
- 后续可优化为根据 active manifest input changes 自动推导受影响区间。

V1 至少必须支持显式区间重建，并保证**全量重建与增量结果一致**。

---

# 8. Quality Gate

新增 volatility quality checks，放入现有 `quality.py` 或独立模块。

必须检查：

1. 主键无重复；
2. 日期单调、字段类型稳定；
3. `coverage_ratio ∈ [0,1]`；
4. breadth 指标 `∈ [0,1]`；
5. RV / dispersion 非负；
6. `valid_obs_*` 不超过窗口；
7. 历史 percentile `∈ [0,1]`；
8. 不允许停牌收益被 0 人工填充；
9. 除权日前后不能出现由未复权价格造成的虚假巨大收益；
10. implied correlation 的极端异常值需要告警；
11. `ALL_A` 只允许在 FULL_HISTORY scope；
12. sector 历史必须能证明 membership 在当时已有效；
13. market/sector 成员数和 coverage 过低时，指标标 NULL 或质量状态，不得静默有效；
14. 每个 derived manifest 记录输入 run / config / rule version。

---

# 9. Research API

更新 `src/qmt_local_data/research.py`。

加入 `_DATE_COLUMNS`：

```text
stock_vol_daily   -> trade_date
market_vol_daily  -> trade_date
sector_vol_daily  -> trade_date
```

新增只读接口：

```python
get_stock_volatility(codes, start=None, end=None)
get_market_volatility(universe_name="ALL_A", start=None, end=None)
get_sector_volatility(
    sector_type,
    sector_codes=None,
    universe_name="ALL_A",
    start=None,
    end=None,
)
```

如果数据库是 `CURRENT_UNIVERSE_ONLY`：

- 默认不能偷偷查询 `ALL_A`；
- 必须要求调用者使用真实 universe name；
- 返回数据保留 universe_scope / quality 信息。

---

# 10. DuckDB Catalog

更新 catalog，使新 Derived datasets 自动建立 active views：

```text
stock_vol_daily
market_vol_daily
sector_vol_daily
```

如果现有 CatalogBuilder 已按 dataset registry 自动发现，则只需补 registry 和测试，不重复写硬编码。

更新 `docs/DATABASE_SCHEMA.md`，记录：

- 三张表业务主键；
- 指标公式；
- annualization；
- min obs；
- percentile 的 prior-only 定义；
- universe / sector PIT 规则；
- implied correlation 不是简单 pairwise average。

更新 `docs/DATA_ACCESS_GUIDE.md` 给出 ResearchData 使用例子。

---

# 11. 单元测试：必须覆盖

新增：

```text
tests/test_volatility.py
```

或按现有 tests 风格拆分。

必须至少覆盖以下 synthetic cases。

## 11.1 常数收益

所有股票每天相同常数收益：

- stock RV = 0；
- dispersion = 0；
- shock_z 在 prior sigma=0 时为 NULL；
- 不产生 inf。

## 11.2 完全同步股票

多个股票收益序列完全相同且有波动：

- dispersion_1d = 0；
- implied_corr ≈ 1。

## 11.3 独立随机股票

固定 seed 生成近似独立收益：

- implied_corr 在合理误差下接近 0；
- 不要求精确为 0。

## 11.4 已知 pairwise panel

小规模完整 panel：

- 直接算 covariance/correlation matrix；
- 手工算 volatility-product weighted pairwise correlation；
- 与 `calculate_implied_correlation()` 一致。

## 11.5 单只股票冲击

构造已知 `shock_z`：

- `shock_up/down/abs_breadth` 必须得到精确已知比例。

## 11.6 停牌

构造中间停牌：

- 停牌日 ret=NULL；
- 不出现人为 0；
- min_obs 规则正确；
- 恢复日使用最近有效交易收盘价。

## 11.7 除权

构造一个价格机械下调但经济价值不变的公司行动：

- raw price 会产生假跌幅；
- adjusted close 的 ret 应接近 0；
- volatility 使用 adjusted return。

## 11.8 历史分位无未来函数

改变 t+1 以后的数据：

- t 日 percentile 不能变化。

## 11.9 Universe PIT

加入未来上市股票：

- 上市前不得进入历史 market breadth / dispersion。

退市后：

- 不再进入 eligible universe；
- 历史退市前仍存在。

## 11.10 Sector PIT

某股票在 T2 才加入 sector：

- T1 sector metrics 不得包含；
- T2 以后才包含。

## 11.11 Full vs Incremental

同一 synthetic data：

```text
full rebuild result == daily incremental result
```

对所有核心字段做 dataframe equality / numerical tolerance 检查。

---

# 12. 集成测试与验收命令

保持现有测试全部通过。

最低执行：

```powershell
python -m pytest -q
python -m compileall src scripts
python -m qmt_local_data.cli --help
python -m qmt_local_data.cli validate
git diff --check
```

若 CLI package entrypoint 已配置，则同时测试：

```powershell
qmt-local-data --help
```

使用小型 fixture 构建波动派生数据并 refresh DuckDB catalog，验证：

```sql
SELECT * FROM stock_vol_daily LIMIT 5;
SELECT * FROM market_vol_daily LIMIT 5;
SELECT * FROM sector_vol_daily LIMIT 5;
```

---

# 13. V1 可视化/观察输出（只做数据接口，不强制 Web UI）

V1 不建设 Web dashboard。

但必须让 Research API 足够支持下面六张图：

1. `ew_rv20` + 252D percentile；
2. `median_stock_rv20`；
3. `dispersion_ma5 / ma20`；
4. `highvol_breadth_80`；
5. `implied_corr20`；
6. `shock_down_breadth` / `down_rv20`。

板块查询必须可以支持：

```text
sector rv20 percentile ranking
sector rv5/rv20 ranking
sector rv20/rv60 ranking
sector dispersion ranking
sector high-vol breadth ranking
sector implied correlation ranking
```

---

# 14. V2：Market Regime 状态机

只有 V1 指标、测试、历史回算和增量一致性全部 PASS 后才开始。

新增：

```text
market_regime_daily
```

业务主键：

```text
trade_date, universe_name, rule_version
```

输入状态向量：

```text
V = ew_rv20_pct252
D = dispersion_ma5_pct252
B = highvol_breadth_80_pct252
C = implied_corr20_pct252
A_fast = rv5_rv20
A_slow = rv20_rv60
R = down_rv20_pct252
S = shock_down_breadth percentile
```

第一版采用**显式规则**，不要直接上 HMM/聚类。

阈值必须放配置，默认值只是研究起点，不宣称最优。

建议状态及优先级：

```text
1. PANIC
2. SYSTEMIC_RISK
3. EXPANSION
4. ROTATION
5. COMPRESSION
6. CALM
7. NORMAL
```

示例规则：

```text
PANIC:
  V >= 0.90
  C >= 0.85
  S >= 0.90

SYSTEMIC_RISK:
  V >= 0.75
  C >= 0.70
  R >= 0.70

EXPANSION:
  A_fast >= 1.25
  A_slow >= 1.05
  B >= 0.60

ROTATION:
  V < 0.50
  D >= 0.70
  C < 0.40

COMPRESSION:
  V <= 0.25
  A_fast < 0.80
  A_slow < 0.80

CALM:
  V < 0.30
  D < 0.30
  B < 0.30

else NORMAL
```

注意：

- `B` 上述规则要明确使用“raw breadth”还是“breadth percentile”，代码与配置必须写清；
- 推荐状态机最终统一使用 percentile 特征，期限比率保留 raw ratio；
- 状态有重叠时按固定优先级选择，确保确定性；
- regime 是研究标签，不是未经验证的交易信号。

---

# 15. V3：解决“这些指标到底有没有用”

新增研究脚本，建议：

```text
scripts/analyze_volatility_predictiveness.py
```

脚本读取 Research API，不直接扫描原始 XtData。

## 15.1 首先验证未来风险，而不是先预测方向

对于每个特征 X：

```text
X_t -> future realized vol 5D
X_t -> future realized vol 20D
X_t -> future absolute EW return 5D / 20D
X_t -> future max drawdown 5D / 20D
```

统计：

```text
Pearson correlation
Spearman correlation
quantile / decile conditional means
sample count
bootstrap or HAC-aware uncertainty if practical
```

## 15.2 收益方向作为次要研究

研究：

```text
X_t -> future EW return 1D / 5D / 20D
```

但报告必须强调：波动指标更可能预测“未来风险大小”而非单纯涨跌方向。

## 15.3 Regime-conditioned factor / strategy analysis

如果仓库后续已有 factor/strategy return：

计算：

```text
IC(Factor | Regime)
strategy_return | Regime
Sharpe | Regime
max_drawdown | Regime
turnover | Regime
```

目标不是证明“某个因子永远有效”，而是回答：

> 哪些因子/策略在什么波动状态下有效或失效？

## 15.4 Walk-forward / No Leakage

所有统计标准化、threshold calibration、regime fitting 都必须：

- expanding / rolling historical only；
- 禁止使用未来区间确定历史 threshold；
- 如果以后上 HMM/GMM/KMeans，训练和测试必须 walk-forward 分离。

---

# 16. V4：完整 Market Regime 系统（本 Plan 只预留接口）

在波动 V1/V2 稳定后，再加入：

```text
1. Volatility
2. Trend
3. Market Breadth
4. Liquidity
5. Risk Appetite
6. Crowding / Concentration
```

未来状态向量：

```text
MarketState = [
    Volatility,
    Trend,
    Breadth,
    Liquidity,
    RiskAppetite,
    Crowding,
]
```

本次实现**不要提前建设完整 V4**，避免一次性过度扩张。

---

# 17. 执行顺序

Codex 必须按以下顺序执行，不要跳步。

## Phase A — Repo inspection / prerequisites

- [ ] 检查 `database_status` 语义；
- [ ] 检查 adjusted price / factor 是否已生产可用；
- [ ] 检查 `historical_universe` 的 current/full scope；
- [ ] 检查是否存在可靠历史 sector membership；
- [ ] 记录 BLOCKED 项，不得伪造替代方案。

## Phase B — Pure math layer

- [ ] 新增 volatility 纯函数；
- [ ] 实现 returns / RV / semivol / percentile / shock；
- [ ] 实现 market aggregation；
- [ ] 实现 implied correlation；
- [ ] synthetic tests PASS。

## Phase C — Derived datasets

- [ ] 注册 `stock_vol_daily`；
- [ ] 注册 `market_vol_daily`；
- [ ] 有 PIT/snapshot membership 才注册 `sector_vol_daily`；
- [ ] 增加 quality gates；
- [ ] publish 使用现有 manifest / storage guard。

## Phase D — Pipeline / CLI / Catalog / Research API

- [ ] DatabaseBuilder 接入；
- [ ] CLI 支持 build/rebuild volatility；
- [ ] DuckDB views；
- [ ] ResearchData getters；
- [ ] 文档更新。

## Phase E — Incremental correctness

- [ ] full rebuild；
- [ ] daily incremental；
- [ ] 两者结果一致；
- [ ] historical correction 可显式区间重建。

## Phase F — Real database validation

- [ ] 在本地真实数据上生成样本区间；
- [ ] 检查除权/停牌/上市/退市边界；
- [ ] 检查全市场 coverage；
- [ ] 检查几次已知高波动时期指标方向是否合理；
- [ ] 不把“看起来合理”当成预测有效性。

## Phase G — Regime / research

V1 验收后再：

- [ ] rule-based regime；
- [ ] predictive validation；
- [ ] regime-conditioned factor/strategy analysis。

---

# 18. 代码改动预期清单

Codex 在开始实现后，原则上会涉及：

```text
config/data_config.yaml              # 或增加 volatility config section
config/datasets.yaml
src/qmt_local_data/config.py
src/qmt_local_data/volatility.py     # 新增，或 package
src/qmt_local_data/pipeline.py
src/qmt_local_data/quality.py
src/qmt_local_data/catalog.py        # 仅在 registry 自动发现不足时
src/qmt_local_data/research.py
src/qmt_local_data/cli.py
scripts/update_daily.py              # 视当前 wrapper 设计接入
scripts/validate_database.py         # 若需要增加 derived validation
scripts/analyze_volatility_predictiveness.py   # V3

tests/test_volatility.py
tests/test_catalog_pipeline.py       # 按需要扩展

docs/DATABASE_SCHEMA.md
docs/DATA_ACCESS_GUIDE.md
docs/RUNBOOK.md
```

不要因为本 Plan 的建议文件名与当前仓库实现不同而机械新增重复模块；先复用现有稳定抽象。

---

# 19. V1 最终验收标准

V1 只有同时满足以下条件才算完成。

## 数据正确性

- [ ] 股票收益基于已验证复权价格；
- [ ] 停牌不填 0；
- [ ] 历史股票池无幸存者偏差，或明确标记 `CURRENT_SURVIVORS`；
- [ ] sector membership 不使用当前成分回填历史；
- [ ] percentile prior-only；
- [ ] Shock 使用 prior volatility；
- [ ] implied correlation 通过 direct small-panel test。

## 功能

- [ ] `stock_vol_daily` 可完整构建；
- [ ] `market_vol_daily` 可完整构建；
- [ ] 有可靠 membership 时 `sector_vol_daily` 可构建；
- [ ] 5/20/60 期限结构可查询；
- [ ] dispersion / breadth / correlation / downside 可查询；
- [ ] ResearchData 有稳定接口；
- [ ] DuckDB active views 正常。

## 工程

- [ ] 全部测试通过；
- [ ] full vs incremental 一致；
- [ ] derived run 可重建；
- [ ] manifest input lineage 完整；
- [ ] storage guard / lock / catalog 机制未被绕开；
- [ ] `git diff --check` PASS；
- [ ] 不提交真实数据库、账号、私有路径和未经去敏的本机报告。

---

# 20. Codex 最终交付说明格式

实现完成后，Codex 最终必须报告：

1. 修改了哪些文件；
2. 三个核心数据集最终 schema；
3. 实际使用的复权收益来源；
4. universe scope；
5. sector membership 来源及是否支持真实历史；
6. full build 与 incremental equality 测试结果；
7. implied correlation 数学验证结果；
8. 单元测试/集成测试命令和结果；
9. 仍然 BLOCKED 的前置条件；
10. 是否已进入 V2 regime（默认不要自动进入，除非 V1 全部验收）。

---

# 21. 不属于 V1 的事项

本轮禁止因为“顺手”而扩大到：

- Tick / 分钟 realized volatility；
- Level 2 / order book volatility；
- 做市商库存或 Gamma exposure 推断；
- Options implied volatility / VIX 复制；
- HMM/GMM/深度学习 regime；
- 自动交易仓位控制；
- Web dashboard；
- 未验证的数据源。

这些可以在 V1 数据契约稳定后单独立项。

---

# 22. 最终设计思想

本项目不是构造“一个波动率数字”，而是构造市场的波动状态向量：

```text
Wave Height       = Market / Stock Volatility
Spatial Variation = Dispersion
Coverage          = High-vol / Shock Breadth
Synchronization   = Implied Correlation
Acceleration      = RV5/RV20, RV20/RV60
Direction         = Upside / Downside Volatility
```

期限结构：

```text
5D → 20D → 60D
```

空间结构：

```text
Stock → Sector → Market
```

V1 的成功标准不是“指标数量多”，而是：

> 指标定义无歧义、数据无未来函数、历史可重建、每日可增量、全市场与板块可以在同一口径下比较，并为后续 Market Regime / 策略条件分析提供可靠底层状态变量。

---

# 23. 用户批准的 V1 增量需求（2026-08-30）

以下内容由用户在原冻结规格之后明确新增，不修改原有指标算法、PIT 原则、5/20/60 期限结构
或质量标准：

1. `market_vol_daily` 和同口径板块聚合新增 `median_stock_rv5`、
   `median_stock_rv60`；原 `median_stock_rv20` 及其历史分位保持不变。
2. `market_vol_daily` 在原市场口径之外，同步提供独立沪深 A 股口径。为避免掩盖股票池
   完整性，名称固定为 `SH_SZ_CURRENT_SURVIVORS`（当前存续库）和
   `SH_SZ_ALL_A`（仅 `READY_FULL_HISTORY` 可用）。
3. 新增独立 Derived 数据集 `index_vol_daily`，业务主键为
   `trade_date, index_code`，覆盖上证50 `000016.SH`、沪深300 `000300.SH`、
   中证500 `000905.SH`、中证1000 `000852.SH`、科创50 `000688.SH`、
   创业板 `399006.SZ`。
4. `index_vol_daily` 直接使用官方指数收盘点位计算简单收益，沿用股票层的
   5/10/20/60/120 RV、80% `min_obs`、`ddof=1`、`sqrt(252)`、RV20 prior-only
   252/756 分位、上下行 RV 和 shock 定义；指数点位不应用股票复权因子。
## 24. 用户批准的参考数据增量（2026-08-30）

用户要求把历史指数成分、历史行业成分、退市个股、当前股票和上市日期过滤纳入数据库。
实机验证结果必须作为实施边界：当前 XtData 虽接受 `real_timetag`，但 2015/2020/2024/2026
返回完全相同的行业和全市场成员；下载行业历史包无进度且不能完成。六个指数只提供当前权重，
没有日期参数。因此不得把当前成员倒填为历史 PIT。

批准的最小安全实施为：交易所官方当前/退市清单进入 `current_stock_list`、
`delisted_stock_list` 和统一 `security_master`；QMT 当前指数权重和申万一级成员分别进入
`index_membership_snapshot_daily`、`sector_membership_snapshot_daily`，质量标记为
`OBSERVED_SNAPSHOT_ONLY`，从首次采集日向后积累。历史回填继续保持
`BLOCKED_SOURCE_UNAVAILABLE`，不改变原 Plan 的 PIT 原则和 sector 发布门禁。
