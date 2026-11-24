"""
胆拖方案展开器 —— 把结构展开成逐注清单
=========================================
胆拖票在彩票店是**机器出票**, 一般不用手写; 但核对、留档、跟同事对账的时候,
需要一份能直接看的"这 84 注到底是哪 84 注"。

用法:
  python scripts/expand_dan_tuo.py --front-dan "2 4 6" --front-tuo "10 14 16 18 23 26 32" \
      --back-dan "2" --back-tuo "4 6 9 12"
  python scripts/expand_dan_tuo.py ... --out reports/方案A清单.txt

★ 会校验:
  - 胆码与拖码不重叠
  - 展开注数 == C(前拖, 5-前胆) × C(后拖, 2-后胆)
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


def _nums(s: str) -> list:
    return sorted(int(x) for x in s.replace(',', ' ').split() if x.strip())


def expand(front_dan, front_tuo, back_dan, back_tuo):
    """展开成逐注 [(前区, 后区), ...]"""
    tickets = []
    for fc in itertools.combinations(front_tuo, 5 - len(front_dan)):
        for bc in itertools.combinations(back_tuo, 2 - len(back_dan)):
            tickets.append((sorted(list(front_dan) + list(fc)),
                            sorted(list(back_dan) + list(bc))))
    return tickets


def _check(front_dan, front_tuo, back_dan, back_tuo) -> int:
    """校验并返回应有注数"""
    if set(front_dan) & set(front_tuo):
        raise SystemExit('❌ 前区胆码与拖码重叠')
    if set(back_dan) & set(back_tuo):
        raise SystemExit('❌ 后区胆码与拖码重叠')
    if len(set(front_dan) | set(front_tuo)) != len(front_dan) + len(front_tuo):
        raise SystemExit('❌ 前区号码有重复')
    if len(set(back_dan) | set(back_tuo)) != len(back_dan) + len(back_tuo):
        raise SystemExit('❌ 后区号码有重复')
    if len(front_dan) > 5 or len(back_dan) > 2:
        raise SystemExit('❌ 胆码个数超限 (大乐透前区最多 5 胆 / 后区最多 2 胆)')
    if len(front_tuo) < 5 - len(front_dan) or len(back_tuo) < 2 - len(back_dan):
        raise SystemExit('❌ 拖码池不够选')
    return comb(len(front_tuo), 5 - len(front_dan)) * comb(len(back_tuo), 2 - len(back_dan))


def main() -> int:
    ap = argparse.ArgumentParser(description='胆拖方案逐注展开')
    ap.add_argument('--front-dan', default='')
    ap.add_argument('--front-tuo', default='')
    ap.add_argument('--back-dan', default='')
    ap.add_argument('--back-tuo', default='')
    ap.add_argument('--price', type=float, default=2.0, help='单注票价 (元)')
    ap.add_argument('--out', default='', help='输出文件 (默认打印到屏幕)')
    args = ap.parse_args()

    fd, ft = _nums(args.front_dan), _nums(args.front_tuo)
    bd, bt = _nums(args.back_dan), _nums(args.back_tuo)

    expected = _check(fd, ft, bd, bt)
    tickets = expand(fd, ft, bd, bt)
    if len(tickets) != expected:
        raise SystemExit(f'❌ 注数校验失败: 展开 {len(tickets)} 注, 应为 {expected} 注')
    for f, b in tickets:
        if len(set(f)) != 5 or len(set(b)) != 2:
            raise SystemExit(f'❌ 注内号码重复: {f} + {b}')

    lines = []
    lines.append('大乐透 胆拖逐注清单')
    lines.append('=' * 58)
    lines.append(f'前区  胆 {" ".join(f"{v:02d}" for v in fd) or "(无)"}'
                 f'   拖 {" ".join(f"{v:02d}" for v in ft)}')
    lines.append(f'后区  胆 {" ".join(f"{v:02d}" for v in bd) or "(无)"}'
                 f'   拖 {" ".join(f"{v:02d}" for v in bt)}')
    lines.append('-' * 58)
    lines.append(f'注数 {len(tickets):,} 注  '
                 f'(前区 C({len(ft)},{5 - len(fd)})={comb(len(ft), 5 - len(fd))} × '
                 f'后区 C({len(bt)},{2 - len(bd)})={comb(len(bt), 2 - len(bd))})'
                 f'  合计 {len(tickets) * args.price:,.0f} 元')
    lines.append('-' * 58)
    for i, (f, b) in enumerate(tickets, 1):
        lines.append(f'{i:>4})  ' + ' '.join(f'{v:02d}' for v in f)
                     + '  +  ' + ' '.join(f'{v:02d}' for v in b))
    lines.append('=' * 58)
    lines.append('★ 每一注的中奖概率完全相同 —— 号码选哪几个不影响概率。')
    lines.append('  期望净收益恒为负 (大乐透单注 -0.9407 元), 买越多亏越多。')
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
