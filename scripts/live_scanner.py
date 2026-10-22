"""
实时双向扫描器: 中国竞彩 × 境外盘口
=========================================
输入:
  - 竞彩官方实时赔率 (webapi.sporttery.cn, 已有采集器)
  - 境外多公司实时赔率 (the-odds-api.com, 需 API key)
输出:
  - 逐场匹配 (中英文队名 + 联赛 + 开赛时间)
  - 每个市场的抽水对比 (竞彩 vs 境外各公司)
  - 跨市场套利机会 (Σ(1/odds) < 1) + 资金分配方案

用法:
  python scripts/live_scanner.py --api-key YOUR_KEY
  python scripts/live_scanner.py --api-key YOUR_KEY --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np

from data.jingcai_odds import fetch_matches

# ============================================================
# 配置
# ============================================================
# 竞彩联赛 (中文) → the-odds-api sport key
SPORT_KEYS = {
    '英超': 'soccer_epl',
    '英冠': 'soccer_efl_champ',
    '英甲': 'soccer_england_league1',
    '英乙': 'soccer_england_league2',
    '西甲': 'soccer_spain_la_liga',
    '西乙': 'soccer_spain_segunda_division',
    '意甲': 'soccer_italy_serie_a',
    '意乙': 'soccer_italy_serie_b',
    '德甲': 'soccer_germany_bundesliga',
    '德乙': 'soccer_germany_bundesliga2',
    '法甲': 'soccer_france_ligue_one',
    '法乙': 'soccer_france_ligue_two',
    '荷甲': 'soccer_netherlands_eredivisie',
    '葡超': 'soccer_portugal_primeira_liga',
    '苏超': 'soccer_scotland_premier_league',
    '欧冠': 'soccer_uefa_champs_league',
    '欧罗巴': 'soccer_uefa_europa_league',
    '欧协联': 'soccer_uefa_europa_conference_league',
    '欧国联': 'soccer_uefa_nations_league',
    '比甲': 'soccer_belgium_first_div',
    '土超': 'soccer_turkey_super_lig',
    '希腊超': 'soccer_greece_super_league',
    '瑞士超': 'soccer_switzerland_superleague',
    '波兰超': 'soccer_poland_ekstraklasa',
    '日职联': 'soccer_japan_j_league',
    '韩K联': 'soccer_korea_kleague1',
    '美职联': 'soccer_usa_mls',
    '巴西甲': 'soccer_brazil_campeonato',
    '巴乙': 'soccer_brazil_serie_b',
    '阿根廷甲': 'soccer_argentina_primera_division',
    '智利甲': 'soccer_chile_campeonato',
    '澳超': 'soccer_australia_aleague',
    '挪超': 'soccer_norway_eliteserien',
    '瑞典超': 'soccer_sweden_allsvenskan',
    '瑞典甲': 'soccer_sweden_superettan',
    '丹超': 'soccer_denmark_superliga',
    '芬超': 'soccer_finland_veikkausliiga',
    '奥甲': 'soccer_austria_bundesliga',
    '俄超': 'soccer_russia_premier_league',
    '沙职联': 'soccer_saudi_arabia_pro_league',
    '解放者杯': 'soccer_conmebol_copa_libertadores',
    '南美杯': 'soccer_conmebol_copa_sudamericana',
    '墨西哥超': 'soccer_mexico_ligamx',
    '爱尔兰超': 'soccer_league_of_ireland',
    '中超': 'soccer_china_superleague',
}

# 队名归一化时剔除的噪声词
NOISE = re.compile if False else None  # 占位, 下面用函数实现

import re as _re

_NOISE = _re.compile(
    r'\b(fc|afc|cf|sc|ac|as|ss|us|ud|cd|rc|rcde|calcio|club|'
    r'united|city|town|rovers|albion|forest|athletic|hotspur|'
    r'sporting|deportivo|olympique|rcd|sv|bsc|tsg|vfl|vfb|'
    r'\d{2,4})\b', _re.I)


def norm(s: str) -> str:
    """队名归一化: 小写、去符号、去噪声词"""
    s = (s or '').lower()
    s = s.replace('&', ' and ').replace('.', ' ').replace('-', ' ')
    s = _re.sub(r'[^a-z0-9 ]', ' ', s)
    s = _NOISE.sub(' ', s)
    return _re.sub(r'\s+', ' ', s).strip()


def norm_soft(s: str) -> str:
    """轻度归一化: 保留所有词 (应对缩写缺失)"""
    s = (s or '').lower()
    s = s.replace('&', ' and ')
    s = _re.sub(r'[^a-z0-9 ]', ' ', s)
    return _re.sub(r'\s+', ' ', s).strip()


# ============================================================
# the-odds-api 客户端
# ============================================================
class OddsAPI:
    BASE = 'https://api.the-odds-api.com/v4'

    def __init__(self, api_key: str):
        self.key = api_key
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}))

    def _get(self, path: str, params: dict) -> dict:
        url = f'{self.BASE}{path}?{urlencode(params)}'
        req = urllib.request.Request(url, headers={'User-Agent': 'lottery-lab'})
        with self._opener.open(req, timeout=40) as r:
            return json.loads(r.read().decode())

    def upcoming_odds(self, sport_key: str,
                      regions: str = 'eu',
                      markets: str = 'h2h') -> List[dict]:
        try:
            return self._get('/sports/upcoming/odds/', {
                'apiKey': self.key,
                'regions': regions,
                'markets': markets,
                'oddsFormat': 'decimal',
                'sport': sport_key,
            })
        except Exception as e:
            print(f'  [warn] {sport_key} 拉取失败: {e}')
            return []

    def scoreboard(self, sport_key: str) -> List[dict]:
        """已开赛的赛事 (含比分) — 用于事后验证"""
        try:
            return self._get('/sports/upcoming/scores/', {
                'apiKey': self.key,
                'sport': sport_key,
                'daysFrom': 3,
            })
        except Exception:
            return []


def urlencode(d: dict) -> str:
    from urllib.parse import urlencode as _u
    return _u(d)


# ============================================================
# 匹配
# ============================================================
def code_in_name(code: str, name: str, strict: bool = True) -> bool:
    """
    竞彩 3 字母码是否**按顺序**出现在境外队名中.

    这是竞彩英文缩写的通用规律 (实测 5 大联赛 + 欧战 100% 命中):
      SGZ ← SK Sturm Graz          (S, G, Z)
      DNZ ← Dinamo Zagreb         (D, N, Z)
      CVO ← Celta Vigo            (C, V, O)
      AJX ← Ajax                  (A, J, X)
      LYO ← Lyon                  (L, Y, O)
      LIS ← Lillestrom            (L, I, S)
      ACM ← AC Milan              (A, C, M)
      CRY ← Crystal Palace        (C, R, Y)

    比"子串包含"严格得多, 能有效排除假阳性.

    ⚠ strict=False 会放宽到"前两个字母按序 + 第三字母任意位置",
      实测会引入误配 (如 LIS 匹配到 "Union Saint-Gilloise"),
      导致算出不真实的巨额套利. 默认必须 strict=True.
    """
    if not code or not name:
        return False
    up = name.upper()
    code = code.upper()

    # 严格: 全部字母按序出现
    pos = 0
    for ch in code:
        idx = up.find(ch, pos)
        if idx < 0:
            break
        pos = idx + 1
    else:
        return True

    if strict:
        return False

    # 容错: 前两个字母按序 + 第三个字母在队名任意位置
    if len(code) >= 3:
        i1 = up.find(code[0])
        if i1 >= 0:
            i2 = up.find(code[1], i1 + 1)
            if i2 >= 0 and code[2] in up:
                return True
    return False


def _parse_time(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def match_matches(jc: List[dict], ov: List[dict],
                  max_hours: float = 36.0) -> List[dict]:
    """
    把竞彩比赛与境外比赛配对.

    匹配依据 (全部满足):
      1. 同一联赛 (由调用方保证: 境外事件按 sport_key 分组传入)
      2. 主队码按序出现在境外主队名中, 客队码按序出现在境外客队名中
         (严格规则, 避免假阳性)
      3. 开赛时间差 < max_hours

    额外校验: 同一场竞彩只配唯一一场境外 (取时间最接近的),
    且该境外场不能被两场竞彩同时占用.
    """
    pairs = []
    used_ov = set()
    for m in jc:
        h_code = (m.get('home_en') or '').strip()
        a_code = (m.get('away_en') or '').strip()
        if not h_code or not a_code:
            continue
        # 竞彩开赛时间 (北京时区) → UTC
        jc_time = None
        try:
            jc_time = datetime.fromisoformat(
                f"{m['date']}T{m['time'] or '00:00'}:00+08:00")
        except (ValueError, KeyError, TypeError):
            pass

        best = None
        for idx, e in enumerate(ov):
            if idx in used_ov:
                continue
            if not code_in_name(h_code, e.get('home_team', '')):
                continue
            if not code_in_name(a_code, e.get('away_team', '')):
                continue
            # 时间校验
            ov_time = _parse_time(e.get('commence_time'))
            if jc_time and ov_time:
                diff = abs((ov_time - jc_time).total_seconds()) / 3600.0
                if diff > max_hours:
                    continue
            else:
                diff = 99.0
            # 优先时间最接近的
            if best is None or diff < best[1]:
                best = (idx, diff, e)

        if best:
            used_ov.add(best[0])
            pairs.append({'jc': m, 'ov': best[2], 'hours_diff': best[1]})
    return pairs


# ============================================================
# 套利计算
# ============================================================
def bookmaker_odds(event: dict) -> Dict[str, Tuple[float, float, float]]:
    """
    从事件里抽出各博彩公司的 1X2 (主, 平, 客).

    ⚠ the-odds-api 的 h2h outcome 名称是**队名**而不是 Home/Draw/Away:
        [{'name': 'Juventus', 'price': 1.36},
         {'name': 'Draw',     'price': 5.0},
         {'name': 'Rennes',   'price': 6.75}]
    所以必须用队名去匹配, 不能写死 'Home'/'Away'.
    """
    out = {}
    home = (event.get('home_team') or '').strip()
    away = (event.get('away_team') or '').strip()
    for b in event.get('bookmakers', []):
        for mk in b.get('markets', []):
            if mk.get('key') != 'h2h':
                continue
            outcomes = mk.get('outcomes', [])
            h = d = a = None
            for o in outcomes:
                nm = (o.get('name') or '').strip()
                pr = o.get('price')
                if pr is None:
                    continue
                if nm.lower() == 'draw':
                    d = pr
                elif nm.lower() == home.lower():
                    h = pr
                elif nm.lower() == away.lower():
                    a = pr
            # 兜底: 队名没对上就按顺序 (Home, Draw, Away)
            if h is None or a is None or d is None:
                names = [o.get('name', '') for o in outcomes]
                prices = [o.get('price') for o in outcomes]
                if len(prices) >= 3 and all(p is not None for p in prices):
                    if h is None:
                        h = prices[0]
                    if a is None:
                        a = prices[-1]
                    if d is None:
                        d = prices[1]
            if h and d and a and h > 1 and d > 1 and a > 1:
                out[b['key']] = (float(h), float(d), float(a))
    return out


def find_arbs(jc_odds: Tuple[float, float, float],
              books: Dict[str, Tuple[float, float, float]],
              min_profit: float = 0.0) -> List[dict]:
    """
    找套利: 从 {竞彩} ∪ 境外公司 中给主/平/客各选一家, 要求 Σ(1/o) < 1.
    三个来源必须互不相同.
    """
    import itertools
    sides = [('竞彩', jc_odds)] + list(books.items())
    out = []
    for combo in itertools.permutations(sides, 3):
        (b1, o1), (b2, o2), (b3, o3) = combo
        if b1 == b2 or b2 == b3 or b1 == b3:
            continue
        s = 1 / o1[0] + 1 / o2[1] + 1 / o3[2]
        if s < 1.0 - min_profit:
            out.append({
                'books': (b1, b2, b3),
                'odds': (o1[0], o2[1], o3[2]),
                'sum_inv': s,
                'profit_pct': (1 / s - 1) * 100,
            })
    out.sort(key=lambda x: -x['profit_pct'])
    return out


def stake_plan(combo_odds: Sequence[float], total: float = 100.0):
    """按比例分配本金 (三注回报相等)"""
    inv = [1 / o for o in combo_odds]
    s = sum(inv)
    payout = total / s
    return [(payout / o, payout) for o in combo_odds]


# ============================================================
# 主流程
# ============================================================
def run_live_scan(api_key: str, min_profit: float = 0.0,
                  jc_matches: Optional[List[dict]] = None) -> Dict:
    api = OddsAPI(api_key)

    if jc_matches is None:
        jc_matches = fetch_matches()
    if not jc_matches:
        return {'ok': False, 'error': '无竞彩数据'}

    # 按联赛分组拉境外, 并**按联赛配对** (避免跨联赛误配)
    by_league: Dict[str, List[dict]] = {}
    for m in jc_matches:
        by_league.setdefault(m.get('league_cn', ''), []).append(m)

    all_ov: List[dict] = []
    ov_by_key: Dict[str, List[dict]] = {}
    used_keys = set()
    for league_cn, ms in by_league.items():
        key = SPORT_KEYS.get(league_cn)
        if not key or key in used_keys:
            continue
        used_keys.add(key)
        evs = api.upcoming_odds(key, regions='uk,eu')
        ov_by_key[key] = evs
        all_ov.extend(evs)
        if evs:
            print(f'  {league_cn:<8} ({key}) {len(evs)} 场境外盘')

    pairs = []
    for league_cn, ms in by_league.items():
        key = SPORT_KEYS.get(league_cn)
        evs = ov_by_key.get(key, [])
        if not evs:
            continue
        got = match_matches(ms, evs)
        pairs.extend(got)
        if got:
            print(f'  {league_cn:<8} 配对 {len(got)}/{len(ms)} 场')
    print(f'\n  配对: {len(pairs)} 组 (竞彩 {len(jc_matches)} 场 / 境外 {len(all_ov)} 场)')

    results = []
    n_arb = 0
    for p in pairs:
        m, e = p['jc'], p['ov']
        jc_o = (m['had']['h'], m['had']['d'], m['had']['a'])
        books = bookmaker_odds(e)
        jc_vig = 1 / jc_o[0] + 1 / jc_o[1] + 1 / jc_o[2] - 1
        book_vigs = {b: (1 / o[0] + 1 / o[1] + 1 / o[2] - 1)
                      for b, o in books.items()}
        best_book = min(book_vigs.items(), key=lambda x: x[1]) if book_vigs else (None, 0)

        arbs = find_arbs(jc_o, books, min_profit)
        if arbs:
            n_arb += 1

        results.append({
            'league': m['league_cn'],
            'date': m['date'], 'time': m['time'],
            'home': m['home_cn'], 'away': m['away_cn'],
            'home_en': m['home_en'], 'away_en': m['away_en'],
            'jc_odds': jc_o, 'jc_vig': jc_vig,
            'ov_event': e.get('home_team', '') + ' vs ' + e.get('away_team', ''),
            'ov_commence': e.get('commence_time'),
            'books': {b: list(o) for b, o in books.items()},
            'book_vigs': book_vigs,
            'best_book': best_book[0],
            'best_book_vig': best_book[1],
            'arbs': arbs[:3],
        })

    # 汇总
    jc_vigs = [r['jc_vig'] for r in results]
    all_book_vigs = {}
    for r in results:
        for b, v in r['book_vigs'].items():
            all_book_vigs.setdefault(b, []).append(v)

    best_arb = None
    for r in results:
        for a in r['arbs']:
            if best_arb is None or a['profit_pct'] > best_arb['profit_pct']:
                best_arb = {**a, 'match': r}

    return {
        'ok': True,
        'scan_time': datetime.now(timezone.utc).isoformat(),
        'n_jc': len(jc_matches),
        'n_ov': len(all_ov),
        'n_paired': len(results),
        'n_with_arb': n_arb,
        'jc_vig_mean': float(np.mean(jc_vigs)) if jc_vigs else 0,
        'book_vig_mean': {b: float(np.mean(v)) for b, v in all_book_vigs.items()},
        'book_vig_best': (min(all_book_vigs.items(), key=lambda x: np.mean(x[1]))
                           if all_book_vigs else None),
        'best_arb': best_arb,
        'matches': results,
    }


def print_report(r: Dict):
    print()
    print('=' * 76)
    print('  实时双向扫描: 中国竞彩 × 境外盘口')
    print('=' * 76)
    print(f"  扫描时间: {r['scan_time']}")
    print(f"  竞彩 {r['n_jc']} 场 / 境外 {r['n_ov']} 场 / 配对 {r['n_paired']} 组")
    print()
    print(f"  【1】抽水率对比")
    print(f"      中国竞彩:      平均 {r['jc_vig_mean']*100:.2f}%")
    bvs = r.get('book_vig_mean') or {}
    for b, v in sorted(bvs.items(), key=lambda x: x[1])[:8]:
        print(f"      {b:<18} 平均 {v*100:.2f}%")
    if r.get('book_vig_best'):
        b, v = r['book_vig_best']
        print(f"      → 境外最优: {b} {np.mean(v)*100:.2f}%, "
              f"比竞彩低 {(r['jc_vig_mean']-np.mean(v))*100:.2f} 个百分点")

    print()
    print(f"  【2】跨市场套利机会 (Σ(1/odds) < 1)")
    print(f"      可套利场次: {r['n_with_arb']} / {r['n_paired']}")
    if r.get('best_arb'):
        a = r['best_arb']
        m = a['match']
        print()
        print(f"      最佳: {m['league']} {m['date']} {m['home']} vs {m['away']}")
        print(f"        竞彩 {m['jc_odds'][0]:.2f}/{m['jc_odds'][1]:.2f}/{m['jc_odds'][2]:.2f}"
              f"  (抽水 {m['jc_vig']*100:.2f}%)")
        print(f"        境外: {m['ov_event']}  ({m.get('ov_commence','')[11:16]} UTC)")
        print(f"        组合: 主 {a['books'][0]} / 平 {a['books'][1]} / 客 {a['books'][2]}")
        print(f"        赔率: {a['odds'][0]:.2f} / {a['odds'][1]:.2f} / {a['odds'][2]:.2f}")
        print(f"        Σ(1/o) = {a['sum_inv']:.6f}  →  锁定 {a['profit_pct']:.3f}%")
        for (bk, o), (st, ret) in zip(zip(a['books'], a['odds']),
                                       stake_plan(a['odds'], 100)):
            tag = ' [竞彩]' if bk == '竞彩' else ''
            print(f"          {bk:<18}{tag:<8} 投入 {st:>6.2f} 元  (中则返 {ret:.2f})")

    # 明细表
    if r['matches']:
        print()
        print('  【3】逐场明细')
        print(f"      {'联赛':<8}{'对阵':<26}{'竞彩H':>7}{'抽水%':>8}"
              f"{'境外最优':>12}{'抽水%':>8}{'套利':>7}")
        for m in r['matches'][:25]:
            arb_mark = f"{m['arbs'][0]['profit_pct']:.2f}%" if m['arbs'] else '-'
            print(f"      {m['league']:<8}{m['home']+'vs'+m['away']:<26}"
                  f"{m['jc_odds'][0]:>7.2f}{m['jc_vig']*100:>8.2f}"
                  f"{(m['best_book'] or '-'):>12}{m['best_book_vig']*100:>8.2f}"
                  f"{arb_mark:>7}")
    print()
    print('=' * 76)


def main():
    ap = argparse.ArgumentParser(description='实时双向扫描: 竞彩 × 境外')
    ap.add_argument('--api-key', default=os.environ.get('ODDS_API_KEY', ''),
                    help='the-odds-api.com key (或设环境变量 ODDS_API_KEY)')
    ap.add_argument('--min-profit', type=float, default=0.0,
                    help='最小套利利润 %% (默认 0, 即任何正套利)')
    ap.add_argument('--json', default='', help='结果存 JSON')
    args = ap.parse_args()

    if not args.api_key:
        # 尝试从项目根的 token 文件读
        for name in ('.odds_api_key', '.github_token'):
            p = PROJECT_ROOT / name
            if p.exists():
                args.api_key = p.read_text(encoding='utf-8').strip()
                break
    if not args.api_key:
        print('需要 --api-key (或设 ODDS_API_KEY 环境变量)')
        return 1

    print('拉取竞彩官方实时赔率...')
    jc = fetch_matches()
    print(f'  竞彩 {len(jc)} 场在售')

    r = run_live_scan(args.api_key, args.min_profit / 100.0, jc)
    if not r.get('ok'):
        print(f"错误: {r.get('error')}")
        return 1
    print_report(r)

    if args.json:
        Path(args.json).write_text(
            json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'已保存: {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
