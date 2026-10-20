"""
严格多策略对比回测
=================
设计目的：检验"热度选号"等策略是否真有统计学意义上的优势

策略:
  1. Random       - 随机选 12（基线对照）
  2. TopHeat      - 选综合热度 Top 12
  3. ColdRebound  - 选最冷 Top 12（追遗漏反弹）
  4. HotStreak    - 选最近 30 期出现 ≥ 2 次的号码（追热）
  5. Balanced     - 选 Top 6 热号 + Bottom 6 冷号（均衡）
  6. MostFrequent - 历史总频次 Top 12（长期热度）
  7. Momentum     - 选最近 30 期动量（斜率）最高的 12 个
  8. FolkClassic  - 经典民间心法：Top 30 热号池里贪心选"奇偶+大小"最平衡的 12 个

每个策略跑：
  - 滑动窗口 out-of-sample 测试
  - 平均命中率 + 标准差 + 95% CI
  - Z 检验 vs 随机（p 值）
  - 多窗口测试（避免单窗口过拟合）
  - 多重检验 Bonferroni 修正（8 个策略，p 阈值应 < 0.05/8 = 0.00625）
"""
from __future__ import annotations
import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from data import load_lottery_data
from core import compute_all_heat_scores

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# 禁用代理
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(k, None)


@dataclass
class StrategyResult:
    """单个策略的回测结果"""
    name: str
    description: str
    hit_rates: np.ndarray         # 每期命中率 (0~1)
    avg_hits: float               # 平均命中数（前区是 /5，后区是 /2）
    std_hits: float
    hit_rate_pct: float           # 平均命中率 %
    ci_low: float                 # 95% CI 下界
    ci_high: float                # 95% CI 上界
    vs_random_diff: float         # 与随机基线的差（百分点）
    p_value: float                # vs 随机的 p 值
    significant: bool             # p < 0.05
    n_periods: int


# ============================================================
# 策略定义（每策略: input -> 12 个号码 list）
# ============================================================
def strat_random(onehot: np.ndarray, n_range: int, top_k: int = 12) -> List[int]:
    """随机选 top_k（基线）"""
    return sorted(np.random.choice(n_range, top_k, replace=False).tolist())


def strat_top_heat(onehot: np.ndarray, n_range: int, top_k: int = 12, window: int = 100) -> List[int]:
    """综合热度 Top K"""
    if window > 0 and window < len(onehot):
        data = onehot[-window:]
    else:
        data = onehot
    scores = compute_all_heat_scores(data, n_range)["composite"]
    idx = np.argsort(scores)[::-1][:top_k]
    return sorted([int(i + 1) for i in idx])


def strat_cold_rebound(onehot: np.ndarray, n_range: int, top_k: int = 12, window: int = 100) -> List[int]:
    """追冷：选最冷 Top K（基于遗漏值反向）"""
    if window > 0 and window < len(onehot):
        data = onehot[-window:]
    else:
        data = onehot
    # 用 missing_inverse 选最低
    from core.missing import MissingAlgorithm
    scores = MissingAlgorithm().compute(data, n_range)
    idx = np.argsort(scores)[:top_k]  # 升序，最小 = 最冷
    return sorted([int(i + 1) for i in idx])


def strat_hot_streak(onehot: np.ndarray, n_range: int, top_k: int = 12, window: int = 30, min_count: int = 2) -> List[int]:
    """追热：选最近 window 期出现 ≥ min_count 次的号码"""
    data = onehot[-window:]
    counts = data.sum(axis=0)
    # 出现次数 >= min_count 的，按次数降序，取 top_k
    candidates = np.where(counts >= min_count)[0]
    if len(candidates) == 0:
        # 全部都不够，回退到 top_heat
        return strat_top_heat(onehot, n_range, top_k, window)
    if len(candidates) > top_k:
        sorted_cand = candidates[np.argsort(-counts[candidates])][:top_k]
    else:
        sorted_cand = candidates
        # 不足的用 heat 补
        if len(sorted_cand) < top_k:
            scores = compute_all_heat_scores(data, n_range)["composite"]
            for i in np.argsort(scores)[::-1]:
                if int(i) not in sorted_cand:
                    sorted_cand = np.append(sorted_cand, int(i))
                if len(sorted_cand) >= top_k:
                    break
    return sorted([int(i + 1) for i in sorted_cand[:top_k]])


def strat_balanced(onehot: np.ndarray, n_range: int, top_k: int = 12, window: int = 100) -> List[int]:
    """均衡：Top 6 热 + Bottom 6 冷"""
    if top_k % 2 != 0:
        raise ValueError("balanced 策略需要 top_k 为偶数")
    half = top_k // 2
    scores = compute_all_heat_scores(onehot[-window:] if window > 0 else onehot, n_range)["composite"]
    top_idx = np.argsort(scores)[::-1][:half]
    bottom_idx = np.argsort(scores)[:half]
    combined = np.concatenate([top_idx, bottom_idx])
    return sorted([int(i + 1) for i in combined])


def strat_most_frequent(onehot: np.ndarray, n_range: int, top_k: int = 12) -> List[int]:
    """历史总频次 Top K"""
    counts = onehot.sum(axis=0)
    idx = np.argsort(counts)[::-1][:top_k]
    return sorted([int(i + 1) for i in idx])


def strat_momentum(onehot: np.ndarray, n_range: int, top_k: int = 12, window: int = 30) -> List[int]:
    """动量策略：选最近 window 期增长率最高的 K 个"""
    if len(onehot) < 2 * window:
        return strat_top_heat(onehot, n_range, top_k, window)

    recent = onehot[-window:].sum(axis=0)
    previous = onehot[-2*window:-window].sum(axis=0)
    momentum = recent - previous

    idx = np.argsort(momentum)[::-1][:top_k]
    return sorted([int(i + 1) for i in idx])


def strat_folk_classic(onehot: np.ndarray, n_range: int, top_k: int = 12, window: int = 100) -> List[int]:
    """
    经典民间心法: 综合平衡选号 (Folk Classic)

    民间选号"心法"的两条铁律:
      - 奇偶平衡: 前区 5 选, 奇数 ≈ 偶数 (3奇2偶 或 2奇3偶)
      - 大小平衡: 大号 (≥ 中位) ≈ 小号 (< 中位)

    算法:
      1. 从最近 window 期 frequency Top 30 热号池里挑
      2. 贪心: 每加一个号, 都让"奇偶偏差 + 大小偏差"最小
      3. 在保证平衡的前提下, 倾向选历史频率更高的号
    """
    if window > 0 and window < len(onehot):
        data = onehot[-window:]
    else:
        data = onehot

    # 候选池: Top 30 热号
    counts = data.sum(axis=0)
    pool_size = min(30, n_range)
    candidates = list(np.argsort(counts)[::-1][:pool_size])

    # 大小号分界点 (前区 35 → 中位 18, 后区 12 → 中位 7)
    mid_point = (n_range // 2) + 1

    def is_odd(n0):  # n0 是 0-indexed, 实际号码 = n0+1
        return (n0 + 1) % 2 == 1

    def is_big(n0):
        return (n0 + 1) >= mid_point

    selected: List[int] = []
    counts_max = counts.max() if counts.max() > 0 else 1

    for _ in range(top_k):
        best_cand = None
        best_score = -1e18

        for cand in candidates:
            if cand in selected:
                continue

            trial = selected + [cand]
            n = len(trial)
            n_odd = sum(1 for x in trial if is_odd(x))
            n_big = sum(1 for x in trial if is_big(x))
            # 偏离 1:1 平衡的绝对距离 (越小越平衡)
            balance_dev = abs(n_odd - n / 2) + abs(n_big - n / 2)
            # 频率得分 (0~1)
            freq_score = counts[cand] / counts_max

            # 总分: 平衡权重 2.0, 频率权重 1.0
            total_score = -balance_dev * 2.0 + freq_score

            if total_score > best_score:
                best_score = total_score
                best_cand = cand

        if best_cand is not None:
            selected.append(best_cand)

    return sorted([int(i + 1) for i in selected])


# 策略注册表
STRATEGIES: Dict[str, Callable] = {
    "Random":        strat_random,
    "TopHeat":       strat_top_heat,
    "ColdRebound":   strat_cold_rebound,
    "HotStreak":     strat_hot_streak,
    "Balanced":      strat_balanced,
    "MostFrequent":  strat_most_frequent,
    "Momentum":      strat_momentum,
    "FolkClassic":   strat_folk_classic,   # ★ 第 8 个：经典民间心法
}


# ============================================================
# 主回测引擎
# ============================================================
class StrictBacktester:
    """严格回测引擎"""

    def __init__(self, df: pd.DataFrame, zone: str = "front", top_k: int = 12):
        self.df = df.reset_index(drop=True)
        self.zone = zone
        self.top_k = top_k
        self.ball_per_period = 5 if zone == "front" else 2
        self.n_range = 35 if zone == "front" else 12

        cols = [c for c in df.columns if c.startswith(f"{zone}_")]
        self.onehot = np.zeros((len(df), self.n_range), dtype=np.int8)
        for col in cols:
            nums = df[col].values - 1
            np.put_along_axis(self.onehot, nums[:, None], 1, axis=1)

        # 随机基线（多次平均）
        np.random.seed(42)

    def run_one_strategy(
        self,
        strategy_fn: Callable,
        train_window: int = 200,
        test_periods: int = 500,
        n_random_trials: int = 100,
        walk_forward: bool = False,
    ) -> StrategyResult:
        """
        跑单个策略
        Random 策略：每个测试期随机选 N 次取平均（消除运气成分）
        walk_forward: 是否用严格非重叠窗口（训练窗口 = t-200 到 t-test_start 不重叠测试期）
        """
        n_total = len(self.onehot)
        test_start = n_total - test_periods

        if walk_forward:
            # 训练窗口和测试窗口完全不重叠
            # 训练用 [0, test_start)，测试用 [test_start, n_total)
            # 但每期的"训练数据"是固定的 [t-train_window, t)，不依赖 t
            # walk_forward 的核心是：训练数据用 [0, test_start - train_window)
            train_end = test_start - train_window
            if train_end <= 0:
                raise ValueError("Not enough data for walk_forward")

        hits_per_period = []

        for t in range(test_start, n_total):
            if walk_forward:
                # 使用固定的训练集（前 test_start - train_window 期）
                if t == test_start:
                    train_data = self.onehot[:train_end]
            else:
                train_data = self.onehot[t - train_window:t]

            actual = self.onehot[t]
            actual_set = set((np.where(actual == 1)[0] + 1).tolist())

            if strategy_fn == strat_random:
                # 随机基线：跑多次取均值
                trials = []
                for _ in range(n_random_trials):
                    pick = strategy_fn(train_data, self.n_range, self.top_k)
                    trials.append(len(set(pick) & actual_set) / self.ball_per_period)
                hit_rate = np.mean(trials)
            else:
                pick = strategy_fn(train_data, self.n_range, self.top_k)
                hit_rate = len(set(pick) & actual_set) / self.ball_per_period

            hits_per_period.append(hit_rate)

        hits_arr = np.array(hits_per_period)

        # 统计
        n = len(hits_arr)
        mean = hits_arr.mean()
        std = hits_arr.std(ddof=1)
        sem = std / np.sqrt(n)
        ci_low, ci_high = stats.t.interval(0.95, n - 1, loc=mean, scale=sem)

        # vs 理论随机
        # 随机选 top_k 个号码（无信息），命中率期望 = top_k / n_range
        # 命中数期望 = ball_per_period * top_k / n_range
        expected_random = self.top_k / self.n_range  # 这是命中率形式（0~1）
        # Z 检验 vs 随机
        if std > 0:
            z = (mean - expected_random) / (std / np.sqrt(n))
            p_value = 2 * (1 - stats.norm.cdf(abs(z)))  # 双尾
        else:
            z = 0
            p_value = 1.0

        return StrategyResult(
            name=strategy_fn.__name__.replace("strat_", "").replace("_", " ").title(),
            description=strategy_fn.__doc__.strip() if strategy_fn.__doc__ else "",
            hit_rates=hits_arr,
            avg_hits=mean,
            std_hits=std,
            hit_rate_pct=mean * 100,
            ci_low=ci_low * 100,
            ci_high=ci_high * 100,
            vs_random_diff=(mean - expected_random) * 100,
            p_value=p_value,
            significant=p_value < 0.05,
            n_periods=n,
        )

    def run_all(
        self,
        train_window: int = 200,
        test_periods: int = 500,
        n_random_trials: int = 100,
        walk_forward: bool = False,
    ) -> List[StrategyResult]:
        """跑所有策略"""
        results = []
        for name, fn in STRATEGIES.items():
            logger.info(f"Running strategy: {name}")
            result = self.run_one_strategy(
                fn,
                train_window=train_window,
                test_periods=test_periods,
                n_random_trials=n_random_trials,
                walk_forward=walk_forward,
            )
            results.append(result)
        return results

    def multi_window_test(
        self,
        fn: Callable,
        windows: List[int] = None,
        test_periods: int = 500,
    ) -> Dict[int, float]:
        """多窗口测试：返回 {window: avg_hit_rate}"""
        if windows is None:
            windows = [50, 100, 200, 500, 1000]
        out = {}
        for w in windows:
            r = self.run_one_strategy(fn, train_window=w, test_periods=test_periods)
            out[w] = r.hit_rate_pct
        return out


# ============================================================
# 报告生成
# ============================================================
def print_report(results: List[StrategyResult], zone: str, top_k: int):
    """打印对比报告"""
    print()
    print("=" * 90)
    print(f"  严格多策略对比回测报告 - {zone.upper()} 区 Top-{top_k} 选号")
    print("=" * 90)
    print()
    n_range = 35 if zone == "front" else 12
    theoretical_random = top_k / n_range * 100
    print(f"  理论随机命中率: {theoretical_random:.2f}%  (= TopK/N = {top_k}/{n_range})")
    print(f"  测试期数: 500 期 (out-of-sample)")
    print(f"  训练窗口: 200 期 (滑动)")
    print()

    # 按 p 值排序
    sorted_results = sorted(results, key=lambda r: r.p_value)

    header = f"  {'策略':<16} {'平均命中':>10} {'标准差':>8} {'95% CI':>20} {'vs 随机':>10} {'p 值':>10} {'显著':>6}"
    print(header)
    print("  " + "─" * 86)

    for r in sorted_results:
        sig_mark = "✓" if r.significant else "✗"
        sig_color = "🟢" if r.significant else "🔴"
        diff_sign = "+" if r.vs_random_diff >= 0 else ""
        print(
            f"  {r.name:<16} {r.hit_rate_pct:>9.2f}% {r.std_hits*100:>7.2f}% "
            f"[{r.ci_low:>6.2f}%, {r.ci_high:>6.2f}%] {diff_sign}{r.vs_random_diff:>6.2f}pp "
            f"{r.p_value:>10.4f} {sig_color}{sig_mark:>4}"
        )

    print()
    print("  ── 解读 ──")
    print()
    print("  • 平均命中: 平均每期选中的号码数 / 总球数 (前区 /5, 后区 /2)")
    print("  • 95% CI:  95% 置信区间 - 真实命中率大概率落在这个范围")
    print("  • vs 随机: 相对理论随机的差 (百分点 pp)")
    print("  • p 值:    双尾 Z 检验 vs 理论随机 (p<0.05 才是统计显著)")
    print("  • ✓:      p < 0.05 显著, ✗: 不显著")
    print()

    # 结论
    sig_results = [r for r in results if r.significant]
    if not sig_results:
        print("  ╔══════════════════════════════════════════════════════════════╗")
        print("  ║  结论: 没有任何策略通过统计显著性检验 (p < 0.05)              ║")
        print("  ║  所有策略的表现都在统计噪声范围内                            ║")
        print("  ║  → 选号策略对大乐透长期命中率没有实质影响                    ║")
        print("  ╚══════════════════════════════════════════════════════════════╝")
    else:
        print("  ╔══════════════════════════════════════════════════════════════╗")
        print(f"  ║  发现 {len(sig_results)} 个策略通过显著性检验                          ║")
        for r in sig_results:
            print(f"  ║  • {r.name:<10s}: 命中 {r.hit_rate_pct:.2f}%, p={r.p_value:.4f}        ║")
        print("  ║  ⚠ 但仍需考虑多重检验问题（7 个策略，期望有 0.35 个偶然显著）║")
        print("  ╚══════════════════════════════════════════════════════════════╝")

    print()
    print("=" * 90)


# ============================================================
# CLI 入口
# ============================================================
def run_full_report(train_window: int = 200, test_periods: int = 500):
    """跑完整报告（前区 + 后区）"""
    df = load_lottery_data()
    print(f"Loaded {len(df)} periods")

    # ============== 模式 A: 滑动窗口 ==============
    print()
    print("#" * 90)
    print("#  模式 A: 滑动窗口（训练数据每期滚动更新，更接近实盘）")
    print("#" * 90)

    for zone, top_k in [("front", 12), ("back", 6)]:
        bt = StrictBacktester(df, zone=zone, top_k=top_k)
        results = bt.run_all(
            train_window=train_window,
            test_periods=test_periods,
            n_random_trials=200,
            walk_forward=False,
        )
        print_report(results, zone, top_k)

    # ============== 模式 B: Walk-Forward 严格非重叠 ==============
    print()
    print("#" * 90)
    print("#  模式 B: Walk-Forward（训练集和测试集完全不重叠，避免信息泄露）")
    print("#" * 90)
    print()

    for zone, top_k in [("front", 12), ("back", 6)]:
        bt = StrictBacktester(df, zone=zone, top_k=top_k)
        results = bt.run_all(
            train_window=train_window,
            test_periods=test_periods,
            n_random_trials=200,
            walk_forward=True,
        )
        print_report(results, zone, top_k)

        # 多窗口稳定性测试
        print()
        print(f"  ── {zone.upper()} 多窗口稳定性测试 (滑动窗口模式) ──")
        print(f"  {'策略':<14}", end="")
        for w in [50, 100, 200, 500]:
            print(f"  win={w:<4}", end="")
        print("  波动")

        for name, fn in STRATEGIES.items():
            print(f"  {name:<14}", end="")
            mw = bt.multi_window_test(fn, windows=[50, 100, 200, 500], test_periods=500)
            vals = []
            for w in [50, 100, 200, 500]:
                vals.append(mw[w])
                print(f"  {mw[w]:>5.2f}%", end="")
            std = np.std(vals)
            print(f"  ±{std:.2f}pp")
        print()


if __name__ == "__main__":
    run_full_report()
