"""
热号幻觉分析核心库
==================
检验"用最近 N 年的热号去预测之后的开奖"是否有预测力。

三层检验 (从弱到强):
  1. **排名延续性** — 相邻年份的热号排名有没有相关性?
     (Spearman ρ / Top-K 重合度, 都要跟随机期望比)
  2. **命中检验** — 用训练期热号选号, 测试期实际命中数 vs 随机期望
  3. **收益检验** — 按热号持续投注, 真实 ROI 是多少

设计要点:
  - 所有"随机期望"都算出来, 不用"看起来差不多"糊弄
  - z 分数给出统计显著性 (|z| < 2 = 与随机无显著差异)
  - 允许用户换任意训练/测试年份, 自己验证结论是否稳定
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from data.games import get_game
from data.strategy_lab import BIG_PRIZE_LABELS


# ============================================================
# 数据准备
# ============================================================
def load_by_year(game: str) -> Dict[str, List[List[int]]]:
    """把开奖数据按年份分组: {年份: [[前区号...], ...]}"""
    from data.sqlite_storage import SQLiteStorage

    cfg = get_game(game)
    df = SQLiteStorage().load_dataframe(game)
    if df is None or df.empty:
        raise RuntimeError('数据库为空, 请先跑 python main.py crawl --game all')

    by_year: Dict[str, List[List[int]]] = collections.defaultdict(list)
    for _, row in df.iterrows():
        period = str(row['period'])
        year = period[:4]
        front = [int(row[f'front_{i+1}']) for i in range(cfg.front_count)]
        by_year[year].append(front)
    return dict(by_year)


def hot_ranking(draws: Sequence[Sequence[int]], front_range: int
                ) -> Tuple[List[Tuple[int, int]], Dict[int, int]]:
    """
    计算热号排名.
    返回 (排序后的 [(号码, 出现次数)], {号码: 排名})
    """
    cnt = collections.Counter()
    for nums in draws:
        cnt.update(nums)
    order = sorted(range(1, front_range + 1),
                   key=lambda v: (-cnt.get(v, 0), v))
    ranked = [(v, cnt.get(v, 0)) for v in order]
    rank_map = {v: i + 1 for i, v in enumerate(order)}
    return ranked, rank_map


def spearman(r1: Dict[int, int], r2: Dict[int, int], front_range: int) -> float:
    """两个排名的 Spearman 相关系数"""
    xs = np.array([r1[v] for v in range(1, front_range + 1)], dtype=float)
    ys = np.array([r2[v] for v in range(1, front_range + 1)], dtype=float)
    rx = np.argsort(np.argsort(xs)).astype(float)
    ry = np.argsort(np.argsort(ys)).astype(float)
    rx -= rx.mean()
    ry -= ry.mean()
    denom = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / denom) if denom else 0.0


# ============================================================
# 检验 1: 排名延续性
# ============================================================
def test_continuity(by_year: Dict[str, List[List[int]]], game: str,
                    top_k: int = 10) -> Dict:
    """相邻年份热号排名的重合度与相关性"""
    cfg = get_game(game)
    fr = cfg.front_range
    years = sorted(by_year.keys())

    ranks = {}
    for y in years:
        if len(by_year[y]) < 20:
            continue
        _, rm = hot_ranking(by_year[y], fr)
        ranks[y] = rm

    ry = sorted(ranks.keys())
    pairs = []
    for i in range(len(ry) - 1):
        y1, y2 = ry[i], ry[i + 1]
        t1 = set(sorted(range(1, fr + 1), key=lambda v: ranks[y1][v])[:top_k])
        t2 = set(sorted(range(1, fr + 1), key=lambda v: ranks[y2][v])[:top_k])
        overlap = len(t1 & t2)
        rho = spearman(ranks[y1], ranks[y2], fr)
        pairs.append({'y1': y1, 'y2': y2, 'overlap': overlap,
                      'rho': round(rho, 4), 'top1': sorted(t1),
                      'top2': sorted(t2)})

    if not pairs:
        return {'pairs': [], 'verdict': '数据不足'}

    exp_overlap = top_k * top_k / fr
    sd_overlap = float(np.sqrt(
        top_k * (fr - top_k) / (fr - 1) * (top_k / fr) * (1 - top_k / fr)))
    mean_ov = float(np.mean([p['overlap'] for p in pairs]))
    z_ov = (mean_ov - exp_overlap) / sd_overlap if sd_overlap else 0.0

    mean_rho = float(np.mean([p['rho'] for p in pairs]))
    se_rho = 1 / np.sqrt(fr - 1)
    z_rho = mean_rho / se_rho if se_rho else 0.0

    return {
        'pairs': pairs,
        'top_k': top_k,
        'overlap_mean': round(mean_ov, 2),
        'overlap_expected': round(exp_overlap, 2),
        'overlap_z': round(z_ov, 2),
        'rho_mean': round(mean_rho, 4),
        'rho_z': round(z_rho, 2),
        'verdict': ('排名不跨年延续, 热号无预测力'
                    if abs(z_ov) < 2 and abs(z_rho) < 2
                    else '排名有显著延续性, 值得进一步看'),
    }


# ============================================================
# 检验 2 + 3: 命中与收益
# ============================================================
def test_predictive(by_year: Dict[str, List[List[int]]], game: str,
                    train_years: Sequence[str], test_years: Sequence[str],
                    top_k: int = 10, pick_n: int = 5) -> Dict:
    """
    用 train_years 的热号预测 test_years.

    - 热号在测试期的实际出现次数 vs 均匀分布期望
    - 若每期都买 Top-N 热号, 实际命中数 vs 随机期望
    - 若真按这个策略买满测试期, 真实 ROI
    """
    from data.pick_advisor import Pick, judge_prize

    cfg = get_game(game)
    fr, fc = cfg.front_range, cfg.front_count

    train_draws = [d for y in train_years for d in by_year.get(y, [])]
    test_draws = [d for y in test_years for d in by_year.get(y, [])]
    if not train_draws or not test_draws:
        raise ValueError('训练期或测试期无数据')

    ranked, _ = hot_ranking(train_draws, fr)
    top_hot = [v for v, _ in ranked[:top_k]]
    pick_set = sorted(top_hot[:pick_n])

    # --- 每个热号在测试期的表现 ---
    test_cnt = collections.Counter()
    for nums in test_draws:
        test_cnt.update(nums)
    n_test = len(test_draws)
    expected_each = n_test * fc / fr
    var_each = expected_each * (1 - fc / fr)

    per_num = []
    for v, cnt in ranked[:top_k]:
        got = test_cnt.get(v, 0)
        z = (got - expected_each) / (var_each ** 0.5) if var_each > 0 else 0
        per_num.append({
            'num': v,
            'train_count': cnt,
            'train_rank': [x for x, _ in ranked].index(v) + 1,
            'test_count': got,
            'expected': round(expected_each, 1),
            'z': round(z, 2),
            'above': got > expected_each,
        })

    hot_avg = sum(p['test_count'] for p in per_num) / len(per_num)
    hot_z = ((hot_avg - expected_each) / (var_each / len(per_num)) ** 0.5
             if var_each > 0 else 0)

    # --- 每期都买 Top-N 热号的实际命中 ---
    actual_hits = sum(len(set(nums) & set(pick_set)) for nums in test_draws)
    exp_hits = n_test * pick_n * fc / fr
    var_hits = exp_hits * (1 - fc / fr)
    hit_z = ((actual_hits - exp_hits) / (var_hits ** 0.5)
             if var_hits > 0 else 0)

    # --- 如果真按这个策略买满测试期, 真实 ROI ---
    total_stake = 0.0
    total_return = 0.0
    big_prizes = 0
    returns_ex_big = 0.0
    prize_counts: Dict[str, int] = {}
    for nums in test_draws:
        prize, money = judge_prize(game, Pick(front=pick_set,
                                               back=[1] * cfg.back_count),
                                   list(nums), [1] * cfg.back_count)
        total_stake += cfg.ticket_price
        total_return += money
        if money > 0:
            prize_counts[prize] = prize_counts.get(prize, 0) + 1
            # 大奖按奖级名判定 (SSQ 三等奖 3000 元, 用 1 万阈值会漏)
            if prize in BIG_PRIZE_LABELS:
                big_prizes += 1
            else:
                returns_ex_big += money

    roi_ex_big = ((returns_ex_big - total_stake) / total_stake * 100
                  if total_stake else 0.0)

    return {
        'train_years': list(train_years),
        'test_years': list(test_years),
        'train_draws': len(train_draws),
        'test_draws': n_test,
        'top_k': top_k,
        'pick_set': pick_set,
        'per_num': per_num,
        'hot_avg_count': round(hot_avg, 1),
        'hot_expected': round(expected_each, 1),
        'hot_z': round(hot_z, 2),
        'actual_hits': actual_hits,
        'expected_hits': round(exp_hits, 1),
        'hit_z': round(hit_z, 2),
        'stake': round(total_stake, 0),
        'returns': round(total_return, 0),
        'net': round(total_return - total_stake, 0),
        'roi': round((total_return - total_stake) / total_stake * 100, 2)
               if total_stake else 0.0,
        'roi_ex_big': round(roi_ex_big, 2),
        'big_prizes': big_prizes,
        'prizes': sorted(prize_counts.items(), key=lambda x: -x[1]),
    }


def _recent_from(years: Sequence[str], n: int) -> Optional[str]:
    """最近 n 个年份的起始年 (不足则返回 None = 不限制)"""
    if len(years) <= n:
        return None
    return years[-n]


# ============================================================
# 稳定性扫描: 遍历所有切分, 看结论稳不稳
# ============================================================
def stability_scan(game: str = 'dlt', top_k: int = 10, pick_n: int = 5,
                   min_train_years: int = 2, test_years_n: int = 2,
                   recent_from: Optional[str] = None) -> Dict:
    """
    遍历所有可能的 (训练期, 测试期) 切分, 统计热号"看起来有效"的比例.

    这是击碎幻觉的最强论证:
      如果换成任何别的年份切分, 结论都还是"和随机一样",
      那么"这次有效"就纯粹是挑数据挑出来的.
    """
    cfg = get_game(game)
    by_year = load_by_year(game)
    years = sorted(by_year.keys())
    if recent_from:
        years = [y for y in years if y >= recent_from]
    if len(years) < min_train_years + test_years_n:
        return {'splits': [], 'verdict': '年份不足'}

    splits = []
    for i in range(len(years) - min_train_years - test_years_n + 1):
        train = years[i:i + min_train_years]
        test = years[i + min_train_years:i + min_train_years + test_years_n]
        try:
            pred = test_predictive(by_year, game, train, test, top_k, pick_n)
        except Exception:
            continue
        splits.append({
            'train': train, 'test': test,
            'hit_z': pred['hit_z'],
            'hot_z': pred['hot_z'],
            'roi': pred['roi'],
            'roi_ex_big': pred['roi_ex_big'],
            'big_prizes': pred['big_prizes'],
            'actual_hits': pred['actual_hits'],
            'expected_hits': pred['expected_hits'],
            'significant': abs(pred['hit_z']) >= 2,
            'better': pred['hit_z'] > 0,
        })

    if not splits:
        return {'splits': [], 'verdict': '无可用切分'}

    n = len(splits)
    n_sig = sum(1 for s in splits if s['significant'])
    n_sig_better = sum(1 for s in splits if s['significant'] and s['better'])
    n_better = sum(1 for s in splits if s['better'])
    mean_z = float(np.mean([s['hit_z'] for s in splits]))
    mean_roi = float(np.mean([s['roi'] for s in splits]))
    mean_roi_ex_big = float(np.mean([s['roi_ex_big'] for s in splits]))
    n_with_big = sum(1 for s in splits if s['big_prizes'] > 0)

    # 如果显著性是随机的, 期望 5% 的切分会显著 (双侧)
    expected_sig = 0.05 * n
    return {
        'splits': splits,
        'count': n,
        'significant_count': n_sig,
        'significant_better_count': n_sig_better,
        'better_count': n_better,
        'expected_significant': expected_sig,
        'mean_z': round(mean_z, 3),
        'mean_roi': round(mean_roi, 2),
        'mean_roi_ex_big': round(mean_roi_ex_big, 2),
        'splits_with_big_prize': n_with_big,
        'min_train_years': min_train_years,
        'test_years_n': test_years_n,
        'verdict': (
            f'{n} 种切分中, 仅 {n_sig} 种显著偏离随机 (随机预期约 {expected_sig:.1f} 种), '
            f'其中真正"更好"的仅 {n_sig_better} 种; '
            f'平均 z = {mean_z:+.3f}, 平均 ROI = {mean_roi:+.1f}% '
            f'(剔除大奖后 {mean_roi_ex_big:+.1f}%)'
        ),
    }


# ============================================================
# 主入口
# ============================================================
def analyze_hot_illusion(game: str = 'dlt',
                          train_years: Optional[Sequence[str]] = None,
                          test_years: Optional[Sequence[str]] = None,
                          top_k: int = 10, pick_n: int = 5,
                          recent_only: bool = True) -> Dict:
    """
    热号幻觉完整分析.

    train_years / test_years: 字符串列表, 如 ['2022','2023','2024']
    recent_only=True 时默认用最近 5 年 (前 3 年训练, 后 2 年测试)
    """
    cfg = get_game(game)
    by_year = load_by_year(game)
    years = sorted(by_year.keys())

    if train_years is None or test_years is None:
        if not recent_only or len(years) < 5:
            train_years = train_years or years[:-2]
            test_years = test_years or years[-2:]
        else:
            train_years = years[-5:-2]
            test_years = years[-2:]

    train_years = [str(y) for y in train_years]
    test_years = [str(y) for y in test_years]

    cont = test_continuity(by_year, game, top_k)
    pred = test_predictive(by_year, game, train_years, test_years,
                            top_k, pick_n)
    scan = stability_scan(game, top_k, pick_n,
                           recent_from=_recent_from(years, 6))

    # 结论
    lines = []
    if abs(pred['hit_z']) < 2:
        lines.append(f'用 {train_years[0]}-{train_years[-1]} 年的热号预测 '
                     f'{test_years[0]}-{test_years[-1]}: 实际命中 {pred["actual_hits"]} 个, '
                     f'随机期望 {pred["expected_hits"]} 个 (z={pred["hit_z"]:+.2f}) '
                     f'→ 与随机无显著差异')
    else:
        better = pred['hit_z'] > 0
        lines.append(f'用 {train_years[0]}-{train_years[-1]} 年的热号预测 '
                     f'{test_years[0]}-{test_years[-1]}: 实际命中 {pred["actual_hits"]} 个, '
                     f'随机期望 {pred["expected_hits"]} 个 (z={pred["hit_z"]:+.2f}) '
                     f'→ {"显著" if better else "显著反向"}偏离随机')
    lines.append(f'热号在测试期平均出现 {pred["hot_avg_count"]} 次 vs 随机期望 '
                 f'{pred["hot_expected"]} 次 (z={pred["hot_z"]:+.2f})')
    lines.append(f'排名延续性: 相邻年 Top-{top_k} 重合 {cont["overlap_mean"]} '
                 f'(随机 {cont["overlap_expected"]}, z={cont["overlap_z"]:+.2f}), '
                 f'ρ={cont["rho_mean"]:+.3f} (z={cont["rho_z"]:+.2f})')
    lines.append(f'若照着热号买满测试期 {pred["test_draws"]} 期: '
                 f'投入 {pred["stake"]:,.0f} 元, 返奖 {pred["returns"]:,.0f} 元, '
                 f'ROI {pred["roi"]:+.1f}%')
    if scan.get('splits'):
        lines.append(f'稳定性扫描: {scan["verdict"]}')

    return {
        'ok': True,
        'game': game,
        'game_name': cfg.name,
        'front_range': cfg.front_range,
        'front_count': cfg.front_count,
        'ticket_price': cfg.ticket_price,
        'all_years': years,
        'train_years': train_years,
        'test_years': test_years,
        'continuity': cont,
        'predictive': pred,
        'scan': scan,
        'conclusion': ' | '.join(lines),
    }


__all__ = [
    'load_by_year', 'hot_ranking', 'spearman',
    'test_continuity', 'test_predictive', 'analyze_hot_illusion',
]
