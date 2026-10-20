"""
zhcw.com (中彩网) 数据采集器
==============================
两个数据源, 互为补充:

源 A — 静态 JSON (含真实开奖日期, 但只有 100 期且是 2020 年缓存)
  https://www.zhcw.com/chartstatic/json/kj_{ssq|dlt}.json
  字段: zjxq[] → qh(期号) / kjsj(开奖日期) / kjjgqq(前区) / kjjghq(后区)

源 B — JSONP 接口 (数据新, 但 resCode=100103 需签名/token)
  https://jc.zhcw.com/port/client_json.php?transactionType=10001001&lotteryId={1|281}
  字段: data[] → issue / openTime / frontWinningNum / backWinningNum

lotteryId 映射 (来自 /static/js/kjsj.min.js):
  ssq=1, d3=2, qlc=3, kl8=6, dlt=281, pl3=283, pl5=284, qxc=282

输出: data-raw/zhcw_{game}.csv  (带真实开奖日期)
"""
from __future__ import annotations
import os
import re
import sys
import csv
import ssl
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

for _k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(_k, None)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / 'data-raw'
DATA_RAW.mkdir(parents=True, exist_ok=True)

HDRS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://www.zhcw.com/kjxx/ssq/',
}

GAMES = {
    'dlt': {
        'name': '超级大乐透',
        'front_count': 5, 'front_range': (1, 35),
        'back_count': 2, 'back_range': (1, 12),
        'period_digits': 5,           # 20098
        'period_prefix': '20',       # 5 位期号 → 2020098
        'lottery_id': '281',
    },
    'ssq': {
        'name': '双色球',
        'front_count': 6, 'front_range': (1, 33),
        'back_count': 1, 'back_range': (1, 16),
        'period_digits': 7,           # 2020098
        'period_prefix': '',
        'lottery_id': '1',
    },
}


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def fetch(url: str, timeout: int = 25, retries: int = 3) -> str:
    last = None
    for i in range(retries):
        try:
            req = Request(url, headers=HDRS)
            return urlopen(req, timeout=timeout, context=_ctx()).read().decode('utf-8', 'ignore')
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'fetch failed: {last}')


# ============================================================
# 源 A: 静态 JSON
# ============================================================
def normalize_date(raw: str) -> str:
    """2020-10-08 / 2020年10月07日 / 2020/10/08 → ISO"""
    if not raw:
        return ''
    s = raw.strip()
    m = re.search(r'(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})', s)
    if m:
        y, mo, d = m.groups()
        return f'{int(y):04d}-{int(mo):02d}-{int(d):02d}'
    return ''


def fetch_static(game: str) -> List[Dict]:
    cfg = GAMES[game]
    url = f'https://www.zhcw.com/chartstatic/json/kj_{game}.json'
    raw = fetch(url)
    data = json.loads(raw)
    records = data.get('zjxq', [])

    out: List[Dict] = []
    for r in records:
        period = str(r.get('qh', '')).strip()
        front_txt = r.get('kjjgqq', '')
        back_txt = r.get('kjjghq', '')
        if not period or not front_txt:
            continue

        front = [int(x) for x in front_txt.split() if x.isdigit()]
        back = [int(x) for x in back_txt.split() if x.isdigit()]

        if len(front) != cfg['front_count'] or len(back) != cfg['back_count']:
            continue
        f_lo, f_hi = cfg['front_range']
        b_lo, b_hi = cfg['back_range']
        if not (all(f_lo <= n <= f_hi for n in front) and all(b_lo <= n <= b_hi for n in back)):
            continue

        # DLT 5 位期号 → 补成 7 位 (20098 → 2020098)
        if cfg['period_digits'] == 5:
            full_period = f'20{period}' if len(period) == 5 else period
        else:
            full_period = period

        out.append({
            'period': full_period,
            'draw_date': normalize_date(r.get('kjsj', '')),
            'front': sorted(front),
            'back': sorted(back),
            'source': 'static',
        })

    return out


# ============================================================
# 源 B: JSONP 接口 (需 token, 保留代码备用)
# ============================================================
def fetch_jsonp(game: str, page_size: int = 100, page_num: int = 1) -> List[Dict]:
    """
    jc.zhcw.com JSONP 接口。
    当前返回 resCode=100103 (需签名), 但结构已确认, 若日后开放可直接用。
    """
    import urllib.parse
    cfg = GAMES[game]
    params = {
        'transactionType': '10001001',
        'lotteryId': cfg['lottery_id'],
        'issueCount': '0',
        'startIssue': '', 'endIssue': '',
        'startDate': '', 'endDate': '',
        'type': '0',
        'pageNum': str(page_num),
        'pageSize': str(page_size),
        'tt': str(int(time.time() * 1000) % 1000000),
        'callback': 'cb',
    }
    url = 'https://jc.zhcw.com/port/client_json.php?' + urllib.parse.urlencode(params)
    try:
        raw = fetch(url)
    except Exception as e:
        print(f'  JSONP ERR: {str(e)[:60]}')
        return []

    m = re.match(r'^\s*[\w$]+\s*\((.*?)\)\s*;?\s*$', raw, re.S)
    try:
        j = json.loads(m.group(1)) if m else json.loads(raw)
    except Exception:
        return []

    if j.get('resCode') != '000000':
        print(f'  JSONP resCode={j.get("resCode")} (需签名, 跳过)')
        return []

    out: List[Dict] = []
    for r in j.get('data', []):
        front = [int(x) for x in str(r.get('frontWinningNum', '')).split() if x.isdigit()]
        back = [int(x) for x in str(r.get('backWinningNum', '')).split() if x.isdigit()]
        if len(front) != cfg['front_count'] or len(back) != cfg['back_count']:
            continue
        out.append({
            'period': str(r.get('issue', '')).strip(),
            'draw_date': normalize_date(str(r.get('openTime', ''))),
            'front': sorted(front),
            'back': sorted(back),
            'source': 'jsonp',
        })
    return out


# ============================================================
# 合并 + 存储
# ============================================================
def load_existing(game: str) -> Dict[str, Dict]:
    path = DATA_RAW / f'zhcw_{game}.csv'
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
    out = DATA_RAW / f'zhcw_{game}.csv'
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['period', 'draw_date']
                   + [f'front_{i+1}' for i in range(cfg['front_count'])]
                   + [f'back_{i+1}' for i in range(cfg['back_count'])])
        for r in records:
            w.writerow([r['period'], r.get('draw_date', '')] + r['front'] + r['back'])
    return out


def collect(game: str = 'dlt', verbose: bool = True) -> List[Dict]:
    cfg = GAMES[game]
    by_period: Dict[str, Dict] = load_existing(game)
    if verbose and by_period:
        print(f'  已有: {len(by_period)} 期')

    # 源 A: 静态 JSON (含真实日期)
    try:
        statics = fetch_static(game)
        if verbose:
            if statics:
                print(f'  源A 静态JSON: {len(statics)} 期 '
                      f'({statics[0]["draw_date"]} ~ {statics[-1]["draw_date"]})')
            else:
                print('  源A 静态JSON: 无数据')
        for r in statics:
            by_period.setdefault(r['period'], r)
    except Exception as e:
        if verbose:
            print(f'  源A ERR: {str(e)[:70]}')

    # 源 B: JSONP (备用)
    try:
        jsonps = fetch_jsonp(game)
        if verbose and jsonps:
            print(f'  源B JSONP: {len(jsonps)} 期')
        for r in jsonps:
            by_period.setdefault(r['period'], r)
    except Exception:
        pass

    records = sorted(by_period.values(), key=lambda x: x['period'])
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
        dated = [r for r in records if r.get('draw_date')]
        if dated:
            print(f'    日期: {dated[0]["draw_date"]} ~ {dated[-1]["draw_date"]} ({len(dated)} 期有真实日期)')
        else:
            print(f'    ⚠ 无真实开奖日期')

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
    ap = argparse.ArgumentParser(description='采集中彩网 (zhcw.com) 彩票数据')
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