"""
竞彩赔率快照采集 (CLI)
=======================
每天跑一次, 积累竞彩 + 境外盘口的历史赔率.

用法:
  python scripts/snapshot.py                # 只抓竞彩 (免费, 不耗 API 配额)
  python scripts/snapshot.py --overseas     # 同时抓境外 (耗 API 配额)
  python scripts/snapshot.py --stats        # 看存档统计
  python scripts/snapshot.py --history 26120  # 看某期的赔率变化
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

from data.snapshot_store import (collect_jingcai, collect_overseas, connect,
                                save_snapshots, stats)


def main():
    ap = argparse.ArgumentParser(description='竞彩赔率快照采集')
    ap.add_argument('--overseas', action='store_true', help='同时抓境外盘口')
    ap.add_argument('--stats', action='store_true', help='只显示统计')
    ap.add_argument('--history', default='', help='显示某期的赔率变化')
    ap.add_argument('--api-key', default='', help='the-odds-api key')
    args = ap.parse_args()

    if args.stats:
        s = stats()
        print()
        print('=' * 66)
        print('  竞彩赔率快照存档')
        print('=' * 66)
        print(f"  总记录: {s['total']}")
        print(f"  覆盖期数: {s['periods']}")
        print(f"  覆盖小时: {s['hours']}")
        print(f"  时间跨度: {s['first']} ~ {s['last']}")
        print()
        print('  各博彩公司 (按平均抽水排序):')
        for b in s['by_book']:
            print(f"    {b['book']:<22} {b['n']:>6} 条  平均抽水 "
                  f"{(b['vig'] or 0)*100:.2f}%")
        print()
        return 0

    if args.history:
        conn = connect()
        rows = conn.execute(
            'SELECT ts, book, odds_h, odds_d, odds_a, vig FROM odds_snapshots '
            'WHERE period=? ORDER BY ts', (args.history,)).fetchall()
        print(f'\n  期号 {args.history} 的赔率变化 ({len(rows)} 条):')
        for ts, book, h, d, a, vig in rows:
            mark = ' [竞彩]' if '竞彩' in book else ''
            print(f'    {ts[:19]}  {book:<20}{mark} '
                  f'{h:.2f}/{d:.2f}/{a:.2f}  抽水 {(vig or 0)*100:.2f}%')
        conn.close()
        return 0

    print('抓取竞彩官方赔率...')
    rows = collect_jingcai()
    print(f'  竞彩 {len(rows)} 条')

    if args.overseas:
        from data.live_scan_service import get_api_key
        key = args.api_key or get_api_key()
        if not key:
            print('  ⚠️ 没有 API key, 跳过境外盘口')
        else:
            print('抓取境外盘口...')
            orows = collect_overseas(key)
            print(f'  境外 {len(orows)} 条')
            rows += orows

    n = save_snapshots(rows)
    s = stats()
    print(f'\n  已存档 {n} 条 (去重后总 {s["total"]} 条 / {s["hours"]} 个小时桶)')

    if rows:
        print()
        print('  本次抓到的抽水率 Top 5 (最低):')
        vics = [(r.get('book'), r) for r in rows]
        for book, r in sorted(
                vics,
                key=lambda x: (1 / x[1]['odds_h'] + 1 / x[1]['odds_d']
                               + 1 / x[1]['odds_a'])
                if all(x[1].get(k) for k in ('odds_h', 'odds_d', 'odds_a'))
                else 99)[:5]:
            h, d, a = r['odds_h'], r['odds_d'], r['odds_a']
            vig = (1 / h + 1 / d + 1 / a) - 1
            print(f'    {book:<22} {h:.2f}/{d:.2f}/{a:.2f}  抽水 {vig*100:.2f}%')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
