"""
chart.ttzoushi.com 采集器 (最终版)
===================================
实测确认的抓取机制:

1. 关键参数: ?maxsize=N
   - maxsize=30   → 30 期 (默认)
   - maxsize=100  → 100 期 ✅ 可用
   - maxsize=200+ → 回退到 30 期 (会员墙)

2. User-Agent 决定页面版本:
   - 桌面 Chrome/Firefox → 服务端渲染, HTML 直接含数据 ✅
   - iPhone/Android UA   → Vue 空模板 (数据靠 JS 加载) ❌
   - 无 UA               → 同桌面版 ✅

3. 开奖行识别:
   - <td class="chartBall01"> = 前区号码 (DLT 5 个 / SSQ 6 个)
   - <td class="chartBall02"> = 后区号码 (DLT 2 个 / SSQ 1 个)
   - 第 0 个 <td>            = 期号

4. 期号格式:
   - DLT: 5 位 (26090)
   - SSQ: 7 位 (2026119)

输出: data-raw/ttz_{game}.csv
"""
from __future__ import annotations
import os
import re
import sys
import csv
import ssl
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List
from urllib.request import Request, urlopen

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

for _k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(_k, None)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / 'data-raw'
DATA_RAW.mkdir(parents=True, exist_ok=True)

BASE = 'https://chart.ttzoushi.com'

# 必须用桌面 UA —— 移动 UA 会拿到 Vue 空模板
HDRS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': f'{BASE}/',
    'Connection': 'keep-alive',
}

GAMES = {
    'dlt': {
        'name': '超级大乐透',
        'front_count': 5, 'front_range': (1, 35),
        'back_count': 2, 'back_range': (1, 12),
        'period_re': r'\d{5}',
        'weekdays': (0, 2, 4),           # 周一/三/五
        'lottery_index': '101',
    },
    'ssq': {
        'name': '双色球',
        'front_count': 6, 'front_range': (1, 33),
        'back_count': 1, 'back_range': (1, 16),
        'period_re': r'\d{7}',
        'weekdays': (1, 3, 6),           # 周二/四/日
        'lottery_index': '102',
    },
}

MAX_FREE = 100      # 实测: 100 期免费, 200 起需会员


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def fetch(game: str, maxsize: int, timeout: int = 30, retries: int = 3) -> str:
    url = f'{BASE}/{game}/?maxsize={maxsize}'
    last = None
    for i in range(retries):
        try:
            req = Request(url, headers=HDRS)
            html = urlopen(req, timeout=timeout, context=_ctx()).read().decode('utf-8', 'ignore')
            if 'chartBall01' not in html:
                last = RuntimeError('anti-bot / empty template')
                time.sleep(2.5 * (i + 1))
                continue
            return html
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'fetch {game} maxsize={maxsize} failed: {last}')


def parse_page(game: str, html: str) -> List[Dict]:
    cfg = GAMES[game]
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S)
    out: List[Dict] = []
    seen = set()

    for row in rows:
        if 'chartBall01' not in row:
            continue
        cells = re.findall(r'<td([^>]*)>(.*?)</td>', row, re.S)
        if not cells:
            continue

        period = re.sub(r'<[^>]+>', '', cells[0][1]).strip()
        if not re.fullmatch(cfg['period_re'], period) or period in seen:
            continue

        buckets: Dict[str, List[int]] = {}
        for attrs, content in cells:
            m = re.search(r'class="([^"]*)"', attrs)
            if not m:
                continue
            bm = re.search(r'chartBall(\d+)', m.group(1))
            if not bm:
                continue
            txt = re.sub(r'<[^>]+>', '', content).strip()
            if txt.isdigit():
                buckets.setdefault(bm.group(1), []).append(int(txt))

        front, back = buckets.get('01', []), buckets.get('02', [])
        if len(front) != cfg['front_count'] or len(back) != cfg['back_count']:
            continue

        f_lo, f_hi = cfg['front_range']
        b_lo, b_hi = cfg['back_range']
        if not (all(f_lo <= n <= f_hi for n in front) and all(b_lo <= n <= b_hi for n in back)):
            continue
        if len(set(front)) != len(front) or len(set(back)) != len(back):
            continue

        seen.add(period)
        out.append({'period': period, 'front': sorted(front), 'back': sorted(back)})

    return out


def estimate_dates(game: str, periods: List[str]) -> Dict[str, str]:
    """走势图无日期字段, 按固定开奖周期从最新期倒推 (近似值)"""
    cfg = GAMES[game]
    wd = set(cfg['weekdays'])
    d = datetime.now().date()
    for _ in range(7):
        if d.weekday() in wd:
            break
        d -= timedelta(days=1)
    out: Dict[str, str] = {}
    for p in reversed(periods):
        out[p] = d.isoformat()
        while True:
            d -= timedelta(days=1)
            if d.weekday() in wd:
                break
    return out


def load_existing(game: str) -> Dict[str, Dict]:
    path = DATA_RAW / f'ttz_{game}.csv'
    if not path.exists():
        return {}
    cfg = GAMES[game]
    out: Dict[str, Dict] = {}
    with open(path, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            out[row['period']] = {
                'period': row['period'],
                'draw_date': row.get('draw_date', ''),
                'front': [int(row[f'front_{i+1}']) for i in range(cfg['front_count'])],
                'back': [int(row[f'back_{i+1}']) for i in range(cfg['back_count'])],
            }
    return out


def save_csv(game: str, records: List[Dict]) -> Path:
    cfg = GAMES[game]
    out = DATA_RAW / f'ttz_{game}.csv'
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['period', 'draw_date']
                   + [f'front_{i+1}' for i in range(cfg['front_count'])]
                   + [f'back_{i+1}' for i in range(cfg['back_count'])])
        for r in records:
            w.writerow([r['period'], r.get('draw_date', '')] + r['front'] + r['back'])
    return out


def collect(game: str = 'dlt', verbose: bool = True) -> List[Dict]:
    """采集指定彩种 (免费额度 100 期)"""
    cfg = GAMES[game]
    by_period: Dict[str, Dict] = load_existing(game)
    if verbose and by_period:
        print(f'  已有: {len(by_period)} 期')

    # 逐档试探, 找到站点实际允许的上限
    for size in (100, 50, 30):
        try:
            html = fetch(game, size)
        except Exception as e:
            if verbose:
                print(f'  maxsize={size:3d} ERR {str(e)[:60]}')
            continue
        recs = parse_page(game, html)
        if verbose:
            print(f'  maxsize={size:3d} → 拿到 {len(recs)} 期')
        if recs:
            for r in recs:
                by_period[r['period']] = r
            break

    records = sorted(by_period.values(), key=lambda x: x['period'])

    need = [r['period'] for r in records if not r.get('draw_date')]
    if need:
        dates = estimate_dates(game, need)
        for r in records:
            if not r.get('draw_date') and r['period'] in dates:
                r['draw_date'] = dates[r['period']]

    out = save_csv(game, records)
    if verbose:
        print(f'  ✅ {len(records)} 期 → {out}')
    return records


def validate(game: str, records: List[Dict]) -> None:
    cfg = GAMES[game]
    print(f'  --- {cfg["name"]} 质量检查 ---')
    print(f'    期数: {len(records)}')
    if records:
        print(f'    期号: {records[0]["period"]} ~ {records[-1]["period"]}')
        print(f'    日期: {records[0]["draw_date"]} ~ {records[-1]["draw_date"]}')

    if len(records) >= 61:
        print(f'    ✅ 满足 DrawScope ≥61 期门槛')
    else:
        print(f'    ⚠ <61 期 (DrawScope 门槛)')

    freq: Dict[int, int] = {}
    for r in records:
        for n in r['front']:
            freq[n] = freq.get(n, 0) + 1

    f_lo, f_hi = cfg['front_range']
    exp = len(records) * cfg['front_count'] / (f_hi - f_lo + 1) if records else 0
    if freq and exp > 0:
        top = sorted(freq.items(), key=lambda x: -x[1])[:5]
        bot = sorted(freq.items(), key=lambda x: x[1])[:5]
        print(f'    理论每号: {exp:.1f} 次')
        print(f'    最热: {top}')
        print(f'    最冷: {bot}')
        chi2 = sum((c - exp) ** 2 / exp for c in freq.values())
        chi2 += (f_hi - f_lo + 1 - len(freq)) * exp
        dof = f_hi - f_lo
        print(f'    χ²={chi2:.1f} df={dof} (≈{dof * 1.5:.0f} 内视为无显著偏离)')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='采集天天走势彩票历史数据 (免费额度 100 期)')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()

    for g in (['dlt', 'ssq'] if args.all else [args.game]):
        print()
        print('#' * 70)
        print(f'# {GAMES[g]["name"]} ({g})')
        print('#' * 70)
        recs = collect(g)
        print()
        validate(g, recs)
        if recs:
            print()
            print('  最新 3 期:')
            for r in recs[-3:]:
                print(f'    {r["period"]} ({r["draw_date"]})  前={r["front"]} 后={r["back"]}')
        print()