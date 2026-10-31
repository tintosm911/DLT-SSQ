"""
开奖数据交叉验证 (本地库 vs 官方 API)
======================================
用**完全独立的第二条链路**核对本地 SQLite 里的开奖数据:

  本地库 (data-raw/lottery.db, 由采集器写入)
      ↕  比对
  官方 API 实时拉取 (完全不走采集器代码)

★ 价值: 采集器可能**静默写错**数据 (字段错位、期号串位、区域解析错)。
  肉眼看库里的数据是正常的, 只有跟官方对拍才会暴露。
  v2.5.x 修采集链路时, 就是靠这个思路定位到"URL 用错域 + Draw 字段不匹配"
  这类静默故障的。

用法:
  python scripts/verify_draws_against_official.py            # 校验最新若干期
  python scripts/verify_draws_against_official.py --n 10      # 校验最新 10 期
  python scripts/verify_draws_against_official.py --full      # 抽 200 期全量对拍 (慢)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import ssl
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

DB = PROJECT_ROOT / 'data-raw' / 'lottery.db'

# --- 独立于项目代码的裸 HTTP 客户端 (刻意不复用 data_source.py) ---
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),          # 公司网死代理, 必须显式禁用
    urllib.request.HTTPSHandler(context=_CTX),
)


def _get_json(url: str, referer: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': referer,
    })
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_sporttery_dlt(n: int) -> list:
    """体彩官方: 大乐透最新 n 期 → [(period7, date, front, back), ...]"""
    url = ('https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry'
           f'?gameNo=85&provinceId=0&pageSize={n}&pageNo=1&isVerify=1')
    j = _get_json(url, 'https://www.sporttery.cn/')
    out = []
    for it in j.get('value', {}).get('list', []):
        raw = str(it.get('lotteryDrawNum', '')).strip()
        if not raw:
            continue
        period = raw if len(raw) == 7 else '20' + raw
        nums = [int(x) for x in str(it.get('lotteryDrawResult', '')).split()]
        if len(nums) != 7:
            continue
        out.append((period, str(it.get('lotteryDrawTime', '')).strip(),
                    sorted(nums[:5]), sorted(nums[5:])))
    return out


def fetch_cwl_ssq(period: str):
    """福彩官方: 双色球单期 → (period, date, front, back)"""
    url = ('https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice'
           f'?name=ssq&issueStart={period}&issueEnd={period}'
           '&pageNo=1&pageSize=1&systemType=PC')
    j = _get_json(url, 'https://www.cwl.gov.cn/')
    res = j.get('result') or []
    if not res:
        return None
    it = res[0]
    red = sorted(int(x) for x in str(it.get('red', '')).split(','))
    blue = sorted(int(x) for x in str(it.get('blue', '')).split(','))
    date = str(it.get('date', '')).split('(')[0]
    return str(it.get('code', '')).strip(), date, red, blue


def local_row(conn, period: str, game: str):
    row = conn.execute(
        'SELECT draw_date, front_numbers, back_numbers FROM draws '
        'WHERE period=? AND game=?', (period, game)).fetchone()
    if not row:
        return None
    return (row[0], sorted(json.loads(row[1])), sorted(json.loads(row[2])))


def main():
    ap = argparse.ArgumentParser(description='开奖数据交叉验证')
    ap.add_argument('--n', type=int, default=3, help='校验最近 N 期 (默认 3)')
    ap.add_argument('--full', action='store_true', help='抽 200 期全量对拍')
    ap.add_argument('--game', default=None, choices=['dlt', 'ssq'])
    args = ap.parse_args()

    if not DB.exists():
        print(f'❌ 数据库不存在: {DB}')
        return 1
    conn = sqlite3.connect(str(DB))
    games = [args.game] if args.game else ['dlt', 'ssq']
    total = bad = 0

    for g in games:
        print()
        print('=' * 78)
        print(f'  {g.upper()} 交叉验证 — 本地库 vs 官方 API')
        print('=' * 78)

        if g == 'dlt':
            rows = fetch_sporttery_dlt(args.n if not args.full else 200)
            checks = [(p, d, f, b) for p, d, f, b in rows]
        else:
            # 双色球官方只支持单期查, 抽若干期逐个查
            local = conn.execute(
                'SELECT period FROM draws WHERE game=? ORDER BY period DESC LIMIT ?',
                (g, args.n if not args.full else 30)).fetchall()
            checks = []
            for (p,) in local:
                try:
                    r = fetch_cwl_ssq(p)
                    if r:
                        checks.append(r)
                except Exception as e:
                    print(f'  ⚠ {p} 官方查询失败: {e}')

        if not checks:
            print('  ⚠ 没有可对拍的数据')
            continue

        for p, d, f, b in checks:
            lr = local_row(conn, p, g)
            total += 1
            if lr is None:
                bad += 1
                print(f'  ❌ {p}  本地缺失')
                continue
            ld, lf, lb = lr
            ok = (ld == d and lf == f and lb == b)
            if not ok:
                bad += 1
            print(f'  {"✅" if ok else "❌"} {p}  日期 {ld}/{d}  '
                  f'前 {lf}/{f}  后 {lb}/{b}')

    conn.close()
    print()
    print('=' * 78)
    if bad:
        print(f'  ❌ {bad}/{total} 条不一致 — 采集链路有问题')
        print('=' * 78)
        return 1
    print(f'  ✅ {total}/{total} 条与官方完全一致')
    print('=' * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
