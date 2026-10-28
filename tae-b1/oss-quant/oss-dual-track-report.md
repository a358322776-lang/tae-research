# GitHub 开源量化策略双轨研究报告（只读核查，未冻结、未验证，不得作为交易规则使用）

> **红线声明：本报告不移植任何策略、不进行实盘交易、不部署任何自动交易；文中一切模拟、回测数字均为模拟口径，绝不称为实盘盈利。**
> **证据口径：＝核查员亲读源码或仓库文件；＝仓库/作者声称但无逐笔、无时间戳、无第三方痕迹；＝本次未确认，不作有/无断言。README 宣传文案不算证据。**
> **方法论铁律：历史已反复使用，任何新规则只算探索；最终验证必须用规则冻结之后新产生的前向数据；不做参数搜索、不筛历史最优组合。**
> **核查方式：4 路并行 git shallow clone 到 /tmp 读真实源码（未实际安装运行任何项目，“可运行”均指代码与配置层面判断）；核查版本 SHA 见各候选条目；完整核查笔记在 /tmp/oss-research/（临时文件，不进仓）。**

## 0. 对照基线 B1 与数据硬约束

- **B1（rules-v0.1-frozen.md）**：1H 严版趋势（最后 3 摆动高/低逐级同向、每级 ≥0.5×ATR）定方向，无大趋势不开单；顺方向关键带同侧第 ≥2 次测试（带由摆动高/低归簇，trailing 400 根 15m 重算）＋ Teo 六种信号 K 入场；止损＝带沿外 1×ATR、永不移动；出场＝初始止损或 15m 收盘越 EMA50 先到者；无固定止盈、无分批。费用口径：入场/止损 taker 0.05%、资金费按名义模型计入；同根顺序不明一律保守（止损优先于出场）。
- **B1 现状**：样本外 123 单净 −0.159R/单、六档全负；归因结论为入场无优势（入场后漂移 ≈0）；E 只是入场限制、不是优势来源。因此本次双轨研究要回答的不是“有没有更赚钱的策略可抄”，而是：有没有**证据更硬**的项目，以及有没有**与 B1 不同的预测变量、时间尺度或收益机制**可作对照或方法论借鉴。
- **数据硬约束**：只有 Binance ETHUSDT 永续公开 K 线（15m/1h/5m，经 www.binance.com 镜像可拉）；没有订单簿、没有逐笔成交、没有强平数据、没有链上数据。任何依赖订单簿/tick/链上数据的候选，在现有条件下都只能记“不可验证”，不得记“可用”。
- **“不同”的定义**：预测变量、时间尺度或收益机制任一实质不同才算不同；换参、换周期、换均线不算不同。

## 1. 评分口径（先写口径再打分）

**A 榜：收益证据可信度（0–5 分）**——衡量“这个项目赚过钱的证据有多硬”，与策略本身好坏无关：

| 分 | 标准 |
|---|---|
| 5 | 逐笔可复核＋手续费/滑点/资金费全计＋第三方或时间戳可核对的前向/实盘记录 |
| 4 | 逐笔可复核的回测＋成本全计 |
| 3 | 有回测结果但缺逐笔或缺部分成本 |
| 2 | 引擎输出可逐笔审计，但无任何策略收益证据（框架类封顶分） |
| 1 | 仅自述数字、控制台粘贴输出、相对数、付费墙后内容、空壳 live 页 |
| 0 | 模板占位、as-shipped 不可运行、或零记录且无结果 |

**B 榜：TAE 研究借鉴价值（0–5 分）**——衡量“对 TAE 当前待决问题（入场优势检验、对照组、验证方法论）有多大用”，不衡量“能不能直接赚钱”：

| 分 | 标准 |
|---|---|
| 5 | 方法论标杆：能把验证从收盘价模拟升级为事件模拟（即使完全兑现需未来数据） |
| 4 | 立即可用且不依赖新数据的方法论改进，直接服务入场优势检验 |
| 3 | 可作对照组/慢速基准/候选特征/第二类事件/机制对照 |
| 2 | 工程参考（代码结构、成本建模、出场对照）或写法范本 |
| 1 | 仅报告格式、单点注释可参考 |
| 0 | 无借鉴价值 |

**两榜分歧的根源（先说结论）**：A 榜最高分只有 2 分——19 个候选无一提供可逐笔复核的策略收益证据，这是开源策略仓的通病（只给代码不给可核对的成绩）；B 榜高分者恰恰是“不带盈利策略的框架”（Jesse、Nautilus），因为 TAE 当前最缺的不是新信号而是更硬的验证方法。策略类在 B 榜的价值几乎全在“对照组”而非“替代品”。

## 2. 候选总览（19 个，含框架与策略单列）

| # | 候选 | 仓库 / 版本锚点 | A | B | 一句话定性 |
|---|---|---|---|---|---|
| T1 | TrendRider（darkvolg） | darkvolg/trendrider-strategy `621b0c8` | 1 | 2 | 代码真、绩效只有相对数＋付费墙；与 B1 同源 |
| T2 | TrendRider（hassannazir） | hassannazir/TrendRider `16bbd24` | 1 | 3 | 极简日线 regime 基准；仓库新建当天，数字无法复现 |
| H | Hummingbot | hummingbot/hummingbot `9af100d` | 1 | 3 | 机制真正不同（价差/基差），但需订单簿、现有数据无法验证 |
| F1 | Supertrend | freqtrade-strategies `f3340ce1` | 1 | 2 | 三重同源＋12 参 hyperopt，换指标变体 |
| F2 | BbandRsi | freqtrade-strategies `f3340ce1` | 1 | 3 | 最干净的均值回归反向对照组 |
| F3 | CombinedBinHAndCluc | freqtrade-strategies `f3340ce1` | 1 | 3 | 单根形态强度是 B1 缺的探索特征；OR 双规则过拟合风险高 |
| F4 | TrendFollowingStrategy | freqtrade-strategies `f3340ce1` | 0 | 1 | 缺 can_short，as-shipped 跑不出空头 |
| F5 | VolatilitySystem | freqtrade-strategies `f3340ce1` | 1 | 3 | 3h 波动突破事件最不同；无止损＋加仓＋2x 绝不能移植 |
| J0 | Jesse 框架 | jesse-ai/jesse `4292249a`（v3.5.3） | 2 | 4 | 蒙特卡洛＋显著性检验，立即可用；回测不计滑点/资金费，需 1m K 线 |
| J1 | Jesse TurtleRules | jesse-ai/example-strategies `7c91e0a3` | 1 | 3 | Donchian 突破触发器对照系；同为趋势延续机制 |
| J2 | Jesse RSI2 | jesse-ai/example-strategies `7c91e0a3` | 1 | 2 | 均值回归反例（负结果粘贴）；无止损、已被用户搁置逆势方向 |
| J3 | Jesse SMACrossover | jesse-ai/example-strategies `7c91e0a3` | 1 | 1 | 13 单牛市窗口粘贴；换均线而已 |
| N0 | Nautilus 框架 | nautechsystems/nautilus_trader `20280856`（2.0.0rc8） | 2 | 5 | 确定性事件引擎＋显式费用/延迟/滑点模型；Bar 级可跑，六项保真度损失须声明 |
| N1 | Nautilus EMACross | 同上 | 1 | 2 | 仅作 Nautilus 写法范本；演示数据非真实回测 |
| N2 | Nautilus GridMarketMaker | 同上 | 1 | 3 | 做市机制对照；2012 外汇测试数据＋假设成交模型，不可验证 |
| O | OctoBot | Drakkar-Software/OctoBot `c45fdc2c` | 1 | 3 | 在维护、有期货符号与资金费账目；零条策略成绩；借鉴工程不借鉴信号 |
| G | Gekko | askmike/gekko `ff5698f1`（已归档） | 1 | 1 | 现货 only、Binance wrapper 无 futures 命中；永续硬伤 |
| Z | Zenbot | DeviaVir/zenbot `52872fb4`（已归档） | 1 | 2 | 成本建模较完整＋波动率自适应阈值；官方遗传调参即禁止的历史筛选 |
| D | QuantDinger（丁格最可能对应物，同一性未证实） | brokermr810/QuantDinger `8b2af21c` | 1 | 2 | 防未来函数意识最好；无自带盈利策略；Binance 永续路径未核实 |

Freqtrade 合集整体：**不给统分**（68 个文件横跨现货与期货、1h 与 5m、止损 −5% 到 −100%，无统一币种/时段/配置、无任何一策略附带逐笔结果；任何单一分数都会把模板的 0 分与 hyperopt 的虚高平均成一个不存在的中间值）。

## 3. 逐候选 7 点核查

### 3.1 T1 — TrendRider（darkvolg/trendrider-strategy，`621b0c8`，2026-04-21，单 commit，stars 22）

身份说明：精确名搜索共 12 仓、stars 最高仅 22；本对象是唯一同时满足“自称 TrendRider 官方 bot 开源策略＋完整可运行源码＋数月存续”者。其余同名项目（看板/空仓/美股/MT5/生成 app 等）见排除清单。

1. **策略与经济逻辑**：1H 仅做多趋势延续，6 入场形态 OR 门＋0–10 分信心拦截，出场为 ROI 阶梯＋−6% 止损＋trailing＋V4 级联时间止损，赚趋势段而非价差/反转。证据：`tr-darkvolg/TrendRiderStrategy.py:29-45,276-402,595-617`。
2. **完整可运行源码**：是，745 行 Freqtrade IStrategy＋Bybit 期货示例配置（dry_run、stake 50），但 `buy_params` 与 `IntParameter` 默认值不一致（ema_slow 16 vs 21、ADX 18 vs 25）、Fear & Greed 被写死为常数 50（`:267`）致该过滤器失效、生产层（资金费/OI/whale）自承缺失。证据：同文件 `:79-99` 及 `README.md`“What's not in this repo”。
3. **回测/前向/实盘**：三者全无可核对文件——回测仅 README 30 天相对数（V4 vs V3 利润 +69%、回撤 −77%，无绝对数），完整报告在 $19 付费墙后；live 页自称“real money, dry-run mode”自相矛盾，2026-10-28 文本抓取仅得 “Loading live stats…”、无交易无时间戳；实盘无证据；三者皆记。
4. **逐笔复核与成本**：逐笔 ✗；手续费 △（框架可计费但仓内无结果可确认）；滑点 ✗；**资金费 ✗（单点指出：期货配置策略的公开版明确排除资金费/OI，任何利润声称均未计资金费）**。
5. **未来函数/过拟合/幸存者偏差**：未见明显未来函数（收盘指标、210 根启动、informative ffill），但过拟合高风险（9＋1 参数＋4 段 ROI＋6 形态＋信心权重，hyperopt 后又在同一 30 天窗比选 V4/V5/V6 宣布“局部最优”），且仅报 BTC/ETH/SOL、无失败币对照。
6. **Binance ETHUSDT 永续与现有数据**：半适用——入场逻辑是 1h K 线驱动可做 K 线最小验证，但原策略依赖 Bybit＋订单簿定价＋交易所止损单＋Telegram 钩子，缺订单簿无法原样跑，移植须重写执行层与资金费处理；且示例 50U/单×3 单与 TAE 现约 56U 规模不匹配。
7. **与 B1 是否不同**：否——同为趋势延续、同套预测变量（EMA/RSI/ADX/MACD/布林/量/OBV）、同一 1h 尺度，差异只在出场工程（ROI/trailing/时间止损），按定义不算新预测或新收益来源。

### 3.2 T2 — TrendRider（hassannazir/TrendRider，`16bbd24`，stars 0）

**Provenance 警示（引用时必须附带）**：该仓库创建于核查当天凌晨（2026-10-28 00:35 UTC）、仅 1 个 commit；其所谓“2024–2026 回测、2026 年 1–10 月未见数据”不可能以该公开仓库为时间戳佐证——只能当“匿名策略文本”核查，不能当“有历史的项目”引用。

1. **策略与经济逻辑**：现货仅做多、无杠杆，日线收盘＞50 日 SMA 则持有否则空仓 USDT（1h 检查、日线才变信号），−15% 仅作灾难止损、永不固定止盈，赚慢速 regime 贝塔而非择时精度。证据：`tr-hassan/user_data/strategies/TrendRider.py` 全文 128 行。
2. **完整可运行源码**：框架层面是（Freqtrade 现货 Binance/OKX 双配置＋paper/live/backtest PowerShell 脚本、默认 dry_run），但未本机实测，且运行环境是 Windows PowerShell、.venv 不入仓。
3. **回测/前向/实盘**：回测仅 README 表格（Top 6 分层 +72%/+7%，BTC+ETH +58%/+20%），仓内无任何结果文件（`backtest_results/`、`*.sqlite`、`user_data/data/` 均被 `.gitignore` 排除，研究脚本要读的 `*-1h.feather` 也不在仓内，无法复现）；前向无结果文件；实盘作者本人只写“Live-ready after paper trading”（未声称已实盘）。
4. **逐笔复核与成本**：逐笔 ✗；手续费口径一致但无结果佐证（研究脚本 0.1%/边、往返 0.2%）；滑点 ✗（假设“收盘决策、下一根开盘成交”，作者自己披露 ATOM 闪崩实例下真实成交差于假设）；资金费 N/A（现货策略，非缺口）。
5. **未来函数/过拟合/幸存者偏差**：脚本本身干净（收盘决策、次根开盘执行、Donchian 用 shift(1)，7 种安全改进经检验全部被拒是反过拟合的诚实披露），但“未见 2026”仅是代码默认 `--split 2026-01-01`、仓库新建当天故无公开时间戳佐证，且币宇宙为成文时 Top 20 存活币、有选择偏差。
6. **Binance ETHUSDT 永续与现有数据**：逻辑最易用现有 K 线验证（1h 重采样为日线即可算 SMA50 规则），但 instrument 不对——现货仅做多、无资金费/保证金/空头，验证出的是现货贝塔而非永续 PnL，移植须重写执行层。
7. **与 B1 是否不同**：是——日线 regime 开关（每月数笔、约一半时间空仓）vs B1 的 15m 带测试＋信号 K 日内入场，时间尺度与决策变量实质不同；但定位是 B1 的**零假设基准**（“复杂日内规则是否跑赢一行日线规则”），而非 B1 入场的修复。

### 3.3 H — Hummingbot（hummingbot/hummingbot，`9af100d`，2026-09-22，stars 20,748，Apache-2.0）

1. **策略与经济逻辑**：非趋势预测而是价差/基差/流动性供给——PMM（mid ± spread 多档挂单）、XEMM（maker 挂单＋taker 对冲赚跨所价差）、PerpMM（永续 PMM＋持仓止盈/止损）、AMM 套利（扣费后 ≥min_profitability）、现货–永续套利（开仓/平仓双阈值赚基差收敛）；可执行细节（报价公式、库存偏斜插值、刷新/撤单、风控参数）已逐项核对源码。证据：`hummingbot/strategy/{pure_market_making/pure_market_making.pyx, cross_exchange_market_making/cross_exchange_market_making.py, perpetual_market_making/perpetual_market_making.py, amm_arb/amm_arb.py, spot_perpetual_arbitrage/spot_perpetual_arbitrage.py}`。
2. **完整可运行源码**：是（Dockerfile、conda 环境、Python ≥3.10.12、Binance 永续连接器、paper-trade 模拟所、配置模板俱全），但核心策略多为 Cython 须编译、依赖重、v1 为旧代（主推方向已是 v2 控制器），且本次未实测安装。
3. **回测/前向/实盘**：v1 策略无回测引擎（仓内无 backtest 命令/结果）；v2 有真实 K 线回测引擎（`hummingbot/strategy_v2/backtesting/backtesting_engine_base.py`，产出费用/回撤/Sharpe/profit factor），但回测的是 v2 控制器（如 pmm_simple）而非 v1 PMM/PerpMM、两者不等价；前向仅 paper-trade 连接器（无运行记录）；实盘框架支持但仓内无任何官方成绩——属“无声称”而非“自述声称”。
4. **逐笔复核与成本**：逐笔 △（用户自己的交易落库 `TradeFill` 可审，但本次无样本）；v2 回测手续费仅为 flat 参数（默认 `trade_cost=0.0002`，非分档真实费率）；滑点无订单簿深度/排队模型（收盘穿越即按收盘价成交）；**资金费：live 连接器真实跟踪（`perpetual_derivative_py_base.py`），但 v2 回测全文 grep funding 为 0 命中——回测不计资金费，单点指出，持有期越长偏差越大**。
5. **未来函数/过拟合/幸存者偏差**：v2 引擎未见前视（`merge_asof` 对齐、按时间顺序推进）；主要偏差是 K 线回测模拟不出做市核心风险（排队位置与逆向选择）因而系统性美化做市策略；v1 无回测故风险转为操作者实盘手调参数；框架不预设币宇宙、无固有幸存者偏差。
6. **Binance ETHUSDT 永续与现有数据**：连接器真实存在（`hummingbot/connector/derivative/binance_perpetual/`），但 v1 策略运行前提是实时订单簿（报价/刷新/止损全看 best bid/ask），15m/1h/5m K 线无法跑通；K 线最小验证只能走 v2 控制器重写路线；且 56U 规模在 ETH 永续常 <0.05% 的盘口价差面前基本无操作空间。
7. **与 B1 是否不同**：是，机制/尺度/预测变量三者全不同（盘口价差与跨市场价差 vs 摆动带结构，秒级刷新 vs 15m K 线）；但它不改进 B1 的预测、而是另一条业务线，且做市在趋势市里的亏损源恰是 B1 想捕捉的方向——借鉴应限于执行概念（库存偏斜公式、刷新容忍度、扣费后盈利门、hanging orders）。

### 3.4 Freqtrade 主仓回测引擎横切结论（适用于 F1–F5；主仓 `4c3e1128`，2026-10-27）

- 手续费：计入，`freqtrade/optimize/backtesting.py:268-281` 默认取交易所 taker/maker 最差档，config 可指定 `--fee`，双边各计一次。
- 滑点：默认不计，`docs/backtesting.md:556-588` 明文“按请求价成交、无滑点”，入场按开盘价、出场信号按次根开盘价、止损恰好在止损价成交。
- 资金费：仅引擎级、有条件计入，`backtesting.py:417-425,1011-1026` 期货模式加载 `funding_rate`＋`mark` 数据并按 funding 周期计入 `trade.funding_fees`，但必须走期货模式且下载到 funding 数据；仅用现有 15m/1h/5m OHLCV 时资金费恒缺失。
- dry-run 与实盘：配置级区分，`docs/configuration.md` 中 dry-run 用模拟钱包（默认 1000）、只读交易所操作、默认库 `tradesv3.dryrun.sqlite`，实盘为 `tradesv3.sqlite` 且切换须换新库。
- 逐笔复核：机制上可复核（引擎导出含逐笔 trades 的 JSON，dry/live 落 sqlite，`docs/backtesting.md:552` 称同数据下可复现），但 5 策略在仓库内均无现成逐笔导出物，且回测假设（0 滑点、根内顺序）使“可复核”不等于“实盘可复现”。
- 合集目录：`user_data/strategies/` 顶层 27 个、`berlinguyinca/` 30 个、`futures/` 7 个、`lookahead_bias/` 4 个，`.py` 文件共 69 个（策略目录 68 个＋hyperopt 1 个）；仓库内无任何回测结果文件、无 config JSON、无逐笔记录；`futures/Readme.md` 仅给一份 Binance 期货 dry-run 配置（`trading_mode: futures`、`margin_mode: isolated`、`dry_run: true`，白名单含 `ETH/USDT:USDT`），无结果表。

### 3.5 F1 — Supertrend（趋势类，`user_data/strategies/Supertrend.py`，1h，仅多头）

1. **策略与经济逻辑**：三组不同乘数/周期 Supertrend 方向同时为 up 做多、同时为 down 平多，赚趋势方向持续的钱而非价差或资金费。
2. **完整可运行源码**：文件完整且语法通过，依赖 freqtrade、pandas、talib 与 technical 库，但文件自承 Supertrend 实现未经验证且本次未实装实跑。
3. **回测/前向/实盘**：三者皆无，唯一痕迹是 hyperopt 命令注释而无币种、终点、结果表与逐笔，故记。
4. **逐笔复核与成本**：仓库内无逐笔导出；费用可由引擎按最差档计入而滑点默认 0；现货向策略本身不建模资金费。
5. **未来函数/过拟合/幸存者偏差**：未见 `shift(-)` 或全帧归一化等直接未来函数，但 12 个 IntParameter 加 ROI 与 trailing 参数均由 hyperopt 在同一段 1h 数据上筛出，过拟合风险高且无样本外说明。
6. **Binance ETHUSDT 永续与现有数据**：仅用 OHLCV 故现有 1h K 线可算信号，但原策略仅多头且参数来自未知币种时段，移永续须走期货模式并补 mark 与 funding_rate 数据后冻结重测。
7. **与 B1 是否不同**：否——预测变量由结构带第 ≥2 次测试加信号 K 换成 ATR 带方向持续，时间尺度与 B1 趋势层重叠且收益机制同为趋势延续，属换指标变体而非新机制。
- 证据：`user_data/strategies/Supertrend.py`（头注释 caveat、L25 hyperopt 命令、L50-66 ROI/止损 −0.265/trailing/1h、L86-156 指标与入场/出场）。

### 3.6 F2 — BbandRsi（均值回归类，`user_data/strategies/berlinguyinca/BbandRsi.py`，1h，仅多头）

1. **策略与经济逻辑**：RSI(14)<30 且收盘跌破布林下轨（20，2σ）做多、RSI>70 平多，赚跌过头向中轨回归的钱且无趋势过滤故为逆势抄底。
2. **完整可运行源码**：文件极简完整且语法通过，依赖仅 talib 与主仓内置 qtpylib，是 5 个中依赖最干净的一个，但本次未实装实跑。
3. **回测/前向/实盘**：三者皆无，文件只有 Minimal ROI 与 Optimal stoploss 这类自述词而无任何数字、时段、币种与逐笔。
4. **逐笔复核与成本**：仓库内无逐笔；费用可由引擎计入而滑点默认 0；止损 −25% 加 ROI 10% 使结果易被扛单后回归主导；策略本身不建模资金费。
5. **未来函数/过拟合/幸存者偏差**：未见未来函数且参数极少固定故参数过拟合风险低，但无币种时段样本量故无法排除只报跑得好版本的幸存者偏差。
6. **Binance ETHUSDT 永续与现有数据**：仅用 OHLCV 且本身就是 1h，最易用现有 1h K 线做最小验证；但移永续须走期货模式补 funding 数据并重算杠杆下 −25% 止损的强平风险（原 −25% 不得直接沿用，见实验 E3）。
7. **与 B1 是否不同**：是——预测变量与方向逻辑均与 B1 相反（逆势回归对顺势延续），故机制上真正不同；但价值在作反向对照而非移植。
- 证据：`user_data/strategies/berlinguyinca/BbandRsi.py` 全文（L26 ROI 0.1、L31 止损 −0.25、L34 1h、L36-62 指标与入场/出场）。

### 3.7 F3 — CombinedBinHAndCluc（多指标组合类，`user_data/strategies/berlinguyinca/CombinedBinHAndCluc.py`，5m，仅多头）

1. **策略与经济逻辑**：BinHV45 的带宽、单根跌幅与下影线条件或 Cluc 的跌破 EMA50 加 0.985 倍 BB 下轨任一命中即做多、中轨出场，赚急跌后短线反弹的钱。
2. **完整可运行源码**：文件完整且语法通过，依赖 talib 与 qtpylib 而无 technical 库，但本次未实装实跑。
3. **回测/前向/实盘**：三者皆无，头注释只有基于回测与 2018 年 1 月单边市的说法而无时段、币种、样本量、结果表与逐笔，故记。
4. **逐笔复核与成本**：仓库内无逐笔；费用可由引擎计入而滑点默认 0 对 5m 急跌买入最偏乐观；且 `exit_profit_only=True` 使亏损单只靠 −5% 止损出场；策略本身不建模资金费。
5. **未来函数/过拟合/幸存者偏差**：未见直接未来函数，但两条各带硬编码阈值（0.008、0.0175、0.25、0.985、20×）的规则用 OR 拼接且腿 B 与 ClucMay72018 逐字重复，属多重检验加只报最优配置的高过拟合风险。
6. **Binance ETHUSDT 永续与现有数据**：仅用 OHLCV 且本身就是 5m，与现有 5m 数据最贴合；但移永续仍须期货模式加 mark 与 funding 数据并另算滑点与强平。
7. **与 B1 是否不同**：半不同——表面都碰带但 S3 无趋势过滤、无测试计数且为 5m 单根跌深信号，新增的单根形态强度（tail/bbdelta/closedelta）是 B1 没有的探索特征；但收益机制仍是碰带反弹，故只算半不同。
- 证据：`user_data/strategies/berlinguyinca/CombinedBinHAndCluc.py` 全文（头注释回测自述、L24-28 ROI/止损/5m、L29-31 `exit_profit_only`、L33-76 指标与双腿入场/中轨出场）。

### 3.8 F4 — TrendFollowingStrategy（期货趋势类，`user_data/strategies/futures/TrendFollowingStrategy.py`，5m，名义双向）

1. **策略与经济逻辑**：收盘上穿 EMA20 且 OBV 上升做多、下穿且 OBV 下降做空，赚趋势延续的钱并以 OBV 作量价确认。
2. **完整可运行源码**：只能算半个——文件语法通过且依赖仅 talib，但多处留“Add your…”占位注释，且本次未实装实跑。
3. **回测/前向/实盘**：三者皆无，futures Readme 只有 tested against config 的说法而无任何一策略的结果表，故记配置存在、结果不存在。
4. **逐笔复核与成本**：仓库内无逐笔；费用可由引擎计入而滑点默认 0；且因 `can_short` 缺失使空头资金费路径 as-shipped 根本走不到；策略本身亦不建模资金费。
5. **未来函数/过拟合/幸存者偏差**：入场未见未来函数，但全文无 `can_short` 使主仓默认 False 门控丢弃全部空头信号，且出场量价条件与入场自相矛盾、止损 −26.5% 疑似复制粘贴。
6. **Binance ETHUSDT 永续与现有数据**：仅用 OHLCV 故现有 5m K 线可算信号，但最小验证前必须补 `can_short=True`、套用期货 isolated 配置并下载 mark 与 funding 数据。
7. **与 B1 是否不同**：否——仍是趋势延续机制且无结构带、无测试计数、无信号 K，EMA 加 OBV 只是换指标换周期，按定义不算不同。
- 证据：`user_data/strategies/futures/TrendFollowingStrategy.py` 全文（L25 5m、L13-23 ROI/止损/trailing、L31-66 入场/出场、全文无 `can_short`、占位注释）；主仓 `freqtrade/strategy/interface.py:89,1385`（`can_short` 门控）；`user_data/strategies/futures/Readme.md`（期货配置）。

### 3.9 F5 — VolatilitySystem（期货波动突破类，`user_data/strategies/futures/VolatilitySystem.py`，1h，内含 3h 重采样，双向）

1. **策略与经济逻辑**：3h 合成 ATR(14)×2 作阈值，绝对收盘变化超前根 ATR 即顺方向入场、反向信号出场，赚大波动后方向延续的钱并含加仓与固定 2x 杠杆放大。
2. **完整可运行源码**：文件完整且语法通过，含 `can_short`、首仓 50%、加仓与 `leverage()` 2.0，是 5 个中期货机制最完整的；但重采样时序须实跑加 lookahead 验证且本次未实装实跑。
3. **回测/前向/实盘**：三者皆无，文件头只有源自 TradingView 脚本与杠杆越低越好的说法而无结果、时段、币种与逐笔；futures Readme 同样无结果表。
4. **逐笔复核与成本**：仓库内无逐笔；费用可由引擎计入而滑点默认 0 对突破根入场偏乐观；且 ROI 100 与止损 −1 使全部出场依赖反向信号；策略本身不建模资金费而须引擎期货模式补数据。
5. **未来函数/过拟合/幸存者偏差**：入场未见直接未来函数，但 3h 重采样加 `fill_na=True` 是否用了未完成部分 bar 无法凭代码排除，且加仓用 live 路径最后一根判断使回测与实盘行为不同，故须以 lookahead-analysis 为准而非肉眼清白。
6. **Binance ETHUSDT 永续与现有数据**：仅用 OHLCV 且 1h 可重采样出 3h，无订单簿/tick/链上依赖，是最贴合永续的一个；但最小验证前须走期货模式、下载 mark 与 funding 数据并测算小本金下 2x 加仓的强平价。
7. **与 B1 是否不同**：是——预测变量为 3h 绝对波动幅度、时间尺度为 3h 合成、收益机制为波动后动量延续加反向出场，均与 B1 不同，是 5 个中最接近真正不同的；但无止损加仓机制绝不能移植。
- 证据：`user_data/strategies/futures/VolatilitySystem.py` 全文（L28 `can_short`、L30-34 ROI 100/止损 −1、L37 1h、L59-70 3h 重采样＋ATR×2、L80-104 入场/反向出场、L108-155 加仓＋杠杆 2.0）；`user_data/strategies/futures/Readme.md`（期货配置）。

### 3.10 J0 — Jesse 框架本体（jesse-ai/jesse，`4292249a`，v3.5.3）

纠正：任务所说的 `jesse-ai/jesse-strategies` 仓库不存在（clone 返 `Repository not found`）；实际核查的是官方 `jesse-ai/example-strategies`，其策略头注释溯源到社区原仓 `gabrielweich/jesse-strategies`。以下 Jesse 策略均为“框架示例”，不是精选策略库。

1. **策略与经济逻辑**：无自带盈利策略，价值在引擎；另附蒙特卡洛与规则显著性检验方法论工具。
2. **完整可运行源码**：Python 源码完整，`requirements.txt` 含 `jesse-rust==1.3.1`、Ray、scikit-learn，PyPI 有包，但未实装验证，且完整 Dashboard 另需服务配置；另：**Jesse 开箱不能跑 Binance 实盘/paper**——`jesse/exchanges/` 仅含抽象基类与 `Sandbox`，live 驱动取自 `config['app']['live_drivers']`，默认值为空 `{}`。
3. **历史/前向/实盘**：三者皆无——框架方只有引擎测试与基准，无任何策略收益记录，不得混谈。
4. **逐笔复核与成本**：逐笔 ✅（`report.trades()`、CSV/JSON 导出）；手续费 ✅ 但为单一费率×名义值、不分 maker/taker；滑点 ❌（全仓检索不到 `slippage`，按订单价精确全量成交）；资金费 ❌（回测不扣，仅 `Position.funding_rate` 只读属性，无扣减路径）——永续策略用它回测必须外部另算资金费。
5. **未来函数/过拟合/幸存者偏差**：结构上无未来函数（周期收盘后执行）；但自带 Optuna 优化模式就是参数搜索工具，筛历史最优组合的风险全在使用者一侧；示例结果只报 BTC 单币种，存在报告偏差。
6. **Binance ETHUSDT 永续与现有数据**：行情导入支持 Binance 永续，但回测硬要求连续 1m K 线（`research/backtest.py` 校验），现有 15m/1h/5m 不能直接喂（当 1m 喂则时间轴错 15 倍，插值拼 1m 则伪造根内路径）；需另拉 1m K 线且重算口径本身就是定义变更。
7. **与 B1 是否不同**：不提供新预测变量，但能改进 B1 验证方法论——1m 步进＋根内 `split_candle` 止损触发恰好能分辨 B1 审计中的同根止损/出场先后问题，另有交易洗牌蒙特卡洛与 bootstrap 显著性检验。
- 证据：`jesse/modes/backtest_mode.py`（`_step_simulator`、`_simulate_price_change_effect:1630`、`_check_for_liquidations:1723`）、`jesse/services/order_service.py:execute_order`、`jesse/models/Position.py`、`jesse/config.py:111`、`jesse/services/api.py:initiate_driver`、`jesse/research/monte_carlo/`、`jesse/research/rule_significance_testing/`。

### 3.11 J1 — Jesse 示例 TurtleRules（海龟规则，`example-strategies/TurtleRules/__init__.py`）

1. **策略与经济逻辑**：趋势延续——Donchian 通道突破入场、2×ATR 止损、盈利方向每 0.5×ATR 加仓最多 4 层、Donchian 反向出场，另有“S1 上一单盈利则跳过”过滤器。
2. **完整可运行源码**：单文件完整可读，依赖仅 Jesse 指标（donchian/atr），但 `on_increased_position` 与 `update_position` 双通道加仓计数疑似重复累加（代码阅读所见，未实测，列为疑点）。
3. **历史/前向/实盘**：三者皆无——仓内该目录仅 `__init__.py`，无任何结果文件；Faith 2003 经典规则背书不是 ETH 永续证据。
4. **逐笔复核与成本**：无结果可复核；若跑 Jesse 回测则继承框架成本模型（手续费单费率 ✅、滑点 ❌、资金费 ❌）。
5. **未来函数/过拟合/幸存者偏差**：无未来函数（收盘根新高触发、按收盘价成交，根内冲回路径会被错过，属语义取舍）；参数约 8 个（20/55/10/20 周期、2N、4 层等）且无样本量可谈，属经典参数移植而非拟合实证。
6. **Binance ETHUSDT 永续与现有数据**：逻辑本身只用 K 线，移植到 ETHUSDT 需重写执行层进 Jesse（或 B1 引擎），且同样卡在 Jesse 的 1m 数据门槛上。
7. **与 B1 是否不同**：触发机制与时间尺度实质不同（Donchian 新高突破 vs B1 带同侧第 ≥2 次测试；原版日线级 vs B1 15m），出场也不同（Donchian 反向 vs EMA50），可作趋势触发器对照系；但收益机制同为趋势延续，不算新收益来源。
- 证据：`example-strategies/TurtleRules/__init__.py`（`entry_dc_period`、`atr_multiplier=2`、`maximum_pyramiding_levels=4`）。

### 3.12 J2 — Jesse 示例 RSI2（Connors 均值回归，`example-strategies/RSI2/`）

1. **策略与经济逻辑**：均值回归——价格在 SMA200 上方且 RSI(2)≤10 做多、反向做空，价格回到 SMA5 另一侧出场，全仓下单。
2. **完整可运行源码**：单文件完整可读，但**代码中没有任何止损设置**，均值回归失败时靠 SMA5 出场硬扛。
3. **历史/前向/实盘**：仅有历史回测粘贴，无前向、无实盘——`RSI2-results.txt` 为控制台输出粘贴（BTCUSDT 3h，2019-06-01→2020-06-01），无逐笔、无费率披露，记；但它是**负结果**，反而增加该仓报忧的可信度。
4. **逐笔复核与成本**：不可逐笔复核；文件内手续费合计 1772.67（116 单），滑点与资金费均未提及，永续口径下资金费缺失须单点指出。
5. **未来函数/过拟合/幸存者偏差**：无未来函数迹象；参数少（5/200/2/90/10），但只报 BTC 单币种单时段，且 116 单净负、胜率 63% 盈亏比仅 0.35，样本结论是“该实现不赚钱”而非“参数被筛过”。
6. **Binance ETHUSDT 永续与现有数据**：逻辑只用 K 线，可跑通最小验证（仍需过 Jesse 的 1m 门槛或移植执行层）；但无止损设计与现行纪律冲突，不可直接采用。
7. **与 B1 是否不同**：是——均值回归与 B1 趋势延续是不同收益机制，理论上有对照价值；但用户已于 2026-10-09 亲口搁置逆势系统，故借鉴仅限反例对照。
- 证据：`example-strategies/RSI2/__init__.py`（无 `stop_loss`）、`example-strategies/RSI2/RSI2-results.txt`（116 单，10000→5675.42，−43.3%，最大回撤 −50.11%）。

### 3.13 J3 — Jesse 示例 SMACrossover（50/200 均线交叉，`example-strategies/SMACrossover/`）

1. **策略与经济逻辑**：趋势延续的 hello world——SMA50 在 SMA200 上方持有多、反之持有空，交叉即反手，全仓，无止损无过滤。
2. **完整可运行源码**：单文件完整可读，依赖仅 Jesse 的 sma 指标。
3. **历史/前向/实盘**：仅有历史回测粘贴，无前向、无实盘——同窗口 BTCUSDT 3h 粘贴输出，记。
4. **逐笔复核与成本**：不可逐笔复核；文件内手续费合计 225.74，但费率与滑点、资金费均未披露。
5. **未来函数/过拟合/幸存者偏差**：无未来函数；但**仅 13 单**样本几乎无统计意义，窗口覆盖 BTC 牛市主升段且期末仍有 1 单浮亏 −1134.74，顺势持有即赚钱，无法证明交叉本身有预测力，兼有单币种报告偏差。
6. **Binance ETHUSDT 永续与现有数据**：逻辑只用 K 线，可移植，但同样受 Jesse 1m 门槛约束，且无止损不可直接用。
7. **与 B1 是否不同**：否——纯换均线，按任务定义不算不同（预测变量仍是趋势方向、收益机制同为趋势延续）。
- 证据：`example-strategies/SMACrossover/__init__.py`、`example-strategies/SMACrossover/SMACrossover-results.txt`（13 单，+84.71%，最大回撤 −53.7%）。

### 3.14 N0 — Nautilus Trader 框架本体（nautechsystems/nautilus_trader，`20280856`，develop，v2.0.0rc8 Beta）

1. **策略与经济逻辑**：无自带盈利策略，价值在引擎——确定性事件驱动架构＋显式费用/延迟/滑点/资金费模型＋L1/L2 订单簿撮合，属“研究到实盘同一语义”的方法论资产。
2. **完整可运行源码**：Python 轮子可装（无需 Rust 工具链），但 Python 须 ≥3.13 且 <3.15，当前为 2.0.0rc8 Beta（API 仍在变）；从源码构建才需 Rust 1.99.1；本核查未实装。
3. **历史/前向/实盘**：三者皆无——仓内只有引擎基准测试与集成测试（如 `crates/backtest/benches/`、`tests/integration/ema_cross.rs`），那是正确性测试，不是收益证据。
4. **逐笔复核与成本**：逐笔 ✅（fills/positions/account 报告＋确定性重跑）；手续费 ✅（MakerTaker 分开，且配置缺失不得静默零费）；滑点 ✅（概率滑一 tick 模型，但参数即假设）；资金费 ✅ 但有条件（引擎有 `FundingRate` 结算模块，却须另行馈入资金费率序列——现有数据下仍缺，模块存在 ≠ 本次可用）；延迟 ✅（insert/update/delete 分别建模）。
5. **未来函数/过拟合/幸存者偏差**：引擎层面事件时间戳严格排序，无系统性未来函数；风险在使用者一侧（fill/latency 参数、默认关闭的 `queue_position`/`liquidity_consumption` 等开关若不逐项声明，等于自选乐观程度）。
6. **Binance ETHUSDT 永续与现有数据**：适配器覆盖 USD-M 期货（fapi.binance.com），但认证仅 Ed25519；**15m Bar 可跑通最小验证**（`process_bar` 按 OHLC 生成合成 tick，仅 L1＋`bar_execution=true`），但保真度损失六项：根内止损/入场先后顺序靠合成顺序假设（B1 的 T2 同根问题无法被解决、只能被假设掉）、无线上订单簿则限价成交概率全靠假设参数、无资金费序列则结算模块空转、无 tick 则延迟只能加固定/抖动延迟、市价成交价来自合成 tick 非真实盘口、`Mark` 价格 Bar 明确不支持 Bar 执行。
7. **与 B1 是否不同**：不提供新预测变量，但能把 B1 验证从“收盘价模拟”升级为“事件模拟”——这是 Jesse 之上再高一档的方法论标杆；代价是其全部高保真能力都锚定在 TAE 目前没有的数据上，当下只能兑现 Bar 级。
- 证据：`crates/backtest/src/config.rs`（fee_model 必显式、`bar_execution` 默认 true、`bar_adaptive_high_low_ordering`）、`crates/execution/src/models/fee.rs`、`fill.rs`、`latency.rs`、`crates/execution/src/matching_engine/mod.rs:1971 process_bar`、`crates/backtest/src/engine.rs:1627/1885`（资金费结算）、`crates/adapters/binance/README.md`（USD-M＋Ed25519）、`python/pyproject.toml`（2.0.0rc8，Python ≥3.13,<3.15）。

### 3.15 N1 — Nautilus 示例 EMACross（`docs/tutorials/ema_cross.py`）

1. **策略与经济逻辑**：趋势延续——快 EMA ≥ 慢 EMA 做多、反之做空，反手时先平仓再开反向；市价单，无止损、无止盈、无仓位管理、无过滤。
2. **完整可运行源码**：完整可读（`docs/tutorials/ema_cross.py`＋`examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py`），是 Nautilus 策略写法（`register_indicator_for_bars`、`on_bar`）的标准范式。
3. **历史/前向/实盘**：三者皆无——示例用 `TestDataProvider` 的测试成交 tick CSV 与 250-TICK 聚合 Bar、演示量级账户（1_000_000 USDT＋10 ETH），不是真实历史回测报告。
4. **逐笔复核与成本**：示例演示了 fills/positions/account 三份报告的生成，但无真实结果可复核；示例费率 MakerTaker 各 0.0001，滑点/延迟均未配置（即默认），资金费无数据。
5. **未来函数/过拟合/幸存者偏差**：`on_bar` 收盘后执行，无未来函数；参数仅 10/20 两根 EMA，谈不上拟合，但也谈不上证据——演示代码的默认参数即全部“证据”。
6. **Binance ETHUSDT 永续与现有数据**：示例本身就是 ETHUSDT 但用的是 tick 数据；改用现有 15m Bar 可跑通（BarType 改 15m 即可），但会跌回 N0 第 6 点的 Bar 级保真度，且策略无止损，与 B1 的“带沿外 1×ATR 永不移动止损”完全不兼容，须重写执行层。
7. **与 B1 是否不同**：否——换均线、换 Bar 类型，不算不同；价值仅在展示 Nautilus 策略写法，不在信号本身。
- 证据：`docs/tutorials/ema_cross.py`（`on_bar`、`close_all_positions`）、`examples/backtest/crypto_ema_cross_ethusdt_trade_ticks.py`（250-TICK Bar、测试 tick CSV）。

### 3.16 N2 — Nautilus 示例 GridMarketMaker（网格做市，`examples/backtest/fx_market_maker_gbpusd_bars.py`）

1. **策略与经济逻辑**：做市价差——3 层网格双边挂单赚买卖价差与均值回归，是与 B1 趋势延续不同的收益机制，理论上算“不同”。
2. **完整可运行源码**：完整可读（`add_builtin_strategy("GridMarketMaker", …)`），但属于框架内置演示策略，参数（层数、单量、最大仓位）即演示假设。
3. **历史/前向/实盘**：三者皆无——数据是 2012 年 FXCM GBPUSD m1 bid/ask 测试数据，成交用 `ProbabilisticFillModel(0.2/0.5/seed 42)`，无任何收益输出。
4. **逐笔复核与成本**：无结果可复核；示例费率 MakerTaker 各 0.00002，滑点与成交概率是 0.2/0.5 的假设参数，换参数即换结论，资金费与库存成本均未建模。
5. **未来函数/过拟合/幸存者偏差**：无未来函数；但 2012 年外汇测试数据＋假设成交模型＋零库存管理，离 ETH 永续做市的真实风险（单边趋势库存、资金费不对称、插针爆仓）极远，属机制演示而非证据。
6. **Binance ETHUSDT 永续与现有数据**：现有条件下**不可用**——做市需要订单簿/报价数据（TAE 没有），且 ETH 永续做市还需库存上限、资金费与强平管理，示例均未提供，须全部重写。
7. **与 B1 是否不同**：机制上是（做市价差 vs 趋势延续），但在现有数据下无法验证，借鉴价值仅限“机制对照”——即提醒 B1 之外还存在一类收益来源，而不是可落地的候选。
- 证据：`examples/backtest/fx_market_maker_gbpusd_bars.py`（`ProbabilisticFillModel`、`GridMarketMakerConfig`、FXCM 2012 数据）；另备查 `examples/backtest/crypto_orderbook_imbalance.py`（需 L2 订单簿增量，现有数据下同样不可用）。

### 3.17 O — OctoBot（Drakkar-Software/OctoBot，`c45fdc2c`，最后提交 2026-10-07，未归档，在维护）

1. **策略与经济逻辑**：框架＋多模式，无“主策略”；TA 评估器是趋势/动量投票，DipAnalyser 是抄底均值回归，网格/做市/套利是价差机制。证据：`OctoBot/packages/tentacles/Evaluator/TA/trend_evaluator/trend.py`（SuperTrend factor=3/length=10）、`Evaluator/Strategies/dip_analyser_strategy_evaluator/dip_analyser_strategy.py`、`Trading/Mode/{grid_trading_mode,dca_trading_mode,arbitrage_trading_mode,market_making_trading_mode}/`。
2. **完整可运行源码**：是，Python 3.13（`setup.py:86`）、`start.py`＋Docker，但 6000+ 文件 monorepo 很重，本次未实装，记“代码完整、未实装”。
3. **回测/前向/实盘**：三者皆无，仓库内只有回测能力，无任何策略成绩文件。证据：`octobot/backtesting/independent_backtesting.py`（`get_dict_formatted_report()`、逐笔 trade history 日志）。
4. **逐笔复核与成本**：逐笔 ✓；手续费 ✓（`packages/trading/octobot_trading/exchanges/connectors/simulator/exchange_simulator_connector.py:233 get_fees()`，maker/taker）；资金费 ✓（`personal_data/positions/channel/positions_updater_simulator.py:92 handle_funding_rate()`）；滑点 △ 未核实。
5. **未来函数/过拟合/幸存者偏差**：高风险点明确——自带官方参数优化器 `octobot/strategy_optimizer/`（StrategyOptimizer/StrategyDesignOptimizer），按铁律筛历史最优即属过拟合，只能探索。
6. **Binance ETHUSDT 永续与现有数据**：四者中适用性最好，期货符号体系已通（`packages/trading/tests_additional/real_exchanges/test_binance_futures.py`，`BTC/USDT:USDT`、含 15m/1h 与止损单类型）；但 B1 的关键带＋信号 K 逻辑需自己写成 tentacle 重写执行层；不依赖订单簿/tick/链上。
7. **与 B1 是否不同**：预测变量上否（TA 评估器只是换指标投票）；模式层的网格/做市/套利机制不同，但那是执行框架而非可验证策略，且套利/做市需订单簿与多所执行，与“仅 K 线”条件不匹配。

### 3.18 G — Gekko（askmike/gekko，`ff5698f1`，最后提交 2020-02-16，GitHub 已归档，README 首行声明不再维护）

1. **策略与经济逻辑**：全部是单指标越阈值趋势跟随（MACD/RSI/DEMA 等），无止损/止盈/仓位管理，无结构带、无回踩。证据：`gekko/strategies/{MACD,RSI,DEMA}.js`。
2. **完整可运行源码**：名义完整、实际半个——`package.json` engines 要求 Node ≥8.11.2，依赖锁定 2018–2020 年代（koa 1.x、sqlite3 ^4.0.6）；本机 Node v24.22.1 下 `node --check` 仅语法通过，`require(core/log.js)` 即报缺 `moment`，sqlite3 v4 原生绑定基本无法在 Node 24 上装上。
3. **回测/前向/实盘**：仅有回测能力＋逐笔导出，仓库内无任何成绩/前向/实盘记录。证据：`web/routes/backtest.js`、`plugins/backtestResultExporter.js`、`plugins/performanceAnalyzer/logger.js`（roundtrip 表＋Sharpe）。
4. **逐笔复核与成本**：逐笔 ✓；手续费 ✓；滑点 ✓（`sample-config.js:70-75`，feeMaker 0.15 / feeTaker 0.25 / slippage 0.05，`plugins/paperTrader/paperTrader.js` 扣费）；资金费 ✗（现货无此概念，永续单点缺）。
5. **未来函数/过拟合/幸存者偏差**：策略只用已收 K 线，无明显未来函数；但阈值＋persistence 多参数且社区传统就是调参找最优，属典型过拟合温床，无跨币种/时段完整报告。
6. **Binance ETHUSDT 永续与现有数据**：✗ 硬伤核实为真——`exchange/wrappers/binance.js` 用 2018 年代现货 `BinanceRest`（api.binance.com），`binance-markets.json` 为 2018 现货币对快照，全仓 grep `fapi|futures|margin|leverage` 在 binance wrapper 与 gekkoBroker 中 0 命中；现货 short 只是卖出持有，需重写执行层，现有永续 K 线不能直喂。
7. **与 B1 是否不同**：否，换指标、换阈值、换周期而已，无新预测变量、无新收益机制。

### 3.19 Z — Zenbot（DeviaVir/zenbot，`52872fb4`，最后提交 2022-02-14，GitHub 已归档，README 首行声明不再积极维护）

1. **策略与经济逻辑**：趋势跟随为主（EMA 斜率/MACD 直方图/SAR 翻转），点缀均值回归/波动率策略，无做市/套利/资金费机制。证据：`zenbot/extensions/strategies/{trend_ema,macd,sar}/strategy.js`。
2. **完整可运行源码**：是（策略＋模拟器＋实盘执行俱全），但已归档、依赖停在 2022 年（ccxt ^1.72.64、Node ≥10），当前环境未验证可跑。
3. **回测/前向/实盘**：仅模拟能力＋sim 报告（含 buy_hold 对照），仓库内无策略成绩/前向/实盘记录；README 反而诚实写明“默认参数常跑输 buy-hold”。证据：`zenbot/commands/sim.js:168-180`。
4. **逐笔复核与成本**：逐笔 ✓（my_trades 含 fee/slippage）；手续费 ✓（`extensions/exchanges/binance/exchange.js:53-54`，maker/taker 均为 0.1，但这是 2022 年快照，不得当现行费率）；滑点 ✓（`lib/engine.js`，avg/markdown/markup/max 四项齐全）；资金费 ✗（现货无，永续单点缺）。
5. **未来函数/过拟合/幸存者偏差**：最大红灯是官方遗传调参 `zenbot/scripts/genetic_backtester/darwin.js`，README 原话“run simulations and find the optimal parameters”——按铁律这正是禁止的历史最优筛选；策略本身无明显未来函数，但单币种报告使幸存者偏差未排除。
6. **Binance ETHUSDT 永续与现有数据**：✗ 需改造——现货 buy/sell only、无空头/杠杆/资金费；注意同名不同物：`extensions/exchanges/binance/products.json`（1501 条）里的 `ETHUSDT` 是现货 ETH/USDT，不是永续；且 sim 依赖 backfill 逐笔成交重建 period（`lib/engine.js:142-165`），现有纯 K 线需转换才能喂入。
7. **与 B1 是否不同**：预测变量上否（EMA/MACD/SAR 均属 B1 已覆盖的趋势族）；唯一可借鉴差异在机制层：`trend_ema` 的 neutral_rate='auto'（以 trend_ema_rate 的 stddev 作自适应阈值）与百分比止损/移动止盈的出场对照——但按铁律也只能算探索假设。
- 证据：`zenbot/extensions/strategies/trend_ema/strategy.js`（neutral_rate auto）。

### 3.20 D — QuantDinger（brokermr810/QuantDinger，`8b2af21c`，最后提交 2026-10-28，在维护，VERSION 5.6.1；官网自称 v5.7.1，口径不一致）

**身份 caveat（引用时必须附带）**：抖音视频未提供给本次核查，无法确认视频里的“量化丁格”就是 QuantDinger；仅凭英文名音近＋搜索唯一命中列为“最可能对应物”，同一性记为。本次结论只凭代码证据，不沿用用户此前“不建议实盘”的结论。

1. **策略与经济逻辑**：平台无自带经济逻辑；附带示例仅为双均线趋势（SPY long-only）与美股 MA 金叉，属最普通的趋势参数族。证据：`QuantDinger/docs/examples/strategy_v2_dual_ema_long.py`、`docs/strategies/sp500_profitable_top50.py`。
2. **完整可运行源码**：平台层面是（Docker Compose 全栈：Python 3.12、PostgreSQL 18、Redis 8、Celery），策略层面只有模板/示例，无“开箱策略”。
3. **回测/前向/实盘**：三者皆无可核记录，只有回测能力；官网/视频晒单均为。证据：`backend_api_python/app/services/backtest/`、`backtest_jobs.py:66-67`。
4. **逐笔复核与成本**：逐笔 △（订单网关存在，但未定位到逐笔导出格式）；手续费 ✓、滑点 ✓（`backtest_execution.py` 的 commission/slippage 输入归一化）；资金费 △（`strategy_daily_pnl.py:209-211` 的 `qd_strategy_funding_fees` 表是实盘账目，回测模拟未核实）；另有陷阱：`backtest_presets.py` 并存 LIVE_ALIGNED 预设与零成本预设，不仔细看会拿到虚高回测。
5. **未来函数/过拟合/幸存者偏差**：防未来函数意识本批最好（warmup、bar-phase 排序测试 `tests/test_strategy_v2_bar_phase_ordering.py`）；sp500 示例注释明确要求 point-in-time 成分，是本批唯一正面处理幸存者偏差的代码；但平台另有 `strategy_evolution/` 参数空间，同样存在历史筛选风险。
6. **Binance ETHUSDT 永续与现有数据**：△ 未核实——官网示例符号 `Crypto:BTC/USDT@okx:swap` 表明符号体系有 swap 概念，但后端 grep `ccxt` 0 命中，也未找到 Binance 永续策略合约示例或执行路径，不可直接宣称支持。
7. **与 B1 是否不同**：否，示例策略与 B1 同属趋势族且更简单；价值在工程（策略契约、bar-phase 排序、point-in-time 注释、资金费账目），不在预测变量或收益机制。

## 4. 两张排行榜

### 4.1 A 榜：收益证据可信度（最高分只有 2 分——这是本研究最重要的发现）

| 名次 | 候选 | A 分 | 理由 |
|---|---|---|---|
| 并列第 1 | Jesse 框架（J0）、Nautilus 框架（N0） | 2 | 引擎输出可逐笔审计、可确定性重跑，但无任何策略收益证据；框架基准 ≠ 收益证据，故封顶 2 分 |
| 并列第 3（16 个） | T1、T2、H、F1、F2、F3、F5、J1、J2、J3、N1、N2、O、G、Z、D | 1 | 仅自述数字、控制台粘贴输出、相对数、付费墙后内容或空壳 live 页；无一逐笔可复核 |
| 垫底 | F4 TrendFollowingStrategy | 0 | 模板占位注释＋`can_short` 缺失，as-shipped 跑不出空头；零绩效记录 |

**A 榜的诚实注记**：并列第 3 的 16 个 1 分内部仍有披露质量差异——J2 RSI2 的负结果粘贴（116 单、−43.3%）比纯自述相对数更诚实，但“诚实披露”不等于“可复核证据”，故不升分。任何把 1 分组里的数字当作“某策略年化 XX%”引用的写法，都是对本榜的误读。

### 4.2 B 榜：TAE 研究借鉴价值

| 名次 | 候选 | B 分 | 借鉴点（均为探索，非结论） |
|---|---|---|---|
| 第 1 | Nautilus 框架（N0） | 5 | 方法论标杆：确定性事件引擎＋显式费用/延迟/滑点模型；当下只能兑现 Bar 级，5 分是标杆分而非即时收益分 |
| 第 2 | Jesse 框架（J0） | 4 | 立即可用：蒙特卡洛交易顺序洗牌＋规则显著性检验，直接服务“入场是否真有优势”这一待决问题，且不依赖新数据 |
| 并列第 3（8 个） | T2 hassannazir、H Hummingbot、F2 BbandRsi、F3 CombinedBinHAndCluc、F5 VolatilitySystem、O OctoBot、J1 TurtleRules、N2 GridMarketMaker | 3 | 依次为：极简慢速基准／做市执行概念／均值回归反向对照／单根形态强度候选特征／3h 波动突破第二类事件／工程参考／Donchian 触发器对照／做市机制对照 |
| 并列第 4（6 个） | T1 darkvolg、F1 Supertrend、Z Zenbot、D QuantDinger、J2 RSI2、N1 EMACross | 2 | 依次为：出场工程对照（ROI/trailing/时间止损）／ATR 带方向对照／波动率自适应阈值＋成本建模／bar-phase 排序与 point-in-time 工程／均值回归反例／Nautilus 写法范本 |
| 并列第 5（3 个） | F4 TrendFollowingStrategy、G Gekko、J3 SMACrossover | 1 | 依次为：OBV 量价确认单点／报告格式参考／无（换均线而已） |

### 4.3 两榜分歧原因（四条）

1. **框架与策略的错位**：A 榜问“赚过钱的证据”，B 榜问“对研究有没有用”。框架类（Jesse、Nautilus）本身不带盈利策略，A 分天然封顶（2 分），却在 B 榜登顶——因为 TAE 当前最缺的不是新信号，而是更硬的验证方法（入场优势检验、同根顺序、显著性）。
2. **策略类在 A 榜全军覆没**：19 个候选里 16 个得 1 分、1 个得 0 分。开源策略仓的通病是只给代码不给可核对的成绩：回测结果文件、逐笔导出、第三方痕迹三者全缺是常态，不是例外。
3. **B 榜高分者多是“对照组”而非“替代品”**：BbandRsi、hassannazir 的价值恰恰在于作 B1 的反面镜子（逆势回归、日线 regime 基准），而不是替代 B1；VolatilitySystem、Combined 的价值在“候选事件/特征”，不是“可移植策略”。
4. **机制真正不同者验证不了**：Hummingbot、GridMarketMaker 的做市/价差机制与 B1 实质不同，但需要订单簿与报价数据——现有数据条件下 B 分给的是机制对照价值，不是落地价值；一旦误读为“可借鉴策略”，就会掉进无数据验证的陷阱。

### 4.4 前三名取法（用于实验方案）

按 B 榜取前二单列（N0、J0）；第三名从 B=3 并列组中按三条 tie-break 规则选出：**现有数据可验证＋与 B1 待决问题最直接＋定义最干净**。符合三条的是 **F2 BbandRsi**（仅用 1h K 线、参数极少、无未来函数、与 B1 方向逻辑相反，是最干净的反向对照）。A＋B 综合分前二同样是 N0（7 分）、J0（6 分），第三名综合也是并列，故最终以前述 tie-break 定 F2。其余 B=3 组成员列为候补：hassannazir 作慢速基准、VolatilitySystem 作第二类事件、Combined 形态强度作候选特征、Hummingbot/GridMarketMaker 作机制对照、OctoBot/TurtleRules 作工程与触发器对照；若用户想换第三名，可替换，实验方案结构不变。

前三实验方案全文见 `top3-experiments.md`（E1 Nautilus Bar 级事件模拟重跑 B1、E2 Jesse 蒙特卡洛＋显著性检验、E3 BbandRsi 均值回归反向对照），三者均只待批准、不执行。

## 5. 排除清单（被排除的项目＋原因）

- **抖音“量化丁格”视频/账号本身**：无代码、无仓库链接、无可核策略文件——纯营销载体，不是源码证据；本次未拿到视频 ID，无法进一步溯源。
- **除 QuantDinger 外的其他“丁格量化/量化丁格”GitHub 仓库**：browser.search（含 site:github.com 限定）未发现第二个同名中文量化仓库——空集，不编造。
- **QuantDinger 官网、AI 应用页、AWS Marketplace 上架页**：宣传与托管页，无策略源码与可核成绩，仅作身份旁证。
- **各项目官网、Medium、第三方评测文**：自述/转载，无逐笔时间戳痕迹；本次仅用其定位仓库名。
- **TrendRider 同名其他项目**：看板/空仓/美股/MT5/生成 app 等（精确名搜索 12 仓中除 T1、T2 外的其余），无完整可运行策略源码或与交易策略无关。
- **`jesse-ai/jesse-strategies`**：仓库不存在（clone 返 `Repository not found`）；实际核查对象为官方 `jesse-ai/example-strategies`。
- **Freqtrade 合集内模板占位策略**：不单独成候选（F4 已体现该类问题：占位注释＋`can_short` 缺失）。
- **未排除项说明**：Gekko 与 Zenbot 虽已归档、依赖过期，但确有完整可运行策略源码，故列为候选而非排除；归档状态已在评分中扣分。

## 6. 核实不了 / 需要用户拍板的部分

1. **未实际安装运行任何项目**：4 路核查均为源码级（语法编译＋依赖＋接口版本）；“能跑”结论未经实装验证。是否实际安装 Jesse 或 Nautilus 做一次最小可运行验证，须用户另行批准（工时见实验方案）。
2. **trendrider.net/live 渲染后内容**：子代理无 live-browser 能力，仅做文本抓取（JS 页只返回 “Loading live stats…”）；如需核实该页渲染后的实际数据，须由有 live-browser 能力的 parent/root 另行委派，本次未声称访问过该页实际数据。
3. **OctoBot 滑点、QuantDinger 逐笔导出格式与 Binance 永续执行路径**：三项记，不作有/无断言。
4. **2022 年以前的费率快照**（如 Zenbot maker/taker 均为 0.1）不得当作现行费率使用。
5. **前三实验方案的待定项**：E1 的滑点模型参数与资金费缺失声明、E2 与 E 实验 family 的多重性关系、E3 的永续止损数值（原 −25% 不得直接沿用）——均须冻结日定，见 `top3-experiments.md`。
6. **B=3 并列组的第三名替换权**：若用户认为慢速基准（T2）或第二类事件（F5）比反向对照（F2）更优先，可替换 E3，结构不变。
7. **本报告未推 GitHub**：交付物只在本地 `tae-b1/oss-quant/`，待 parent 验过后才推；B1、扫描器、执行器、前向观察系统一律未动。

## 7. 总结论（一句话）

开源世界里**没有一个现成策略能拿着可逐笔复核的证据来回答 B1 的问题**——19 个候选的收益证据最高分只有 2 分（且那是两个不带盈利策略的框架）；真正值得拿走的不是策略，而是三样东西：**Nautilus 的事件引擎方法论（标杆）、Jesse 的蒙特卡洛＋显著性检验（立即可用）、以及 BbandRsi 这类干净的反向对照（照出 B1 的边界）**；其余一切都只是探索假设，须冻结后前向验证。
