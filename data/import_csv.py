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
    from data.games import normalize_period
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
            # 统一期号格式 (gh 用 7 位, zhcw/ttz 用 5 位, 不统一会导致重复入库)
            period = normalize_period(period, game)
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


def import_sources(game: str, sources: List[str], verbose: bool = True,
                   purge: bool = False,
                   prefer: List[str] = None) -> int:
    """
    导入多个源 (默认按 prefer 优先级, 靠后的源只补缺不覆盖)

    ⚠ 默认 **不清空** 数据库, 走 upsert。
    历史教训 (2026-10-22): 早期版本先 DELETE 再导入, 导致 GitHub 全量历史
    (3037+3516 期) 被 zhcw/ttz 的 100 期局部数据整体覆盖, 期数从 6553 掉到 402。
    只有显式 purge=True 才清空 (用于重建库)。

    ⚠ **源优先级** (2026-10-22 第二次事故):
      各源期号体系不一致 (gh 用 7 位 YYYY+期序, zhcw/ttz 用 5 位 YY+期序),
      且 ttz 的开奖日期整体偏移 1 天。若无脑 upsert, 后导入的局部源会污染
      主力源的全量数据 (实测: 68 期重复入库 + 前区 χ² 从 ~48 飙到 90)。
      规则: prefer 里的源优先写入, 其余源 **只补缺, 不覆盖**。
    """
    storage = SQLiteStorage(db_path=str(DB_PATH))
    total = 0

    # 源优先级: prefer 在前, 其余按 sources 原序
    ordered = list(sources)
    if prefer:
        ordered = ([s for s in prefer if s in sources]
                   + [s for s in sources if s not in prefer])
    primary = ordered[0] if ordered else None

    if purge:
        with storage._connect() as conn:
            cur = conn.execute('DELETE FROM draws WHERE game=?', (game,))
            deleted = cur.rowcount
            conn.commit()
        if verbose and deleted:
            print(f'  [purge] 清空旧数据: {deleted} 条')
    elif verbose:
        with storage._connect() as conn:
            existing = conn.execute(
                'SELECT COUNT(*) FROM draws WHERE game=?', (game,)).fetchone()[0]
        print(f'  [upsert] 保留现有 {existing} 条, 增量写入')
        if len(ordered) > 1:
            print(f'  [priority] 源优先级: {" > ".join(ordered)}'
                  f'  (靠后的源只补缺, 不覆盖)')

    # 已入库的 (期号集合, 号码组合集合), 用于冲突检测
    existing_periods = set()
    existing_numbers = set()
    if not purge:
        with storage._connect() as conn:
            for period, fn in conn.execute(
                    'SELECT period, front_numbers FROM draws WHERE game=?', (game,)):
                existing_periods.add(str(period))
                if fn:
                    existing_numbers.add(str(fn))

    for src in ordered:
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

        # --- 冲突过滤: 非主力源只补缺 ---
        if src != primary:
            filtered = []
            skipped_dup = skipped_conflict = 0
            for r in recs:
                num_key = str(r['front'])
                if r['period'] in existing_periods:
                    skipped_dup += 1
                    continue
                if num_key and num_key in existing_numbers:
                    # 期号不同但号码组合相同 → 该源期号体系与主力源不一致
                    skipped_conflict += 1
                    continue
                filtered.append(r)
            if verbose and (skipped_dup or skipped_conflict):
                msg = f'  {src}: 跳过 {skipped_dup} 期重复期号'
                if skipped_conflict:
                    msg += (f' + {skipped_conflict} 同期号不同期号'
                            f'(该源期号体系与主力源不一致)')
                print(msg)
            recs = filtered

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
            print(f'  {src}: 导入 {n} 条 ({path.name})')

        for r in recs:
            existing_periods.add(str(r['period']))
            existing_numbers.add(str(r['front']))

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