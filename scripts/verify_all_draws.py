"""
开奖数据全量对拍 (本地库 vs 官方 API)
====================================
把本地 SQLite 的**每一期**都跟官方 API 对一遍, 找出所有静默错误:
  - 开奖日期标错 (上游数据源常见问题: 期号对、日期错)
  - 号码错位 / 串期
  - 缺失期号

★ 为什么需要全量: 抽查只能发现"最近"的问题。v2.6.0 就在全量体检里
  发现 SSQ 2026120 的日期被上游标成了 10-22 (正确是 10-20),
  导致同一个日期出现两期 —— 这在肉眼扫库时完全看不出来。

数据源:
  DLT  体彩 getHistoryPageListV1 (分页, pageSize=100)
  SSQ  福彩 findDrawNotice (按期号区间批量查)

用法:
  python scripts/verify_all_draws.py            # 全量对拍
  python scripts/verify_all_draws.py --fix      # 对拍并用官方数据修正
  python scripts/verify_all_draws.py --sample 300   # 只抽最近 300 期
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import sqlite3

DB = PROJECT_ROOT / 'data-raw' / 'lottery.db'

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=_CTX),
)
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def _get_json(url: str, referer: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={
        'User-Agent': _UA, 'Referer': referer})
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_dlt_all(progress=True) -> dict:
    """体彩官方: 全部大乐透 → {period7: (date, front, back)}"""
    out = {}
    page, pages = 1, None
    while True:
        url = ('https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry'
               f'?gameNo=85&provinceId=0&pageSize=100&pageNo={page}&isVerify=1')
        j = _get_json(url, 'https://www.sporttery.cn/')
        v = j.get('value', {})
        if pages is None:
            pages = int(v.get('pages') or 1)
            total = v.get('total')
            if progress:
                print(f'  官方声明 total={total}, pages={pages}', flush=True)
        lst = v.get('list') or []
        if not lst:
            break
        for it in lst:
            raw = str(it.get('lotteryDrawNum', '')).strip()
            if not raw:
                continue
            period = raw if len(raw) == 7 else '20' + raw
            nums = [int(x) for x in str(it.get('lotteryDrawResult', '')).split()]
            if len(nums) != 7:
                continue
            out[period] = (str(it.get('lotteryDrawTime', '')).strip(),
                            sorted(nums[:5]), sorted(nums[5:]))
        if progress:
            print(f'  已取 {page}/{pages} 页, 累计 {len(out)} 期', flush=True)
        if page >= pages:
            break
        page += 1
        time.sleep(0.25)
    return out


def fetch_ssq_all(progress=True) -> dict:
    """福彩官方: 全量双色球 → {period: (date, front, back)}"""
    out = {}
    # 按年份区间批量查, 每年 ~153 期, 一次 pageSize=200 足够
    for year in range(2003, 2027):
        start, end = f'{year}001', f'{year}200'
        try:
            url = ('https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice'
                   f'?name=ssq&issueStart={start}&issueEnd={end}'
                   '&pageNo=1&pageSize=200&systemType=PC')
            j = _get_json(url, 'https://www.cwl.gov.cn/')
            res = j.get('result') or []
            for it in res:
                period = str(it.get('code', '')).strip()
                if not period:
                    continue
                red = sorted(int(x) for x in str(it.get('red', '')).split(','))
                blue = sorted(int(x) for x in str(it.get('blue', '')).split(','))
                out[period] = (str(it.get('date', '')).split('(')[0], red, blue)
        except Exception as e:
            print(f'  ⚠ {year} 查询失败: {e}', flush=True)
        if progress:
            print(f'  {year} 年完成, 累计 {len(out)} 期', flush=True)
        time.sleep(0.35)
    return out


def local_all(conn, game):
    rows = conn.execute(
        'SELECT period, draw_date, front_numbers, back_numbers FROM draws '
        'WHERE game=? ORDER BY period', (game,)).fetchall()
    return {r[0]: (r[1], sorted(json.loads(r[2])), sorted(json.loads(r[3])))
            for r in rows}


def compare(game, official, local):
    """
    返回 (真差异, 官方未覆盖, 本地缺失)

    ★ 官方接口的历史覆盖是**有限**的 (例如福彩只回溯到 2009 年左右),
      "官方没有这一期" **不等于** 本地数据错 —— 它只是官方没开放那段历史。
      所以这类期号单独归类, 不算错误。
    """
    diffs = []
    no_official = []
    for p, lv in local.items():
        ov = official.get(p)
        if ov is None:
            no_official.append(p)
            continue
        ld, lf, lb = lv
        od, of_, ob = ov
        if ld != od:
            diffs.append((p, lv, ov, f'日期 {ld} ≠ {od}'))
        elif lf != of_:
            diffs.append((p, lv, ov, f'前区 {lf} ≠ {of_}'))
        elif lb != ob:
            diffs.append((p, lv, ov, f'后区 {lb} ≠ {ob}'))
    missing = [p for p in official if p not in local]
    return diffs, no_official, missing


def fix(conn, game, diffs, official):
    n = 0
    for p, lv, ov, _ in diffs:
        if ov is None:
            continue
        od, of_, ob = ov
        conn.execute(
            'UPDATE draws SET draw_date=?, front_numbers=?, back_numbers=? '
            'WHERE period=? AND game=?',
            (od, json.dumps(of_), json.dumps(ob), p, game))
        n += 1
    conn.commit()
    return n


def main():
    ap = argparse.ArgumentParser(description='开奖数据全量对拍')
    ap.add_argument('--fix', action='store_true',
                    help='用官方数据修正"内容不同"的记录 (不新增期号)')
    ap.add_argument('--insert-missing', action='store_true',
                    help='额外把官方有、本地缺的期号补进来 (谨慎使用)')
    ap.add_argument('--sample', type=int, default=0,
                    help='只查最近 N 期 (0=全量)')
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB))
    total_bad = 0

    for game, fetcher in (('dlt', fetch_dlt_all), ('ssq', fetch_ssq_all)):
        print()
        print('=' * 78)
        print(f'  {game.upper()} 全量对拍')
        print('=' * 78)
        local = local_all(conn, game)
        if args.sample:
            keys = sorted(local)[-args.sample:]
            local = {k: local[k] for k in keys}
        print(f'  本地 {len(local)} 期, 开始拉官方 ...', flush=True)
        official = fetcher()
        print(f'  官方 {len(official)} 期')

        diffs, no_official, missing = compare(game, official, local)
        covered = len(local) - len(no_official)
        print()
        print(f'  官方覆盖 {covered}/{len(local)} 期'
              + (f' (未覆盖 {len(no_official)} 期: {no_official[0]}~{no_official[-1]})'
                 if no_official else ''))
        if not diffs and not missing:
            print(f'  ✅ 覆盖范围内 {covered} 期全部与官方一致')
        else:
            print(f'  ❌ 发现 {len(diffs)} 处差异'
                  + (f' + {len(missing)} 期本地缺失' if missing else ''))
            for p, lv, ov, why in diffs[:50]:
                print(f'     {p}: {why}')
            if len(diffs) > 50:
                print(f'     ... 还有 {len(diffs) - 50} 处')
            if missing:
                print(f'     本地缺失: {missing[:20]}'
                      + (f' ...共{len(missing)}期' if len(missing) > 20 else ''))
            total_bad += len(diffs)

            if args.fix:
                n = fix(conn, game, diffs, official)
                print(f'  ✅ 已修正 {n} 期 (以官方数据为准)')

            # ★ 补缺失期只在**全量模式**下允许:
            #   sample 模式下 local 是子集, "官方有本地无"会被整片误判成缺失。
            # ★ 而且默认不补 —— "官方有本地无"往往说明官方历史覆盖比本地短
            #   (例如福彩只回溯到 2013), 补进去反而可能覆盖掉更完整的数据。
            if args.insert_missing:
                if args.sample:
                    print('  ⚠ --insert-missing 不能与 --sample 同用, 已跳过')
                else:
                    added = 0
                    for p in missing:
                        od, of_, ob = official[p]
                        conn.execute(
                            'INSERT OR REPLACE INTO draws (period, game, draw_date, '
                            'front_numbers, back_numbers, front_count, back_count) '
                            'VALUES (?,?,?,?,?,?,?)',
                            (p, game, od, json.dumps(of_), json.dumps(ob),
                             len(of_), len(ob)))
                        added += 1
                    conn.commit()
                    print(f'  ✅ 已补入 {added} 期')

    conn.close()
    print()
    print('=' * 78)
    if total_bad:
        print(f'  合计 {total_bad} 处差异')
        print('=' * 78)
        return 1
    print('  ✅ 全部一致')
    print('=' * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
