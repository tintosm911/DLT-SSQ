"""
多源合并采集器
==============
把 zhcw.com (2019-12 ~ 2020-10, 含真实日期) 和
chart.ttzoushi.com (2026-03 ~ 2026-10) 合并,
并允许接入未来的数据源。

输出: data-raw/merged_{game}.csv  (按期号排序, 真实日期优先)
"""
from __future__ import annotations
import os
import sys
import csv
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / 'data-raw'
DATA_RAW.mkdir(parents=True, exist_ok=True)

GAMES = {
    'dlt': {'name': '超级大乐透', 'front_count': 5, 'front_range': (1, 35),
            'back_count': 2, 'back_range': (1, 12)},
    'ssq': {'name': '双色球', 'front_count': 6, 'front_range': (1, 33),
            'back_count': 1, 'back_range': (1, 16)},
}


def read_csv(path: Path, game: str) -> List[Dict]:
    cfg = GAMES[game]
    if not path.exists():
        return []
    out = []
    with open(path, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                front = [int(row[f'front_{i+1}']) for i in range(cfg['front_count'])]
                back = [int(row[f'back_{i+1}']) for i in range(cfg['back_count'])]
            except (KeyError, ValueError):
                continue
            out.append({
                'period': row['period'].strip(),
                'draw_date': row.get('draw_date', '').strip(),
                'front': sorted(front),
                'back': sorted(back),
            })
    return out


def merge(game: str, sources: List[str], verbose: bool = True) -> List[Dict]:
    """
    合并多个源。
    规则: 同期号保留 draw_date 非空的那个 (真实日期优先)。
    """
    cfg = GAMES[game]
    merged: Dict[str, Dict] = {}

    for src in sources:
        path = DATA_RAW / f'{src}_{game}.csv'
        recs = read_csv(path, game)
        if not recs:
            if verbose:
                print(f'  {src}: 无数据')
            continue

        added = dated = 0
        for r in recs:
            p = r['period']
            if p not in merged:
                merged[p] = r
                added += 1
                if r['draw_date']:
                    dated += 1
            else:
                # 已有记录, 只补日期
                if not merged[p]['draw_date'] and r['draw_date']:
                    merged[p]['draw_date'] = r['draw_date']
                    dated += 1

        if verbose:
            with_date = sum(1 for r in recs if r['draw_date'])
            print(f'  {src}: {len(recs)} 期 (其中 {with_date} 期有真实日期), 新增 {added}')

    records = sorted(merged.values(), key=lambda x: x['period'])

    out = DATA_RAW / f'merged_{game}.csv'
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['period', 'draw_date']
                   + [f'front_{i+1}' for i in range(cfg['front_count'])]
                   + [f'back_{i+1}' for i in range(cfg['back_count'])])
        for r in records:
            w.writerow([r['period'], r['draw_date']] + r['front'] + r['back'])

    if verbose:
        print(f'  ✅ 合并 {len(records)} 期 → {out}')
    return records


def validate(game: str, records: List[Dict]) -> None:
    cfg = GAMES[game]
    print(f'  --- {cfg["name"]} 合并后质量检查 ---')
    print(f'    期数: {len(records)}')
    if records:
        print(f'    期号: {records[0]["period"]} ~ {records[-1]["period"]}')

    dated = [r for r in records if r['draw_date']]
    print(f'    真实日期: {len(dated)}/{len(records)} 期')
    if dated:
        dates = sorted(r['draw_date'] for r in dated)
        print(f'    日期跨度: {dates[0]} ~ {dates[-1]}')

    # 连续性检查 (只针对有日期的连续段)
    if len(dated) >= 2:
        from datetime import datetime
        ds = sorted(r['draw_date'] for r in dated)
        try:
            gaps = []
            for a, b in zip(ds, ds[1:]):
                da = datetime.fromisoformat(a)
                db = datetime.fromisoformat(b)
                gap = (db - da).days
                if gap > 7:
                    gaps.append(f'{a}→{b} ({gap}天)')
            if gaps:
                print(f'    ⚠ 时间断点: {", ".join(gaps[:5])}')
            else:
                print(f'    ✅ 日期连续 (无 >7 天空洞)')
        except Exception:
            pass

    if len(records) >= 61:
        print(f'    ✅ 满足 DrawScope ≥61 期')
    else:
        print(f'    ⚠ <61 期')

    freq: Dict[int, int] = {}
    for r in records:
        for n in r['front']:
            freq[n] = freq.get(n, 0) + 1

    f_lo, f_hi = cfg['front_range']
    exp = len(records) * cfg['front_count'] / (f_hi - f_lo + 1) if records else 0
    if freq and exp > 0:
        print(f'    理论每号: {exp:.1f} 次')
        top = sorted(freq.items(), key=lambda x: -x[1])[:5]
        bot = sorted(freq.items(), key=lambda x: x[1])[:5]
        print(f'    最热: {top}')
        print(f'    最冷: {bot}')
        chi2 = sum((c - exp) ** 2 / exp for c in freq.values())
        chi2 += (f_hi - f_lo + 1 - len(freq)) * exp
        dof = f_hi - f_lo
        print(f'    χ²={chi2:.1f} df={dof} (≈{dof * 1.5:.0f} 内视为无显著偏离)')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='多源合并')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--sources', default='zhcw,ttz',
                    help='逗号分隔的源名前缀 (对应 data-raw/{src}_{game}.csv)')
    args = ap.parse_args()

    sources = [s.strip() for s in args.sources.split(',') if s.strip()]

    for g in (['dlt', 'ssq'] if args.all else [args.game]):
        print()
        print('#' * 70)
        print(f'# 合并 {GAMES[g]["name"]} ({g}) ← {" + ".join(sources)}')
        print('#' * 70)
        recs = merge(g, sources)
        print()
        validate(g, recs)
        if recs:
            print()
            print('  最新 3 期:')
            for r in recs[-3:]:
                print(f'    {r["period"]} ({r["draw_date"] or "?"})  前={r["front"]} 后={r["back"]}')
        print()