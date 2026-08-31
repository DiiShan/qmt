# 全市场、板块与宽基指数波动率可视化用户手册

## 1. 手册范围

本手册说明如何安装、启动和使用项目内的只读波动率仪表盘。界面严格读取：

- `market_vol_daily`：全市场波动率；
- `sector_vol_daily`：板块波动率；
- `index_vol_daily`：六个宽基指数波动率；
- `database_status.json`：数据库状态和股票池范围。

界面不重新计算指标、不修改 Parquet、不切换 active manifest，也不会绕过复权因子、历史
universe 或 sector membership 门禁。指标定义、5/20/60 期限结构、PIT 原则和质量标准仍以
项目根目录的 `全市场与板块波动率系统_CODEX_PLAN.md` 为准。

当前真实数据库是 `READY_CURRENT_UNIVERSE_ONLY`，因此页面显示的“全市场”实际股票池名为
`CURRENT_SURVIVORS`，存在幸存者偏差，不能解释为 `ALL_A`。

截至 2026-08-30，`adjust_factor`、`stock_vol_daily`、双口径 `market_vol_daily` 和
`index_vol_daily` 已发布；市场与五个长历史指数覆盖 2011-01-04 至 2026-08-21，科创50
从 2019-12-31 起有有效观测。`sector_vol_daily` 仍因历史 PIT 板块成员缺失保持 BLOCKED。

## 2. 安装

在项目根目录打开 PowerShell：

```powershell
cd D:\project\codex\investment\qmt\qmt-api-probe
python -m pip install -e ".[dashboard,dev]"
```

`dashboard` 额外依赖只用于界面展示；数据库构建和普通研究 API 不强制加载它们。

安装后先检查命令：

```powershell
qmt-local-data dashboard --help
```

## 3. 启动与停止

### 3.1 本机启动

```powershell
qmt-local-data dashboard --config config/data_config.yaml
```

浏览器访问：

```text
http://127.0.0.1:8501
```

停止服务：回到运行命令的 PowerShell，按 `Ctrl+C`。

### 3.2 指定端口

```powershell
qmt-local-data dashboard --config config/data_config.yaml --port 8765
```

随后访问 `http://127.0.0.1:8765`。

### 3.3 局域网访问

只有在受信任的局域网内确有需要时才监听所有网卡：

```powershell
qmt-local-data dashboard --config config/data_config.yaml `
  --host 0.0.0.0 --port 8501
```

该命令本身不提供登录鉴权，不应直接暴露到公网。

## 4. 页面结构

仪表盘包含四个页签：

1. **全市场**：展示 `market_vol_daily`；
2. **板块**：展示 `sector_vol_daily`；
3. **宽基指数**：展示 `index_vol_daily`；
4. **数据状态**：展示数据库、视图和门禁状态。

页面顶部始终显示数据库路径、数据库状态和真实股票池名。若数据库为
`CURRENT_UNIVERSE_ONLY`，页面会持续显示幸存者偏差警告。

## 5. 全市场页面

### 5.1 操作方法

1. 选择全范围 A 股或独立沪深 A 股统计口径；
2. 选择开始日期和结束日期；默认显示最近约三年；
3. 查看最新交易日的核心数值；
4. 在主题图中观察期限结构、横截面、广度、相关性和下行风险；
5. 在“全部指标浏览”中勾选任意数值字段进行组合比较；
6. 展开“查看全市场明细数据”，核对原始派生字段和质量状态。

### 5.2 核心指标

| 字段 | 中文说明 | 用于什么判断 |
|---|---|---|
| `eligible_stock_count` | 当日历史股票池中满足上市日期等资格条件的股票数。当前数据库的范围是 `CURRENT_SURVIVORS`，不是完整历史 `ALL_A`。 | 判断当日统计母体的大小，并识别股票池范围是否发生异常变化。 |
| `valid_return_count` | 当日存在有效复权收益的股票数；停牌、无有效成交或价格无效的股票不计入，且收益不会填成 0。 | 判断当天实际有多少股票参与市场聚合计算。 |
| `coverage_ratio` | `valid_return_count / eligible_stock_count`；当前合格阈值为 80%。 | 判断当天指标覆盖是否足够；低于阈值时应先处理数据质量问题，不宜直接解释市场状态。 |
| `ew_ret` | 当日所选口径中有效股票简单收益率等权平均，即 `mean(ret_i,t)`；全范围包含 `.SH/.SZ/.BJ`，沪深口径只包含 `.SH/.SZ`。 | 判断普通股票的等权涨跌体验，避免少数大市值股票主导结果。 |
| `ew_rv5/20/60` | 等权市场收益在 5/20/60 个市场交易日窗口内的样本标准差乘 `sqrt(252)`。 | 分别观察短期、中期和较慢的全市场波动水平。 |
| `rv5_rv20` | `ew_rv5 / ew_rv20`；分母无效或为 0 时为 NULL。 | 判断近期波动相对一个月基准是在升温（大于 1）还是冷却（小于 1）。 |
| `rv20_rv60` | `ew_rv20 / ew_rv60`；分母无效或为 0 时为 NULL。 | 判断一个月波动相对三个月背景处于扩张还是收缩。 |
| `median_stock_rv5/20/60` | 当日 eligible 股票各自 5/20/60 日年化实现波动率的横截面中位数。 | 同时观察“典型股票”的短、中、较长期波动，并与等权市场 RV 对照。 |
| `p25/p75/p90_stock_rv20` | 个股 20 日年化实现波动率横截面的 25%、75% 和 90% 分位数。 | 判断个股波动分布的层次、尾部及高波动股票是否集中在少数标的。 |
| `dispersion_1d` | 当日有效个股简单收益率的横截面样本标准差，即 `std_i(ret_i,t, ddof=1)`；保持日收益单位，不年化。例如 `0.025` 表示约 2.5 个百分点的横截面标准差。 | 判断当天个股涨跌是否分化。市场平均收益接近 0 但该值很高，通常表示赢家和输家差异很大，而不是市场平静。 |
| `dispersion_ma5/20` | 两个独立字段 `dispersion_ma5` 和 `dispersion_ma20`，分别是 `dispersion_1d` 的 5 日、20 日滚动均值；这里的 `/` 表示并列，不是 `ma5 / ma20`。 | 比较短期与中期分化趋势：MA5 高于 MA20 表示近期分化扩大，反之表示分化收敛。 |
| `dispersion_ewma20` | `dispersion_1d` 的递归 EWMA，半衰期为 20 日，较近观测权重更大。 | 平滑观察分化状态，同时比普通 MA20 更快反映新变化。 |
| `highvol_breadth_80/90` | 个股 `rv20` 在自身 prior-only 252 日历史中达到 80%/90% 分位的股票占比。 | 判断高波动是少数股票的局部现象，还是正在向大量股票扩散。 |
| `shock_up_breadth` | 先计算个股 `shock_z20 = ret_1d[t] / (rv20[t-1] / sqrt(252))`，再统计 `shock_z20 >= +2` 的股票占有效 shock 股票比例；当前阈值为 2.0。 | 判断超出个股自身正常波动约两倍的异常上涨是否广泛扩散。 |
| `shock_down_breadth` | 统计 `shock_z20 <= -2` 的股票占有效 shock 股票比例；使用前一日 RV20，不把当日冲击计入分母。 | 判断异常下跌冲击是否从少数股票扩散为较广泛的市场压力。 |
| `shock_abs_breadth` | 统计 `abs(shock_z20) >= 2` 的股票占比，同时包含向上和向下冲击。“绝对冲击”是相对股票自身历史波动标准化后的异常变化，不是固定涨跌幅阈值。 | 判断市场总体异常扰动的覆盖面；结合 up/down breadth 才能区分扰动方向。 |
| `implied_corr20/60` | 在对应 20/60 日窗口中，只保留每天都有有效收益的固定股票集合，由等权组合方差和个股方差反推波动率乘积加权隐含平均相关性；不是所有两两 Pearson 相关系数的简单平均，也不强制截断到 `[0,1]`。 | 判断股票是否同步运动。高值表示分散化效果下降、系统性共振增强；低值配合高 dispersion 通常更接近个股分化或板块轮动。 |
| `implied_corr20/60_stock_count` | 对应相关性计算实际使用的完整窗口股票数。股票只要在窗口内有一天缺少有效收益，就不进入该窗口的固定集合。 | 判断隐含相关性的样本代表性；相关性变化时，应同时确认参与股票数是否发生明显跳变。 |
| `up_rv20` | `sqrt(252 * mean(max(ew_ret, 0)^2))`，使用同一个 20 日窗口；负收益日在平方项中按 0 处理，不按上涨日数量重新归一。 | 判断近期正收益日的上涨幅度是否剧烈，即波动中的上行部分有多强。 |
| `down_rv20` | `sqrt(252 * mean(min(ew_ret, 0)^2))`，使用同一个 20 日窗口；正收益日在平方项中按 0 处理。 | 判断近期负收益日的下跌幅度是否剧烈，是观察下行风险的核心方向性指标。 |
| `down_up_ratio` | `down_rv20 / up_rv20`；上行半波动率为 0 或无效时返回 NULL，不产生无穷大。 | 判断波动方向是否不对称：大于 1 表示下行波动占优，小于 1 表示上行波动占优；它不是涨跌概率或预测信号。 |
| `quality_status` | 当日聚合指标质量状态。全市场当前包括 `PASS`（覆盖率达到 80%）和 `LOW_COVERAGE`（低于 80%）；板块路径还定义 `INSUFFICIENT_MEMBERS`（成员少于 5 只）。 | 决定该日指标是否适合解读。应先检查此字段，再分析波动曲线；`PASS` 也不代表已消除 `CURRENT_SURVIVORS` 的幸存者偏差。 |
| `quality_flags` | 质量问题的机器可读原因，例如 `coverage_below_threshold` 或 `sector_stock_count_below_threshold`；无问题时为空字符串。 | 定位 `quality_status` 非 PASS 的具体原因，区分覆盖不足、成员不足等问题。 |

以下序列各自包含 prior-only 的 252 日和 756 日历史经验分位：

- `ew_rv20`；
- `median_stock_rv20`；
- `dispersion_ma5`；
- `highvol_breadth_80`；
- `implied_corr20`；
- `down_rv20`。

字段名形式为 `<指标>_pct252` 和 `<指标>_pct756`。分位只使用当前日之前的历史样本，
不会把当前值放进自己的参考分布。

### 5.3 建议阅读顺序

1. 先检查 `coverage_ratio` 和 `quality_status`；低覆盖日的聚合指标按规则置空；
2. 看 `ew_rv5/20/60` 和两个期限比值，判断短期波动是否相对中长期抬升；
3. 用 `median_stock_rv5/20/60`、P25/P75/P90 和 `highvol_breadth` 判断风险是集中还是广泛；
4. 用 `dispersion` 与 `implied_corr` 区分个股分化和同步共振；
5. 用 `down_rv20`、`down_up_ratio` 和 shock breadth 查看下行风险是否占优。

上述指标用于描述市场状态，不等同于预测信号或交易建议。

## 6. 板块页面

### 6.1 门禁状态

只有可靠历史 PIT 行业成员或逐日真实 snapshot 上线、`sector_vol_daily` 通过质量门并注册为
active DuckDB view 后，板块页面才展示真实曲线。

在此之前，页面会明确显示：

- `sector membership = BLOCKED`；
- `sector_vol_daily manifest = 未发布`；

参考数据已在 2026-08-30 增加首个真实观察快照：六个指数权重和申万一级行业成员均可通过
ResearchData 或 DuckDB 查询。该快照不代表 2026-08-30 以前的历史成分，因此板块历史波动率
页面仍保持门禁；后续每日运行 `update-reference-data` 可从首个采集日开始积累真实 PIT 历史。
- 当前真实 universe scope。

这是预期行为。不要为了让页面出现曲线而用今天的行业成分回填历史。

### 6.2 数据就绪后的操作方法

1. 选择板块分类，例如未来发布的申万一级等真实分类；
2. 选择一个或多个板块，建议同时比较不超过 8 个；
3. 选择日期范围；
4. 查看最新交易日板块排名表；
5. 比较板块 RV20、历史分位、高波动广度、隐含相关性、离散度和下行/上行比；
6. 在“板块全部指标浏览”中选择其他已发布字段；
7. 展开明细数据核对成员数、覆盖率与质量状态。

### 6.3 板块指标

| 字段 | 中文说明 |
|---|---|
| `sector_type/code/name` | 板块分类、稳定代码和展示名称 |
| `eligible_stock_count` | 当日属于该板块且满足历史 universe 资格的股票数 |
| `valid_return_count` | 当日该板块的有效收益股票数 |
| `coverage_ratio` | 板块有效收益覆盖率 |
| `rv5/20/60` | 板块等权收益 5/20/60 日年化实现波动率 |
| `rv20_pct252/756` | 板块 RV20 的 prior-only 历史分位 |
| `rv5_rv20`、`rv20_rv60` | 板块波动率期限比值 |
| `median_stock_rv5/20/60`、`p25/p75/p90_stock_rv20` | 板块内个股多期限中位数及 RV20 横截面分布 |
| `dispersion_1d/ma5/ma20/ewma20` | 板块内个股收益离散度及平滑值 |
| `highvol_breadth_80/90` | 板块内高波动和极高波动股票占比 |
| `shock_up/down/abs_breadth` | 板块内上涨、下跌和绝对冲击广度 |
| `implied_corr20/60` | 板块内 20/60 日隐含平均相关性 |
| `implied_corr20/60_stock_count` | 相关性完整窗口实际使用股票数 |
| `up_rv20`、`down_rv20`、`down_up_ratio` | 板块上行、下行半波动率及其比值 |
| `quality_status/flags` | 低覆盖、成员不足等质量状态与标记 |

板块成员数低于配置的 `sector_min_stock_count` 时，相关截面指标会置空，并显示
`INSUFFICIENT_MEMBERS`，不应把空值当作零。

## 7. 宽基指数页面

该页覆盖：上证50、沪深300、中证500、中证1000、科创50和创业板。先多选指数和日期，
再查看最新截面表、RV20、RV20 历史分位、短中期波动率比值、下行/上行比及任意字段曲线。

`index_vol_daily` 使用官方指数收盘点位，包含 `rv5/10/20/60/120`、期限比值、
`rv20_pct252/756`、上下行 RV、`down_up_ratio`、`shock_z20` 和各窗口有效观测数。
指数点位不应用股票复权因子。

## 8. 数据构建后刷新界面

复权因子审计与发布命令：

```powershell
qmt-local-data build-adjust-factor --config config/data_config.yaml `
  --audit-output reports/adjust_factor_audit.json

qmt-local-data build-adjust-factor --config config/data_config.yaml `
  --factor-version xtdata_dr_cumprod_v1 `
  --audit-output reports/adjust_factor_audit.json --publish
```

复权因子门禁通过后，首次构建全市场数据：

```powershell
qmt-local-data build-volatility --config config/data_config.yaml `
  --start 2011-01-04 --end <最新交易日>

qmt-local-data refresh-catalog --config config/data_config.yaml
qmt-local-data validate --config config/data_config.yaml
```

若 `index_daily` 尚缺科创50或创业板，先补齐指数行情：

```powershell
qmt-local-data update --config config/data_config.yaml --asset index `
  --start 2011-01-04 --end <最新交易日> --download
```

指数数据也可不依赖股票波动率而独立构建：

```powershell
qmt-local-data build-index-volatility --config config/data_config.yaml `
  --start 2011-01-04 --end <最新交易日>
```

日常只追加新交易日：

```powershell
qmt-local-data build-volatility --config config/data_config.yaml `
  --start <首个新增交易日> --end <最新交易日>

上游行情、复权因子或 universe 历史修订时：

```powershell
qmt-local-data build-volatility --config config/data_config.yaml `
  --rebuild-from <最早变更日> --end <最新交易日>
```

仪表盘页面刷新后会读取新的 active DuckDB view。不要在页面里直接修改数据库文件。

## 9. 常见问题

### 页面提示 `market_vol_daily` 尚未发布

原因通常是复权因子仍为 `RAW_ONLY_PENDING_FACTOR_SEMANTICS_VALIDATION`。先完成至少三个真实
除权事件和一个无事件区间的因子连续性核验。不得跳过验证或猜测 Raw `dr` 的语义。

### 板块页面只有 BLOCKED 提示

这是当前 V1 数据前置条件的真实状态。需要可靠历史 PIT 成分或从首次日期开始积累的逐日真实
snapshot，之后才可发布 `sector_vol_daily`。

### 宽基指数页面提示 `index_vol_daily` 尚未发布

先用 `update --asset index` 补齐配置中的六个指数，再运行 `build-index-volatility`。该流程不受
股票复权因子门禁影响。

### 页面显示 `CURRENT_SURVIVORS`

这是数据库状态决定的真实股票池。退市股票闭环并重建 `READY_FULL_HISTORY` 之前，不能在页面、
报告或研究结论中改称 `ALL_A`。

### 图表出现断点或空值

先查看同日 `quality_status`、`quality_flags`、`coverage_ratio` 和股票数。停牌收益不填零，低覆盖、
分母为零、窗口样本不足或成员不足时，指标按规格保留为 NULL。

### 端口被占用

换用其他端口：

```powershell
qmt-local-data dashboard --config config/data_config.yaml --port 8765
```

### 找不到 `qmt-local-data`

重新执行：

```powershell
python -m pip install -e ".[dashboard]"
```

并确认当前 PowerShell 使用的是同一个 Python 环境。

## 10. 验收命令

```powershell
python -m pytest -q
python -m compileall src scripts
qmt-local-data dashboard --help
qmt-local-data validate --config config/data_config.yaml
git diff --check
```

启动界面后还应人工确认：

1. 全市场页的日期选择、悬停提示、自选指标和明细表可用；
2. 页面股票池与 `database_status.json` 一致；
3. 数据缺失时显示门禁，不生成演示数据；
4. 宽基指数页可同时比较六个指数并浏览任意字段；
5. sector view 就绪后，分类、板块多选、排名表和六组主题图可用；
6. 关闭浏览器不会影响数据进程，`Ctrl+C` 可以正常停止界面服务。
