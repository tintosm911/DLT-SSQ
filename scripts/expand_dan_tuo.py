"""
胆拖方案展开器 —— 把结构展开成逐注清单
=========================================
胆拖票在彩票店是**机器出票**, 一般不用手写; 但核对、留档、跟同事对账的时候,
需要一份能直接看的"这 84 注到底是哪 84 注"。

用法:
  # 大乐透 (前 5 + 后 2)
  python scripts/expand_dan_tuo.py --front-dan "2 4 6" --front-tuo "10 14 16 18 23 26 32" \
      --back-dan "2" --back-tuo "4 6 9 12"
  # 双色球 (前 6 + 后 1)
  python scripts/expand_dan_tuo.py --game ssq --front-dan "2" --front-tuo "4 6 10 14 16" \
      --back-tuo "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16" \
      --out reports/组5清单.txt

★ 会校验:
  - 号码在彩种有效范围内 (双色球红球只到 33 —— 大乐透的 35 混进来会直接报错)
  - 胆码与拖码不重叠
  - 展开注数 == C(前拖, 需选) × C(后拖, 需选)
  - 每注内号码不重复
  对不上直接报错退出 (不打印半份清单)。
"""
from __future__ import annotations

import argparse
import itertools
import sys
from math import comb
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.games import get_game


def _nums(s: str) -> list:
    return sorted(int(x) for x in s.replace(',', ' ').split() if x.strip())


def expand(front_dan, front_tuo, back_dan, back_tuo, need_f, need_b):
    """展开成逐注 [(前区, 后区), ...]"""
    tickets = []
    for fc in itertools.combinations(front_tuo, need_f):
        for bc in itertools.combinations(back_tuo, need_b):
            tickets.append((sorted(list(front_dan) + list(fc)),
                            sorted(list(back_dan) + list(bc))))
    return tickets


def _check(cfg, front_dan, front_tuo, back_dan, back_tuo) -> int:
    """校验并返回应有注数"""
    if set(front_dan) & set(front_tuo):
        raise SystemExit('❌ 前区胆码与拖码重叠')
    if set(back_dan) & set(back_tuo):
        raise SystemExit('❌ 后区胆码与拖码重叠')
    if len(set(front_dan) | set(front_tuo)) != len(front_dan) + len(front_tuo):
        raise SystemExit('❌ 前区号码有重复')
    if len(set(back_dan) | set(back_tuo)) != len(back_dan) + len(back_tuo):
        raise SystemExit('❌ 后区号码有重复')
    # ★ 号码范围校验 (v3.2.2): 两个彩种号码范围不同, 混用会出废注
    bad_f = [v for v in front_dan + front_tuo
             if not (1 <= v <= cfg.front_range)]
    bad_b = [v for v in back_dan + back_tuo
             if not (1 <= v <= cfg.back_range)]
    if bad_f:
        raise SystemExit(f'❌ 前区号码 {sorted(set(bad_f))} 超出范围 '
                         f'1-{cfg.front_range} ({cfg.name})')
    if bad_b:
        raise SystemExit(f'❌ 后区号码 {sorted(set(bad_b))} 超出范围 '
                         f'1-{cfg.back_range} ({cfg.name})')
    if len(front_dan) > cfg.front_count or len(back_dan) > cfg.back_count:
        raise SystemExit(f'❌ 胆码个数超限 ({cfg.name} 前区最多 {cfg.front_count} 胆 / '
                         f'后区最多 {cfg.back_count} 胆)')
    need_f = cfg.front_count - len(front_dan)
    need_b = cfg.back_count - len(back_dan)
    if need_f > len(front_tuo) or need_b > len(back_tuo):
        raise SystemExit('❌ 拖码池不够选')
    return comb(len(front_tuo), need_f) * comb(len(back_tuo), need_b)


def main() -> int:
    ap = argparse.ArgumentParser(description='胆拖方案逐注展开')
    ap.add_argument('--game', default='dlt', choices=['dlt', 'ssq'])
    ap.add_argument('--front-dan', default='')
    ap.add_argument('--front-tuo', default='')
    ap.add_argument('--back-dan', default='')
    ap.add_argument('--back-tuo', default='')
    ap.add_argument('--price', type=float, default=2.0, help='单注票价 (元)')
    ap.add_argument('--out', default='', help='输出文件 (默认打印到屏幕)')
    args = ap.parse_args()

    cfg = get_game(args.game)
    fd, ft = _nums(args.front_dan), _nums(args.front_tuo)
    bd, bt = _nums(args.back_dan), _nums(args.back_tuo)

    expected = _check(cfg, fd, ft, bd, bt)
    need_f = cfg.front_count - len(fd)
    need_b = cfg.back_count - len(bd)
    tickets = expand(fd, ft, bd, bt, need_f, need_b)
    if len(tickets) != expected:
        raise SystemExit(f'❌ 注数校验失败: 展开 {len(tickets)} 注, 应为 {expected} 注')
    for f, b in tickets:
        if len(set(f)) != cfg.front_count or len(set(b)) != cfg.back_count:
            raise SystemExit(f'❌ 注内号码重复: {f} + {b}')

    lines = []
    lines.append(f'{cfg.name} 胆拖逐注清单')
    lines.append('=' * 58)
    lines.append(f'前区  胆 {" ".join(f"{v:02d}" for v in fd) or "(无)"}'
                 f'   拖 {" ".join(f"{v:02d}" for v in ft)}')
    lines.append(f'后区  胆 {" ".join(f"{v:02d}" for v in bd) or "(无)"}'
                 f'   拖 {" ".join(f"{v:02d}" for v in bt)}')
    lines.append('-' * 58)
    lines.append(f'注数 {len(tickets):,} 注  '
                 f'(前区 C({len(ft)},{need_f})={comb(len(ft), need_f)} × '
                 f'后区 C({len(bt)},{need_b})={comb(len(bt), need_b)})'
                 f'  合计 {len(tickets) * args.price:,.0f} 元')
    lines.append('-' * 58)
    for i, (f, b) in enumerate(tickets, 1):
        lines.append(f'{i:>4})  ' + ' '.join(f'{v:02d}' for v in f)
                     + '  +  ' + ' '.join(f'{v:02d}' for v in b))
    lines.append('=' * 58)
    lines.append('★ 每一注的中奖概率完全相同 —— 号码选哪几个不影响概率。')
    lines.append('  期望净收益恒为负, 买越多亏越多。')
    text = '\n'.join(lines)

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + '\n', encoding='utf-8')
        print(f'✅ 已写出 {p}  ({len(tickets):,} 注, '
              f'{len(tickets) * args.price:,.0f} 元)')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
