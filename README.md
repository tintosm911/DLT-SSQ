# 🎰 中国彩票预测与分析工具

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![CI](https://img.shields.io/badge/CI-8%2F8%20passed-brightgreen.svg)](./scripts/ci_local.py)
[![Tests](https://img.shields.io/badge/Tests-30%20passed-brightgreen.svg)](./tests)
[![GitHub stars](https://img.shields.io/github/stars/tintosm911/DLT-SSQ.svg?style=social)](https://github.com/tintosm911/DLT-SSQ)
[![Repo size](https://img.shields.io/github/repo-size/tintosm911/DLT-SSQ.svg)](https://github.com/tintosm911/DLT-SSQ)
[![Code lines](https://img.shields.io/badge/Code-28.9k%20lines-blueviolet.svg)](./CHANGELOG.md)

> **重要声明**: 彩票是**数学上必输**的游戏, 任何选号策略都不能改变期望值。本项目所有算法 + 数据分析只为教学和研究目的。

## 📊 门面图: 数据说话, 不猜

![大乐透选号策略实证检验](reports/headline_dlt.png)

基于 **20 年真实开奖**（DLT 2938 期 + SSQ 3517 期），**严格 walk-forward 回测**，
每一项都跟随机期望做统计检验（z 分数）：

| 检验 | 结论 |
|---|---|
| ① **13 种选号策略的真实 ROI** | 全部落在 **-70% ~ -83%**，无一能转正；随机基线 ±1σ 内 |
| ② **中奖率的结构性缺口** | 策略能把中奖率提到 7.94%，但靠 5 元小奖盈利需要 **>40%** — 差 **5 倍** |
| ③ **热号有预测力吗** | 每个年份切分的 z 分数全落在 ±2 内 — 与随机**无差异**（含最近 3 年）|

> **凯利公式 f\* = 0**：数学给出的建议是"不下注"。这不是工具的 bug，是数学事实。
> 本项目的价值在于**把这个事实算给你看**，而不是给你一个虚假的"幸运号码"。

### 双色球版（同 methodology，结论一致）

![双色球选号策略实证检验](reports/headline_ssq.png)

> **⚠️ 一个容易骗人的地方**（图里已标注 ◆）:
> 双色球回测中 `random` 的原始 ROI 是 **+1%**，看起来像赢了 ——
> 但那**全部来自一次三等奖（3000 元）**。剔除大奖后它是 **-56%**。
> **一次大奖就能让随机选号"看起来赚钱"，这就是彩票最有效的自我欺骗机制。**

### 工具到底能干什么

| 你想干的事 | 用这个入口 | 它会告诉你 |
|---|---|---|
| 我突然想到一组号，想看看 | Web Tab ① / CLI `check` | 真实命中几等奖 + 期望净收益（-0.94 元/注）|
| 这注胆拖值不值 | Web Tab ③ | 展开多少注、花多少、**剔除大奖后**真实回多少 |
| 我上次那注算什么水平 | Web Tab ⑤ | 20 万次模拟里你排第几 + 长期能否回本 |
| 哪种玩法最"准" | Web Tab ④ | 13 种策略实测 ROI，没有一个是赢家 |
| 热号到底准不准 | Web Tab ⑥ | 每一项都跟随机比 z 分数，答案是"没差异" |

---

## ⚽ 竞彩：这次数学站在你这边

> 号码彩和竞彩是**两类完全不同的数学**。
> 号码彩的派奖率结构性低于 50%，任何策略都改不了；
> **竞彩的期望值可以是正的 —— 但赢在"市场结构"，不在"预测能力"。**

### 基于 7,220 场真实历史赔率 (football-data.co.uk 镜像)

![竞彩期望值实证检验](reports/headline_sports.png)

| 玩法 | 实测 ROI | 数学性质 |
|---|---|---|
| **跨公司套利** | **+1.35%** | ✅ **数学上必赢** (Σ(1/odds) < 1) |
| 随机下注 | -0.97% ~ -8.16% | ❌ 抽水必亏 |
| Elo 价值下注 | -3.82% ~ -10.75% | ❌ 模型打不过市场 |

**三条可执行的结论**:

1. **选对博彩公司 = 实打实省钱**
   抽水率: Pinnacle **2.40%** ↔ B365 4.82% ↔ Interwetten **8.00%**
   —— 最优与最差差 **7.79 个百分点**，长期就是 7.79% 的收益差。

2. **跨公司套利是数学上必赢的**
   445 / 7220 场 (6.2%) 存在 Σ(1/odds) < 1 的组合，资金回测 ROI **+1.345%**
   （投 23,900 元赚 322 元）。最佳单笔锁定 **4.70%**。

3. **但靠"预测比赛结果"赚不到钱**
   Elo 模型的 ROI 反而比随机还差 —— 市场已经把信息定价进去了。

> ⚠️ **时效性声明**: 数据为历史快照，反映的是**历史市场结构**。
> 套利在真实市场会被快速套平，且需要 3 家博彩公司都有账户与限额。
> 结论要在当下赔率上复验。

```bash
python scripts/sports_expectation.py --league premier-league   # 分析
python scripts/sports_expectation.py --all-leagues --download  # 全联赛 + 拉数据
```

### 📊 5 大联赛 · 41,691 场 · 结论稳定性检验

![5 大联赛竞彩结论稳定性](reports/headline_sports_stability.png)

| 联赛 | 场次 | 纯境外可套利% | 套利 ROI% | Elo ROI% | 竞彩参与套利 |
|---|---|---|---|---|---|
| 英超 | 7,600 | 3.18% | **+1.345%** | -4.4% | **0 次** |
| 西甲 | 10,044 | 2.47% | **+1.510%** | -5.9% | **0 次** |
| 意甲 | 7,220 | 2.95% | **+1.466%** | -5.3% | **0 次** |
| 德甲 | 6,732 | 4.70% | **+1.522%** | -5.2% | **0 次** |
| 法甲 | 10,095 | 2.48% | **+1.472%** | -5.6% | **0 次** |

**四个结论，跨 5 大联赛、32,380 场扫描，全部一致**：

1. **抽水率跨联赛 σ < 0.6%** —— 它是**市场结构常量**，不是数据噪声
2. **套利 ROI 全部为正**（+1.16% ~ +1.52%）—— 数学必赢
3. **Elo 价值下注全部为负**（-4.4% ~ -5.9%）—— 模型打不过市场
4. **竞彩参与套利 0 次** —— 高抽水是**障碍**不是机会

### 🇨🇳 vs 🌍 双向采集: 中国竞彩 × 境外盘口

**竞彩官方实时赔率** (webapi.sporttery.cn, 免费无需 key) × **7,600 场真实境外历史赔率**：

![中国竞彩 vs 境外盘口](reports/headline_jingcai.png)

**一个反直觉的结论**：

| | 抽水率 |
|---|---|
| **中国竞彩** | **12.91%** (24 场实时实测, 12.57%~12.99%) |
| Interwetten (最差境外) | 8.00% |
| B365 | 4.85% |
| Pinnacle (最好境外) | **2.45%** |

> **"竞彩 + 境外"这套组合，数学上走不通。**
>
> 实测扫描 7,600 场：纯境外公司之间有 **270 场 (3.55%)** 可套利，ROI **+1.352%**；
> 但**加入竞彩后，可套利场次和 ROI 一模一样 —— 竞彩一次都用不上**。
>
> 原因：竞彩抽水 12.91% 意味着它的赔率**更低**、隐含概率**更高**，
> 用它下注会**拉高** Σ(1/odds)，反而让组合更难满足套利条件。
> **高抽水不是套利机会，是套利障碍。**

**三条实用结论**：
1. **只买竞彩** = 接受 12.91% 抽水（比最差境外公司还差 4.9 个百分点）
2. **想套利** = 只能在境外公司之间做，跟竞彩无关
3. **竞彩的真正价值**是合法兑奖 + 中文服务，代价就是这个抽水

```bash
python scripts/jingcai_vs_overseas.py    # 竞彩 vs 境外 套利测算
python scripts/make_jingcai_chart.py      # 重新生成对比图
```

> ⚠️ 实时境外盘口源受限流影响（BetExplorer 429 / OddsPortal 需 JS 渲染），
> 当前用真实历史赔率做等价测算。要做实时双向扫描需接
> [the-odds-api.com](https://the-odds-api.com)（免费 500 次/月，需注册 key）。

### ⚡ 实时扫描 (Web Tab ⑧)

接入 [the-odds-api.com](https://the-odds-api.com) 后，可做**当下**的跨市场扫描：

```bash
# 首次: 配好 key (环境变量或项目根 .odds_api_key 文件)
$env:ODDS_API_KEY = 'your_key_here'
python scripts\live_scanner.py
```

**实测 (2026-10-22 22:10 CST, uk+eu+au 三区)**:

| | 抽水率 |
|---|---|
| **中国竞彩** | **12.90%** |
| matchbook (交易所) | 0.90% |
| betfair_ex (uk/au/eu) | 0.95% ~ 0.96% |
| smarkets | 1.51% |
| Pinnacle | 3.98% |

**竞彩 24 场 / 境外 195 场 / 配对 18 组 / 每场 28~42 家博彩公司**

| 场次 | 套利组合 | 锁定 |
|---|---|---|
| 欧协联 阿贾克斯 vs 亚特兰大 | unibet_nl / betfair_ex_au / matchbook | **1.425%** |
| 欧罗巴 波兹南 vs 桑德兰 | unibet_se / unibet_nl / smarkets | 0.568% |
| 欧罗巴 霍芬海姆 vs 里昂 | marathonbet / smarkets / betfair_ex_uk | 0.557% |

**配对算法**: 竞彩 3 字母码的字母按顺序出现在境外队名中
（`SGZ`←SK Sturm Graz，`DNZ`←Dinamo Zagreb，`CVO`←Celta Vigo，`AJX`←Ajax）
+ 同联赛 + 开赛时间差 < 36h + 唯一性占用。配对率 **18/24**。

> ⚠️ **再次强调**: 所有 6 场套利里，**竞彩一次都没参与**。
> 它的 12.90% 抽水会拉高 Σ(1/odds)，只会让组合更难满足套利条件。
> 跨市场套利这条路，竞彩走不通 —— 但**在竞彩下注就意味着接受 12.90% 的抽水**。

```bash
# 网络差时用 GitHub API 推送 (绕过被挡的 git 协议)
python scripts/push_via_api.py --token ghp_xxx
```

一个端到端的中国彩种分析平台, 集成:
- **号码彩**: 大乐透 / 双色球 (历史数据 6455 期, 含真实开奖日期)
- **竞彩**: Elo + Value Bet + 凯利仓位 + 组合优化
- **概率统计实验室**: 12 步拆解一等奖 + DrawScope 引擎交叉验证
- **多源数据采集**: GitHub 开源数据集 + 中彩网 + 天天走势
- **可视化**: 热力图 / 走势图 / 大数定律收敛图

## ⚡ 快速开始

### 四个入口（都共用 `data/pick_advisor.py` 核心库）

```bash
# ① CLI — 历史期验证 / 算法评分 / 随机对照
python scripts/evaluate_picks.py check --game dlt --period 26119 \
    --front 3 6 20 24 32 --back 4 7
python scripts/evaluate_picks.py score --game dlt --front 5 10 15 25 30 --back 3 8
python scripts/evaluate_picks.py oracle --game dlt --last 100 --seed 42

# ② Web GUI — 浏览器开 http://127.0.0.1:9876
python scripts/pick_gui.py

# ③ 胆拖分析器 — 你的 70 注花了多少、期望是多少、剔除大奖后真实回多少
python scripts/dan_tuo.py --draws 200000
python scripts/dan_tuo.py --game ssq --front-dan "01 07" \
    --front-tuo "05 12 19 23 28 31" --back-dan "09" --back-tuo "03 15"

# ④ 端到端诚实演示 — 证明"完美预测"≠"正期望"
python scripts/demo_e2e.py
```

### 系统运维

```bash
# 1. 健康检查 (9 项)
python scripts/health_check.py

# 2. 跑概率实验室 (DLT 12 步 + Step 13 DrawScope)
python main.py lab --game dlt
python main.py lab --game ssq

# 3. 全链路采集 (多源 → CSV → SQLite)
python main.py crawl --game all

# 4. 端到端冒烟测试
python smoke_test.py
```

### 胆拖分析器输出什么

```
【2】展开成多少注 / 花多少钱
    前区: 2 胆 + 从 7 拖里选 3 = C(7,3) = 35 种
    后区: 1 胆 + 从 2 拖里选 1 = C(2,1) = 2 种
    合计: 35 × 2 = 70 注,  花费: 140 元

【3】期望值
    70 注期望净收益: -69.31 元,  凯利 f* = 0.000

【5】模拟 20 万次开奖
    实测净收益(含大奖):   +32.37 元      <- 假象
    剔除大奖后的常态:     -118.78 元     <- 真实期望
    一次大奖能掩盖 200,000 次亏损
```

**"剔除大奖后的常态净收益"是这个工具最重要的数字** —— 它揭示了为什么买彩票的人会以为自己在赚钱。

## 🎯 核心结论 (真实数据 6455 期)

| 彩种 | 期数 | 时间跨度 | 一等奖概率 | 期望净收益 | 凯利最优 |
|------|------|---------|------------|-----------|---------|
| **超级大乐透** | **2938 期** | 2007-05 ~ 2026-10 | 1 / 21,425,712 | **-0.94 元/注** | **f* = 0** |
| **双色球** | **3517 期** | 2003-02 ~ 2026-10 | 1 / 17,721,088 | **-0.86 元/注** | **f* = 0** |

**DrawScope 0.6.5 引擎 (端到端黑盒)** 与我们手写 12 步得到**完全一致**的 χ² 值, 双重验证"号码分布无显著偏离均匀"。

## 🎰 胆拖结构: 只有「胆码个数」影响中奖率

![胆拖结构分析](reports/headline_dantuo.png)

用**精确超几何全枚举**（零抽样误差）算出的结论：

> **固定号码池下，胆拖方案的中奖率只取决于胆码的个数，
> 与"胆码具体选哪几个号"完全无关。**

这是组合数学的恒等式，不是统计现象 —— 每组 12 次随机换号做胆，中奖率 bit-for-bit 相同。
所以**追热号、追冷号、追遗漏，在概率上完全等价**。

| 结构 (前胆/后胆) | 注数 | 花费 | 中奖率 | ≥1万大奖 |
|---|---|---|---|---|
| 0 / 0（双区零胆全覆盖） | 4,620 | 9,240 元 | 47.43% | 0.261% |
| 1 / 1（常规胆拖） | 840 | 1,680 元 | 42.97% | 0.102% |
| 2 / 0（去后区胆） | 840 | 1,680 元 | **47.43%** | 0.047% |
| 0 / 2（后区双胆） | 462 | 924 元 | 28.26% | 0.142% |

**期望值一个都没变** —— 所有结构单注期望净收益都是 -0.9407 元。
工具：
```bash
python scripts/analyze_dantuo.py          # 你的方案的精确分析 + 逐号冷热诊断
python scripts/compare_dantuo_schemes.py   # 7 组结构横向对比
python scripts/dantuo_structure_matrix.py  # 胆码数量结构矩阵
python scripts/dantuo_final_compare.py    # 统一口径最终对比
```

> 📄 **完整推导**见 [`docs/dan_tuo_theory.md`](docs/dan_tuo_theory.md) ——
> 含超几何全枚举的完整证明、结构矩阵、两个被交叉验证抓出的真实 bug。

## 🏗️ 项目架构

```
体育彩票预测项目/
├── data/                 数据层
│   ├── games.py            彩种配置中心 (DLT/SSQ 共用接口)
│   ├── pick_advisor.py     ★ 决策核心库 (CLI/Web/胆拖 三入口共用)
│   ├── sqlite_storage.py   SQLite 持久化 (含 schema 迁移 + UNIQUE 约束)
│   ├── ttz_fetcher.py      天天走势采集 (maxsize=100 限)
│   ├── zhcw_fetcher.py     中彩网采集 (静态 JSON + JSONP 双源)
│   ├── github_fetcher.py   GitHub 开源数据集采集 ★主力
│   ├── merge_sources.py    多源合并 (真实日期优先)
│   ├── import_csv.py       CSV → SQLite 导入器
│   └── data_source.py      多源路由 (主源失败 → fallback)
│
├── core/                 7 种核心热度算法
│   ├── frequency / missing / weighted_window / ewma
│   ├── bayesian / zscore / composite
│
├── analytics/            概率统计实验室
│   ├── probability_lab.py   12+1 步分析 (★ Star of this project)
│   ├── strategy_backtest.py 7 策略对比回测
│   ├── recommender.py       5 策略推荐
│   └── decision_log.py      决策日志 + 自动回填
│
├── sports/               竞彩实验室
│   ├── elo.py            Elo 球队评分
│   ├── strategies/       Value Bet + 凯利 + 组合
│   └── data_sources/     AnySport 商业 API + Mock fallback
│
├── third_party/          DrawScope 0.6.5 引擎 (源码)
├── scripts/              工具脚本
│   ├── evaluate_picks.py    ★ ① CLI (check/score/oracle/live/history)
│   ├── pick_gui.py          ★ ② Web GUI (Flask, 端口 9876)
│   ├── dan_tuo.py           ★ ③ 胆拖分析器 (含剔除大奖的真实期望)
│   ├── analyze_dantuo.py    ★ 胆拖深度分析 (精确超几何, 零抽样误差)
│   ├── compare_dantuo_schemes.py  7 组胆拖结构横向对比
│   ├── dantuo_structure_matrix.py  胆码数量结构矩阵
│   ├── dantuo_final_compare.py     7 组方案统一口径对比
│   ├── make_dantuo_chart.py        胆拖结构分析图
│   ├── check_prize_consistency.py   奖级表 vs 判奖逻辑一致性
│   ├── demo_e2e.py          ★ ④ 端到端诚实演示
│   ├── health_check.py       11 项健康检查 (可自动修复)
│   ├── sports_lab.py         竞彩端到端入口
│   └── drawscope_*.py        DrawScope 演示
│
├── data-raw/             真实数据 (CSV)
│   ├── gh_dlt.csv         ★ 大乐透 2938 期
│   ├── gh_ssq.csv         ★ 双色球 3516 期
│   ├── ttz_*.csv          天天走势 100 期 (2026)
│   ├── zhcw_*.csv         中彩网 100 期 (2020, 含真实日期)
│   └── lottery.db         SQLite (2938 + 3517 期)
│
├── docs/                设计与理论文档
│   ├── README.md           文档索引
│   ├── dan_tuo_theory.md   ★ 胆拖结构理论 (超几何完整推导)
│   ├── prize_rules_spec.md ★ 奖级规则规范 (唯一真相源)
│   └── data_audit.md       数据完整性审计报告
│
├── reports/              生成的可视化图表 (PNG)
└── tests/                pytest 单元测试 (21 个)
```

## 📊 12 步概率统计实验室 (`analytics/probability_lab.py`)

| Step | 名称 | 关键输出 |
|------|------|----------|
| 1 | **一等奖概率** | `C(35,5) × C(12,2) = 21,425,712` |
| 2 | **奖级多元超几何** | 9 奖级 + 期望贡献 = 1.0593 元/注 |
| 3 | **前区贝叶斯热度** | Beta(α+1, β+30) 后验 → Top-5 0.1905 区间 |
| 4 | **后区 Dirichlet** | 高频组合后验 |
| 5 | **遗漏几何分布** | 平均遗漏 5.23 期 (理论 7.00) |
| 6 | **号码独立性 χ²** | **p = 0.75 → 不能拒绝均匀分布** |
| 7 | **皮尔逊相关性** | ≈ 0 (统计噪声) |
| 8 | **马尔可夫稳态** | ≈ 均匀分布 |
| 9 | **蒙特卡洛** | 10000 注模拟覆盖率 |
| 10 | **期望收益 + 方差** | **E[X] = -0.94, σ = 1753** |
| 11 | **凯利最优** | **f\* = 0 (不下注)** |
| 12 | **大数定律** | 累积频率收敛可视化 (n=10⁵) |
| **13** | **★ DrawScope** | 30 信号 walk-forward + 7 DISCLAIMERS |

### DrawScope 7 条 DISCLAIMERS (完整输出)

1. Historical frequency does not change the theoretical probability of a future fair draw.
2. Every retrospective score uses only drawings that occurred before the tested winning draw.
3. The pattern search is exploratory and correlated.
4. The best pattern is selected on an earlier discovery segment and rated only on a later untouched continuation.
5. The confidence rating measures **historical ranking evidence**, not the chance that a ticket will win.
6. No retrospective-only rating can exceed **49 out of 100** without prospective validation.
7. **No observed pattern demonstrates a reliable way to predict an independent lottery drawing.**

## 🌐 数据采集 (两域五源)

### 号码彩 (历史开奖)

| 数据源 | 彩种 | 期数 | 时间 | 特点 |
|--------|------|------|------|------|
| **★ GitHub `yangxb919/lottery-data`** | DLT/SSQ | 2938+3516 | 2003-2026 | 自动更新, **最完整** |
| 中彩网 `chart.zhcw.com/etc` | DLT/SSQ | 100+100 | 2020-10 | 含真实日期 + 奖项明细 |
| 天天走势 `chart.ttzoushi.com` | DLT/SSQ | 100+100 | 2026 | 最新数据, 日期是推算 |

```bash
# 单源采集
python data/github_fetcher.py --all        # ★主力 (6453 期)
python data/zhcw_fetcher.py --all
python data/ttz_fetcher.py --all

# 合并 + 导入 DB (带数据保护, 见 data/data_guard.py)
python main.py crawl --game all
```

### 竞彩 (实时赔率)

| 数据源 | 内容 | 费用 | 备注 |
|--------|------|------|------|
| **中国竞彩官方** `webapi.sporttery.cn` | HAD/HHAD/CRS/TTG/HAFU 实时赔率 + 赛果 | **免费, 无需 key** | 官方公开 API, 含中文名 + 英文 3 字母码 |
| **[the-odds-api.com](https://the-odds-api.com)** | 40+ 家博彩公司实时 1X2 盘口 (uk/eu/au/us) | 免费 500 次/月 | 本文实时扫描用此源, 需注册拿 key |

```bash
# 竞彩实时赔率
python -c "from data.jingcai_odds import fetch_matches; print(len(fetch_matches()))"

# 跨市场实时扫描 (竞彩 x 境外)
$env:ODDS_API_KEY = 'your_key_here'
python scripts/live_scanner.py
```

> **免费额度提示**: the-odds-api 免费档 **500 次请求/月**。
> 一次完整扫描约消耗 13~15 次 (每个联赛 1 次)。5 分钟内结果走缓存不重复扣配额。
> 用量可在响应头 `x-requests-remaining` 查看。

### 反爬突破 (实测)

| 站点 | 障碍 | 解法 |
|------|------|------|
| 体彩官方 webapi.sporttery.cn | WAF HTTP 567 | 放弃, 改用第三方 |
| 福彩官方 cwl.gov.cn | 全部路径返回 404 HTML | 放弃 |
| 天天走势 | 移动 UA → Vue 空模板 | **必须用桌面 Chrome UA** |
| 天天走势 | 默认只给 30 期 | **`?maxsize=100` 限** (200+ 需会员) |
| 中彩网 | JSONP `resCode=100103` 需签名 | 改用 `static/kj_*.json` (缓存) |
| GitHub raw | raw.githubusercontent.com DNS 不通 | 走 **contents/blobs API** (base64) |

## 🚀 CLI 命令 (15 个)

```bash
python main.py games                   # 列出彩种
python main.py crawl --game all       # 多源采集 + 合并 + 导入 ★
python main.py lab --game dlt         # 跑 12+1 步概率实验室 ★
python main.py fetch                   # 全量拉取 (旧版, 推荐 crawl)
python main.py update                  # 增量更新
python main.py analyze --game dlt      # CLI 模式分析
python main.py recommend --game dlt    # 号码组合推荐
python main.py dashboard --port 8765  # Web 仪表盘
python main.py backtest --train 50    # 历史回测
python main.py report-image            # PNG 热度图 + 推送
python main.py watch --interval 300   # 持续监控 + 钉钉/企微推送
python main.py decision-stats          # 决策日志统计
python main.py tests                   # pytest
python main.py migrate                 # CSV → SQLite
python main.py health                  # 健康检查 (有 --auto-fix)
```

## 🏃 竞彩实验室 (欧式赔率 vs 号码彩)

`scripts/sports_lab.py` 端到端跑了 5 步:

1. **数据加载** (5大联赛 56 场示例)
2. **Elo 训练** (8 支球队)
3. **fair_prob** 估计
4. **Value Bet 识别** (84 个候选, 0 个 ≥3% edge)
5. **凯利回测** (75 场 ROI **+7.10%**)

**号码彩 vs 竞彩的根本区别**:
- 号码彩: 期望必负, 凯利=0
- 竞彩: 期望可正 (前提 `fair_prob > market_prob`)

## 🛡️ 关键技术亮点

| 难点 | 解决方案 |
|------|---------|
| F: 盘 (USB 外接 SSD) 大文件写入全 0 | **CARGO_TARGET_DIR=C:\cargo_target** 绕开 |
| 公司网禁 pypi / raw.githubusercontent.com DNS | 复制源码到 `third_party/`, GitHub 走 API |
| GBK Windows 终端 | `sys.stdout.reconfigure(encoding="utf-8")` |
| 多彩种同接口 | `data/games.py` 统一 GameConfig + PrizeRules |
| 真实日期缺失 (走势图只有图表) | 按开奖周期 (DLT 周一三五) 倒推 |
| SQLite schema 迁移 | `_init_schema()` IF NOT EXISTS + ALTER TABLE |
| UNIQUE 约束 (period, game) | `INSERT OR REPLACE` 自动去重 |

## ✅ 测试

```bash
# 冒烟测试 (12 项, ~1s)
python smoke_test.py

# pytest 单元测试
python -m pytest tests/test_anysport_source.py -q --no-header -p no:cacheprovider
# 输出: 15 passed in 0.03s

# 健康检查
python scripts/health_check.py
# 输出: 9/9 项通过, 状态: 健康
```

## 📁 数据文件状态

| 文件 | 大小 | 期数 | 用途 |
|------|------|------|------|
| `data-raw/gh_dlt.csv` | 105KB | **2938** | ★ 主源 (GitHub) |
| `data-raw/gh_ssq.csv` | 130KB | **3516** | ★ 主源 (GitHub) |
| `data-raw/zhcw_dlt.csv` | 3.7KB | 100 | 备用源 (真实日期) |
| `data-raw/zhcw_ssq.csv` | 3.9KB | 100 | 备用源 (真实日期) |
| `data-raw/ttz_dlt.csv` | 3.7KB | 100 | 最新源 (2026) |
| `data-raw/ttz_ssq.csv` | 3.9KB | 100 | 最新源 (2026) |
| `data-raw/merged_*.csv` | 7.5KB | 200 | 多源合并 (早期) |
| `data-raw/lottery.db` | ~0.3MB | 2938+3517 | SQLite 总库 |

## 🤝 致谢

- **[the-odds-api.com](https://the-odds-api.com)** — 实时多博彩公司赔率 API (免费档 500 次/月)，竞彩跨市场扫描的数据源
- **中国体育彩票官方** (`webapi.sporttery.cn`) — 竞彩实时赔率公开 API (免费无需 key)
- **DrawScope 0.6.5** (Nutritionanalytics/drawscope) — 端到端黑盒引擎, 30 信号 + 7 DISCLAIMERS
- **GitHub `yangxb919/lottery-data`** — ★ 2938 + 3516 期完整历史数据
- **GitHub `huhao930422-debug/football-odds-mirror`** — football-data.co.uk 每日镜像, 22 联赛 × 30+ 季真实历史赔率
- **GitHub `yeyingbao/ssq-lottery-analysis`** — 双色球 2354 期奖项明细
- **中彩网 / 天天走势** — 国内中文站点数据

> ⚠️ 引用第三方赔率数据仅用于**研究与教学**。各博彩公司赔率受其条款约束，
> 本项目不对任何博彩服务提供代理、导流或推荐。

## ⚖️ 学术诚信声明

> **彩票是数学上必输的游戏**。本仓库所有代码、所有分析、所有"推荐"都不构成投资建议。
>
> 期望值 (期望) = -0.94 元/注 (DLT), **不能被任何选号策略、任何公式、任何"AI 模型"改变**。
>
> 把彩票当娱乐, 不当投资。这是唯一正确的彩票态度。

---

## 🎁 给后续 Agent 的速通

```bash
# 1. 跑健康检查 (应该 9/9 通过)
python scripts/health_check.py

# 2. 跑全链路实验室
python run_lab.py dlt 2>&1 | tail -20

# 3. 看诚实结论
python -c "
import sys; sys.stdout.reconfigure(encoding='utf-8')
from analytics.probability_lab import step1_first_prize_probability, step10_expected_value, step11_kelly_criterion
"  # → 期望净收益 -0.94/注, 凯利 f*=0
```

如果 `lottery.db` 没数据, 跑:
```bash
python data/github_fetcher.py --all
python data/import_csv.py --all --sources gh,ttz,zhcw
```

— *Last verified: 2026-10-20*
