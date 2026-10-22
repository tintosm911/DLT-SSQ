"""
本地 CI 脚本
============
不依赖 GitHub Actions 的完整检查流程 —— 跟 .github/workflows/ci.yml 里跑的是同一套.

用途:
  1. 本地/内网跑 (公司网推不了 workflow 时也能用)
  2. pre-push hook 拦截
  3. 生成 shields.io 动态 badge 用的 JSON

用法:
  python scripts/ci_local.py              # 跑全部检查
  python scripts/ci_local.py --badge      # 只更新 badge JSON
  python scripts/ci_local.py --quick     # 跳过慢的检查
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

BADGE_DIR = PROJECT_ROOT / 'badges'
G = '\033[92m'
R = '\033[91m'
Y = '\033[93m'
D = '\033[90m'
B = '\033[1m'
N = '\033[0m'


class Check:
    def __init__(self, name: str, cmd: list, desc: str = ''):
        self.name = name
        self.cmd = cmd
        self.desc = desc
        self.ok = False
        self.detail = ''
        self.seconds = 0.0


def run_checks(quick: bool = False) -> list:
    py = sys.executable
    checks = [
        Check('单元测试', [py, 'tests/test_pick_advisor.py'], '核心库 8 个用例'),
        Check('胆拖精确求解器', [py, 'tests/test_dan_tuo_exact.py'], '5 个性质验证'),
        Check('奖级一致性', [py, 'scripts/check_prize_consistency.py'],
              'PRIZE_RULES vs judge_prize'),
        Check('数据守卫测试', [py, 'tests/test_data_guard.py'], '故障注入 22 个用例'),
        Check('文件完整性', [py, 'scripts/check_corrupt.py'], 'null bytes 损坏检测'),
        Check('健康检查', [py, 'scripts/health_check.py'], '11 项'),
        Check('核心模块导入', [py, '-c', '''
import sys
mods = ['data.games','data.pick_advisor','data.dan_tuo_core','data.dan_tuo_exact',
        'data.strategy_lab',
        'data.hot_illusion','data.sports_odds','data.sports_arb','data.sports_lab2',
        'data.jingcai_odds','data.data_guard','data.live_scan_service',
        'data.data_fetcher','ui','core','analytics.probability_lab','scripts.pick_gui']
bad = []
for m in mods:
    try: __import__(m)
    except Exception as e: bad.append(f'{m}: {e}')
if bad:
    print('导入失败:', bad); sys.exit(1)
print(f'OK {len(mods)} 个模块')
'''], '17 个模块'),
        Check('编译检查', [py, '-m', 'compileall', '-q',
                           'data', 'core', 'analytics', 'scripts', 'sports',
                           'tests', 'ui'], '语法'),
        Check('Web GUI 冒烟', [py, '-c', '''
import sys
from scripts.pick_gui import app
c = app.test_client()
r = c.get('/')
assert r.status_code == 200, f'首页 {r.status_code}'
n = r.get_data(as_text=True).count('data-tab=')
assert n >= 9, f'Tab {n} < 9'
print(f'OK {n} Tabs')
'''], '首页 + Tab 数'),
    ]
    if not quick:
        checks.append(
            Check('图表生成', [py, 'scripts/make_headline_chart.py'],
                  '号码彩门面图'))
    return checks


def execute(checks: list) -> int:
    print()
    print('=' * 68)
    print('  本地 CI')
    print('=' * 68)
    passed = 0
    for c in checks:
        t0 = time.time()
        try:
            r = subprocess.run(c.cmd, cwd=str(PROJECT_ROOT),
                               capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=600)
            c.ok = (r.returncode == 0)
            out = (r.stdout or '') + (r.stderr or '')
            c.detail = out.strip().split('\n')[-1][:70] if out.strip() else ''
        except subprocess.TimeoutExpired:
            c.ok = False
            c.detail = '超时'
        except Exception as e:
            c.ok = False
            c.detail = str(e)[:70]
        c.seconds = time.time() - t0
        mark = f'{G}✓{N}' if c.ok else f'{R}✗{N}'
        print(f'  {mark} {c.name:<16} {c.seconds:>6.1f}s  {D}{c.detail}{N}')
        if c.ok:
            passed += 1
    print()
    print(f'  {passed}/{len(checks)} 通过')
    print('=' * 68)
    return passed


def write_badge(passed: int, total: int) -> None:
    """生成 shields.io endpoint 用的 JSON (badge 动态显示本地 CI 结果)"""
    BADGE_DIR.mkdir(parents=True, exist_ok=True)
    color = 'brightgreen' if passed == total else ('yellow' if passed >= total * 0.8
                                                  else 'red')
    label = 'CI (local)'
    message = f'{passed}/{total} passed'
    payload = {
        'schemaVersion': 1,
        'label': label,
        'message': message,
        'color': color,
    }
    out = BADGE_DIR / 'ci.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding='utf-8')
    print(f'  badge 已写: {out}')


def main():
    ap = argparse.ArgumentParser(description='本地 CI')
    ap.add_argument('--quick', action='store_true', help='跳过慢的检查')
    ap.add_argument('--badge', action='store_true', help='只更新 badge JSON')
    args = ap.parse_args()

    if args.badge:
        # 用上次结果或重跑
        checks = run_checks(quick=args.quick)
        passed = execute(checks)
        write_badge(passed, len(checks))
        return 0 if passed == len(checks) else 1

    checks = run_checks(quick=args.quick)
    passed = execute(checks)
    write_badge(passed, len(checks))
    return 0 if passed == len(checks) else 1


if __name__ == '__main__':
    sys.exit(main() or 0)
