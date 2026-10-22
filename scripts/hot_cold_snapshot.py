"""
当前冷热号快照
================
算出"截至最新一期的冷热号排名", 并明确它的性质:
  - 这是**描述性**指标 (过去多热), 不是**预测性** (下期开什么)
  - 配套给出"随机期望"对照, 让人自己判断偏离是否显著

用法:
  python scripts/hot_cold_snapshot.py
  python scripts/hot_cold_snapshot.py --game ssq --window 100
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np

from data.games import get_game


def build_onehot(df, cfg):
    fh, bh = cfg.front_range, cfg.back_range
    f_mat = np.zeros((len(df), fh), dtype=np.int8)
    b_mat = np.zeros((len(df), bh), dtype=np.int8)
    for i, (_, row) in enumerate(df.iterrows()):
        for j in range(cfg.front_count):
            n = int(row[f'front_{j+1}'])
            if 1 <= n <= fh:
                f_mat[i, n - 1] = 1
        for j in range(cfg.back_count):
            n = int(row[f'back_{j+1}'])
            if 1 <= n <= bh:
                b_mat[i, n - 1] = 1
    return f_mat, b_mat


def missing_values(onehot, n_range):
    """每个号距上次出现的期数"""
    n = onehot.shape[0]
    out = np.zeros(n_range + 1, dtype=int)
    for v in range(1, n_range + 1):
        col = onehot[:, v - 1]
        idx = np.where(col > 0)[0]
        out[v] = (n - 1 - idx[-1]) if len(idx) else n
    return out


def main():
    ap = argparse.ArgumentParser(description='冷热号快照')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--window', type=int, default=0,
                    help='只看最近 N 期 (0 = 全部)')
    ap.add_argument('--top', type=int, default=10, help='显示前 N 个')
    args = ap.parse_args()

    from data.sqlite_storage import SQLiteStorage
    cfg = get_game(args.game)
    df = SQLiteStorage().load_dataframe(args.game)
    if df.empty:
        print('数据库为空')
        return 1
    if args.window:
        df = df.tail(args.window)

    f_mat, b_mat = build_onehot(df, cfg)
    n = len(df)

    from core import compute_all_heat_scores

    f_scores = compute_all_heat_scores(f_mat, cfg.front_range)
    b_scores = compute_all_heat_scores(b_mat, cfg.back_range)
    f_miss = missing_values(f_mat, cfg.front_range)
    b_miss = missing_values(b_mat, cfg.back_range)

    comp_f = f_scores['composite']
    comp_b = b_scores['composite']

    print()
    print('=' * 74)
    print(f'  冷热号快照  —  {cfg.name}  截至第 {df.iloc[-1]["period"]} 期 '
          f'({df.iloc[-1].get("draw_date","")})')
    print(f'  样本: 最近 {n} 期')
    print('=' * 74)
    print('  这是**描述过去**的排名, 不是**预测下期**.')
    print('  配套给出随机期望对照: 偏离在 ±2σ 内 = 与随机无差异.')

    for label, comp, miss, n_range, cnt in (
            (cfg.front_label, comp_f, f_miss, cfg.front_range, f_mat.sum(axis=0)),
            (cfg.back_label, comp_b, b_miss, cfg.back_range, b_mat.sum(axis=0))):
        def sc(v, _c=comp):
            i = v - 1
            return float(_c[i]) if 0 <= i < len(_c) else 50.0

        print()
        print(f'  【{label} 1-{n_range}】')
        order = sorted(range(1, n_range + 1), key=lambda v: -sc(v))
        print(f'    最热 Top{args.top}:')
        hot_str = '  '.join(
            f'{v:02d}({sc(v):.0f}分/{int(cnt[v-1])}次/遗漏{int(miss[v])})'
            for v in order[:args.top])
        print(f'      {hot_str}')
        print(f'    最冷 Top{args.top}:')
        cold_str = '  '.join(
            f'{v:02d}({sc(v):.0f}分/{int(cnt[v-1])}次/遗漏{int(miss[v])})'
            for v in order[-args.top:][::-1])
        print(f'      {cold_str}')

    print()
    print('  格式: 号码(百分位分/出现次数/遗漏期数)')
    print()


if __name__ == '__main__':
    main()
