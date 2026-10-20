# Changelog

本项目的所有版本变更都会记录在这里。版本遵循 [SemVer](https://semver.org/)。

## [v1.0.0] - 2026-10-20

### 🎉 首个稳定版本

完整工程化、可运行、可封板的版本。所有"曾经的实验性脚本"已收口，核心逻辑全部基于真实数据验证。

### 核心能力

#### 1. 号码彩冷热度分析（7 算法）
- **Frequency** 频率统计
- **Missing** 遗漏值（反向频率）
- **WeightedWindow** 加权窗口（近期权重高）
- **EWMA** 指数加权移动平均
- **Bayesian** 贝叶斯先验 + 似然
- **ZScore** Z 分数异常度
- **Composite** 综合（7 算法平均百分位）
- 全部算法通过交叉验证一致性检查（DLT χ²=28.16 / SSQ χ²=44.70）

#### 2. 概率统计实验室（12 步 + Step 13 DrawScope）
- Step 1-3: 描述统计、分布拟合（Normal/Poisson/Geometric）、KS 检验
- Step 4-6: 卡方检验、自相关（ACF/PACF）、平稳性（ADF）
- Step 7-9: 信息量（熵/互信息）、马尔可夫链、蒙特卡洛模拟
- Step 10-12: 分层随机 / 系统随机 / 正弦伪随机对照实验
- **Step 13 DrawScope**: 集成 Rust 编译的可执行文件 (`DrawScope.exe`)，跑 30 信号 + 7 disclaimers

#### 3. 多源数据采集 + 自动降级
- **GitHub `yangxb919/lottery-data`**（主力）：DLT 2937 期 + SSQ 3516 期，2003-2026，匿名 API 取 base64
- **中彩网 zhcw.com**（次选）：静态 JSON + JSONP 双源
- **天天走势 ttzoushi.com**（兜底）：桌面 UA 破解移动 UA 的 Vue 空模板
- **彩种**: 大乐透（DLT）+ 双色球（SSQ）+ 7 个其它彩种（福彩 3D、排列 3/5、刮刮乐等）+ AnySport 竞彩接口
- **存储**: SQLite WAL 模式 + schema 迁移 + UNIQUE 约束 + period/game 多彩种联合索引

#### 4. 多入口统一核心库（v1.0 新增）
- **`data/pick_advisor.py`** — Pick / AssessResult / PickAdvisor / PickHistory / DataSnapshot 五大组件
- **CLI** `scripts/evaluate_picks.py`：check / score / oracle / live / history 五个子命令，`--save` 持久化到 `data-raw/my_picks.jsonl`
- **Web GUI** `scripts/pick_gui.py`：Flask 单页应用（端口 9876），可视化选号 + 算法评分 + 历史记录
- 同一份核心库同时支持 CLI / Web，后续 Desktop GUI（Tauri）直接复用

#### 5. 推送能力
- 钉钉 / 企业微信 / Telegram 三渠道
- 跑完概率实验室自动推送 PDF/PNG 报告

#### 6. DrawScope 桌面端
- Rust 1.88 + Tauri，`CARGO_TARGET_DIR=C:\cargo_target\drawscope` 绕开 USB 外接 SSD bug
- 5.7 MB 单文件可执行，零安装即可用

### 诚实结论（最重要的一节）

> **大乐透期望净收益 -0.99 元/注，双色球 -0.81 元/注。凯利公式 f*=0.000 — 数学公式告诉你"不下注"。**

这不是 bug，这是数学事实。任何选号算法（基于历史频率、贝叶斯先验、神经网络...）都无法突破这个**结构性亏损**，因为：

1. 派奖率本身就低于 50%（公价 2 元的票，期望返奖仅 1 元出头）
2. 一等奖概率在大乐透是 **1/21,425,712**，双色球是 **1/17,721,088**
3. 历史频率不影响未来开奖（独立同分布假设下）

本工具的**唯一价值**：
- ✅ 你已经想到一组号码时，验证它是不是真的"幸运号"（其实没有），或纯粹娱乐
- ✅ 算法温度分给你一个"看起来好"的选号依据（心理价值 > 数学价值）
- ❌ **不**作为投资建议，不应该有"靠这个回本"的期待

**DrawScope DISCLAIMER 已嵌入所有评估结果底部。**

### 工程升级

| 项 | 状态 |
|---|---|
| SQLite 持久化 | ✅ WAL 模式 + UNIQUE 约束 |
| 多彩种 schema 迁移 | ✅ `data-raw/lottery.db` (DLT 3037 + SSQ 3516 期) |
| 多源自动降级 | ✅ GitHub > 中彩网 > 天天走势 |
| 健康检查 | ✅ 9/9 项通过（`python scripts/health_check.py`） |
| 中文 README | ✅ 11KB |
| 单测 | ✅ `tests/test_pick_advisor.py` 8/8 通过 |
| 跨平台编码 | ✅ Windows GBK / Linux UTF-8 |

### 暂缓 / 未做

- 🚧 **竞彩板块**（Elo + Value Bet + 凯利仓位 + 组合优化）— 真实数据 8 年前止于 2017，对当下赔率无外推价值，**已与用户达成共识暂缓**。代码保留在 `sports/` 不动。
- 🚧 **Desktop GUI（Tauri Web 端 + DrawScope 前端联动）**— Rust 后端已编译，HTML/JS 前端待补。

### 项目结构

```
D:\工作区\体育彩票预测项目\
├── data/                  # 数据层 (SQLite + 多源采集 + 游戏配置)
│   ├── games.py           # GameConfig + PRIZE_RULES 中心
│   ├── sqlite_storage.py  # SQLite WAL
│   ├── github_fetcher.py  # 主力采集 (yangxb919/lottery-data)
│   ├── zhcw_fetcher.py    # 中彩网
│   ├── ttz_fetcher.py     # 天天走势
│   └── pick_advisor.py    # ⭐ 决策核心库 (CLI/Web 共用)
├── core/                  # 7 算法 (Frequency/Missing/ZScore/...)
├── analytics/             # 12 步概率实验室
│   └── probability_lab.py # 含 Step 13 DrawScope 引擎
├── sports/                # 竞彩 (暂缓)
├── third_party/
│   └── drawscope_engine/  # DrawScope Rust 源码 + 编译产物引用
├── scripts/
│   ├── evaluate_picks.py  # ⭐ CLI (check/score/oracle/live)
│   ├── pick_gui.py        # ⭐ Web GUI (Flask 单页)
│   ├── health_check.py    # 9 项健康检查
│   ├── crawl_*.py         # 数据采集
│   └── drawscope_cn_demo.py
├── tests/
│   └── test_pick_advisor.py  # ⭐ 8 个核心用例
├── data-raw/
│   ├── gh_dlt.csv         # 2937 期 (GitHub 主力)
│   ├── gh_ssq.csv         # 3516 期
│   ├── merged_*.csv       # 早期融合源
│   └── my_picks.jsonl     # 你的评估记录 (gitignored)
├── main.py                # CLI 入口 (crawl / lab / health)
├── README.md              # 用户手册
├── CHANGELOG.md           # 本文件
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

- **v0.1** — 7 算法核心 + 可视化
- **v0.2** — 真实数据验证 (2935 期 DLT)
- **v0.3** — 推送能力 (钉钉/企微/Telegram)
- **v0.4** — 多策略回测
- **v0.5** — 12 步概率统计实验室
- **v0.6** — 工程升级 (SQLite + 多源降级)
- **v0.7** — 多源 + 多彩种扩展
- **v0.8** — DrawScope 集成
- **v0.9** — DrawScope 桌面端编译
- **v1.0** — 收尾三件套 + 输入端三合一 ⬅️ 本次

---

**本项目的精神**: 诚实、可复现、可封板、可被后人接手。
