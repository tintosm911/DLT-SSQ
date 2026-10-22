"""
真实历史赔率采集器 (football-data.co.uk GitHub 镜像)
======================================================
数据源: github.com/huh ao930422-debug/football-odds-mirror
        (football-data.co.uk 的每日镜像, 每天自动更新)

覆盖: 22 个联赛 × 30+ 赛季 (英超 1993-94 ~ 2025-26)
字段: 赛果 + 8+ 家博彩公司赛前/收盘 1X2 赔率 + 大小球 + 亚洲盘

为什么用这个源:
  - **完全免费**, 无需 API Key (对比 AnySport Pro $199/月)
  - **30+ 年真实历史**, 不是模拟数据
  - 含**收盘赔率** (PSCH/AvgCH 等) — 评估"能否战胜市场"的黄金标准
  - 含**多家公司** — 可做跨公司套利检测

本地缓存: data-raw/sports/{league}_{season}.csv
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / 'data-raw' / 'sports'

REPO = 'huhao930422-debug/football-odds-mirror'
API = f'https://api.github.com/repos/{REPO}'
HDRS = {'Accept': 'application/vnd.github+json', 'User-Agent': 'lottery-lab'}

# ⚠ 环境变量里的 HTTP_PROXY 指向公司网死代理, urllib 会自动读取导致连接被拒.
#   实测 api.github.com 直连可用, 所以显式禁用代理 (可用 SPORTS_GITHUB_PROXY 覆盖)
_PROXY = os.environ.get('SPORTS_GITHUB_PROXY', '').strip()
if _PROXY:
    _opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({'http': _PROXY, 'https': _PROXY}))
else:
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# GitHub token: 匿名 API 限流 60 次/小时, 带 token 是 5000 次/小时.
# 优先读环境变量 GITHUB_TOKEN / GH_TOKEN, 其次读项目根的 .github_token
def _load_token() -> str:
    for env in ('SPORTS_GITHUB_TOKEN', 'GITHUB_TOKEN', 'GH_TOKEN'):
        v = os.environ.get(env, '').strip()
        if v:
            return v
    for name in ('.github_token', 'token.txt'):
        p = PROJECT_ROOT / name
        if p.exists():
            try:
                v = p.read_text(encoding='utf-8').strip()
                if v:
                    return v
            except OSError:
                pass
    return ''


GITHUB_TOKEN = _load_token()
if GITHUB_TOKEN:
    HDRS['Authorization'] = f'Bearer {GITHUB_TOKEN}'


# ============================================================
# 联赛 → 镜像目录名 映射
# ============================================================
LEAGUE_DIRS = {
    'premier-league': '英超',
    'la-liga': '西甲',
    'serie-a': '意甲',
    'bundesliga': '德甲',
    'ligue-1': '法甲',
    'championship': '英冠',
    'scottish-premiership': '苏超',
    'eredivisie': '荷甲',
    'primeira-liga': '葡超',
    'denmark': '丹麦超',
    'norway': '挪超',
    'sweden': '瑞典超',
    'finland': '芬超',
    'jupiler-league': '比甲',
    'super-lig': '土超',
    'brazil': '巴西甲',
    'japan': '日职联',
    'usa': '美职联',
    'league-one': '英甲',
    'la-liga-2': '西乙',
    'bundesliga-2': '德乙',
    'serie-b': '意乙',
    'scottish-championship': '苏冠',
    'ligue-2': '法乙',
}


# ============================================================
# 博彩公司 (只列"真正独立的公司", 排除 Max/Avg 这类聚合列)
# ============================================================
BOOKMAKERS: Dict[str, tuple] = {
    'B365':       ('B365H', 'B365D', 'B365A'),
    'Pinnacle':   ('PSH', 'PSD', 'PSA'),
    'WilliamHill': ('WHH', 'WHD', 'WHA'),
    'Betfair':    ('BFH', 'BFD', 'BFA'),
    'VCBet':      ('VCH', 'VCD', 'VCA'),
    'Interwetten': ('IWH', 'IWD', 'IWA'),
    'Ladbrokes':  ('LBH', 'LBD', 'LBA'),
    'Unibet':     ('UBH', 'UBD', 'UBA'),
}

# 收盘赔率 (closing line) — 市场最终定价, 评估价值下注的金标准
CLOSING_BOOKMAKERS: Dict[str, tuple] = {
    'B365_C':     ('B365CH', 'B365CD', 'B365CA'),
    'Pinnacle_C': ('PSCH', 'PSCD', 'PSCA'),
    'Avg_C':      ('AvgCH', 'AvgCD', 'AvgCA'),
    'Max_C':      ('MaxCH', 'MaxCD', 'MaxCA'),
}

# 聚合列 (不是独立公司, 只用于"市场共识"参考)
AGGREGATE_BOOKS: Dict[str, tuple] = {
    'Max':  ('MaxH', 'MaxD', 'MaxA'),
    'Avg':  ('AvgH', 'AvgD', 'AvgA'),
}


# ============================================================
# 采集
# ============================================================
def _gh_get(path: str):
    req = urllib.request.Request(f'{API}/{path}', headers=HDRS)
    with _opener.open(req, timeout=40) as r:
        return json.loads(r.read().decode())


def list_seasons(league: str) -> List[str]:
    """列出某联赛所有赛季文件名"""
    try:
        items = _gh_get(f'contents/data/{league}')
    except Exception as e:
        print(f'  [warn] 列目录失败 {league}: {e}')
        return []
    return sorted([i['name'] for i in items if i['name'].endswith('.csv')])


def fetch_season_csv(league: str, season_file: str) -> Optional[str]:
    """拉取一个赛季的 CSV 原文 (带本地缓存)"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f'{league}_{season_file}'
    if cache.exists() and cache.stat().st_size > 1000:
        return cache.read_text(encoding='utf-8-sig')
    try:
        info = _gh_get(f'contents/data/{league}/{season_file}')
        blob = _gh_get(f'git/blobs/{info["sha"]}')
        text = base64.b64decode(blob['content']).decode('utf-8-sig')
        cache.write_text(text, encoding='utf-8')
        return text
    except Exception as e:
        print(f'  [warn] 拉取失败 {league}/{season_file}: {e}')
        return None


def fetch_league(league: str, seasons: Optional[List[str]] = None,
                 verbose: bool = True) -> Dict[str, str]:
    """拉取一个联赛的全部赛季 (或指定赛季)"""
    files = seasons or list_seasons(league)
    out = {}
    for f in files:
        if verbose:
            print(f'  {league}/{f} ...', end=' ', flush=True)
        txt = fetch_season_csv(league, f)
        if txt:
            out[f] = txt
            if verbose:
                print(f'OK ({len(txt.splitlines())} 行)')
        elif verbose:
            print('FAIL')
    return out


def parse_season(text: str) -> List[Dict]:
    """解析 CSV → 标准化的比赛记录"""
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in rows:
        try:
            fthg = int(r['FTHG'])
            ftag = int(r['FTAG'])
        except (KeyError, ValueError, TypeError):
            continue
        rec = {
            'date': (r.get('Date') or '').strip(),
            'home': (r.get('HomeTeam') or '').strip(),
            'away': (r.get('AwayTeam') or '').strip(),
            'fthg': fthg,
            'ftag': ftag,
            'ftr': (r.get('FTR') or '').strip(),   # H / D / A
            'odds': {},
            'closing': {},
        }
        for name, (h, d, a) in BOOKMAKERS.items():
            try:
                oh, od, oa = float(r[h]), float(r[d]), float(r[a])
                if oh > 1 and od > 1 and oa > 1:
                    rec['odds'][name] = (oh, od, oa)
            except (KeyError, ValueError, TypeError):
                pass
        for name, (h, d, a) in CLOSING_BOOKMAKERS.items():
            try:
                oh, od, oa = float(r[h]), float(r[d]), float(r[a])
                if oh > 1 and od > 1 and oa > 1:
                    rec['closing'][name] = (oh, od, oa)
            except (KeyError, ValueError, TypeError):
                pass
        for name, (h, d, a) in AGGREGATE_BOOKS.items():
            try:
                oh, od, oa = float(r[h]), float(r[d]), float(r[a])
                if oh > 1 and od > 1 and oa > 1:
                    rec['odds'][name] = (oh, od, oa)
            except (KeyError, ValueError, TypeError):
                pass
        if rec['ftr'] not in ('H', 'D', 'A'):
            continue
        out.append(rec)
    return out


def load_league(league: str, seasons: Optional[List[str]] = None,
                verbose: bool = True) -> List[Dict]:
    """拉取 + 解析一个联赛的全部比赛"""
    data = fetch_league(league, seasons, verbose)
    matches = []
    for f, txt in sorted(data.items()):
        matches.extend(parse_season(txt))
    return matches


__all__ = [
    'LEAGUE_DIRS', 'BOOKMAKERS', 'CLOSING_BOOKMAKERS', 'AGGREGATE_BOOKS',
    'list_seasons', 'fetch_season_csv', 'fetch_league', 'parse_season',
    'load_league', 'CACHE_DIR',
]
