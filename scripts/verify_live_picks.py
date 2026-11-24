"""
事前存档 · 开奖后自动核对
==========================
读 data-raw/live_picks.jsonl 里存档的方案, 跟真实开奖对账。

★ 这构成一个**真正的实战闭环**:
  事前 (脚本 dantuo_live_test.py)  →  生成方案并存档, 记下目标期号
  开奖后 (本脚本)                →  拉真实开奖, 判奖, 结算, 记入战绩

★ 为什么要做这个:
  系统的所有结论都来自"过去的统计"。真正能检验它的是**往前看** ——
  事前定好方案, 事后开奖, 看看实际中没中、中了多少、跟期望差多少。
  这是唯一能把"回测"变成"实测"的方式。

用法:
  python scripts/verify_live_picks.py           # 核对所有已开奖的存档
  python scripts/verify_live_picks.py --stats   # 看战绩汇总
"""
from __future__ import annotations

import argparse
import json
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

from data.games import normalize_period
from data.pick_advisor import Pick, judge_prize

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
LEDGER = PROJECT_ROOT / 'data-raw' / 'live_picks_ledger.jsonl'


def _get_json(url, referer):
    req = urllib.request.Request(url, headers={
        'User-Agent': _UA, 'Referer': referer})
    with _OPENER.open(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def official_dlt_map(n=6):
    """体彩官方最近 n 期 → {7位期号: (date, front, back)}"""
    url = ('https://webapi.sporttery.cn/gateway/lottery/'
           f'getHistoryPageListV1.qry?gameNo=85&provinceId=0'
           f'&pageSize={n}&pageNo=1&isVerify=1')
    j = _get_json(url, 'https://www.sporttery.cn/')
    out = {}
    for it in (j.get('value') or {}).get('list') or []:
        nums = [int(x) for x in str(it.get('lotteryDrawResult', '')).split()]
        raw = str(it.get('lotteryDrawNum', '')).strip()
        if not raw or len(nums) != 7:
            continue
        p = raw if len(raw) == 7 else '20' + raw
        out[p] = (str(it.get('lotteryDrawTime', '')).strip(),
                  sorted(nums[:5]), sorted(nums[5:]))
    return out


def load_archive():
    if not ARCHIVE.exists():
        return []
    out = []
    for line in ARCHIVE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_ledger():
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def judge_record(rec, draw):
    """把一个存档方案跟真实开奖对账, 返回结算结果"""
    date, af, ab = draw
    tickets = []
    import itertools
    for fc in itertools.combinations(rec['front_tuo'],
                                     5 - len(rec['front_dan'])):
        for bc in itertools.combinations(rec['back_tuo'],
                                         2 - len(rec['back_dan'])):
            tickets.append((sorted(list(rec['front_dan']) + list(fc)),
                            sorted(list(rec['back_dan']) + list(bc))))
    levels = {}
    money = 0.0
    for f, b in tickets:
        lab, m = judge_prize('dlt', Pick(front=f, back=b), af, ab)
        if m > 0:
            levels[lab] = levels.get(lab, 0) + 1
            money += m
    return {
        'draw_date': date,
        'n_tickets': len(tickets),
        'levels': levels,
        'returned': money,
        'cost': rec['cost'],
        'net': money - rec['cost'],
        'hit': money > 0,
    }


def main():
    ap = argparse.ArgumentParser(description='事前存档开奖后核对')
    ap.add_argument('--stats', action='store_true', help='只显示战绩汇总')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    archive = load_archive()
    ledger = load_ledger()
    done = {(r['target_period'], r.get('ts')) for r in ledger}

    if not args.stats:
        try:
            draws = official_dlt_map(8)
        except Exception as e:
            print(f'❌ 拉官方开奖失败: {e}')
            return 1

        pending = [r for r in archive
                   if (r['target_period'], r.get('ts')) not in done]
        new_rows = []
        for rec in pending:
            tp = normalize_period(rec['target_period'], 'dlt')
            if tp not in draws:
                continue
            res = judge_record(rec, draws[tp])
            row = {
                'checked_at': datetime.now().isoformat(timespec='seconds'),
                'target_period': tp,
                'ts': rec.get('ts'),
                'structure': rec['structure'],
                'expected_net': rec['expected_net'],
                'expected_win_rate': rec['win_rate'],
                **res,
            }
            new_rows.append(row)

        if new_rows:
            with LEDGER.open('a', encoding='utf-8') as f:
                for row in new_rows:
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
            ledger.extend(new_rows)

        if not args.quiet:
            if new_rows:
                print()
                print('=' * 84)
                print('  新开奖核对结果')
                print('=' * 84)
                for r in new_rows:
                    print(f'  期号 {r["target_period"]} ({r["draw_date"]})  '
                          f'{r["structure"]}')
                    if r['hit']:
                        lv = ', '.join(f'{k}×{v}' for k, v in
                                       sorted(r['levels'].items(),
                                              key=lambda x: -x[1]))
                        print(f'    ✅ 中奖: {lv}')
                    else:
                        print(f'    ❌ 未中奖 ({r["n_tickets"]:,} 注全灭)')
                    print(f'    投入 {r["cost"]:,.0f} 元 → 返奖 {r["returned"]:,.0f} 元 '
                          f'→ 净 {r["net"]:+,.0f} 元')
                    print(f'    (事前预期: 期望净收益 {r["expected_net"]:+.2f} 元, '
                          f'中奖率 {r["expected_win_rate"]:.2f}%)')
                    print()
            else:
                pending_p = sorted({r['target_period'] for r in archive
                                     if (r['target_period'], r.get('ts')) not in done})
                print(f'  暂无新开奖可核对 (待核对期号: '
                      f'{", ".join(pending_p) if pending_p else "无"})')

    # ---- 战绩汇总 ----
    if not ledger:
        print('  战绩为空 (还没有已开奖的存档)')
        return 0

    print()
    print('=' * 84)
    print('  实战战绩汇总 (事前定方案 → 开奖后核对)')
    print('=' * 84)
    n = len(ledger)
    hits = sum(1 for r in ledger if r['hit'])
    stake = sum(r['cost'] for r in ledger)
    ret = sum(r['returned'] for r in ledger)
    print(f'  已核对 {n} 期 | 中奖 {hits} 期 ({hits / n * 100:.1f}%)')
    print(f'  总投入 {stake:,.0f} 元 → 总返奖 {ret:,.0f} 元 → 净 {ret - stake:+,.0f} 元')
    print(f'  实际 ROI {(ret - stake) / stake * 100:+.2f}%')
    exp_win = sum(r['expected_win_rate'] for r in ledger) / n
    print(f'  事前预期中奖率 {exp_win:.2f}%  vs  实际中奖率 {hits / n * 100:.2f}%')
    exp_net = sum(r['expected_net'] for r in ledger)
    print(f'  事前预期净收益 {exp_net:+,.0f} 元  vs  实际 {ret - stake:+,.0f} 元')
    print()
    print('  ★ 样本还很小, 统计上说明不了什么 —— 但这是**唯一**能检验系统的')
    print('    "往前看"的方式, 攒够期数后才有参考价值。')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
