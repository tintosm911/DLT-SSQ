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
    """
    本地 CI 检查项。

    ★ 选标准 (2026-11-18 收敛):
      只保留**能拦住真静默故障**的项 —— 每一项历史上都抓到过
      "肉眼看数据完全正常"的问题。其余项降级为手动脚本, 不占 CI 时间。

      砍掉的项 (降级为手动):
        - 图表生成        → 生成物存在性, 不是逻辑正确性; 16 秒
        - 核心模块导入    → 编译检查的子集, 几乎不可能失败
        - 编译检查        → 几乎不可能失败
        - 数据守卫测试    → 故障注入测的是 guard 自己, 半年没抓到过东西
        - 文件完整性      → null bytes 是 2026-10 的一次性事故, 已根治
        - 全量对拍抽样    → 37 秒; 改为手动/每日跑 (scripts/verify_all_draws.py)
        - 胆拖方案对比    → 优化器测试已覆盖同样的结构计算
    """
    py = sys.executable
    checks = [
        # ---- 守门组: 期望值口径 + 核心数学 ----
        Check('单元测试', [py, 'tests/test_pick_advisor.py'], '核心库 8 个用例'),
        Check('奖级一致性', [py, 'scripts/check_prize_consistency.py'],
              'PRIZE_RULES vs judge_prize'),
        Check('胆拖精确求解器', [py, 'tests/test_dan_tuo_exact.py'], '5 个性质验证'),
        Check('胆拖结构优化器', [py, 'tests/test_dan_tuo_optimizer.py'], '5 个用例'),

        # ---- 守门组: 数据真伪与完整性 ----
        Check('数据完整性审计', [py, 'scripts/audit_data_integrity.py'],
              '期号连续性 + 日期间隔 + 同日期检测'),
        Check('官方交叉验证', [py, 'scripts/verify_draws_against_official.py',
                               '--n', '2'], '本地库 vs 官方 API'),
        Check('健康检查', [py, 'scripts/health_check.py'], '11 项'),
        Check('前端契约', [py, 'scripts/check_frontend.py'],
              'JS 语法 + DOM + 接口契约 + 解包规则'),
        Check('前端守门回归', [py, 'tests/test_frontend_guard.py'],
              '注入 bug 验证守门有效'),

        # ---- 守门组: 环境与前端 ----
        Check('脚本编码检查', [py, 'scripts/check_script_encoding.py', '--all'],
              'PowerShell 需 UTF-8 BOM'),
        Check('Web GUI 冒烟', [py, '-c', '''
import sys
from scripts.pick_gui import app
c = app.test_client()
r = c.get('/')
assert r.status_code == 200, f'首页 {r.status_code}'
n = r.get_data(as_text=True).count('data-tab=')
assert n >= 10, f'Tab {n} < 10'
# 优化器端点冒烟
r2 = c.post('/api/dan-tuo-optimize',
            json={'game': 'dlt', 'budget': 1680, 'goal': 'win'})
d = r2.get_json()
assert d.get('best'), f'优化器无解: {d}'
assert d['best']['n_bets'] * 2 <= 1680, '优化器超出预算'
print(f'OK {n} Tabs, 优化器 {d["best"]["structure"]}')
'''], '首页 + Tab 数 + 优化器'),
    ]
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
