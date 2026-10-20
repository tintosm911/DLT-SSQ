"""
GitHub 数据集采集器
====================
从开源仓库抓取完整历史开奖数据 (官方 API 全封的替代方案)。

★ 主数据集: yangxb919/lottery-data (自动更新到最新)
    data/dlt.json — 大乐透 2937 期 (2007-05-30 ~ 2026-10-19)
    data/ssq.json — 双色球 3516 期 (2003-02-23 ~ 2026-10-18)
    字段: issue / date / front|red / back|blue / source(500.com)
    ★ 含真实开奖日期, 这是最完整的历史数据源

★ 备用数据集: yeyingbao/ssq-lottery-analysis
    ssq_data_clean.csv — 双色球 2354 期 (2008-2023)
    含销售额/各奖级注数/奖金/奖池 (仅 SSQ)

下载方式: GitHub API contents/blobs 端点 (base64)
    —— raw.githubusercontent.com 在公司网 DNS 不通, 必须走 API

输出: data-raw/gh_{game}.csv
"""
from __future__ import annotations
import os
import re
import sys
import csv
import ssl
import json
import base64
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

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
    'Accept': 'application/vnd.github+json',
}

GAMES = {
    'dlt': {'name': '超级大乐透', 'front_count': 5, 'front_range': 35,
            'back_count': 2, 'back_range': 12, 'min_periods': 200},
    'ssq': {'name': '双色球', 'front_count': 6, 'front_range': 33,
            'back_count': 1, 'back_range': 16, 'min_periods': 200},
}

# 数据源注册表 (按优先级)
SOURCES = [
    {
        'id': 'yangxb',
        'repo': 'yangxb919/lottery-data',
        'desc': '★ 主源 · 大乐透 2937 期 (2007-2026) + 双色球 3516 期 (2003-2026)',
        'files': {
            'dlt': ['data/dlt.json'],
            'ssq': ['data/ssq.json'],
        },
        'kind': 'json_yangxb',
    },
    {
        'id': 'yeyingbao',
        'repo': 'yeyingbao/ssq-lottery-analysis',
        'desc': '备用源 · 双色球 2354 期 (2008-2023), 含奖项明细',
        'files': {
            'ssq': ['ssq_data_clean.csv'],
        },
        'kind': 'csv_yeyingbao',
    },
]


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def gh_api_bytes(url: str, timeout: int = 90, retries: int = 4) -> bytes:
    """
    调GitHub API 并完整读取响应体。
    GitHub 大 blob 会 IncompleteRead, 必须分块读 + 重试。
    """
    last = None
    for i in range(retries):
        try:
            req = Request(url, headers=HDRS)
            with urlopen(req, timeout=timeout, context=_ctx()) as r:
                buf = b''
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    buf += chunk
            return buf
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(2.0 * (i + 1))
    raise RuntimeError(f'GitHub API failed: {last}')


def gh_download(repo: str, path: str) -> bytes:
    """下载仓库文件 (走 API, 避开 raw DNS)"""
    meta = json.loads(gh_api_bytes(f'https://api.github.com/repos/{repo}/contents/{path}'))
    if meta.get('size', 0) > 500_000:
        blob = json.loads(gh_api_bytes(
            f'https://api.github.com/repos/{repo}/git/blobs/{meta["sha"]}'))
        return base64.b64decode(blob['content'].replace('\n', ''))
    return base64.b64decode(meta['content'].replace('\n', ''))


def normalize_date(raw: str) -> str:
    """2023-07-18(二) / 2008/1/1 / 2020年10月07日 → ISO"""
    if not raw:
        return ''
    s = str(raw).strip()
    s = re.sub(r'\([^)]{0,8}\)|（[^）]{0,8}）', '', s)
    m = re.search(r'(\d{4})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})', s)
    if m:
        y, mo, d = m.groups()
        return f'{int(y):04d}-{int(mo):02d}-{int(d):02d}'
    return ''


def normalize_period(raw: str) -> str:
    """
    期号归一化 (统一成 7 位: 2026001)
    DLT 5 位 (26119) → 2026119
    SSQ 7 位 (2026119) → 2026119
    """
    s = str(raw).strip()
    if len(s) == 5:
        return f'20{s}'
    if len(s) == 7:
        return s
    if len(s) == 6:
        return f'20{s}'
    return s


def _valid(game: str, front: List[int], back: List[int]) -> bool:
    cfg = GAMES[game]
    if len(front) != cfg['front_count'] or len(back) != cfg['back_count']:
        return False
    if not all(1 <= n <= cfg['front_range'] for n in front):
        return False
    if not all(1 <= n <= cfg['back_range'] for n in back):
        return False
    return len(set(front)) == len(front) and len(set(back)) == len(back)


def parse_yangxb(game: str, data: bytes) -> List[Dict]:
    """yangxb919 JSON: [{issue, date, front|red, back|blue, source}]"""
    j = json.loads(data.decode('utf-8', 'ignore'))
    out = []
    for r in j:
        issue = str(r.get('issue', '')).strip()
        if not re.fullmatch(r'\d{5,7}', issue):
            continue
        # DLT: front/back   SSQ: red/blue
        front_raw = r.get('front') or r.get('red') or []
        back_raw = r.get('back') or r.get('blue') or []
        try:
            front = sorted(int(x) for x in front_raw)
            back = sorted(int(x) for x in back_raw)
        except (ValueError, TypeError):
            continue
        if not _valid(game, front, back):
            continue
        out.append({
            'period': normalize_period(issue),
            'draw_date': normalize_date(r.get('date', '')),
            'front': front,
            'back': back,
        })
    return out


def parse_yeyingbao(game: str, data: bytes) -> List[Dict]:
    """yeyingbao CSV: 序号,开奖日期,期号,红球1-6,蓝球,销售额,...奖池"""
    text = data.decode('utf-8-sig', errors='ignore')
    lines = text.strip().split('\n')
    header = [c.strip().lstrip('\ufeff') for c in lines[0].split(',')]

    def col(name):
        return header.index(name) if name in header else -1

    i_date = col('开奖日期')
    i_period = col('期号')
    i_front = [col(f'红球{i}') for i in range(1, 7)]
    i_back = [col('蓝球')]
    i_sales = col('销售额')
    i_prize = col('奖池（元）')

    if i_period < 0 or any(i < 0 for i in i_front):
        raise ValueError(f'列名不匹配: {header[:8]}')

    out = []
    for line in lines[1:]:
        cells = line.split(',')
        if len(cells) <= max(i_period, *i_front):
            continue
        try:
            period = cells[i_period].strip()
            front = sorted(int(cells[i].strip()) for i in i_front)
            back = [int(cells[i_back[0]].strip())]
        except (ValueError, IndexError):
            continue
        if not re.fullmatch(r'\d{5,8}', period) or not _valid(game, front, back):
            continue

        def _f(idx):
            if idx < 0 or idx >= len(cells):
                return None
            try:
                return float(cells[idx].strip())
            except ValueError:
                return None

        out.append({
            'period': normalize_period(period),
            'draw_date': normalize_date(cells[i_date]) if i_date >= 0 else '',
            'front': front,
            'back': back,
            'sales': _f(i_sales),
            'prize_money': _f(i_prize),
        })
    return out


PARSERS = {
    'json_yangxb': parse_yangxb,
    'csv_yeyingbao': parse_yeyingbao,
}


def load_existing(game: str) -> Dict[str, Dict]:
    path = DATA_RAW / f'gh_{game}.csv'
    if not path.exists():
        return {}
    cfg = GAMES[game]
    out: Dict[str, Dict] = {}
    with open(path, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                front = [int(row[f'front_{i+1}']) for i in range(cfg['front_count'])]
                back = [int(row[f'back_{i+1}']) for i in range(cfg['back_count'])]
            except (KeyError, ValueError):
                continue
            out[row['period']] = {
                'period': row['period'], 'draw_date': row.get('draw_date', ''),
                'front': sorted(front), 'back': sorted(back),
                'sales': row.get('sales'), 'prize_money': row.get('prize_money'),
            }
    return out


def save_csv(game: str, records: List[Dict]) -> Path:
    cfg = GAMES[game]
    out = DATA_RAW / f'gh_{game}.csv'
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['period', 'draw_date']
                   + [f'front_{i+1}' for i in range(cfg['front_count'])]
                   + [f'back_{i+1}' for i in range(cfg['back_count'])]
                   + ['sales', 'prize_money'])
        for r in records:
            w.writerow([r['period'], r['draw_date']] + r['front'] + r['back']
                       + [r.get('sales') or '', r.get('prize_money') or ''])
    return out


def collect(game: str = 'dlt', verbose: bool = True) -> List[Dict]:
    by_period: Dict[str, Dict] = load_existing(game)
    if verbose and by_period:
        print(f'  已有: {len(by_period)} 期')

    for spec in SOURCES:
        paths = spec['files'].get(game)
        if not paths:
            continue
        if verbose:
            print(f'\n  [{spec["id"]}] {spec["repo"]}')
            print(f'    {spec["desc"]}')

        for path in paths:
            if verbose:
                print(f'    ↓ {path}')
            try:
                data = gh_download(spec['repo'], path)
                recs = PARSERS[spec['kind']](game, data)
                new = 0
                for r in recs:
                    p = r['period']
                    if p not in by_period:
                        by_period[p] = r
                        new += 1
                    else:
                        # 补真实日期
                        if not by_period[p].get('draw_date') and r.get('draw_date'):
                            by_period[p]['draw_date'] = r['draw_date']
                        for fld in ('sales', 'prize_money'):
                            if not by_period[p].get(fld) and r.get(fld):
                                by_period[p][fld] = r[fld]
                if verbose:
                    dated = sum(1 for r in recs if r.get('draw_date'))
                    print(f'      解析 {len(recs)} 期 ({dated} 有真实日期), 新增 {new}')
            except Exception as e:
                if verbose:
                    print(f'      ERR: {str(e)[:110]}')

    records = sorted(by_period.values(), key=lambda x: x['period'])
    out = save_csv(game, records)
    if verbose:
        print(f'\n  ✅ {len(records)} 期 → {out}')
    return records


def validate(game: str, records: List[Dict]) -> None:
    cfg = GAMES[game]
    print(f'\n  --- {GAMES[game]["name"]} GitHub 数据集 ---')
    print(f'    期数: {len(records)}')
    if records:
        print(f'    期号: {records[0]["period"]} ~ {records[-1]["period"]}')
    dated = [r for r in records if r.get('draw_date')]
    print(f'    真实日期: {len(dated)}/{len(records)}')
    if dated:
        ds = sorted(r['draw_date'] for r in dated)
        print(f'    日期跨度: {ds[0]} ~ {ds[-1]}')

    if len(records) >= cfg['min_periods']:
        print(f'    ✅ 远超 {cfg["min_periods"]} 期门槛')
    else:
        print(f'    ⚠ 少于 {cfg["min_periods"]} 期')

    # 连续性
    if len(dated) >= 2:
        from datetime import datetime
        ds = sorted(r['draw_date'] for r in dated)
        gaps = []
        for a, b in zip(ds, ds[1:]):
            gap = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days
            if gap > 15:
                gaps.append(f'{a}→{b}({gap}天)')
        if gaps:
            print(f'    ⚠ 时间断点 {len(gaps)} 处: {gaps[:3]}')
        else:
            print(f'    ✅ 日期连续 (无 >15 天空洞)')

    # χ²
    freq: Dict[int, int] = {}
    for r in records:
        for n in r['front']:
            freq[n] = freq.get(n, 0) + 1
    exp = len(records) * cfg['front_count'] / cfg['front_range'] if records else 0
    if freq and exp > 0:
        top = sorted(freq.items(), key=lambda x: -x[1])[:5]
        bot = sorted(freq.items(), key=lambda x: x[1])[:5]
        chi2 = sum((c - exp) ** 2 / exp for c in freq.values())
        chi2 += (cfg['front_range'] - len(freq)) * exp
        dof = cfg['front_range'] - 1
        print(f'    理论每号: {exp:.1f} 次')
        print(f'    最热: {top}')
        print(f'    最冷: {bot}')
        print(f'    χ²={chi2:.1f} df={dof} (≈{dof * 1.5:.0f} 内无显著偏离)')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='从 GitHub 开源仓库采集彩票历史数据')
    ap.add_argument('--game', default='dlt', choices=['ssq', 'dlt'])
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()

    for g in (['dlt', 'ssq'] if args.all else [args.game]):
        print()
        print('#' * 74)
        print(f'# GitHub 数据集 · {GAMES[g]["name"]} ({g})')
        print('#' * 74)
        recs = collect(g)
        validate(g, recs)
        print()