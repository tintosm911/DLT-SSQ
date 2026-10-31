"""
开奖数据每日增量更新 (供计划任务调用)
=====================================
把两个彩种的最新开奖从官方 API 拉进 SQLite。

被 Windows 计划任务 `LotteryDrawUpdate` 调用 (每天 21:30),
也可以手动跑:
  python scripts/update_draws.py

★ 与 `python main.py update` 的区别:
  - 本脚本: 无输出到终端 (计划任务环境下静默), 写日志到 logs/
  - main.py update: 交互式, 打印明细
  两者共用同一套逻辑 (本脚本是 main.cmd_update 的无交互封装)
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.data_fetcher import PAGE_SIZE
from data.games import get_game, normalize_period
from data.sqlite_storage import SQLiteStorage

LOG_DIR = PROJECT_ROOT / 'logs'


def update_one(game_code: str, storage) -> tuple:
    """返回 (新增期数, 消息列表)"""
    msgs = []
    latest_local = storage.get_latest_period(game_code)

    if game_code == 'ssq':
        from data.data_source import WelfareSSQSource
        source = WelfareSSQSource()
    else:
        from data.data_source import OfficialSource
        source = OfficialSource()

    latest_remote = source.fetch_latest()
    if not latest_remote:
        return 0, [f'{game_code}: 无法获取最新期号']
    remote_period = normalize_period(latest_remote.period, game_code)

    if latest_local and int(remote_period) <= int(latest_local):
        return 0, [f'{game_code}: 已是最新 ({latest_local})']

    new_draws = []
    if game_code == 'ssq':
        start = (int(latest_local) + 1) if latest_local else int(remote_period) - 10
        new_draws = source._fetch_range(start, int(remote_period))
    else:
        for page in range(1, 8):
            batch = source.fetch_page(page, PAGE_SIZE)
            if not batch:
                break
            reached_old = False
            for d in batch:
                p = normalize_period(d.period, game_code)
                if latest_local and int(p) <= int(latest_local):
                    reached_old = True
                    break
                new_draws.append(replace(d, period=p, game=game_code))
            if reached_old:
                break

    if not new_draws:
        return 0, [f'{game_code}: 没抓到新期号']

    n = storage.save_draws(new_draws)
    for d in sorted(new_draws, key=lambda x: x.period):
        msgs.append(f'{game_code}: {d.period} {d.draw_date} '
                    f'前{" ".join(f"{v:02d}" for v in d.front)} '
                    f'后{" ".join(f"{v:02d}" for v in d.back)}')
    return n, msgs


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    storage = SQLiteStorage()
    lines = []
    total = 0
    for g in ('dlt', 'ssq'):
        try:
            n, msgs = update_one(g, storage)
            total += n
            lines.extend(msgs)
        except Exception as e:
            lines.append(f'{g}: 失败 {type(e).__name__}: {e}')

    stamp = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
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
