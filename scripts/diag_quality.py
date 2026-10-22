"""诊断数据质量: 重复期号 / 号码越界 / 同期重复 / 频次 χ²"""
import sys
import collections
import json
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

conn = sqlite3.connect('data-raw/lottery.db')

for game, fcols, bcols, fr, br in (('dlt', 5, 2, 35, 12), ('ssq', 6, 1, 33, 16)):
    print('=' * 62)
    print(f'  {game.upper()} 数据质量诊断')
    print('=' * 62)

    cur = conn.execute(
        'SELECT period, draw_date, notes, front_numbers, back_numbers '
        'FROM draws WHERE game=? ORDER BY period', (game,))
    rows = cur.fetchall()
    print(f'  总行数: {len(rows)}')

    def parse(s):
        if not s:
            return []
        try:
            return json.loads(s) if s.strip().startswith('[') else [
                int(x) for x in str(s).replace(',', ' ').split()]
        except Exception:
            try:
                return [int(x) for x in str(s).strip().split(',') if x.strip()]
            except Exception:
                return []

    parsed = [(r[0], r[1], r[2], parse(r[3]), parse(r[4])) for r in rows]

    # 重复期号
    cnt = collections.Counter(p[0] for p in parsed)
    dups = {p: n for p, n in cnt.items() if n > 1}
    print(f'  重复期号: {len(dups)} 个')
    for p, n in list(dups.items())[:6]:
        print(f'    {p} × {n}:')
        for rec in parsed:
            if rec[0] == p:
                print(f'      date={rec[1]} src={rec[2]} '
                      f'front={rec[3]} back={rec[4]}')

    # 期号长度
    lens = collections.Counter(len(str(r[0])) for r in parsed)
    print(f'  期号长度分布: {dict(lens)}')
    want_len = 5 if game == 'dlt' else 7
    odd = [r[0] for r in parsed if len(str(r[0])) != want_len]
    if odd:
        print(f'  长度异常: {len(odd)} 个 → {odd[:10]}')

    # 号码数量/越界
    bad_cnt, bad_range, dup_in = 0, [], []
    for p, dt, src, f, b in parsed:
        if len(f) != fcols or len(b) != bcols:
            bad_cnt += 1
        for v in f:
            if not (1 <= v <= fr):
                bad_range.append((p, v))
        for v in b:
            if not (1 <= v <= br):
                bad_range.append((p, v))
        if len(set(f)) != len(f) or len(set(b)) != len(b):
            dup_in.append(p)
    print(f'  号码个数错误: {bad_cnt} 期')
    print(f'  号码越界: {len(bad_range)} 处 {bad_range[:6]}')
    print(f'  同期号码重复: {len(dup_in)} 期 {dup_in[:10]}')

    # 来源分布
    srcs = collections.Counter(r[2] for r in parsed)
    print(f'  来源分布: {dict(srcs)}')

    # 频次 χ²
    nums = collections.Counter()
    for _, _, _, f, _ in parsed:
        for v in f:
            nums[v] += 1
    expected = len(parsed) * fcols / fr
    chi2 = sum((nums.get(n, 0) - expected) ** 2 / expected for n in range(1, fr + 1))
    print(f'  前区 χ² = {chi2:.1f} (df={fr-1}, 阈值 ~51)')
    worst = sorted(range(1, fr + 1),
                   key=lambda n: -abs(nums.get(n, 0) - expected))[:6]
    print(f'  偏离最大号: {[(n, nums.get(n, 0)) for n in worst]} (期望 {expected:.1f})')
    print()

conn.close()
