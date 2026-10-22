"""
中国体育彩票竞彩 官方赔率采集器
=================================
源: webapi.sporttery.cn 官方公开 API (无需 key, 实时更新)

覆盖玩法:
  - HAD  胜平负 (固定奖金)
  - HHAD 让球胜平负 (含让球数)
  - CRS  比分
  - TTG  总进球
  - HAFU 半全场

每场带:
  - 中文队名 (homeTeamAbbName)
  - **英文缩写** (homeTeamAbbEnName, 如 JUV / RMA) → 用于跟境外盘口匹配
  - 英文全名 (homeTeamAllName)
  - 竞彩编号 (matchNumStr)

本地缓存: data-raw/jingcai/latest.json
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / 'data-raw' / 'jingcai'

# 体彩官方 API
API_CALC = ('https://webapi.sporttery.cn/gateway/jc/football/'
            'getMatchCalculatorV1.qry?poolCode=hhad,had,crs,ttg,hafu&channel=c')
API_RESULT = ('https://webapi.sporttery.cn/gateway/jc/football/'
               'getMatchResultV1.qry?poolCode=hhad,had&channel=c')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
HEADERS = {
    'User-Agent': UA,
    'Referer': 'https://www.sporttery.cn/',
    'Accept': 'application/json, text/plain, */*',
}

# ⚠ 环境变量里的死代理会让 urllib 连接被拒 → 显式禁用
_PROXY = os.environ.get('SPORTS_GITHUB_PROXY', '').strip()
if _PROXY:
    _opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({'http': _PROXY, 'https': _PROXY}))
else:
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ============================================================
# 联赛映射 (竞彩中文 → 境外常用英文)
# ============================================================
LEAGUE_MAP = {
    '欧冠': 'uefa-champions-league',
    '欧罗巴': 'uefa-europa-league',
    '欧协联': 'uefa-conference-league',
    '英超': 'premier-league',
    '西甲': 'la-liga',
    '意甲': 'serie-a',
    '德甲': 'bundesliga',
    '法甲': 'ligue-1',
    '荷甲': 'eredivisie',
    '葡超': 'primeira-liga',
    '苏超': 'scottish-premiership',
    '日职联': 'j-league',
    '美职联': 'mls',
    '巴西甲': 'brasileirao-serie-a',
    '挪超': 'norway-eliteserien',
    '瑞典超': 'allsvenskan',
    '丹超': 'danish-superliga',
    '比甲': 'belgian-jupiler-pro-league',
    '土超': 'turkish-super-lig',
    '奥甲': 'austrian-bundesliga',
    '苏超杯': 'scottish-premiership',
    '解放者杯': 'copa-libertadores',
    '巴西杯': 'copa-do-brasil',
    '欧篮': 'basketball-euroleague',
}


def _http_json(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with _opener.open(req, timeout=30) as r:
            raw = r.read()
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8', errors='replace')
            return json.loads(raw)
    except Exception as e:
        print(f'  [warn] 请求失败 {url[:70]}: {e}')
        return None


# ============================================================
# 采集
# ============================================================
def fetch_matches(pools: str = 'hhad,had,crs,ttg,hafu') -> List[Dict]:
    """拉取当前在售竞彩足球比赛 (含各玩法赔率)"""
    url = (f'https://webapi.sporttery.cn/gateway/jc/football/'
           f'getMatchCalculatorV1.qry?poolCode={pools}&channel=c')
    data = _http_json(url)
    if not data or not data.get('success'):
        return []

    out = []
    for group in (data.get('value') or {}).get('matchInfoList') or []:
        for m in group.get('subMatchList') or []:
            had = m.get('had') or {}
            hhad = m.get('hhad') or {}
            if not (had.get('h') and had.get('d') and had.get('a')):
                continue

            def f(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            rec = {
                'match_id': str(m.get('matchId', '')),
                'match_num': str(m.get('matchNumStr') or m.get('matchNum', '')),
                'date': m.get('matchDate', ''),
                'time': m.get('matchTime', ''),
                'weekday': m.get('matchWeek', ''),
                'league_cn': m.get('leagueAbbName', ''),
                'league_all': m.get('leagueAllName', ''),
                'league_code': str(m.get('leagueCode', '')),
                'league_slug': LEAGUE_MAP.get(m.get('leagueAbbName', ''), ''),
                'home_cn': m.get('homeTeamAbbName', ''),
                'away_cn': m.get('awayTeamAbbName', ''),
                'home_en': (m.get('homeTeamAbbEnName') or '').strip(),
                'away_en': (m.get('awayTeamAbbEnName') or '').strip(),
                'home_all': m.get('homeTeamAllName', ''),
                'away_all': m.get('awayTeamAllName', ''),
                'status': m.get('matchStatus', ''),
                'update_time': f"{had.get('updateDate','')} {had.get('updateTime','')}".strip(),
                'had': {'h': f(had.get('h')), 'd': f(had.get('d')),
                        'a': f(had.get('a'))},
                'hhad': {'h': f(hhad.get('h')), 'd': f(hhad.get('d')),
                         'a': f(hhad.get('a')),
                         'goal_line': hhad.get('goalLine', '')},
                'had_update': f"{had.get('updateDate','')} {had.get('updateTime','')}".strip(),
            }
            out.append(rec)
    return out


def fetch_results() -> List[Dict]:
    """拉取已开奖结果 (含最终比分)"""
    data = _http_json(API_RESULT)
    if not data or not data.get('success'):
        return []
    out = []
    for m in (data.get('value') or {}).get('resultList') or []:
        try:
            hg = int(m.get('sectionsNo999', {}).get('h', 0))
        except (TypeError, ValueError):
            hg = None
        out.append({
            'match_id': str(m.get('matchId', '')),
            'date': m.get('businessDate', ''),
            'league_cn': m.get('leagueAbbName', ''),
            'home_cn': m.get('homeTeamAbbName', ''),
            'away_cn': m.get('awayTeamAbbName', ''),
            'home_en': (m.get('homeTeamAbbEnName') or '').strip(),
            'away_en': (m.get('awayTeamAbbEnName') or '').strip(),
            'had': m.get('had', {}),
            'hhad': m.get('hhad', {}),
            'sections': m.get('sectionsNo999', {}),
            'had_result': m.get('hadResult', ''),
            'hhad_result': m.get('hhadResult', ''),
        })
    return out


def save_cache(matches: List[Dict], path: Path = None) -> Path:
    path = path or (CACHE_DIR / 'latest.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'fetched_at': datetime.now().isoformat(timespec='seconds'),
        'count': len(matches),
        'matches': matches,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    return path


def load_cache(path: Path = None) -> List[Dict]:
    path = path or (CACHE_DIR / 'latest.json')
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding='utf-8')).get('matches', [])
    except Exception:
        return []


# ============================================================
# 分析
# ============================================================
def analyze_vig(matches: List[Dict]) -> Dict:
    """竞彩自身的抽水分析 (HAD 胜平负)"""
    vigs = []
    per_league = {}
    for m in matches:
        o = m.get('had') or {}
        h, d, a = o.get('h'), o.get('d'), o.get('a')
        if not (h and d and a and h > 1 and d > 1 and a > 1):
            continue
        v = (1 / h + 1 / d + 1 / a) - 1
        vigs.append(v)
        per_league.setdefault(m.get('league_cn', ''), []).append(v)
    if not vigs:
        return {'count': 0}
    import numpy as np
    arr = np.array(vigs)
    leagues = {k: {'count': len(v), 'mean': float(np.mean(v)),
                   'median': float(np.median(v))}
               for k, v in per_league.items()}
    return {
        'count': len(vigs),
        'mean': float(arr.mean()),
        'median': float(np.median(arr)),
        'min': float(arr.min()),
        'max': float(arr.max()),
        'leagues': dict(sorted(leagues.items(),
                                key=lambda x: x[1]['mean'])),
    }


__all__ = [
    'LEAGUE_MAP', 'fetch_matches', 'fetch_results', 'save_cache',
    'load_cache', 'analyze_vig', 'CACHE_DIR',
]
