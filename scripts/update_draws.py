"""
开奖数据每日增量更新 (供计划任务调用)
=====================================
把两个彩种的最新开奖从官方 API 拉进 SQLite。

★ 2026-11-19 修复一个逻辑缺陷:
  原实现只比较"远程最新期号 vs 本地最新期号", 若远程 > 本地就抓最新一期。
  但官方 API 的开奖数据**同步有延迟** —— 例如 2026132 是 11-18 开奖的,
  而 11-18 21:30 那次运行时官方还没同步, 于是判断"已是最新"直接返回,
  **整期被漏掉**, 而且逻辑没变所以永远补不回来。

  现在改成**逐期核对连续性**:
  批量拉取最近一大批 (DLT 100 期 / SSQ 近 2 年), 与本地比对,
  把**所有缺失的期号**一次性补齐 —— 同步延迟多少都能自愈。

用法:
  python scripts/update_draws.py            # 手动跑
  python scripts/update_draws.py --dry-run  # 只看不写
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import ssl
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.games import normalize_period
from data.sqlite_storage import SQLiteStorage

LOG_DIR = PROJECT_ROOT / 'logs'
DB = PROJECT_ROOT / 'data-raw' / 'lottery.db'

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),          # 公司网死代理, 必须显式禁用
    urllib.request.HTTPSHandler(context=_CTX),
)


def _get_json(url: str, referer: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={
        'User-Agent': _UA, 'Referer': referer})
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


# ============================================================
# 官方 API 批量拉取 (不逐期请求)
# ============================================================
def fetch_dlt_recent(n: int = 100) -> list:
    """体彩官方: 最近 n 期大乐透 → [Draw, ...]"""
    from data.data_fetcher import Draw
    out = []
    for page in range(1, max(1, (n + 99) // 100) + 1):
        url = ('https://webapi.sporttery.cn/gateway/lottery/'
               f'getHistoryPageListV1.qry?gameNo=85&provinceId=0'
               f'&pageSize=100&pageNo={page}&isVerify=1')
        j = _get_json(url, 'https://www.sporttery.cn/')
        lst = (j.get('value') or {}).get('list') or []
        for it in lst:
            raw = str(it.get('lotteryDrawNum', '')).strip()
            nums = [int(x) for x in str(it.get('lotteryDrawResult', '')).split()]
            if not raw or len(nums) != 7:
                continue
            period = raw if len(raw) == 7 else '20' + raw
            out.append(Draw(
                period=period,
                draw_date=str(it.get('lotteryDrawTime', '')).strip(),
                game='dlt',
                front=sorted(nums[:5]), back=sorted(nums[5:])))
        if len(lst) < 100:
            break
    return out


def fetch_ssq_recent(back_years: int = 2) -> list:
    """福彩官方: 最近若干期双色球 (按期号区间批量查)"""
    from data.data_fetcher import Draw
    out = []
    now = datetime.now()
    for y in range(now.year, now.year - back_years - 1, -1):
        url = ('https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/'
               f'findDrawNotice?name=ssq&issueStart={y}001&issueEnd={y}200'
               '&pageNo=1&pageSize=100&systemType=PC')
        try:
            j = _get_json(url, 'https://www.cwl.gov.cn/')
        except Exception:
            continue
        for it in (j.get('result') or []):
            try:
                period = str(it.get('code', '')).strip()
                red = sorted(int(x) for x in str(it.get('red', '')).split(','))
                blue = sorted(int(x) for x in str(it.get('blue', '')).split(','))
                if not period or len(red) != 6 or len(blue) != 1:
                    continue
                out.append(Draw(
                    period=period,
                    draw_date=str(it.get('date', '')).split('(')[0],
                    game='ssq', front=red, back=blue))
            except (TypeError, ValueError):
                continue
    return out


# ============================================================
# 增量入库
# ============================================================
def local_periods(game_code: str) -> set:
    conn = sqlite3.connect(str(DB))
    try:
        return {str(p) for (p,) in conn.execute(
            'SELECT period FROM draws WHERE game=?', (game_code,))}
    finally:
        conn.close()


def update_one(game_code: str, storage, dry_run: bool = False):
    """返回 (新增期数, 消息列表)"""
    msgs = []
    remote = fetch_ssq_recent() if game_code == 'ssq' else fetch_dlt_recent()
    if not remote:
        return 0, [f'{game_code}: 官方接口没返回数据']

    have = local_periods(game_code)

    # ★ 找**所有**缺失的期号, 不只是最新一期
    missing = []
    for d in remote:
        p = normalize_period(d.period, game_code)
        if p not in have:
            missing.append((p, d))

    if not missing:
        latest = max(normalize_period(d.period, game_code) for d in remote)
        return 0, [f'{game_code}: 已是最新 ({latest}), 无缺失期']

    missing.sort(key=lambda x: x[0])
    if dry_run:
        return 0, [f'{game_code}: 待补 {len(missing)} 期 -> '
                   + ', '.join(p for p, _ in missing[:20])]

    n = 0
    for p, d in missing:
        d.period = p
        d.game = game_code
        try:
            storage.save_draws([d])
            n += 1
            msgs.append(f'{game_code}: {p} {d.draw_date} '
                        f'前{" ".join(f"{v:02d}" for v in d.front)} '
                        f'后{" ".join(f"{v:02d}" for v in d.back)}')
        except Exception as e:
            msgs.append(f'{game_code}: {p} 入库失败 {e}')
    return n, msgs


def main():
    ap = argparse.ArgumentParser(description='开奖数据每日增量更新')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    storage = SQLiteStorage()
    total = 0
    lines = []
    for g in ('dlt', 'ssq'):
        try:
            n, msgs = update_one(g, storage, args.dry_run)
            total += n
            lines.extend(msgs)
        except Exception as e:
            lines.append(f'{g}: 失败 {type(e).__name__}: {e}')

    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log = LOG_DIR / 'draw_update.log'
    # utf-8-sig: 带 BOM, 记事本 / Excel / Get-Content 都能正确显示中文
    with log.open('a', encoding='utf-8-sig') as f:
        f.write(f'[{stamp}] 新增 {total} 期\n')
        for ln in lines:
            f.write(f'    {ln}\n')

    print(f'新增 {total} 期')
    for ln in lines:
        print(' ', ln)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
