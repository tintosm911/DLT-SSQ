"""
热号预测力检验 (先验证用户的直觉, 再决定怎么写演示器)
=====================================================
核心问题: 用 N 年数据算出的"热号", 对第 N+1 年有预测力吗?

统计检验思路:
  1. 年份间热号排名重合度 (Top-K 交集) vs 随机期望
  2. 年份间热号排名 Spearman 相关 vs 随机期望
  3. 用热号选号的实际命中率 vs 随机期望
"""
import csv
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np

GAMES = {'dlt': (5, 35, 'data-raw/gh_dlt.csv'),
         'ssq': (6, 33, 'data-raw/gh_ssq.csv')}


def load(game):
    fcols, fr, path = GAMES[game]
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    by_year = collections.defaultdict(list)
    for r in rows:
        nums = []
        ok = True
        for i in range(1, fcols + 1):
            v = r.get(f'front_{i}')
            if v is None or not str(v).strip():
                ok = False
                break
            nums.append(int(v))
        if ok:
            by_year[str(r['period'])[:4]].append(nums)
    return by_year, fcols, fr


def rank_of(year_nums, fr):
    """返回每个号的热度排名 (1 = 最热)"""
    cnt = collections.Counter()
    for nums in year_nums:
        cnt.update(nums)
    order = sorted(range(1, fr + 1), key=lambda v: (-cnt.get(v, 0), v))
    rank = {v: i + 1 for i, v in enumerate(order)}
    return rank, cnt


def spearman(r1, r2, fr):
    xs = np.array([r1[v] for v in range(1, fr + 1)], dtype=float)
    ys = np.array([r2[v] for v in range(1, fr + 1)], dtype=float)
    rx = np.argsort(np.argsort(xs)).astype(float)
    ry = np.argsort(np.argsort(ys)).astype(float)
    rx -= rx.mean(); ry -= ry.mean()
    denom = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / denom) if denom else 0.0


def main():
    for game in ('dlt', 'ssq'):
        by_year, fcols, fr = load(game)
        years = sorted(by_year.keys())
        print('=' * 74)
        print(f'  {game.upper()} 热号预测力检验  ({len(years)} 年数据)')
        print('=' * 74)

        ranks = {y: rank_of(by_year[y], fr)[0] for y in years}

        # --- 1. 相邻年 Top-K 重合度 ---
        print()
        print('  【1】相邻年份 Top-10 热号重合度')
        print(f'      {"年份对":<14}{"实际重合":>9}{"随机期望":>11}{"偏差":>8}')
        overlaps = []
        for i in range(len(years) - 1):
            y1, y2 = years[i], years[i + 1]
            top1 = set(sorted(range(1, fr + 1), key=lambda v: ranks[y1][v])[:10])
            top2 = set(sorted(range(1, fr + 1), key=lambda v: ranks[y2][v])[:10])
            ov = len(top1 & top2)
            exp = 10 * 10 / fr
            overlaps.append(ov)
            print(f'      {y1}→{y2:<9}{ov:>9}{exp:>11.2f}{ov-exp:>+8.2f}')
        if overlaps:
            mean_ov = np.mean(overlaps)
            exp_ov = 10 * 10 / fr
            sd = np.sqrt(10 * (fr - 10) / (fr - 1) * (10 / fr) * (1 - 10 / fr))
            z = (mean_ov - exp_ov) / sd if sd else 0
            print(f'      平均 {mean_ov:.2f} vs 随机期望 {exp_ov:.2f} '
                  f'(σ {sd:.2f}, z = {z:+.2f})')
            if abs(z) < 2:
                print(f'      → ✅ 与随机无显著差异, 热号排名不跨年延续')
            else:
                print(f'      → ⚠️ 与随机有显著差异 (z={z:+.2f})')

        # --- 2. 相邻年排名相关性 ---
        print()
        print('  【2】相邻年份热号排名 Spearman 相关')
        cors = []
        for i in range(len(years) - 1):
            y1, y2 = years[i], years[i + 1]
            c = spearman(ranks[y1], ranks[y2], fr)
            cors.append(c)
            print(f'      {y1} → {y2}:  ρ = {c:+.4f}')
        if cors:
            m = np.mean(cors)
            se = 1 / np.sqrt(fr - 1)
            z = m / se
            print(f'      平均 ρ = {m:+.4f} (随机期望 0, 近似标准误 {se:.4f}, z = {z:+.2f})')
            if abs(z) < 2:
                print('      → ✅ 与随机无显著差异')
            else:
                print(f'      → ⚠️ 与随机有显著差异 (z={z:+.2f})')

        # --- 3. 用 2022-2024 热号预测 2025-2026 ---
        print()
        print('  【3】"用前 3 年热号预测后 2 年"的实际效果')
        recent = [y for y in years if y >= '2022']
        if len(recent) >= 4:
            train_years = recent[:-2]
            test_years = recent[-2:]
            train_nums = [nums for y in train_years for nums in by_year[y]]
            train_cnt = collections.Counter()
            for nums in train_nums:
                train_cnt.update(nums)
            top = sorted(range(1, fr + 1), key=lambda v: (-train_cnt.get(v, 0), v))[:10]

            test_cnt = collections.Counter()
            test_total = 0
            for y in test_years:
                for nums in by_year[y]:
                    test_cnt.update(nums)
                    test_total += 1
            expected_each = test_total * fcols / fr

            print(f'      训练期 {train_years[0]}-{train_years[-1]} 的 Top-10 热号: '
                  f'{top}')
            print(f'      测试期 {test_years[0]}-{test_years[-1]} ({test_total} 期) 的实际表现:')
            hit_sum = 0
            for v in top:
                got = test_cnt.get(v, 0)
                hit_sum += got
                z = (got - expected_each) / (expected_each * (1 - fcols / fr)) ** 0.5
                flag = '★' if got > expected_each else ' '
                print(f'        {v:>2}: 出现 {got:>4} 次 (期望 {expected_each:.1f}, '
                      f'z={z:+5.2f}) {flag}')
            avg_hit = hit_sum / len(top)
            print(f'      热号平均出现 {avg_hit:.1f} 次 vs 随机期望 {expected_each:.1f} 次 '
                  f'→ {"高于" if avg_hit > expected_each else "低于"}随机 '
                  f'{abs(avg_hit - expected_each) / expected_each * 100:.1f}%')

            # 如果每期都买这个 Top-10 里的 5 个号
            hot_pick = sorted(top[:5])
            print(f'      若每期都买 {hot_pick} (训练期 Top-5 热号):')
            actual = 0
            n_draws = 0
            for y in test_years:
                for nums in by_year[y]:
                    n_draws += 1
                    actual += len(set(nums) & set(hot_pick))
            exp_hits = n_draws * 5 * fcols / fr
            z = (actual - exp_hits) / (exp_hits * (1 - fcols / fr)) ** 0.5
            print(f'        实际命中 {actual} 个 vs 随机期望 {exp_hits:.1f} 个 '
                  f'(z = {z:+.2f})')
            print(f'        {"✅ 与随机无差异, 热号无预测力" if abs(z) < 2 else "⚠️ 有显著差异"}')
        print()


if __name__ == '__main__':
    main()
