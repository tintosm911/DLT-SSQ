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
PURCHASED = PROJECT_ROOT / 'data-raw' / 'live_picks_purchased.jsonl'


def _get_json(url, referer):
    req = urllib.request.Request(url, headers={
        'User-Agent': _UA, 'Referer': referer})
    with _OPENER.open(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def _fetch_dlt(page_size):
    """按 pageSize 拉官方最近若干期 → {7位期号: (date, front, back)}"""
    url = ('https://webapi.sporttery.cn/gateway/lottery/'
           f'getHistoryPageListV1.qry?gameNo=85&provinceId=0'
           f'&pageSize={page_size}&pageNo=1&isVerify=1')
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


def select_fresh_map(candidates, newest):
    """从多个 pageSize 的结果里挑一个**含最新期号**的

    ★ 为什么要这个函数:
      体彩官方 API 对**特定 pageSize 会返回过期缓存**。
      实测 2026-11-25 26135 开奖后:
        pageSize = 1/2/3/5/6/30/100 → 最新 2026135  ✅
        pageSize = 8/10            → 最新 2026134  ❌ (陈旧缓存)
      verify_live_picks.py 原本固定用 pageSize=8 → 开奖后一直"暂无新开奖可核对"。

    candidates: {page_size: map}
    newest:      已确认的最新期号 (来自 pageSize=1 这条总是新鲜的路径)
    返回: 含 newest 的那份 map; 都过期则返回 None
    """
    for _, m in sorted(candidates.items()):
        if m and newest in m:
            return m
    return None


def official_dlt_map(n=6, retries=3):
    """体彩官方最近 n 期 → {7位期号: (date, front, back)}

    ⚠ 带**缓存陈旧交叉校验** (见 select_fresh_map 的说明):
      先用 pageSize=1 确认最新期号, 再用不同 pageSize 拉历史,
      哪个含最新期号就用哪个; 全都过期则重试。
    """
    import time
    last_err = None
    for attempt in range(retries):
        candidates = {}
        # pageSize=1 → 这条路径的缓存总是新鲜的, 用它确认最新期号
        try:
            newest_map = _fetch_dlt(1)
            newest = max(newest_map) if newest_map else None
        except Exception as e:
            last_err = e
            time.sleep(2)
            continue
        if not newest:
            time.sleep(2)
            continue
        # 依次尝试几个 pageSize, 跳过已被证实会返回陈旧缓存的组合
        for ps in (n, 30, 100, 6, 3, 2):
            if ps == 1:
                continue
            try:
                candidates[ps] = _fetch_dlt(ps)
            except Exception as e:
                last_err = e
                continue
            fresh = select_fresh_map(candidates, newest)
            if fresh is not None:
                return fresh
        time.sleep(2)
    if last_err:
        raise last_err
    return candidates.get(n) or {}


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


def _key(rec):
    """
    存档与账本的配对键。

    ★ v3.3.1 修复: 存档里期号是 5 位 ('26133'), 账本里是 7 位 ('2026133') —— 
      之前直接比较字符串, 永远匹配不上 → **每跑一次就重复结算一次**,
      战绩汇总的投入被翻倍污染。期号必须先规范化再比。

    ★ v3.3.2 再修复: 键里必须带 **label**。
      原键是 (期号, ts) —— 但同一期批量生成的 A/B/C 三套方案 **ts 完全相同**
      ('2026-11-24T16:59:11'), 于是 B 版和 C 版被当成重复结算**去重掉了**。
      实测: 账本只写进 4 条, B/C 两套的成绩被永久吞掉, 总投入少算 162 元。
      → 键必须是 (期号, ts, label) 三元组, label 为空时用 ''。
    """
    return (normalize_period(rec.get('target_period', ''), 'dlt'),
            rec.get('ts'),
            rec.get('label') or '')


def dedup_ledger(records):
    """按 (规范化期号, ts) 去重, 保留第一条"""
    seen = set()
    uniq = []
    for r in records:
        k = _key(r)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


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
    # 去重 (修复历史脏数据: 同一 (期号, ts) 只保留第一条)
    return dedup_ledger(out)


def load_purchased():
    """读实买声明 → {(规范化期号, label), ...}

    ★ 为什么单独一个文件, 不在存档里加字段:
      data-raw/live_picks.jsonl 是**事前定死**的证据, 必须保持字节级不可变。
      "哪几套是真掏钱买的" 是购票事实, 用独立声明文件记录, 随时可审计/修订。
    """
    if not PURCHASED.exists():
        return set()
    out = set()
    for line in PURCHASED.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        period = normalize_period(str(rec.get('target_period', '')), 'dlt')
        label = str(rec.get('label', ''))
        if period and label:
            out.add((period, label))
    return out


def split_real_paper(ledger, purchased):
    """账本行拆成 (实买, 演练) 两组"""
    real, paper = [], []
    for r in ledger:
        k = (normalize_period(str(r.get('target_period', '')), 'dlt'),
             str(r.get('label', '')))
        (real if k in purchased else paper).append(r)
    return real, paper


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


def _fmt_levels(levels):
    if not levels:
        return '未中奖'
    return ', '.join(f'{k}×{v}' for k, v in
                     sorted(levels.items(), key=lambda x: -x[1]))


def _prior_levels(archive, row):
    """重算某方案的**各奖级事前概率** (至少中一注该奖级的概率, %)"""
    period = normalize_period(str(row.get('target_period', '')), 'dlt')
    ts = str(row.get('ts', ''))
    rec = None
    for a in archive:
        if (normalize_period(str(a.get('target_period', '')), 'dlt') == period
                and str(a.get('ts', '')) == ts):
            rec = a
            break
    if not rec:
        return []
    try:
        from data.dan_tuo_exact import exact_dan_tuo
        r = exact_dan_tuo(rec.get('game', 'dlt'),
                          front_dan=rec.get('front_dan') or [],
                          front_tuo=rec.get('front_tuo') or [],
                          back_dan=rec.get('back_dan') or [],
                          back_tuo=rec.get('back_tuo') or [])
    except Exception:
        return []
    out = []
    for p in r.get('prize_dist') or []:
        if p['label'] == '未中' or p.get('prob_any', 0) <= 0:
            continue
        out.append((p['label'], p['prob_any'] * 100, p['money']))
    return out


def _print_score(rows, title, note='', archive=None):
    """打印一组账本行的战绩 (主成绩单 / 演练对照 共用)"""
    if not rows:
        return False
    n = len(rows)
    periods = {normalize_period(str(r.get('target_period', '')), 'dlt')
               for r in rows}
    hits = sum(1 for r in rows if r['hit'])
    stake = sum(r['cost'] for r in rows)
    ret = sum(r['returned'] for r in rows)
    exp_win = sum(r['expected_win_rate'] for r in rows) / n
    exp_net = sum(r['expected_net'] for r in rows)

    print()
    print('=' * 84)
    print(f'  {title}')
    print('=' * 84)
    print(f'  已核对 {n} 个方案 ({len(periods)} 期开奖) | '
          f'中奖 {hits} 个方案 ({hits / n * 100:.1f}%)')
    print(f'  总投入 {stake:,.0f} 元 → 总返奖 {ret:,.0f} 元 → 净 {ret - stake:+,.0f} 元')
    print(f'  实际 ROI {(ret - stake) / stake * 100:+.2f}%')
    print(f'  事前预期中奖率 {exp_win:.2f}%  vs  实际中奖率 {hits / n * 100:.2f}%')
    print(f'  事前预期净收益 {exp_net:+,.0f} 元  vs  实际 {ret - stake:+,.0f} 元')
    if note:
        print(f'  {note}')
    print()

    # ---- 逐方案: 事前预期 vs 实际 ----
    print('  ── 逐方案 (事前预期 vs 实际) ──')
    for r in rows:
        label = r.get('label') or '(未标注)'
        print(f'    ▸ {label}   {r["structure"]}')
        print(f'      {r["n_tickets"]:,.0f} 注 / {r["cost"]:,.0f} 元'
              f'   |   事前预期: 中奖率 {r["expected_win_rate"]:.2f}%  '
              f'期望净 {r["expected_net"]:+.2f} 元')
        # 各奖级: 事前概率 vs 实际命中数
        prior = _prior_levels(archive or [], r)
        actual = r.get('levels') or {}
        if prior:
            print('      各奖级 事前概率 → 实际命中:')
            for lv, prob, money in prior:
                got = actual.get(lv, 0)
                print(f'        {lv:<6} {prob:>7.3f}%  (单注 {money:,.0f} 元)'
                      f'  →  {got} 注')
        lv = _fmt_levels(actual)
        print(f'      实际结果: {lv}')
        print(f'      投入 {r["cost"]:,.0f} → 返奖 {r["returned"]:,.0f} 元 → '
              f'净 {r["net"]:+,.0f} 元  (ROI {r["net"] / r["cost"] * 100:+.2f}%)')
        print()
    return True


def main():
    ap = argparse.ArgumentParser(description='事前存档开奖后核对')
    ap.add_argument('--stats', action='store_true', help='只显示战绩汇总')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    archive = load_archive()
    ledger = load_ledger()
    # 账本去重后写回 (清理历史重复结算)
    if LEDGER.exists():
        raw = [l for l in LEDGER.read_text(encoding='utf-8').splitlines()
               if l.strip()]
        if len(ledger) != len(raw):
            with LEDGER.open('w', encoding='utf-8') as f:
                for r in ledger:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
            print(f'  ⚠ 账本清理: {len(raw)} 条 → {len(ledger)} 条 '
                  f'(删除重复结算记录)')
            print()
    done = {_key(r) for r in ledger}

    if not args.stats:
        try:
            draws = official_dlt_map(8)
        except Exception as e:
            print(f'❌ 拉官方开奖失败: {e}')
            return 1

        pending = [r for r in archive if _key(r) not in done]
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
                'label': rec.get('label', ''),
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
                    if r.get('label'):
                        print(f'    方案: {r["label"]}')
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
                pending_p = sorted({normalize_period(r['target_period'], 'dlt')
                                    for r in archive if _key(r) not in done})
                print(f'  暂无新开奖可核对 (待核对期号: '
                      f'{", ".join(pending_p) if pending_p else "无"})')

    # ---- 战绩汇总 ----
    if not ledger:
        print('  战绩为空 (还没有已开奖的存档)')
        return 0

    purchased = load_purchased()
    real_rows, paper_rows = split_real_paper(ledger, purchased)

    # 主成绩单 = 实买 (paper-only 时退回全部, 并注明)
    if real_rows:
        _print_score(real_rows, '实战战绩 · 实买 (真实购票)',
                     '口径: 只统计 data-raw/live_picks_purchased.jsonl 里声明的实买方案。',
                     archive=archive)
        if paper_rows:
            _print_score(paper_rows, '实战战绩 · 演练对照 (未实际购票)',
                         '口径: 这些是方法论演练方案, 未掏钱; 注数大、样本足, '
                         '用来对照"事前预期"是否站得住。', archive=archive)
    else:
        _print_score(ledger, '实战战绩 · 全部方案 (尚无实买声明)',
                     '口径: 还没有任何方案被登记为实买, 此处统计全部存档方案。',
                     archive=archive)

    print('  ★ 样本还很小, 统计上说明不了什么 —— 但这是**唯一**能检验系统的')
    print('    "往前看"的方式, 攒够期数后才有参考价值。')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
