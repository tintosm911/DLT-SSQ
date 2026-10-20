"""
健康检查
========
检查数据层、数据库、采集器、算法的可用性, 并给出可执行修复建议。

用法:
  python scripts/health_check.py
  python scripts/health_check.py --json
  python scripts/health_check.py --auto-fix
"""
from __future__ import annotations
import os
import sys
import json
import sqlite3
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'third_party'))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

for _k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(_k, None)

DATA_RAW = PROJECT_ROOT / 'data-raw'
DB_PATH = DATA_RAW / 'lottery.db'
REPORTS = PROJECT_ROOT / 'reports'

GAMES = {
    'dlt': {'name': '超级大乐透', 'front_count': 5, 'front_range': 35,
            'back_count': 2, 'back_range': 12, 'min_periods': 61},
    'ssq': {'name': '双色球', 'front_count': 6, 'front_range': 33,
            'back_count': 1, 'back_range': 16, 'min_periods': 61},
}


# ============================================================
# 检查项
# ============================================================
def check_python() -> Dict[str, Any]:
    v = sys.version_info
    ok = v >= (3, 9)
    return {
        'name': 'Python 运行时',
        'ok': ok,
        'detail': f'{v.major}.{v.minor}.{v.micro}',
        'fix': '' if ok else '需要 Python 3.9+',
    }


def check_dependencies() -> Dict[str, Any]:
    required = ['pandas', 'numpy', 'scipy', 'matplotlib']
    missing = []
    versions = {}
    for mod in required:
        try:
            m = __import__(mod)
            versions[mod] = getattr(m, '__version__', '?')
        except ImportError:
            missing.append(mod)
    return {
        'name': 'Python 依赖',
        'ok': not missing,
        'detail': ', '.join(f'{k}={v}' for k, v in versions.items()) or '全部缺失',
        'fix': '' if not missing else f'pip install {" ".join(missing)}',
    }


def check_modules() -> Dict[str, Any]:
    """核心模块能否 import"""
    modules = [
        ('core', '核心算法'),
        ('data', '数据层'),
        ('analytics.probability_lab', '概率实验室'),
        ('sports.elo', '竞彩 Elo'),
        ('sports.strategies', '竞彩策略'),
        ('drawscope_engine.statistics.analytics', 'DrawScope 引擎'),
        ('sports.drawscope_adapter', 'DrawScope 适配层'),
    ]
    ok_count = 0
    fails = []
    for mod, label in modules:
        try:
            __import__(mod)
            ok_count += 1
        except Exception as e:
            fails.append(f'{label}({mod}): {str(e)[:40]}')
    return {
        'name': '核心模块',
        'ok': not fails,
        'detail': f'{ok_count}/{len(modules)} 可用',
        'fix': '' if not fails else '; '.join(fails[:3]),
    }


def check_db() -> Dict[str, Any]:
    if not DB_PATH.exists():
        return {
            'name': 'SQLite 数据库',
            'ok': False,
            'detail': f'不存在 ({DB_PATH})',
            'fix': 'python main.py crawl --game all',
        }

    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    stats = {}
    try:
        con = sqlite3.connect(str(DB_PATH))
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        for g in GAMES:
            cur.execute('SELECT COUNT(*), MIN(period), MAX(period) FROM draws WHERE game=?', (g,))
            row = cur.fetchone()
            stats[g] = {'count': row[0], 'min_period': row[1], 'max_period': row[2]}
        con.close()
    except Exception as e:
        return {
            'name': 'SQLite 数据库',
            'ok': False,
            'detail': f'{size_mb:.2f}MB, 读取失败: {str(e)[:50]}',
            'fix': '删除 lottery.db 后重新 crawl',
        }

    ok = all(s['count'] >= 30 for s in stats.values())
    lines = [f'{g}:{s["count"]}期({s["min_period"]}~{s["max_period"]})' for g, s in stats.items()]
    return {
        'name': 'SQLite 数据库',
        'ok': ok,
        'detail': f'{size_mb:.2f}MB, tables={tables}, ' + ', '.join(lines),
        'fix': '' if ok else '数据不足, 跑 python main.py crawl --game all',
    }


def check_csv() -> Dict[str, Any]:
    files = sorted(DATA_RAW.glob('*.csv'))
    csvs = [f for f in files if f.stat().st_size > 100]
    return {
        'name': 'CSV 数据文件',
        'ok': len(csvs) > 0,
        'detail': f'{len(csvs)} 个有效 CSV: ' + ', '.join(f.name for f in csvs[:6]),
        'fix': '' if csvs else 'python main.py crawl --game all',
    }


def check_data_quality() -> Dict[str, Any]:
    """号码范围 + χ² 快速体检"""
    import csv as _csv
    issues = []
    checked = 0

    for game, cfg in GAMES.items():
        path = DATA_RAW / f'merged_{game}.csv'
        if not path.exists():
            path = DATA_RAW / f'gh_{game}.csv'
        if not path.exists():
            continue

        checked += 1
        freq: Dict[int, int] = {}
        n = 0
        with open(path, 'r', encoding='utf-8') as f:
            for row in _csv.DictReader(f):
                try:
                    front = [int(row[f'front_{i+1}']) for i in range(cfg['front_count'])]
                    back = [int(row[f'back_{i+1}']) for i in range(cfg['back_count'])]
                except (KeyError, ValueError):
                    continue
                if not all(1 <= x <= cfg['front_range'] for x in front):
                    issues.append(f'{game} 号码越界: {front}')
                    break
                for x in front:
                    freq[x] = freq.get(x, 0) + 1
                n += 1

        if n:
            exp = n * cfg['front_count'] / cfg['front_range']
            chi2 = sum((c - exp) ** 2 / exp for c in freq.values())
            chi2 += (cfg['front_range'] - len(freq)) * exp
            dof = cfg['front_range'] - 1
            if chi2 > dof * 1.5:
                issues.append(f'{game} χ²={chi2:.1f} 超过阈值 {dof*1.5:.0f} (可能数据有问题)')

    return {
        'name': '数据质量',
        'ok': checked > 0 and not issues,
        'detail': f'体检 {checked} 个数据集, {len(issues)} 个问题' + (f': {issues[0]}' if issues else ''),
        'fix': '' if not issues else '检查 data-raw/*.csv',
    }


def check_fetchers() -> Dict[str, Any]:
    fetchers = ['data/ttz_fetcher.py', 'data/zhcw_fetcher.py',
                'data/github_fetcher.py', 'data/merge_sources.py',
                'data/import_csv.py']
    exists = [f for f in fetchers if (PROJECT_ROOT / f).exists()]
    return {
        'name': '采集器',
        'ok': len(exists) >= 3,
        'detail': f'{len(exists)}/{len(fetchers)}: ' + ', '.join(Path(f).stem for f in exists),
        'fix': '' if len(exists) >= 3 else '采集器文件缺失',
    }


def check_reports() -> Dict[str, Any]:
    pngs = sorted(REPORTS.glob('*.png')) if REPORTS.exists() else []
    return {
        'name': '报告图表',
        'ok': len(pngs) > 0,
        'detail': f'{len(pngs)} 张 PNG' + (f': {", ".join(p.name for p in pngs[:3])}' if pngs else ''),
        'fix': '' if pngs else 'python main.py lab --game dlt',
    }


def check_disk() -> Dict[str, Any]:
    try:
        import shutil
        total, used, free = shutil.disk_usage(PROJECT_ROOT)
        free_gb = free / 1024 ** 3
        ok = free_gb > 1.0
        return {
            'name': '磁盘空间',
            'ok': ok,
            'detail': f'可用 {free_gb:.1f}GB / 总 {total/1024**3:.0f}GB',
            'fix': '' if ok else '磁盘空间不足 (<1GB)',
        }
    except Exception as e:
        return {'name': '磁盘空间', 'ok': True, 'detail': f'检测失败: {str(e)[:40]}', 'fix': ''}


CHECKS = [
    check_python,
    check_dependencies,
    check_modules,
    check_db,
    check_csv,
    check_data_quality,
    check_fetchers,
    check_reports,
    check_disk,
]


# ============================================================
# 主流程
# ============================================================
def run_all() -> List[Dict[str, Any]]:
    results = []
    for fn in CHECKS:
        try:
            results.append(fn())
        except Exception as e:
            results.append({
                'name': fn.__name__.replace('check_', ''),
                'ok': False,
                'detail': f'检查异常: {type(e).__name__}: {str(e)[:60]}',
                'fix': '',
            })
    return results


def auto_fix(results: List[Dict[str, Any]]) -> List[str]:
    """执行可自动修复的项"""
    actions = []

    # 1. 数据不足 → 跑 crawl
    if not next((r for r in results if r['name'] == 'SQLite 数据库'), {}).get('ok', True):
        print('  → 尝试重新采集数据...')
        try:
            r = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / 'main.py'), 'crawl', '--game', 'all'],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=600,
            )
            actions.append(f'crawl 退出码 {r.returncode}')
        except Exception as e:
            actions.append(f'crawl 失败: {str(e)[:60]}')

    # 2. 报告缺失 → 跑 lab
    if not next((r for r in results if r['name'] == '报告图表'), {}).get('ok', True):
        print('  → 尝试生成报告图表...')
        try:
            subprocess.run(
                [sys.executable, str(PROJECT_ROOT / 'main.py'), 'lab', '--game', 'dlt'],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=900,
            )
            actions.append('lab 已运行')
        except Exception as e:
            actions.append(f'lab 失败: {str(e)[:60]}')

    return actions


def main():
    ap = argparse.ArgumentParser(description='健康检查')
    ap.add_argument('--json', action='store_true', help='JSON 输出')
    ap.add_argument('--auto-fix', action='store_true', help='自动修复可修复项')
    args = ap.parse_args()

    results = run_all()

    if args.json:
        print(json.dumps({
            'status': 'ok' if all(r['ok'] for r in results) else 'degraded',
            'timestamp': datetime.now().isoformat(),
            'checks': results,
        }, ensure_ascii=False, indent=2))
        return 0 if all(r['ok'] for r in results) else 1

    print('=' * 74)
    print(f'  健康检查  ({datetime.now():%Y-%m-%d %H:%M:%S})')
    print('=' * 74)
    print()

    for r in results:
        mark = '✅' if r['ok'] else '❌'
        print(f'  {mark} {r["name"]}')
        print(f'     {r["detail"]}')
        if not r['ok'] and r.get('fix'):
            print(f'     → 修复: {r["fix"]}')
        print()

    ok = sum(1 for r in results if r['ok'])
    total = len(results)
    print('-' * 74)
    print(f'  结果: {ok}/{total} 项通过')
    if ok == total:
        print('  状态: ✅ 健康')
    else:
        print('  状态: ⚠ 有问题项 (见上方修复建议)')
    print('-' * 74)
    print()

    if args.auto_fix:
        print('🔧 自动修复中...')
        actions = auto_fix(results)
        if actions:
            for a in actions:
                print(f'  • {a}')
        else:
            print('  无可自动修复项')
        print()
        print('重新检查:')
        results2 = run_all()
        ok2 = sum(1 for r in results2 if r['ok'])
        print(f'  {ok2}/{len(results2)} 项通过')

    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())