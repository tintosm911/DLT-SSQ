"""
实时扫描服务层
==============
把"竞彩官方 + 境外实时赔率"的双向扫描包装成 Web 可调用的服务.

API key 存放优先级:
  1. 环境变量 ODDS_API_KEY
  2. 项目根的 .odds_api_key 文件 (已 gitignore)
前端永远拿不到 key, 只看结果.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

KEY_FILE = PROJECT_ROOT / '.odds_api_key'

# 上次扫描结果缓存 (避免重复消耗 API 配额)
_cache: Dict = {'result': None, 'time': 0.0}
CACHE_TTL = 300  # 5 分钟内复用


def get_api_key() -> str:
    """
    读取 API key.

    ⚠ 必须剥离 UTF-8 BOM: Windows PowerShell 5.1 的 Set-Content -Encoding UTF8
      会写 BOM, 读出来变成 '\\ufeff<key>' → the-odds-api 返回 401 Unauthorized.
    """
    v = os.environ.get('ODDS_API_KEY', '').strip().lstrip('﻿')
    if v:
        return v
    if KEY_FILE.exists():
        try:
            raw = KEY_FILE.read_text(encoding='utf-8-sig')
            return raw.strip().lstrip('﻿')
        except OSError:
            pass
    return ''


def has_key() -> bool:
    return bool(get_api_key())


def run_scan(min_profit: float = 0.0,
             use_cache: bool = True) -> Dict:
    """跑一次实时双向扫描"""
    key = get_api_key()
    if not key:
        return {'ok': False, 'error': '未配置 the-odds-api key '
                                     '(设 ODDS_API_KEY 环境变量或放 .odds_api_key 文件)'}

    # 缓存
    now = time.time()
    if use_cache and _cache['result'] and now - _cache['time'] < CACHE_TTL:
        r = dict(_cache['result'])
        r['from_cache'] = True
        r['cache_age_sec'] = int(now - _cache['time'])
        return r

    from scripts.live_scanner import run_live_scan
    from data.jingcai_odds import fetch_matches

    jc = fetch_matches()
    if not jc:
        return {'ok': False, 'error': '竞彩官方数据拉取失败'}

    r = run_live_scan(key, min_profit=min_profit, jc_matches=jc)
    if r.get('ok'):
        r['from_cache'] = False
        _cache['result'] = r
        _cache['time'] = now
    return r


def summarize(r: Dict) -> Dict:
    """给前端的精简摘要"""
    if not r.get('ok'):
        return r
    matches = r.get('matches', [])
    # book_vig_best 可能是 (name, np.array) — 统一成 (name, float 均值)
    bvb = r.get('book_vig_best')
    if bvb is not None:
        import numpy as np
        name, val = bvb
        bvb = (name, float(np.mean(val)) if hasattr(val, '__len__')
               else float(val))

    # best_arb 里嵌了 match (含 numpy 数组), 转成纯 Python
    best = r.get('best_arb')
    if best:
        best = {
            'books': list(best.get('books', [])),
            'odds': [float(x) for x in best.get('odds', [])],
            'sum_inv': float(best.get('sum_inv', 0)),
            'profit_pct': float(best.get('profit_pct', 0)),
            'stakes': _stakes([float(x) for x in best.get('odds', [])], 100),
            'match': best.get('match', {}),
        }
    return {
        'ok': True,
        'scan_time': r.get('scan_time'),
        'from_cache': r.get('from_cache', False),
        'cache_age_sec': r.get('cache_age_sec', 0),
        'n_jc': r.get('n_jc', 0),
        'n_ov': r.get('n_ov', 0),
        'n_paired': r.get('n_paired', 0),
        'n_with_arb': r.get('n_with_arb', 0),
        'jc_vig_mean': r.get('jc_vig_mean', 0),
        'book_vig_mean': {b: float(v) for b, v in
                          (r.get('book_vig_mean') or {}).items()},
        'book_vig_best': bvb,
        'best_arb': best,
        'matches': [{
            'league': m['league'],
            'date': m['date'], 'time': m['time'],
            'home': m['home'], 'away': m['away'],
            'home_en': m['home_en'], 'away_en': m['away_en'],
            'jc_odds': m['jc_odds'],
            'jc_vig': m['jc_vig'],
            'ov_event': m['ov_event'],
            'ov_commence': m.get('ov_commence'),
            'best_book': m.get('best_book'),
            'best_book_vig': m.get('best_book_vig', 0),
            'n_books': len(m.get('books', {})),
            'arbs': [{
                'books': list(a['books']),
                'odds': list(a['odds']),
                'sum_inv': a['sum_inv'],
                'profit_pct': a['profit_pct'],
                'stakes': _stakes(a['odds'], 100),
            } for a in m.get('arbs', [])],
        } for m in matches],
    }


def _stakes(odds, total=100.0):
    """资金分配方案"""
    inv = [1 / o for o in odds]
    s = sum(inv)
    payout = total / s
    return [{'stake': round(payout / o, 2), 'payout': round(payout, 2)}
            for o in odds]


__all__ = ['get_api_key', 'has_key', 'run_scan', 'summarize', 'KEY_FILE']
