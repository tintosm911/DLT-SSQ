"""
竞彩赔率快照存档
==================
每天定时抓一次竞彩官方赔率 + 境外盘口, 存进 SQLite.

为什么需要:
  - 竞彩**没有公开历史赔率**, 网上找不到 → 只能自己存
  - 存 3 个月后就有自己的历史数据, 可以做:
    · 竞彩赔率临场变化追踪 (降价 = 庄家认为该结果概率上升)
    · 竞彩 vs 境外 的历史套利验证 (用真实当期数据, 不用模拟)
    · 竞彩抽水率随时间的变化
  - 这是**唯一拿不到**的东西 (其他数据都有公开源)

表结构:
  odds_snapshots(ts, game, period, league, home, away, book,
                 odds_h, odds_d, odds_a, vig, source)
  UNIQUE(ts_bucket, period, book)  -- 同一期同一公司每小时只存一条
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

DB_PATH = PROJECT_ROOT / 'data-raw' / 'odds_snapshots.db'

SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,          -- ISO 时间
    ts_hour     TEXT NOT NULL,          -- 小时桶 (去重用)
    game        TEXT NOT NULL,          -- dlt / ssq / 竞彩
    period      TEXT NOT NULL,          -- 期号
    league      TEXT,
    home        TEXT,
    away        TEXT,
    book        TEXT NOT NULL,          -- 博彩公司 key
    odds_h      REAL,
    odds_d      REAL,
    odds_a      REAL,
    vig         REAL,                   -- 抽水率
    source      TEXT,                   -- jingcai / oddsapi
    UNIQUE(ts_hour, period, book)
);
CREATE INDEX IF NOT EXISTS idx_snap_period ON odds_snapshots(period);
CREATE INDEX IF NOT EXISTS idx_snap_ts     ON odds_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_snap_book   ON odds_snapshots(book);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def save_snapshots(rows: Sequence[Dict], conn: Optional[sqlite3.Connection] = None,
                   db_path: Path = DB_PATH) -> int:
    """
    写入快照 (同小时桶同期同公司去重).

    rows: [{ts, game, period, league, home, away, book,
            odds_h, odds_d, odds_a, source}]
    """
    own = conn is None
    if own:
        conn = connect(db_path)
    try:
        n = 0
        for r in rows:
            h, d, a = r.get('odds_h'), r.get('odds_d'), r.get('odds_a')
            vig = None
            if h and d and a and h > 1 and d > 1 and a > 1:
                vig = (1 / h + 1 / d + 1 / a) - 1
            ts = r.get('ts') or datetime.now(timezone.utc).isoformat()
            ts_hour = ts[:13]  # 2026-10-22T14
            try:
                conn.execute(
                    'INSERT OR REPLACE INTO odds_snapshots '
                    '(ts, ts_hour, game, period, league, home, away, book, '
                    ' odds_h, odds_d, odds_a, vig, source) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (ts, ts_hour, r.get('game', ''), r.get('period', ''),
                     r.get('league'), r.get('home'), r.get('away'),
                     r.get('book', ''), h, d, a, vig, r.get('source')))
                n += 1
            except sqlite3.Error:
                continue
        conn.commit()
        return n
    finally:
        if own:
            conn.close()


def collect_jingcai() -> List[Dict]:
    """抓竞彩官方赔率 → 快照行"""
    from data.jingcai_odds import fetch_matches
    try:
        ms = fetch_matches()
    except Exception:
        return []
    ts = datetime.now(timezone.utc).isoformat()
    rows = []
    for m in ms:
        o = m.get('had') or {}
        rows.append({
            'ts': ts, 'game': 'jc', 'period': m.get('match_id', ''),
            'league': m.get('league_cn'), 'home': m.get('home_cn'),
            'away': m.get('away_cn'), 'book': '竞彩官方',
            'odds_h': o.get('h'), 'odds_d': o.get('d'), 'odds_a': o.get('a'),
            'source': 'jingcai',
        })
    return rows


def collect_overseas(api_key: str) -> List[Dict]:
    """抓境外盘口 → 快照行 (可选, 消耗 API 配额)"""
    if not api_key:
        return []
    from scripts.live_scanner import OddsAPI, SPORT_KEYS
    from data.jingcai_odds import fetch_matches

    try:
        jc = fetch_matches()
    except Exception:
        return []
    api = OddsAPI(api_key)
    ts = datetime.now(timezone.utc).isoformat()
    rows = []

    seen = set()
    for m in jc:
        key = SPORT_KEYS.get(m.get('league_cn', ''))
        if not key or key in seen:
            continue
        seen.add(key)
        for ev in api.upcoming_odds(key, regions='uk,eu,au'):
            from scripts.live_scanner import bookmaker_odds
            books = bookmaker_odds(ev)
            for book, (h, d, a) in books.items():
                rows.append({
                    'ts': ts, 'game': 'soccer', 'period': ev.get('id', ''),
                    'league': m.get('league_cn'),
                    'home': ev.get('home_team'), 'away': ev.get('away_team'),
                    'book': book,
                    'odds_h': h, 'odds_d': d, 'odds_a': a,
                    'source': 'oddsapi',
                })
    return rows


def stats(conn: Optional[sqlite3.Connection] = None) -> Dict:
    """存档统计"""
    own = conn is None
    if own:
        conn = connect()
    try:
        cur = conn.execute(
            'SELECT COUNT(*), COUNT(DISTINCT period), COUNT(DISTINCT ts_hour), '
            'MIN(ts), MAX(ts) FROM odds_snapshots').fetchone()
        by_book = conn.execute(
            'SELECT book, COUNT(*), AVG(vig) FROM odds_snapshots '
            'GROUP BY book ORDER BY AVG(vig) ASC LIMIT 12').fetchall()
        return {
            'total': cur[0], 'periods': cur[1], 'hours': cur[2],
            'first': cur[3], 'last': cur[4],
            'by_book': [{'book': b, 'n': n, 'vig': v} for b, n, v in by_book],
        }
    finally:
        if own:
            conn.close()


__all__ = [
    'DB_PATH', 'connect', 'save_snapshots', 'collect_jingcai',
    'collect_overseas', 'stats',
]
