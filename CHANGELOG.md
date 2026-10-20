# Changelog

本项目的所有版本变更都会记录在这里。版本遵循 [SemVer](https://semver.org/)。

## [v1.1.0] - 2026-10-20

### 新增: 胆拖投注分析器 (`scripts/dan_tuo.py`)

用户随时会把一注胆拖丢进来问"这注怎么样"。现在有专门的工具回答。

**输入**: 胆码 + 拖码 (连续数字串或空格分隔都认)

```bash
python scripts/dan_tuo.py
python scripts/dan_tuo.py --game ssq --front-dan "01 07" \
    --front-tuo "05 12 19 23 28 31" --back-dan "09" --back-tuo "03 15"
```

**输出 6 段**:
1. 号码解析 + 范围/重复校验
2. 展开注数 (`C(拖, 需)`) + 总花费
3. 期望值 + 凯利 f\* + 一等奖覆盖倍数
4. 7 算法给每个胆码/拖码打分 (标热号冷号)
5. **numpy 向量化蒙特卡洛** (20 万次 2.7 秒)
6. 胆拖 vs 随机买同样注数的关键对比

**最有价值的一个数字**: `剔除大奖后的常态净收益`

```
实测平均返奖: 172.37 元/期
实测净收益:   +32.37 元/期   (含大奖)
--- 剔除 40 次大奖 (占 0.020%) ---
常态净收益:   -118.78 元/期   <-- 这才是真实期望
```

它揭示了买彩票的人为什么以为自己能赢: **一次大奖能掩盖 200,000 次亏损**。

**性能**: numpy one-hot 矩阵乘法 (`(m, 35) @ (70, 35).T`) 替代逐注 Python 循环, 40 秒 → 2.7 秒。

### 新增: 端到端诚实演示 (`scripts/demo_e2e.py`)

```bash
python scripts/demo_e2e.py
```

双彩种 (DLT + SSQ) 各取真实开奖号, 让工具评审这注号码:

```
--- 事后视角 (已开奖) ---
命中奖级:   一等奖
中奖金额:   5,000,000 元

--- 事前视角 (开奖前你不知道结果) ---
期望净收益: -0.9902 元/注   <-- 数学是负的
凯利 f*:    0.000           <-- 公式说 [不投]

--- 算法对"完美预测"的评分 (讽刺点) ---
冷号警告:   [20]  <-- 中奖的号被判为 [冷号]
```

**中 500 万的那一注, 事前依然是"数学上该亏 0.99 元"的注。** 两个彩种的中奖号都被自己的算法判成了冷号。

### README 更新

"快速开始"重构为 **四个入口** (CLI / Web GUI / 胆拖分析器 / 端到端演示), 都标注共用 `data/pick_advisor.py` 核心库。

---

## [v1.0.0] - 2026-10-20

### 🎉 首个稳定版本

完整工程化、可运行、可封板的版本。早期散落的实验脚本已统一收口到 `main.py` + `scripts/` 两个入口，核心逻辑全部基于真实开奖数据验证。

### 核心能力

#### 1. 号码彩冷热度分析（7 种算法）

每个号码在算法层面输出"热度分"（越高表示近期窗口出现越频繁），最终把所有号码归一化到百分位供对比。

| 算法 | 原理 | 适用场景 |
|---|---|---|
| **Frequency** | 近期 N 期内出现频次 | 直观"热号" |
| **Missing** | 距离上次出现期数（反向频率） | 找"久未出现的冷号" |
| **WeightedWindow** | 越靠近当下权重越高 | 关注最近 5 期 vs 50 期 |
| **EWMA** | 指数加权移动平均 | 平滑趋势 |
| **Bayesian** | 先验 + 似然组合估计 | 小样本稳健 |
| **ZScore** | 与均匀分布偏离标准差 | 异常显著号 |
| **Composite** | 7 种算法平均百分位 | 综合热度 |

七算法互相印证一致率（DLT χ²=28.16, SSQ χ²=44.70，p>0.05 — 各算法给出的热度排名无显著差异，可作为对照基线）。

#### 2. 概率统计实验室（12 步 + Step 13 DrawScope）

对单彩种历史数据做完整分布研究：

- **Step 1-3** 描述统计、分布拟合（Normal/Poisson/Geometric）、KS 检验
- **Step 4-6** 卡方检验、自相关（ACF/PACF）、平稳性（ADF）
- **Step 7-9** 信息量（熵/互信息）、马尔可夫链、蒙特卡洛模拟
- **Step 10-12** 分层随机 / 系统随机 / 正弦伪随机对照实验
- **Step 13 DrawScope** Rust 编译引擎，跑 30 信号 + 7 disclaimers，对照"理论独立同分布假设"

入口：`python main.py lab --game dlt` 或 `--game ssq`。

#### 3. 多源数据采集 + 自动降级链

```
GitHub `yangxb919/lottery-data`  （主力，可匿名 API 取 base64）
   ↓ 失败时
中彩网 zhcw.com                   （静态 JSON + JSONP 双源）
   ↓ 失败时
天天走势 ttzoushi.com             （伪造 User-Agent 解决移动端 Vue 空模板）
```

| 彩种 | 已采集期数 | 范围 |
|---|---|---|
| 大乐透 (DLT) | 2937-3037 | 2007-001 ~ 2026-119 |
| 双色球 (SSQ) | 3516 | 2003-001 ~ 2026-119 |
| 其余 7 彩种 | 配置采集器已就绪 | 实战数据待补 |

存储：SQLite WAL 模式 + schema 迁移脚本 + UNIQUE 约束 + `(period, game)` 联合主键。

#### 4. 多入口统一核心库（v1.0 新增）

抽出了 `data/pick_advisor.py` 单一可复用模块，所有入口都调用它：

- **`Pick`** 数据类（前区/后区/标签/单价）
- **`AssessResult`** 评估结果（含 `to_dict()` JSON 序列化）
- **`PickAdvisor`** 评估器（期望值 + 历史命中反查 + 7 算法评分 + 建议）
- **`PickHistory`** 评估持久化（NDJSON 格式，按行独立可读）
- **`DataSnapshot`** 数据快照辅助（CLI / Web / Desktop 共用）

配套入口：

| 入口 | 命令 | 协议 |
|---|---|---|
| **CLI** | `python scripts/evaluate_picks.py {check,score,oracle,live,history}` | argparse 子命令 |
| **Web GUI** | `python scripts/pick_gui.py`（端口 9876） | Flask REST API |
| **Desktop GUI** | Tauri Web 端（HTML/JS 待补） | Rust 后端已编译好 |

后续 Desktop GUI 完成后，三个入口业务代码完全一致（同一份 `pick_advisor.py`）。

#### 5. 推送能力

钉钉 / 企业微信 / Telegram 三渠道，跑完概率实验室自动推送报告（PDF/PNG）。

#### 6. DrawScope 桌面端

- Rust 1.88 + Tauri 2.x 编译，5.7 MB 单文件可执行
- 构建产物路径：`CARGO_TARGET_DIR=C:\cargo_target\drawscope`（绕开 USB 外接 SSD bug）
- 零安装即可用

### 诚实结论（最重要的一节）

> **大乐透期望净收益 -0.99 元/注，双色球 -0.81 元/注。凯利公式 f\*=0.000 — 数学公式告诉你"不下注"。**

这不是 bug，这是数学事实。任何选号算法（基于历史频率、贝叶斯先验、神经网络、量子计算...）都无法突破这个**结构性亏损**，因为：

1. 派奖率本身就低于 50%（公价 2 元的票，期望返奖仅 1 元出头）
2. 一等奖概率在大乐透是 **1/21,425,712**，双色球是 **1/17,721,088**
3. 历史频率不影响未来开奖（独立同分布假设下，"热号魔咒"是错觉）

本工具的**唯一价值**：

- ✅ 你已经想到一组号码时，验证它是不是真的"幸运号"（其实没有），或纯粹娱乐
- ✅ 算法温度分给你一个"看起来好"的选号依据（心理价值 > 数学价值）
- ❌ **不**作为投资建议，不应该有"靠这个回本"的期待

**DrawScope DISCLAIMER 已嵌入所有评估结果底部。**

### 工程升级

| 项 | 状态 | 备注 |
|---|---|---|
| SQLite 持久化 | ✅ | WAL 模式 + UNIQUE 约束 |
| 多彩种 schema 迁移 | ✅ | `lottery.db` (DLT 3037 + SSQ 3516 期) |
| 多源自动降级 | ✅ | GitHub > 中彩网 > 天天走势 |
| 健康检查 | ✅ | 9/9 项通过（`python scripts/health_check.py`） |
| 中文 README | ✅ | 12KB |
| 单测 | ✅ | `tests/test_pick_advisor.py` 8/8 通过（手动） |
| 跨平台编码 | ✅ | Windows GBK / Linux UTF-8 双适配 |

### 暂缓 / 未做

- 🚧 **竞彩板块**（Elo + Value Bet + 凯利仓位 + 组合优化）— 真实数据 8 年前止于 2017，对当下赔率无外推价值，**已与用户达成共识暂缓**。代码保留在 `sports/` 不动，未来若需要可独立成子项目。
- 🚧 **Desktop GUI（Tauri Web 端的 HTML/JS）**— Rust 后端已编译（5.7 MB），Web 端的前端联动 HTML 还在 `/scripts/pick_gui.py`（Flask）。两者桥接一层 Tauri 即可。

### 项目结构

```
project-root/                       # 任何 OS 都适用 (Windows D:\工作区\…)
├── data/                           # 数据层
│   ├── games.py                    # GameConfig + PRIZE_RULES 中心
│   ├── sqlite_storage.py           # SQLite WAL
│   ├── github_fetcher.py           # 主力采集 (yangxb919/lottery-data)
│   ├── zhcw_fetcher.py             # 中彩网
│   ├── ttz_fetcher.py              # 天天走势
│   └── pick_advisor.py             # ⭐ 决策核心库 (CLI/Web 共用)
├── core/                           # 7 算法 (Frequency/Missing/ZScore/...)
├── analytics/                      # 12 步概率实验室
│   └── probability_lab.py          # 含 Step 13 DrawScope 引擎
├── sports/                         # 竞彩 (暂缓)
├── third_party/
│   └── drawscope_engine/           # DrawScope Rust 源码 + 协议模型
├── scripts/
│   ├── evaluate_picks.py           # ⭐ CLI (check/score/oracle/live)
│   ├── pick_gui.py                 # ⭐ Web GUI (Flask 单页)
│   ├── health_check.py             # 9 项健康检查
│   ├── crawl_*.py                  # 数据采集
│   └── drawscope_cn_demo.py
├── tests/
│   └── test_pick_advisor.py        # ⭐ 8 个核心用例
├── data-raw/                       # gitignore 大文件
│   ├── gh_dlt.csv                  # 2937 期 (GitHub 主力)
│   ├── gh_ssq.csv                  # 3516 期
│   ├── merged_*.csv                # 早期融合源
│   └── my_picks.jsonl              # 你的评估记录 (gitignored)
├── main.py                         # CLI 入口 (crawl / lab / health)
├── README.md                       # 用户手册
├── CHANGELOG.md                    # 本文件
├── LICENSE                         # MIT
└── .gitignore
```

### 上手示例

```bash
# 数据采集 (一次性, 30 秒)
python main.py crawl --game all

# 概率统计实验室 (12 + 1 步)
python main.py lab --game dlt
python main.py lab --game ssq

# 历史期验证 (你最常用的功能)
python scripts/evaluate_picks.py check --game dlt --period 26119 --front 3 6 20 24 32 --back 4 7

# 任意号码评分
python scripts/evaluate_picks.py score --game dlt --front 5 10 15 25 30 --back 3 8

# Web 界面 (浏览器开 http://127.0.0.1:9876)
python scripts/pick_gui.py

# 健康检查
python scripts/health_check.py

# 单元测试
python tests/test_pick_advisor.py
```

### 历史里程碑

| 版本 | 能力 |
|---|---|
| v0.1 | 7 算法核心 + 可视化 |
| v0.2 | 真实数据验证 (2935 期 DLT) |
| v0.3 | 推送能力 (钉钉/企微/Telegram) |
| v0.4 | 多策略回测 |
| v0.5 | 12 步概率统计实验室 |
| v0.6 | 工程升级 (SQLite + 多源降级) |
| v0.7 | 多源 + 多彩种扩展 |
| v0.8 | DrawScope 集成 |
| v0.9 | DrawScope 桌面端编译 |
| **v1.0** | 收尾三件套 + 输入端三合一 ⬅️ 本次 |

---

**本项目的精神**: 诚实、可复现、可封板、可被后人接手。
