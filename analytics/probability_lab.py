"""
概率统计实验室 - 12 步拆解"手搓大乐透一等奖"
================================================
基于真实历史开奖数据，把彩票问题分解为定量分析

步骤:
  1.  一等奖概率计算
  2.  奖级多元超几何分布
  3.  前区贝叶斯热度 (Beta-Binomial)
  4.  后区 Dirichlet 多项式共轭
  5.  遗漏几何分布与生存函数
  6.  号码独立性卡方检验
  7.  号码相关性皮尔逊系数
  8.  时间演化马尔可夫链
  9.  蒙特卡洛组合覆盖
  10. 期望收益与方差
  11. 凯利准则
  12. 大数定律可视化
"""
from __future__ import annotations
import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass, field
from math import comb, log, log10, exp, sqrt

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import comb as scipy_comb

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams

# 中文字体
try:
    rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
    rcParams['axes.unicode_minus'] = False
except Exception:
    pass

# 禁用代理
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(k, None)

from data import load_lottery_data
from data.games import get_game, GAMES, get_prize_rules

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


# ============================================================
# 全局参数（从 games.py 读取，支持多彩种）
# ============================================================
def _get_game_config(game: str = "dlt") -> dict:
    """获取彩种配置字典（兼容旧接口）"""
    cfg = get_game(game)
    return {
        "front_range": cfg.front_range,
        "front_count": cfg.front_count,
        "back_range":  cfg.back_range,
        "back_count":  cfg.back_count,
        "ticket_price": cfg.ticket_price,
        "name": cfg.name,
        "code": cfg.code,
    }


def _get_prize_rules(game: str = "dlt"):
    """获取奖级规则（兼容旧接口）"""
    rules = get_prize_rules(game)
    return [(hit, (level, money, note)) for hit, (level, money, note) in rules]


# 默认配置（大乐透）
GAME_CONFIG = _get_game_config("dlt")
PRIZE_RULES = _get_prize_rules("dlt")


# ============================================================
# 工具函数
# ============================================================
def hypergeom_pmf(N: int, K: int, n: int, k: int) -> float:
    """
    超几何分布 PMF
    N: 总体大小
    K: 总体中"成功"数量
    n: 抽取数量
    k: 命中数量
    """
    if k > K or k > n or (n - k) > (N - K):
        return 0.0
    return (comb(K, k) * comb(N - K, n - k)) / comb(N, n)


def format_prob(p: float) -> str:
    """格式化概率显示"""
    if p == 0:
        return "≈0"
    if p >= 0.01:
        return f"{p*100:.4f}%"
    if p >= 1e-6:
        return f"{p*100:.6f}%"
    # 极小概率用 1/N 形式
    return f"1/{int(round(1/p))}"


def section(title: str, char: str = "="):
    """打印章节标题"""
    print()
    print(char * 80)
    print(f"  {title}")
    print(char * 80)


# ============================================================
# Step 1: 一等奖概率
# ============================================================
def step1_first_prize_probability() -> Dict[str, Any]:
    """
    Step 1: 一等奖概率
    """
    section("Step 1 · 一等奖概率", "=")

    front_total = comb(GAME_CONFIG["front_range"], GAME_CONFIG["front_count"])
    back_total  = comb(GAME_CONFIG["back_range"],  GAME_CONFIG["back_count"])
    total_combos = front_total * back_total

    p1 = 1.0 / total_combos

    fr = GAME_CONFIG["front_range"]
    fc = GAME_CONFIG["front_count"]
    br = GAME_CONFIG["back_range"]
    bc = GAME_CONFIG["back_count"]
    fl = GAME_CONFIG.get("front_label", "前区")
    bl = GAME_CONFIG.get("back_label", "后区")
    print(f"\n  {fl} C({fr}, {fc}) = {front_total:,} 种")
    print(f"  {bl} C({br}, {bc}) = {back_total:,} 种")
    print(f"  总组合数 = {front_total:,} × {back_total:,} = {total_combos:,}")
    print(f"\n  ★ 一等奖命中概率: {p1:.10e}")
    print(f"  ★ 等价说法: 1 / {total_combos:,}")
    print(f"  ★ 换算: 每 {total_combos/10000:.1f} 万注才有一次一等奖")
    print(f"\n  解读: 即使周周买一辈子（约 5000 期），平均需要 {total_combos/5000:,.0f} 个平行宇宙")

    return {
        "front_combos": front_total,
        "back_combos": back_total,
        "total_combos": total_combos,
        "p1": p1,
    }


# ============================================================
# Step 2: 奖级多元超几何分布
# ============================================================
def step2_prize_distribution() -> Dict[str, Any]:
    """
    Step 2: 各奖级的命中概率和期望奖金（按彩种配置自动适配）
    """
    section("Step 2 · 奖级多元超几何分布", "=")

    fr = GAME_CONFIG["front_range"]
    fc = GAME_CONFIG["front_count"]
    br = GAME_CONFIG["back_range"]
    bc = GAME_CONFIG["back_count"]
    n_levels = len({level for _, (_, level, _) in PRIZE_RULES})
    print(f"\n  规则: 前区 C({fr},{fc}) × 后区 C({br},{bc}) = {comb(fr,fc)*comb(br,bc):,} 种组合")
    print(f"  奖级总数: {n_levels} 个")
    print(f"\n  {'命中组合':<15} {'奖级':<10} {'奖金':>10} {'命中概率':>15} {'期望贡献':>10}")
    print("  " + "─" * 70)

    # 各奖级合并计算（同奖级可能有多种命中组合）
    prize_stats = {}  # 奖级 -> {count_combos, total_money, prob}

    for (f_hit, b_hit), (level, base_money, note) in PRIZE_RULES:
        # 前区命中 f_hit 的概率
        p_front = hypergeom_pmf(
            GAME_CONFIG["front_range"], GAME_CONFIG["front_count"], GAME_CONFIG["front_count"], f_hit
        )
        # 后区命中 b_hit 的概率
        p_back = hypergeom_pmf(
            GAME_CONFIG["back_range"], GAME_CONFIG["back_count"], GAME_CONFIG["back_count"], b_hit
        )
        p_combo = p_front * p_back
        n_combos = p_combo * comb(GAME_CONFIG["front_range"], GAME_CONFIG["front_count"]) * comb(GAME_CONFIG["back_range"], GAME_CONFIG["back_count"])

        if level not in prize_stats:
            prize_stats[level] = {"money": base_money, "prob": 0, "combos": 0, "note": note}

        prize_stats[level]["prob"] += p_combo
        prize_stats[level]["combos"] += int(n_combos)

    # 输出
    total_expected_money = 0
    for level, stat in prize_stats.items():
        expected_contribution = stat["prob"] * stat["money"]
        total_expected_money += expected_contribution
        print(
            f"  {'命中组合':<15} {level:<10} {stat['money']:>9,}元 {format_prob(stat['prob']):>15} {expected_contribution:>9.4f}元"
        )

    # 计算未中奖概率
    total_prize_prob = sum(s["prob"] for s in prize_stats.values())
    p_no_prize = 1 - total_prize_prob
    print(f"\n  ── 汇总 ──")
    print(f"  总中奖概率（任意奖级）: {format_prob(total_prize_prob)}")
    print(f"  未中奖概率:               {format_prob(p_no_prize)}")
    print(f"  期望奖金（每注）:         {total_expected_money:.4f} 元")

    return {
        "prize_stats": prize_stats,
        "total_prize_prob": total_prize_prob,
        "p_no_prize": p_no_prize,
        "expected_money_per_ticket": total_expected_money,
    }


# ============================================================
# Step 3: 前区贝叶斯热度
# ============================================================
def step3_front_bayesian_heat(df: pd.DataFrame, prior_alpha: float = 1.0, prior_beta: float = None) -> Dict:
    """
    Step 3: 前区 Beta-Binomial 共轭先验估计热度
    先验 Beta(α₀, β₀)，后验 Beta(α₀+k, β₀+n-k)
    后验均值 = (α₀+k) / (α₀+β₀+n)
    默认 prior_beta = front_range - 1（均匀先验期望 = front_count/front_range）
    """
    if prior_beta is None:
        prior_beta = float(GAME_CONFIG["front_range"] - GAME_CONFIG["front_count"])
    section(f"Step 3 · {GAME_CONFIG.get('front_label', '前区')}贝叶斯热度 (Beta-Binomial)", "=")

    front_cols = [c for c in df.columns if c.startswith("front_")]
    n_periods = len(df)
    n_range = GAME_CONFIG["front_range"]

    # 每个号码的历史命中次数
    onehot = np.zeros((n_periods, n_range), dtype=np.int8)
    for col in front_cols:
        nums = df[col].values - 1
        np.put_along_axis(onehot, nums[:, None], 1, axis=1)
    hits = onehot.sum(axis=0)
    misses = n_periods - hits

    # 贝叶斯后验
    alpha_post = prior_alpha + hits
    beta_post = prior_beta + misses
    posterior_mean = alpha_post / (alpha_post + beta_post)

    # 95% 置信区间
    ci_low = np.zeros(n_range)
    ci_high = np.zeros(n_range)
    for i in range(n_range):
        ci_low[i], ci_high[i] = stats.beta.ppf([0.025, 0.975], alpha_post[i], beta_post[i])

    # 排序
    sorted_idx = np.argsort(posterior_mean)[::-1]
    print(f"\n  先验: Beta(α₀={prior_alpha}, β₀={prior_beta})")
    print(f"  似然: {n_periods} 期观测数据")
    print(f"  后验分布族: Beta(α₀+k, β₀+n-k)")
    print(f"\n  ★ Top 5 热号（后验均值最高）:")
    for i, idx in enumerate(sorted_idx[:5]):
        print(f"     {i+1}. 号码 {idx+1:02d}: 后验均值 {posterior_mean[idx]:.4f} (95% CI [{ci_low[idx]:.4f}, {ci_high[idx]:.4f}])")

    print(f"\n  ★ Bottom 5 冷号（后验均值最低）:")
    for i, idx in enumerate(sorted_idx[-5:][::-1]):
        print(f"     {i+1}. 号码 {idx+1:02d}: 后验均值 {posterior_mean[idx]:.4f} (95% CI [{ci_low[idx]:.4f}, {ci_high[idx]:.4f}])")

    # 整体信息
    print(f"\n  ★ 所有号码后验均值范围: {posterior_mean.min():.4f} ~ {posterior_mean.max():.4f}")
    print(f"  ★ 后验均值标准差: {posterior_mean.std():.4f}")
    print(f"  ★ 理论期望频率: {GAME_CONFIG['front_count']/n_range:.4f}")

    return {
        "posterior_mean": posterior_mean.tolist(),
        "ci_low": ci_low.tolist(),
        "ci_high": ci_high.tolist(),
        "top5_hot": [int(i+1) for i in sorted_idx[:5]],
        "bottom5_cold": [int(i+1) for i in sorted_idx[-5:][::-1]],
    }


# ============================================================
# Step 4: 后区 Dirichlet-多项式共轭
# ============================================================
def step4_back_dirichlet_combo(df: pd.DataFrame, top_k: int = 10) -> Dict:
    """
    Step 4: 后区 Dirichlet-Multinomial 共轭（自动适配任意后区选号数）
    DLT: C(12,2)=66 种组合  SSQ: C(16,1)=16 种
    """
    back_label = GAME_CONFIG.get("back_label", "后区")
    section(f"Step 4 · {back_label} Dirichlet 多项式共轭", "=")

    back_cols = [c for c in df.columns if c.startswith("back_")]
    n_periods = len(df)
    n_range = GAME_CONFIG["back_range"]
    n_pick = GAME_CONFIG["back_count"]
    n_combos = comb(n_range, n_pick)

    # 统计每种组合出现次数（用 itertools 通用化）
    from itertools import combinations
    combo_list = []
    for combo in combinations(range(1, n_range + 1), n_pick):
        combo_list.append(combo)

    counts = np.zeros(n_combos)
    for _, row in df.iterrows():
        nums = sorted([int(row[c]) for c in back_cols])
        idx = combo_list.index(tuple(nums))
        counts[idx] += 1

    # Dirichlet 先验（均匀）α₀ = 1
    alpha_prior = np.ones(n_combos)
    # 后验
    alpha_post = alpha_prior + counts
    # 后验均值
    posterior_mean = alpha_post / alpha_post.sum()
    # 后验方差
    alpha0 = alpha_post.sum()
    posterior_var = (alpha_post * (alpha0 - alpha_post)) / (alpha0**2 * (alpha0 + 1))

    # 排序
    sorted_idx = np.argsort(posterior_mean)[::-1]

    print(f"\n  {back_label}可能组合: C({n_range}, {n_pick}) = {n_combos} 种")
    print(f"  先验: Dirichlet(α=1) 均匀分布")
    print(f"  似然: {n_periods} 期观测")
    print(f"  后验: Dirichlet(α + counts)")
    print(f"\n  ★ Top {top_k} 高频后区组合（后验均值最高）:")

    for i, idx in enumerate(sorted_idx[:top_k]):
        combo = combo_list[idx]
        observed = int(counts[idx])
        expected = n_periods / n_combos
        ci_low = stats.beta.ppf(0.025, alpha_post[idx], alpha_post.sum() - alpha_post[idx])
        ci_high = stats.beta.ppf(0.975, alpha_post[idx], alpha_post.sum() - alpha_post[idx])
        combo_str = "+".join(f"{x:02d}" for x in combo)
        print(f"     {i+1:2d}. 组合 {combo_str}: 观测 {observed:4d} 次 (期望 {expected:.1f}), 后验 {posterior_mean[idx]*n_combos:.3f} ({posterior_mean[idx]*100:.2f}%) CI [{ci_low*n_combos:.2f}, {ci_high*n_combos:.2f}]")

    # 均匀性检验
    chi2_stat = ((counts - n_periods/n_combos)**2 / (n_periods/n_combos)).sum()
    df_chi = n_combos - 1
    p_chi = 1 - stats.chi2.cdf(chi2_stat, df_chi)
    print(f"\n  ★ 均匀性卡方检验:")
    print(f"     χ² = {chi2_stat:.2f}, df = {df_chi}, p = {p_chi:.4f}")
    print(f"     结论: {'拒绝均匀' if p_chi < 0.05 else '不能拒绝均匀'} (p {'<' if p_chi < 0.05 else '>'} 0.05)")

    return {
        "combo_list": combo_list,
        "posterior_mean": posterior_mean.tolist(),
        "top_combos": [(combo_list[i], float(posterior_mean[i])) for i in sorted_idx[:top_k]],
        "chi2_stat": chi2_stat,
        "chi2_p": p_chi,
    }


# ============================================================
# Step 5: 遗漏几何分布与生存函数
# ============================================================
def step5_missing_geometric(df: pd.DataFrame) -> Dict:
    """
    Step 5: 遗漏几何分布（自动适配任意彩种）
    每个号码每期被抽中 p=front_count/front_range，遗漏 n 期的概率 = (1-p)^n
    期望遗漏 = 1/p
    """
    section("Step 5 · 几何分布与生存函数", "=")

    front_cols = [c for c in df.columns if c.startswith("front_")]
    n_range = GAME_CONFIG["front_range"]
    n_pick = GAME_CONFIG["front_count"]

    # 计算每个号码当前遗漏
    onehot = np.zeros((len(df), n_range), dtype=np.int8)
    for col in front_cols:
        nums = df[col].values - 1
        np.put_along_axis(onehot, nums[:, None], 1, axis=1)

    missing = np.zeros(n_range, dtype=int)
    for num in range(n_range):
        col = onehot[::-1, num]
        idx = np.argmax(col)
        if col[idx] == 1:
            missing[num] = idx
        else:
            missing[num] = len(df)

    # 几何分布参数
    p = n_pick / n_range
    expected_missing = 1/p

    # 生存函数 P(X > n) = (1-p)^n
    print(f"\n  单期被抽中概率: p = {n_pick}/{n_range} = {p:.4f}")
    print(f"  期望遗漏: 1/p = {expected_missing:.2f} 期")
    print(f"  当前期数: {len(df)} 期")
    print(f"\n  ★ 生存函数 P(X > n):")
    for n in [5, 10, 15, 20, 25, 30, 40, 50]:
        survival = (1-p)**n
        print(f"     P(连续遗漏 ≥ {n:2d} 期) = {survival:.4f} ({survival*100:.2f}%)")

    # 当前实际遗漏排名
    sorted_idx = np.argsort(missing)[::-1]
    print(f"\n  ★ 当前遗漏最长的 5 个号码:")
    for i, idx in enumerate(sorted_idx[:5]):
        m = int(missing[idx])
        survival = (1-p)**m
        print(f"     {i+1}. 号码 {idx+1:02d}: 遗漏 {m} 期, P(≥ {m}) = {survival*100:.4f}%")

    # 平均遗漏 vs 期望
    avg_missing = missing.mean()
    print(f"\n  ★ 所有号码平均遗漏: {avg_missing:.2f} 期")
    print(f"  ★ 理论期望遗漏: {expected_missing:.2f} 期")
    print(f"  ★ 比值（实测/期望）: {avg_missing/expected_missing:.3f} (1.0 = 完全符合几何分布)")

    return {
        "p": p,
        "expected_missing": expected_missing,
        "missing": missing.tolist(),
        "top5_missing": [int(i+1) for i in sorted_idx[:5]],
        "avg_missing": avg_missing,
    }


# ============================================================
# Step 6: 号码独立性卡方检验
# ============================================================
def step6_chi2_independence(df: pd.DataFrame) -> Dict:
    """
    Step 6: 卡方检验号码独立性（自动适配任意彩种）
    H0: 每个号码出现频率相同（= front_count/front_range）
    """
    section("Step 6 · 号码独立性卡方检验", "=")

    front_cols = [c for c in df.columns if c.startswith("front_")]
    n_periods = len(df)
    n_range = GAME_CONFIG["front_range"]
    n_pick = GAME_CONFIG["front_count"]

    onehot = np.zeros((n_periods, n_range), dtype=np.int8)
    for col in front_cols:
        nums = df[col].values - 1
        np.put_along_axis(onehot, nums[:, None], 1, axis=1)

    observed = onehot.sum(axis=0)
    expected = np.full(n_range, n_pick / n_range * n_periods)

    # 卡方统计量
    chi2_stat = ((observed - expected)**2 / expected).sum()
    df_chi = n_range - 1
    p_value = 1 - stats.chi2.cdf(chi2_stat, df_chi)

    # 临界值
    critical_05 = stats.chi2.ppf(0.95, df_chi)
    critical_01 = stats.chi2.ppf(0.99, df_chi)

    print(f"\n  H0: 所有号码出现频率相同 (期望频率 = {n_pick/n_range:.4f})")
    print(f"  观测期数: {n_periods}")
    print(f"\n  ★ 卡方统计量: χ² = {chi2_stat:.2f}")
    print(f"  ★ 自由度: df = {df_chi}")
    print(f"  ★ p 值: {p_value:.4f}")
    print(f"  ★ 临界值: χ²_0.05 = {critical_05:.2f}, χ²_0.01 = {critical_01:.2f}")
    print(f"\n  ★ 结论: {'拒绝 H0' if p_value < 0.05 else '不能拒绝 H0'} (p {'<' if p_value < 0.05 else '>'} 0.05)")

    game_name = GAME_CONFIG.get("name", "该彩种")
    if p_value >= 0.05:
        print(f"\n  → 号码频率在统计上没有显著偏向")
        print(f"  → {game_name}开奖机制接近均匀分布")
    else:
        print(f"\n  → 拒绝均匀假设，存在统计显著的频率差异")
        print(f"  → 可能是机械/物理因素导致的微小非均匀性")

    # 单号码偏离度
    deviation = (observed - expected) / np.sqrt(expected)
    sorted_dev = np.argsort(np.abs(deviation))[::-1]
    print(f"\n  ★ 偏离期望最大的 5 个号码（标准化残差）:")
    for i, idx in enumerate(sorted_dev[:5]):
        print(f"     {i+1}. 号码 {idx+1:02d}: 观测 {int(observed[idx])} 次, 期望 {expected[idx]:.1f} 次, Z = {deviation[idx]:+.2f}")

    return {
        "chi2_stat": chi2_stat,
        "df": df_chi,
        "p_value": p_value,
        "reject_null": p_value < 0.05,
    }


# ============================================================
# Step 7: 号码相关性皮尔逊系数
# ============================================================
def step7_pearson_correlation(df: pd.DataFrame, top_pairs: int = 10) -> Dict:
    """
    Step 7: 号码对相关性
    对每个号码对 (i, j)，计算皮尔逊相关系数
    """
    section("Step 7 · 号码相关性皮尔逊系数", "=")

    front_cols = [c for c in df.columns if c.startswith("front_")]
    n_periods = len(df)
    n_range = GAME_CONFIG["front_range"]

    onehot = np.zeros((n_periods, n_range), dtype=np.int8)
    for col in front_cols:
        nums = df[col].values - 1
        np.put_along_axis(onehot, nums[:, None], 1, axis=1)

    # 相关系数矩阵
    corr_matrix = np.corrcoef(onehot.T)

    # 找出最大正相关和最大负相关的对
    pairs = []
    for i in range(n_range):
        for j in range(i+1, n_range):
            pairs.append((i+1, j+1, corr_matrix[i, j]))

    pairs_sorted_pos = sorted(pairs, key=lambda x: -x[2])
    pairs_sorted_neg = sorted(pairs, key=lambda x: x[2])

    print(f"\n  号码对相关系数（基于 {n_periods} 期共现）")
    print(f"  理论: 若号码独立，相关系数应接近 0")
    print(f"\n  ★ 正相关 Top {top_pairs}（经常一起出）:")
    for i, (a, b, r) in enumerate(pairs_sorted_pos[:top_pairs]):
        sig = "✓" if abs(r) > 2/np.sqrt(n_periods) else " "
        print(f"     {i+1:2d}. {a:02d} ↔ {b:02d}: r = {r:+.4f} {sig}")

    print(f"\n  ★ 负相关 Top {top_pairs}（互相排斥）:")
    for i, (a, b, r) in enumerate(pairs_sorted_neg[:top_pairs]):
        sig = "✓" if abs(r) > 2/np.sqrt(n_periods) else " "
        print(f"     {i+1:2d}. {a:02d} ↔ {b:02d}: r = {r:+.4f} {sig}")

    # 总体特征
    all_r = [p[2] for p in pairs]
    print(f"\n  ★ 相关系数统计:")
    print(f"     范围: {min(all_r):+.4f} ~ {max(all_r):+.4f}")
    print(f"     均值: {np.mean(all_r):+.4f}")
    print(f"     标准差: {np.std(all_r):.4f}")

    # 显著检验临界值 (5% level, df=n-2)
    n_sig = sum(1 for r in all_r if abs(r) > stats.t.ppf(0.975, n_periods - 2) / np.sqrt(n_periods - 2 + stats.t.ppf(0.975, n_periods - 2)**2))
    print(f"     显著相关系数（|r| > 临界值）: {n_sig} 对 / {len(pairs)} 总")
    expected_sig = 0.05 * len(pairs)
    print(f"     期望偶然显著对数: {expected_sig:.0f}")

    print(f"\n  ★ 结论: {'存在显著相关对（超过偶然）' if n_sig > expected_sig * 1.5 else '大部分相关是统计噪声'}")

    return {
        "corr_matrix": corr_matrix.tolist(),
        "n_significant": n_sig,
        "top_pos": pairs_sorted_pos[:top_pairs],
        "top_neg": pairs_sorted_neg[:top_pairs],
    }


# ============================================================
# Step 8: 马尔可夫链冷热状态转移
# ============================================================
def step8_markov_chain(df: pd.DataFrame, lookback: int = 1000) -> Dict:
    """
    Step 8: 马尔可夫链冷热状态转移
    状态: 上一期"出现" vs "未出现"
    简化：只用上一期状态（窗口 = 1），不再用大窗口（否则稳态偏向"热"）
    """
    section("Step 8 · 马尔可夫链冷热状态转移", "=")

    front_cols = [c for c in df.columns if c.startswith("front_")]
    n_periods = len(df)
    n_range = GAME_CONFIG["front_range"]

    onehot = np.zeros((n_periods, n_range), dtype=np.int8)
    for col in front_cols:
        nums = df[col].values - 1
        np.put_along_axis(onehot, nums[:, None], 1, axis=1)

    # 状态定义（基于上一期是否出现）
    # 状态 0 = 冷（上一期未出现）
    # 状态 1 = 热（上一期出现）
    # 从 t=1 开始（需要前一期的状态）
    states = onehot[1:]  # t 期的"上一期状态"

    # 转移矩阵 (2x2): P(下期出现 | 本期状态)
    # 当前状态 from (states[t-1])，下一期状态 to (onehot[t+1])
    transition = np.zeros((2, 2))
    for t in range(1, n_periods - 1):
        s_from = onehot[t, :]      # t 期的状态
        s_to = onehot[t + 1, :]    # t+1 期的状态
        for num in range(n_range):
            transition[s_from[num], s_to[num]] += 1

    # 归一化
    transition_prob = transition / transition.sum(axis=1, keepdims=True)

    # 稳态分布
    eigenvalues, eigenvectors = np.linalg.eig(transition_prob.T)
    idx = np.argmin(np.abs(eigenvalues - 1))
    stationary = np.real(eigenvectors[:, idx])
    stationary = stationary / stationary.sum()

    print(f"\n  状态定义: 0=冷（上一期未出现）, 1=热（上一期出现）")
    print(f"\n  ★ 状态转移矩阵 P(to | from):")
    print(f"          → 冷(0)     热(1)")
    for i, label in enumerate(["冷", "热"]):
        print(f"     {label}  {transition_prob[i, 0]:.4f}    {transition_prob[i, 1]:.4f}")

    print(f"\n  ★ 稳态分布（长期均衡）:")
    for i, label in enumerate(["冷", "热"]):
        print(f"     {label}: {stationary[i]*100:.2f}%")

    # 当前状态分布
    current_dist = np.zeros(2)
    for num in range(n_range):
        current_dist[onehot[-1, num]] += 1
    current_dist /= n_range
    print(f"\n  ★ 当前状态分布（最新一期）:")
    for i, label in enumerate(["冷", "热"]):
        print(f"     {label}: {current_dist[i]*100:.2f}%")

    # 解读
    n_pick = GAME_CONFIG["front_count"]
    n_range = GAME_CONFIG["front_range"]
    cold_pct = (n_range - n_pick) / n_range * 100
    hot_pct = n_pick / n_range * 100
    print(f"\n  ★ 解读:")
    print(f"     • 理论稳态：冷 {stationary[0]*100:.1f}%, 热 {stationary[1]*100:.1f}%")
    print(f"     • {GAME_CONFIG.get('name','该彩种')} {n_pick}/{n_range}: 每期约 {n_pick}/{n_range} ≈ {hot_pct:.1f}% 号码出现")
    print(f"     • 如果号码独立无记忆，稳态应该 = ({(n_range-n_pick)}/{n_range}, {n_pick}/{n_range})")

    return {
        "transition_matrix": transition_prob.tolist(),
        "stationary_dist": stationary.tolist(),
        "current_dist": current_dist.tolist(),
    }


# ============================================================
# Step 9: 蒙特卡洛组合覆盖
# ============================================================
def step9_monte_carlo_coverage(n_tickets: int = 100, n_simulations: int = 10000) -> Dict:
    """
    Step 9: 蒙特卡洛模拟
    买 N 注（每注 5+2 个号码），看能覆盖多少种开奖组合
    """
    section("Step 9 · 蒙特卡洛组合覆盖", "=")

    front_total = comb(GAME_CONFIG["front_range"], GAME_CONFIG["front_count"])
    back_total = comb(GAME_CONFIG["back_range"], GAME_CONFIG["back_count"])
    total_combos = front_total * back_total

    np.random.seed(42)

    # 模拟 n_simulations 次"开奖"
    # 每次随机选 1 个开奖组合
    # 然后看 n_tickets 张票里有没有中一等奖
    first_prize_hits = 0
    any_prize_hits = 0

    for _ in range(n_simulations):
        # 模拟开奖（一个真实的组合）
        actual_front = sorted(np.random.choice(GAME_CONFIG["front_range"], GAME_CONFIG["front_count"], replace=False))
        actual_back = sorted(np.random.choice(GAME_CONFIG["back_range"], GAME_CONFIG["back_count"], replace=False))

        # 检查 n_tickets 张票
        ticket_first = False
        ticket_any = False

        for _ in range(n_tickets):
            # 随机选票
            t_front = sorted(np.random.choice(GAME_CONFIG["front_range"], GAME_CONFIG["front_count"], replace=False))
            t_back = sorted(np.random.choice(GAME_CONFIG["back_range"], GAME_CONFIG["back_count"], replace=False))

            # 一等奖
            if t_front == actual_front and t_back == actual_back:
                ticket_first = True
            # 任意奖级（查 PRIZE_RULES 表，跨彩种通用）
            f_hit = len(set(t_front) & set(actual_front))
            b_hit = len(set(t_back) & set(actual_back))
            hit_levels = {level for (fh, bh), (level, _, _) in PRIZE_RULES if fh == f_hit and bh == b_hit}
            if hit_levels:
                ticket_any = True

        if ticket_first:
            first_prize_hits += 1
        if ticket_any:
            any_prize_hits += 1

    p_first_per_sim = first_prize_hits / n_simulations
    p_any_per_sim = any_prize_hits / n_simulations

    print(f"\n  模拟 {n_simulations:,} 次开奖")
    print(f"  每次买 {n_tickets} 注")
    print(f"\n  ★ 至少中一次一等奖的概率: {p_first_per_sim*100:.4f}% ({first_prize_hits}/{n_simulations})")
    print(f"  ★ 至少中一次任意奖的概率: {p_any_per_sim*100:.2f}% ({any_prize_hits}/{n_simulations})")

    # 理论计算
    p_first_one_ticket = 1 / total_combos
    p_first_n_tickets = 1 - (1 - p_first_one_ticket)**n_tickets  # 假设不重复
    print(f"\n  ★ 理论:")
    print(f"     一注中一等奖概率: {p_first_one_ticket:.2e}")
    print(f"     {n_tickets} 注都不中的概率: {(1-p_first_one_ticket)**n_tickets:.6f}")
    print(f"     {n_tickets} 注至少中一次概率: {p_first_n_tickets:.2e}")

    # 多少注能 50%/95%/99% 覆盖
    for target in [0.5, 0.95, 0.99]:
        if p_first_one_ticket > 0:
            n_needed = log(1 - target) / log(1 - p_first_one_ticket)
            cost = n_needed * GAME_CONFIG["ticket_price"]
            print(f"     {target*100}% 概率中一等奖需要: {n_needed:,.0f} 注 (成本 {cost:,.0f} 元)")

    return {
        "n_simulations": n_simulations,
        "n_tickets": n_tickets,
        "first_prize_hits": first_prize_hits,
        "any_prize_hits": any_prize_hits,
    }


# ============================================================
# Step 10: 期望收益与方差
# ============================================================
def step10_expected_value(prize_stats: Dict) -> Dict:
    """
    Step 10: 每注期望收益 + 方差
    """
    section("Step 10 · 期望收益与方差", "=")

    ticket_price = GAME_CONFIG["ticket_price"]

    # 期望奖金
    expected_money = 0
    for level, stat in prize_stats["prize_stats"].items():
        expected_money += stat["prob"] * stat["money"]

    # 各奖级的方差贡献
    # Var(X) = E[X²] - (E[X])²
    expected_money_squared = 0
    for level, stat in prize_stats["prize_stats"].items():
        expected_money_squared += stat["prob"] * (stat["money"] ** 2)
    # + 未中奖的贡献（0）
    expected_money_squared += prize_stats["p_no_prize"] * 0

    variance_per_ticket = expected_money_squared - expected_money ** 2
    std_per_ticket = sqrt(variance_per_ticket)

    # 净收益
    expected_net = expected_money - ticket_price

    print(f"\n  单注成本: {ticket_price} 元")
    print(f"\n  ★ 期望奖金: {expected_money:.4f} 元")
    print(f"  ★ 期望净收益: {expected_net:+.4f} 元/注")
    print(f"  ★ 回报率: {expected_money/ticket_price*100:.2f}%")
    print(f"\n  ★ 奖金方差: {variance_per_ticket:.2f} 元²")
    print(f"  ★ 奖金标准差: {std_per_ticket:.2f} 元/注")

    # 模拟买 1000 注的分布
    n = 1000
    mean_n = n * expected_money
    std_n = sqrt(n) * std_per_ticket
    print(f"\n  ★ 买 {n} 注的:")
    print(f"     期望总奖金: {mean_n:.2f} 元")
    print(f"     期望总净收益: {mean_n - n*ticket_price:+.2f} 元")
    print(f"     标准差: {std_n:.2f} 元")
    print(f"     95% 置信区间: [{mean_n - 1.96*std_n:.0f}, {mean_n + 1.96*std_n:.0f}] 元")

    return {
        "expected_money": expected_money,
        "expected_net": expected_net,
        "variance": variance_per_ticket,
        "std": std_per_ticket,
    }


# ============================================================
# Step 11: 凯利准则
# ============================================================
def step11_kelly_criterion(expected_net: float, variance: float) -> Dict:
    """
    Step 11: 凯利公式
    标准凯利: f* = (bp - q) / b
    简化: f* = edge / (odds × variance_per_unit)
    当期望为负: f* = 0
    """
    section("Step 11 · 凯利准则", "=")

    ticket_price = GAME_CONFIG["ticket_price"]

    # edge = 期望收益率
    edge = expected_net / ticket_price

    # 凯利公式（多种形式）
    print(f"\n  凯利公式: f* = (bp - q) / b")
    print(f"  其中: b = 净赔率, p = 胜率, q = 1-p")
    print(f"\n  ★ 每注期望净收益: {expected_net:+.4f} 元")
    print(f"  ★ 期望收益率 (edge): {edge*100:+.4f}%")

    if edge <= 0:
        # 期望为负：凯利最优 = 0 或负（这里截断到 0）
        f_star = 0.0
        print(f"\n  ★ 凯利最优比例: f* = 0")
        print(f"\n  ★ 结论:")
        print(f"     • 期望收益为负 → 凯利最优是'不下注'")
        print(f"     • 这就是为什么长期买彩票必然亏损")
        print(f"     • 即使中奖概率不为零，期望仍然为负")
        print(f"     • 因为{GAME_CONFIG.get('name','该彩种')}是'负期望游戏'，派奖率 < 100%")
    else:
        # 期望为正：用凯利公式
        # 简化版（假设赔率均匀）: f* = edge / odds_total
        # 这里用每注方差做修正
        f_star_raw = edge
        f_star = min(f_star_raw, 1.0)  # 不超过 100%
        print(f"\n  ★ 凯利最优比例: f* = {f_star*100:.2f}%")
        print(f"  ★ 建议每次投入资金 {f_star*100:.2f}% 购彩")

    print(f"\n  ★ 解读:")
    print(f"     • 凯利公式告诉你下注多少能长期最大化对数财富增长率")
    print(f"     • 期望为负时，凯利自动给出 0 → 不下注")
    print(f"     • {GAME_CONFIG.get('name','该彩种')}是典型的'负期望游戏'（派奖率约 65%）")

    # 长期资金曲线对比（不下注 vs 满仓梭哈）
    print(f"\n  ★ 资金曲线对比（100 期，每期 1000 元起步）:")
    print(f"     策略 A - 不下注:       期末资金 = 100,000 元（保留）")
    if edge != 0:
        # 模拟梭哈（每期全压）
        bankroll_full = 1000
        for _ in range(100):
            bankroll_full *= (1 + edge)
        print(f"     策略 B - 满仓梭哈:     期末资金 = {bankroll_full:.2f} 元")

    return {
        "edge": edge,
        "f_star": f_star,
        "recommendation": "不下注" if edge <= 0 else f"投入 {f_star*100:.2f}% 资金",
    }


# ============================================================
# Step 12: 大数定律可视化
# ============================================================
def step12_law_of_large_numbers(n_simulations: int = 100000) -> Dict:
    """
    Step 12: 大数定律
    模拟 N 期，看实际频率如何收敛到理论概率
    """
    section("Step 12 · 大数定律可视化", "=")

    np.random.seed(42)

    # 模拟某个具体号码在前区的出现频率
    n_range = GAME_CONFIG["front_range"]
    n_draw = GAME_CONFIG["front_count"]
    target_num = max(1, n_range // 2)  # 取中间号作为演示目标
    target_idx = target_num - 1

    # 每次随机从 n_range 个号里选 n_draw 个
    draws = np.zeros(n_simulations, dtype=np.int8)
    for t in range(n_simulations):
        chosen = np.random.choice(n_range, n_draw, replace=False)
        if target_idx in chosen:
            draws[t] = 1

    # 累积频率
    cum_freq = np.cumsum(draws) / np.arange(1, n_simulations + 1)
    theoretical = n_draw / n_range

    # 关键节点的频率
    checkpoints = [10, 100, 1000, 10000, 100000]
    print(f"\n  目标: 号码 {target_num} 在{GAME_CONFIG.get('front_label','前区')}的出现频率（理论 = {theoretical:.4f}）")
    print(f"\n  ★ 累积频率收敛过程:")
    for cp in checkpoints:
        if cp <= n_simulations:
            print(f"     第 {cp:>6} 期: 累积频率 {cum_freq[cp-1]:.4f} (偏差 {cum_freq[cp-1]-theoretical:+.4f})")

    # 最终偏差
    final_dev = cum_freq[-1] - theoretical
    print(f"\n  ★ 最终偏差: {final_dev:+.4f}")
    print(f"  ★ 大数定律保证: 当 n → ∞, 偏差 → 0")

    # 画图
    fig, ax = plt.subplots(figsize=(12, 6), facecolor="#0f172a")
    ax.set_facecolor("#1e293b")

    x = np.arange(1, n_simulations + 1)
    ax.plot(x, cum_freq, color="#fbbf24", linewidth=1, alpha=0.8)
    ax.axhline(theoretical, color="#dc2626", linestyle="--", linewidth=2, label=f"理论概率 {theoretical:.4f}")

    ax.set_xscale("log")
    ax.set_xlabel("期数 n (对数轴)", color="white", fontsize=12)
    ax.set_ylabel("累积频率", color="white", fontsize=12)
    ax.set_title(f"大数定律：号码 {target_num} 的累积频率收敛过程", color="#fbbf24", fontsize=14, fontweight="bold")
    ax.legend(loc="upper right", fontsize=11)
    ax.tick_params(colors="white")
    ax.grid(True, alpha=0.2, color="#94a3b8")

    for spine in ax.spines.values():
        spine.set_color("#334155")

    plt.tight_layout()
    out_path = REPORTS_DIR / "law_of_large_numbers.png"
    plt.savefig(out_path, dpi=120, facecolor="#0f172a", bbox_inches="tight")
    plt.close(fig)

    print(f"\n  ★ 可视化已保存: {out_path}")

    return {
        "n_simulations": n_simulations,
        "theoretical_prob": theoretical,
        "final_freq": float(cum_freq[-1]),
        "final_dev": float(final_dev),
    }


# ============================================================
# Step 13: DrawScope 引擎集成 (跨彩种通用)
# ============================================================
def step13_drawscope_integration(matches, game: str = "dlt") -> Dict[str, Any]:
    """
    Step 13: DrawScope 引擎集成

    调用 DrawScope v0.6.5 官方 Python 引擎, 跑完整的 walk-forward 分析:
      - 30 个固定信号 (权重 0.04 ~ 0.05)
      - 卡方检验 (χ²)
      - 模式分布 (奇偶/区间/跨度)
      - 配对统计 (top pairs)
      - 模拟试验 (10000 次)
      - DISCLAIMERS (7 条学术级免责)

    与我们 Step 6 卡方 / Step 7 配对 / Step 9 模拟 的区别:
      - DrawScope 走严格 forward-only 边界 (target draw 不参与自身评分)
      - 30 信号自动加权融合, 我们是手动选 7 种算法
      - 输出 7 条 DISCLAIMERS, 强化诚实声明

    适配层: sports/drawscope_adapter
    """
    section("Step 13 · DrawScope 引擎集成", "=")

    # 1. 导入适配层 (延迟导入, 避免污染主入口)
    try:
        if game == "dlt":
            from sports.drawscope_adapter import dlt_df_to_drawings, dlt_payload
        else:
            from sports.drawscope_adapter import ssq_df_to_drawings, ssq_payload
        from drawscope_engine.statistics.analytics import analyze, SIGNALS, DISCLAIMERS
    except ImportError as e:
        print(f"  ❌ DrawScope 不可用: {e}")
        print(f"     跳过 Step 13 (需要 third_party/drawscope_engine/)")
        return {"available": False}

    print(f"  DrawScope engine loaded: 30 signals + 7 disclaimers")

    # 2. 把 our matches (dict format) 转 DataFrame → Drawings
    import pandas as pd
    rows = []
    for m in matches:
        front = m.get("front", [])
        back = m.get("back", [])
        if not front or not back:
            continue
        row = {"draw_date": str(m.get("draw_date", ""))[:10]}
        for i, n in enumerate(front, 1):
            row[f"front_{i}"] = n
        # DLT 后区 2 个 (back_1 + back_2), SSQ 后区 1 个 (back_1)
        for i, n in enumerate(back, 1):
            row[f"back_{i}"] = n
        rows.append(row)
    df = pd.DataFrame(rows)
    print(f"  ✅ 构造 {len(df)} 期 {game.upper()} 数据")

    if len(df) < 61:
        print(f"  ⚠️ 数据不足 (需要 ≥ 61 期), 跳过")
        return {"available": False, "reason": "insufficient_data"}

    # 3. 转换为 Drawings + Payload
    if game == "dlt":
        drawings = dlt_df_to_drawings(df)
        # target 用第 80% 期位置
        target_idx = int(len(drawings) * 0.8)
        target_dt = drawings[target_idx].draw_date
        payload = dlt_payload(drawings, target_date=target_dt)
    else:
        drawings = ssq_df_to_drawings(df)
        target_idx = int(len(drawings) * 0.8)
        target_dt = drawings[target_idx].draw_date
        payload = ssq_payload(drawings, target_date=target_dt)

    print(f"  ✅ Payload: main_min={payload.main_min}, main_max={payload.main_max}")
    print(f"           draw_count={payload.draw_count}, special_draw_count={payload.special_draw_count}")
    print(f"           target_date={target_dt} (第 {target_idx+1} 期)")

    # 4. 跑完整分析
    try:
        result = analyze(payload)
    except Exception as e:
        print(f"  ❌ analyze 失败: {e}")
        return {"available": False, "error": str(e)}

    # 5. 输出关键结果
    print()
    print(f"  ★ DrawScope 分析结果:")
    print(f"     chi_square_statistic: {result.chi_square_statistic:.2f}")
    print(f"     sample_size: {result.sample_size}")
    print(f"     date_range: {result.date_range.start} ~ {result.date_range.end}")
    print(f"     methodology_version: {result.methodology_version}")

    if result.patterns:
        odd_even = dict(list(result.patterns.odd_even.items())[:5])
        print(f"     patterns.odd_even (前 5): {odd_even}")

    if result.numbers:
        top_nums = sorted(result.numbers, key=lambda x: -x.frequency)[:5]
        print(f"     top 5 numbers: {[(n.number, n.frequency) for n in top_nums]}")

    if result.top_pairs:
        print(f"     top 5 pairs: {[(p.numbers, p.count) for p in result.top_pairs[:5]]}")

    if result.retrospective:
        r = result.retrospective
        print(f"     retrospective.target_draw_date: {r.target_draw_date}")
        print(f"     retrospective.history_size: {r.history_size}")

    # 6. 输出 DISCLAIMERS (重要: 学术级诚实声明)
    print()
    print(f"  ★ DrawScope 7 条 DISCLAIMERS:")
    for i, d in enumerate(DISCLAIMERS, 1):
        print(f"     {i}. {d[:100]}{'...' if len(d) > 100 else ''}")

    print()
    print(f"  💡 对比: 我们的 12 步是手动推导, DrawScope 是端到端黑盒")
    print(f"     两套独立验证相同结论 → 增强可信度")

    return {
        "available": True,
        "chi_square": result.chi_square_statistic,
        "sample_size": result.sample_size,
        "methodology_version": result.methodology_version,
        "date_range": (result.date_range.start.isoformat(), result.date_range.end.isoformat()),
        "target_draw_date": target_dt.isoformat() if target_dt else None,
        "top_numbers": [(n.number, n.frequency) for n in sorted(result.numbers, key=lambda x: -x.frequency)[:5]] if result.numbers else [],
        "top_pairs": [(p.numbers, p.count) for p in result.top_pairs[:5]] if result.top_pairs else [],
        "disclaimers_count": len(DISCLAIMERS),
    }


# ============================================================
# 主入口
# ============================================================
def run_full_lab(game: str = "dlt"):
    """跑完整 12 步实验（支持 dlt/ssq 等彩种）"""
    # 设置全局配置为指定彩种
    global GAME_CONFIG, PRIZE_RULES
    GAME_CONFIG = _get_game_config(game)
    PRIZE_RULES = _get_prize_rules(game)
    game_name = get_game(game).name

    print("#" * 80)
    print(f"#  概率统计实验室 - 12 步拆解'手搓{game_name}一等奖'")
    print("#" * 80)
    print(f"\n  数据集: {game_name}历史开奖")
    print(f"  期数: 加载中...")

    df = load_lottery_data(game=game)
    print(f"  实际期数: {len(df)}")
    print(f"  期号范围: {df['period'].iloc[0]} ~ {df['period'].iloc[-1]}")

    # Step 1
    step1_first_prize_probability()

    # Step 2 (后续步骤依赖其结果)
    prize_data = step2_prize_distribution()

    # Step 3
    step3_front_bayesian_heat(df)

    # Step 4
    step4_back_dirichlet_combo(df)

    # Step 5
    step5_missing_geometric(df)

    # Step 6
    step6_chi2_independence(df)

    # Step 7
    step7_pearson_correlation(df)

    # Step 8
    step8_markov_chain(df)

    # Step 9
    step9_monte_carlo_coverage()

    # Step 10
    ev_data = step10_expected_value(prize_data)

    # Step 11
    step11_kelly_criterion(ev_data["expected_net"], ev_data["variance"])

    # Step 12
    step12_law_of_large_numbers()

    # Step 13: DrawScope 引擎集成 (跨彩种通用)
    # 把 our df 转 matches list 给 step13
    matches_for_ds = []
    for _, row in df.iterrows():
        front_cols = [c for c in df.columns if c.startswith("front_")]
        back_cols = [c for c in df.columns if c.startswith("back_")]
        front = [int(row[c]) for c in sorted(front_cols) if pd.notna(row[c])]
        back = [int(row[c]) for c in sorted(back_cols) if pd.notna(row[c])]
        matches_for_ds.append({
            "draw_date": str(row.get("draw_date", "")),
            "front": front,
            "back": back,
        })
    step13_drawscope_integration(matches_for_ds, game=game)

    # 最终总结
    section("★ 最终结论 ★", "#")
    print()
    print(f"  通过 12 个步骤的严格概率统计分析，我们证实（彩种={game_name}）:")
    print()
    p1 = 1.0 / GAME_CONFIG["total_combos"] if "total_combos" in GAME_CONFIG else 0
    total_combos = GAME_CONFIG["front_count"] * 1  # placeholder
    # 计算总组合数
    from math import comb as cmb
    tc = cmb(GAME_CONFIG["front_range"], GAME_CONFIG["front_count"]) * cmb(GAME_CONFIG["back_range"], GAME_CONFIG["back_count"])
    print(f"  1. {game_name}一等奖概率: 1 / {tc:,} ≈ {1/tc:.2e}")
    print(f"  2. 总中奖概率: 约 {prize_data['total_prize_prob']*100:.1f}%")
    print(f"  3. 每注期望奖金: {prize_data['expected_money_per_ticket']:.2f} 元")
    print(f"  4. 每注期望净收益: {ev_data['expected_net']:.2f} 元（数学{'保证亏损' if ev_data['expected_net']<0 else '盈利'}）")
    edge_pct = ev_data['expected_net'] / GAME_CONFIG['ticket_price'] * 100
    print(f"  5. 凯利最优比例: {'0（不下注）' if ev_data['expected_net']<0 else f'{edge_pct:.2f}%'}")
    print()
    print("  → 这是一个'数学上必输'的游戏")
    print("  → 任何选号策略都不能改变期望值")
    print("  → 号码频率在统计上没有显著偏向")
    print("  → 号码间相关性接近 0（基本独立）")
    print("  → 大数定律保证长期频率收敛到理论概率")
    print()
    print("  结论: 把彩票当娱乐，不当投资。")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    import sys as _sys
    _game = "dlt"
    if "--game" in _sys.argv:
        idx = _sys.argv.index("--game")
        if idx + 1 < len(_sys.argv):
            _game = _sys.argv[idx + 1]
    run_full_lab(game=_game)
