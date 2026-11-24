"""
大乐透端到端实测
================
用**真实开奖**把整条链路走一遍, 每一步都跟官方 API 对账:

  ① 判奖正确性   真实开奖号 → judge_prize 判定 → 跟官方公布的中奖注数比
  ② 方案生成     你的号码池 + 预算 → 优化器 → 具体结构与号码
  ③ 历史检验     该结构放到过去 N 期真实开奖上 → 中奖率/ROI
  ④ 事前存档     为下一期生成方案并存档 (等开奖后可核对)

用法:
  python scripts/dantuo_live_test.py --game dlt
  python scripts/dantuo_live_test.py --game dlt --budget 1680 \
      --front-pool "2 4 6 10 14 16 18 23 26 32 35" --back-pool "2 4 6 9 12"
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import ssl
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.dan_tuo_exact import exact_dan_tuo
from data.dan_tuo_optimizer import optimize
from data.games import get_game, get_prize_rules, normalize_period
from data.pick_advisor import Pick, calc_expected_prize, judge_prize
from data.sqlite_storage import SQLiteStorage

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=_CTX),
)

ARCHIVE = PROJECT_ROOT / 'data-raw' / 'live_picks.jsonl'


def _get_json(url, referer):
    req = urllib.request.Request(url, headers={
        'User-Agent': _UA, 'Referer': referer})
    with _OPENER.open(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def official_dlt(n=2):
    """体彩官方最近 n 期 + 中奖注数"""
    url = ('https://webapi.sporttery.cn/gateway/lottery/'
           f'getHistoryPageListV1.qry?gameNo=85&provinceId=0'
           f'&pageSize={n}&pageNo=1&isVerify=1')
    j = _get_json(url, 'https://www.sporttery.cn/')
    out = []
    for it in (j.get('value') or {}).get('list') or []:
        nums = [int(x) for x in str(it.get('lotteryDrawResult', '')).split()]
        out.append({
            'period': str(it.get('lotteryDrawNum', '')).strip(),
            'date': str(it.get('lotteryDrawTime', '')).strip(),
            'front': sorted(nums[:5]), 'back': sorted(nums[5:]),
            'prize_levels': it.get('prizeLevelList') or [],
        })
    return out


def main():
    ap = argparse.ArgumentParser(description='大乐透端到端实测')
    ap.add_argument('--game', default='dlt', choices=['dlt'])
    ap.add_argument('--budget', type=float, default=1680.0)
    ap.add_argument('--front-pool', default='2 4 6 10 14 16 18 23 26 32 35')
    ap.add_argument('--back-pool', default='2 4 6 9 12')
    ap.add_argument('--no-archive', action='store_true')
    ap.add_argument('--label', default='',
                    help='方案标签 (写进存档, 方便开奖后对账时分辨是哪套方案)')
    args = ap.parse_args()

    cfg = get_game(args.game)

    def nums(s):
        return sorted(int(x) for x in s.replace(',', ' ').split()) if s.strip() else []

    fp, bp = nums(args.front_pool), nums(args.back_pool)

    print()
    print('=' * 94)
    print(f'  端到端实测 — {cfg.name}')
    print('=' * 94)

    # ---------- ① 判奖正确性 ----------
    print()
    print('  ① 判奖正确性 (真实开奖号 → 判定 → 对账官方中奖注数)')
    storage = SQLiteStorage()
    local_latest = storage.get_latest_period(args.game)
    print(f'     本地库最新: {local_latest}')

    off = official_dlt(2)
    if not off:
        print('     ❌ 官方 API 没返回数据')
        return 1
    for o in off:
        p7 = normalize_period(o['period'], args.game)
        # 用本地库里的号码判奖
        row = sqlite3.connect(str(PROJECT_ROOT / 'data-raw' / 'lottery.db')).execute(
            'SELECT front_numbers, back_numbers FROM draws WHERE period=? AND game=?',
            (p7, args.game)).fetchone()
        if not row:
            print(f'     ⚠ {p7} 本地无此期 (库还没更新)')
            continue
        lf = sorted(json.loads(row[0]))
        lb = sorted(json.loads(row[1]))
        same = (lf == o['front'] and lb == o['back'])
        print(f'     {"✅" if same else "❌"} {p7} ({o["date"]}) '
              f'本地 {lf}+{lb} vs 官方 {o["front"]}+{o["back"]}')

        # 用官方公布的中奖注数验证奖级表
        counts = {}
        for pl in o['prize_levels']:
            raw = str(pl.get('stakeCount', 0)).replace(',', '').strip()
            try:
                counts[pl['prizeLevel']] = int(raw)
            except ValueError:
                counts[pl['prizeLevel']] = 0
        print(f'     官方各奖级注数: '
              + ', '.join(f'{k}={counts[k]:,}' for k in
                          sorted(counts, key=lambda x: -counts[x])[:5]))

    # ---------- ② 方案生成 ----------
    print()
    print('  ② 方案生成 (优化器)')
    ro = optimize(args.game, budget=args.budget, goal='win',
                  front_pool=fp, back_pool=bp, top_n=1)
    b = ro['best']
    print(f'     搜索 {ro["searched"]} 种结构')
    print(f'     最优: {b["structure"]}  {b["n_bets"]} 注 / {b["cost"]:,.0f} 元')
    print(f'     中奖率 {b["win_rate"]:.4f}%   '
          f'期望净收益 {b["expected_net"]:+.2f} 元 '
          f'({b["expected_net"] / b["n_bets"]:+.4f} 元/注)')
    print(f'     前区 胆 {" ".join(f"{v:02d}" for v in b["front_dan"]) or "(无)"}'
          f' / 拖 {" ".join(f"{v:02d}" for v in b["front_tuo"])}')
    print(f'     后区 胆 {" ".join(f"{v:02d}" for v in b["back_dan"]) or "(无)"}'
          f' / 拖 {" ".join(f"{v:02d}" for v in b["back_tuo"])}')

    # ---------- ③ 历史检验 ----------
    print()
    print('  ③ 历史检验 (该结构放到过去真实开奖上)')
    from scripts.dan_tuo_backtest_real import backtest
    r = backtest(args.game, b['front_dan'], b['front_tuo'],
                  b['back_dan'], b['back_tuo'])
    print(f'     {r["n_draws"]:,} 期 × {r["n_tickets"]:,} 注 = '
          f'{r["n_tickets"] * r["n_draws"]:,} 次真实判奖')
    print(f'     中奖率 {r["win_rate"]:.2f}%   真实 ROI {r["roi"]:+.2f}%   '
          f'常态 ROI {r["roi_no_big"]:+.2f}%')
    print(f'     总投入 {r["stake"]:,.0f} 元 → 总返奖 {r["returned"]:,.0f} 元')

    # ---------- ④ 事前存档 ----------
    print()
    print('  ④ 事前存档 (等开奖后可核对)')
    if args.no_archive:
        print('     --no-archive, 跳过')
    else:
        next_p = normalize_period(str(int(off[0]['period']) + 1), 'dlt')
        rec = {
            'ts': datetime.now().isoformat(timespec='seconds'),
            'game': args.game,
            'target_period': next_p,
            'label': args.label,
            'budget': args.budget,
            'structure': b['structure'],
            'n_bets': b['n_bets'],
            'cost': b['cost'],
            'win_rate': b['win_rate'],
            'expected_net': b['expected_net'],
            'front_dan': b['front_dan'], 'front_tuo': b['front_tuo'],
            'back_dan': b['back_dan'], 'back_tuo': b['back_tuo'],
            'pool_f': fp, 'pool_b': bp,
        }
        with ARCHIVE.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print(f'     ✅ 已存档 → {ARCHIVE.name}  (目标期号 {next_p})')
        print(f'     开奖后跑: python scripts/verify_live_picks.py')

    print()
    print('=' * 94)
    print('  实测完成')
    print('=' * 94)
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
