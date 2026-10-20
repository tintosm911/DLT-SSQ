"""
CSV → SQLite 导入器
====================
把 data-raw/*.csv (zhcw_/ttz_/merged_) 导入 lottery.db,
让 load_lottery_data() 和 run_full_lab() 能端到端跑通。

用法:
  python data/import_csv.py --all
  python data/import_csv.py --game dlt --sources merged,zhcw,ttz
"""
from __future__ import annotations
import os
import sys
import csv
import logging
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from data.sqlite_storage import SQLiteStorage, Draw, DB_PATH
from data.games import get_game

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / 'data-raw'

logger = logging.getLogger(__name__)


def read_csv(path: Path, game: str) -> List[Dict]:
    """读 CSV → [{period, draw_date, front, back, prize_money, sales}]"""
    cfg = get_game(game)
    fc, bc = cfg.front_count, cfg.back_count

    if not path.exists():
        return []

    out: List[Dict] = []
    with open(path, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            period = str(row.get('period', '')).strip()
            if not period:
                continue
            try:
                front = sorted(int(row[f'front_{i+1}']) for i in range(fc))
                back = sorted(int(row[f'back_{i+1}']) for i in range(bc))
            except (KeyError, ValueError):
                continue

            # 号码范围校验
            f_lo, f_hi = 1, cfg.front_range
            b_lo, b_hi = 1, cfg.back_range
            if not all(f_lo <= n <= f_hi for n in front):
                continue
            if not all(b_lo <= n <= b_hi for n in back):
                continue
            if len(set(front)) != len(front) or len(set(back)) != len(back):
                continue

            def _num(key):
                v = str(row.get(key, '')).replace(',', '').strip()
                try:
                    return float(v) if v else None
                except ValueError:
                    return None

            out.append({
                'period': period,
                'draw_date': str(row.get('draw_date', '')).strip(),
                'front': front,
                'back': back,
                'prize_money': _num('prize_money') or _num('jcje'),
                'sales': _num('sales') or _num('qgxsje'),
                'notes': str(row.get('source', '')).strip() or None,
            })

    return out


def import_sources(game: str, sources: List[str], verbose: bool = True) -> int:
    """导入多个源 (后者覆盖前者, merged 优先)"""
    storage = SQLiteStorage(db_path=str(DB_PATH))
    total = 0

    # 先清空该彩种, 保证干净导入
    with storage._connect() as conn:
        cur = conn.execute('DELETE FROM draws WHERE game=?', (game,))
        deleted = cur.rowcount
        conn.commit()
    if verbose and deleted:
        print(f'  清空旧数据: {deleted} 条')

    for src in sources:
        path = DATA_RAW / f'{src}_{game}.csv'
        recs = read_csv(path, game)
        if not recs:
            if verbose:
                print(f'  {src}: 无数据 ({path.name})')
            continue

        # 缺日期的用期号兜底 (probability_lab 需要 draw_date 非空)
        for r in recs:
            if not r['draw_date']:
                r['draw_date'] = _synthesize_date(game, r['period'])
            r['notes'] = src

        draws = [
            Draw(
                period=r['period'],
                draw_date=r['draw_date'],
                game=game,
                front=r['front'],
                back=r['back'],
                prize_money=r['prize_money'],
                sales=r['sales'],
                notes=r['notes'],
            )
            for r in recs
        ]
        n = storage.save_draws(draws)
        total += n
        if verbose:
            with_date = sum(1 for r in recs if r['draw_date'] and not r['draw_date'].startswith('20') is None)
            print(f'  {src}: 导入 {n} 条 ({path.name})')

    return total


def _synthesize_date(game: str, period: str) -> str:
    """
    期号 → 近似日期 (缺真实日期时兜底).

    DLT 5 位 (26091) → 2026 + 091 期 → 2026-03-04 (每周 3 期, 约 45 期/月)
    SSQ 7 位 (2026091) → 同理
    """
    from datetime import datetime, timedelta

    cfg = get_game(game)
    digits = str(period).strip()

    # 提取年份 + 期号
    if len(digits) >= 7:
        year = int(digits[:4])
        seq = int(digits[4:])
    elif len(digits) == 5:
        year = 2000 + int(digits[:2])
        seq = int(digits[2:])
    else:
        return '2020-01-01'

    # 大乐透每年约 150 期, 双色球约 153 期
    per_year = 150 if game == 'dlt' else 153
    day_offset = (seq - 1) * (365 / per_year)

    base = datetime(year, 1, 1)
    return (base + timedelta(days=int(day_offset))).strftime('%Y-%m-%d')


def verify(game: str) -> None:
    storage = SQLiteStorage(db_path=str(DB_PATH))
    df = storage.load_dataframe(game=game)
    print()
    print(f'  --- {game} 数据库验证 ---')
    print(f'    行数: {len(df)}')
    if len(df) == 0:
        return
    print(f'    列: {list(df.columns)}')
    print(f'    期号: {df["period"].iloc[0]} ~ {df["period"].iloc[-1]}')
    print(f'    日期: {df["draw_date"].iloc[0]} ~ {df["draw_date"].iloc[-1]}')
    print(f'    最新期:')
    row = df.iloc[-1]
    front_cols = sorted([c for c in df.columns if c.startswith('front_')],
                        key=lambda x: int(x.split('_')[1]))
    back_cols = sorted([c for c in df.columns if c.startswith('back_')],
                       key=lambda x: int(x.split('_')[1]))
    print(f'      {row["period"]}  前={[int(row[c]) for c in front_cols]}  后={[int(row[c]) for c in back_cols]}')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='CSV → SQLite 导入')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--sources', default='merged,zhcw,ttz',
                    help='导入顺序 (前面的优先)')
    args = ap.parse_args()

    sources = [s.strip() for s in args.sources.split(',') if s.strip()]

    print(f'DB: {DB_PATH}')
    print()

    for g in (['dlt', 'ssq'] if args.all else [args.game]):
        print('#' * 60)
        print(f'# 导入 {g}')
        print('#' * 60)
        total = import_sources(g, sources)
        print(f'  合计导入 {total} 条')
        verify(g)
        print()