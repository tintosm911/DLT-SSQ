"""
近期热号榜 —— 按最近 N 期真实开奖统计
=========================================
给你一份**现成的热度榜**, 不用自己翻走势图排序。

输出每个号码的:
  出现次数 / 期望次数 / 偏离度 z 值 / 当前遗漏期数 / 最大遗漏

★ 为什么要给 z 值:
  "热号"如果只是"最近出现得多", 那很可能只是**随机波动**。
  z = (实际次数 - 期望次数) / 标准差
    z > +2  → 统计上确实偏热 (大约 2.5% 的概率纯随机会出现)
    |z| < 1 → 完全是噪声, 别当信号用
  所以榜里直接标出来 —— 哪些是真热, 哪些只是看着热。

用法:
  python scripts/hot_numbers.py --game dlt --n 30
  python scripts/hot_numbers.py --game ssq --n 50 --top 15
  python scripts/hot_numbers.py --game dlt --n 100 --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from math import sqrt
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.games import get_game

DB = PROJECT_ROOT / 'data-raw' / 'lottery.db'


def _load(game: str, n: int):
    """取最近 n 期开奖 → (期号列表, 每期前区, 每期后区)"""
    con = sqlite3.connect(str(DB))
    rows = con.execute(
        'SELECT period, front_numbers, back_numbers FROM draws '
        'WHERE game=? ORDER BY period DESC LIMIT ?', (game, n)).fetchall()
    con.close()
    rows.reverse()
    periods = [r[0] for r in rows]
    fronts = [json.loads(r[1]) for r in rows]
    backs = [json.loads(r[2]) for r in rows]
    return periods, fronts, backs


def _rank_zone(numbers_per_draw, hi, n_draws, draw_count):
    """统计一个区 (前区/后区) 的号码热度"""
    cnt = {v: 0 for v in range(1, hi + 1)}
    last_seen = {v: None for v in range(1, hi + 1)}
    max_gap = {v: 0 for v in range(1, hi + 1)}
    for i, draw in enumerate(numbers_per_draw):
        for v in draw:
            cnt[v] = cnt.get(v, 0) + 1
            if last_seen[v] is not None:
                max_gap[v] = max(max_gap[v], i - last_seen[v])
            last_seen[v] = i
    out = []
    for v in range(1, hi + 1):
        cur_omission = (n_draws - 1 - last_seen[v]) if last_seen[v] is not None \
            else n_draws
        out.append({
            'num': v,
            'count': cnt[v],
            'expect': n_draws * draw_count / hi,
            'z': (cnt[v] - n_draws * draw_count / hi) /
                 sqrt(n_draws * (draw_count / hi) * (1 - draw_count / hi))
                 if n_draws else 0.0,
            'omission': cur_omission,
            'max_omission': max(max_gap[v], cur_omission),
        })
    return out


def _fmt_rows(rows, title, top):
    print(f'  ── {title} ' + '─' * (66 - len(title)))
    print(f'  {"号":<5}{"出现":>5}{"期望":>7}{"z":>7}{"现遗漏":>8}'
          f'{"最大遗漏":>9}   标记')
    hot = [r for r in rows if r['z'] >= 2]
    for r in rows[:top]:
        tag = '★ 真热 (z≥2)' if r['z'] >= 2 else \
              ('· 偏冷' if r['z'] <= -2 else '')
        print(f'  {r["num"]:>02}   {r["count"]:>4}{r["expect"]:>7.1f}'
              f'{r["z"]:>+7.2f}{r["omission"]:>8}{r["max_omission"]:>9}   {tag}')
    if hot:
        print(f'    ★ 统计上真热的号 (z≥2): '
              + ' '.join(f'{r["num"]:02d}' for r in hot))
    else:
        print('    ★ 本期窗口内没有 z≥2 的号 —— "热号"只是随机波动, '
              '没有一个够得上统计显著')
    return hot


def main() -> int:
    ap = argparse.ArgumentParser(description='近期热号榜')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--n', type=int, default=30, help='统计窗口期数')
    ap.add_argument('--top', type=int, default=0, help='每个区显示几个 (0=全列)')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    cfg = get_game(args.game)
    periods, fronts, backs = _load(args.game, args.n)
    if not periods:
        print('❌ 本地库没有开奖数据')
        return 1
    n_draws = len(periods)

    f_rows = _rank_zone(fronts, cfg.front_range, n_draws, cfg.front_count)
    b_rows = _rank_zone(backs, cfg.back_range, n_draws, cfg.back_count)
    f_rows.sort(key=lambda r: (-r['z'], -r['count']))
    b_rows.sort(key=lambda r: (-r['z'], -r['count']))

    if args.json:
        print(json.dumps({
            'game': args.game, 'n_draws': n_draws,
            'period_from': periods[0], 'period_to': periods[-1],
            'front': f_rows, 'back': b_rows,
        }, ensure_ascii=False, indent=2))
        return 0

    top = args.top or cfg.front_range
    print()
    print('=' * 78)
    print(f'  {cfg.name} 近期热号榜 — 最近 {n_draws} 期 '
          f'({periods[0]} ~ {periods[-1]})')
    print('=' * 78)
    _fmt_rows(f_rows, f'前区 {cfg.front_range} 选 {cfg.front_count}', top)
    print()
    _fmt_rows(b_rows, f'后区 {cfg.back_range} 选 {cfg.back_count}',
              args.top or cfg.back_range)
    print()
    print('  ★ z 值 = (实际次数 - 期望次数) / 标准差。z≥2 才算统计上偏热,')
    print('    |z|<1 基本是噪声。号码本身没有预测力 —— 冷热只影响"胆码怎么摆",')
    print('    不影响任何概率 (v2.5.0 定理)。')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
