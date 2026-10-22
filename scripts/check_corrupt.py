"""
检测工作区里"内容全为 null bytes"的损坏文件
=============================================
2026-10-22 发现: 18 个文件内容整体变成 null bytes (14965 字节全 0).
磁盘写入正常 (新文件写回 OK), 说明是**某次批量操作把这些坏文件提交进了 git**,
所以 git 历史里也存的是坏的.

用法:
  python scripts/check_corrupt.py            # 只检测
  python scripts/check_corrupt.py --fix-git  # 从 git 历史恢复 (用最后一个好版本)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 明显是一次性的探针脚本, 损坏后直接删掉即可
PROBE_HINTS = ('probe_', 'test_api_paths', 'test_official_api', 'test_router',
                'test_sse', 'find_api', 'dump_em', 'debug_ssq', 'verify_db',
                'parse_official', 'full_fetch_ssq', 'sports_init')


def is_corrupt(path: Path) -> bool:
    """文件内容是否大面积为 null bytes"""
    try:
        b = path.read_bytes()
    except OSError:
        return False
    if not b:
        return False
    return b.count(0) > len(b) * 0.5


def scan(root: Path = PROJECT_ROOT) -> List[Path]:
    bad = []
    for p in root.rglob('*'):
        if not p.is_file():
            continue
        if any(x in p.parts for x in ('.git', '__pycache__', 'node_modules',
                                      'backups', '.venv', 'venv')):
            continue
        if p.suffix.lower() not in ('.py', '.md', '.txt', '.json', '.html',
                                    '.css', '.js', '.yml', '.yaml', '.csv'):
            continue
        if is_corrupt(p):
            bad.append(p)
    return sorted(bad)


def git_commits_for(path: Path) -> List[str]:
    """该文件的历史 commit 列表 (新→旧)"""
    r = subprocess.run(['git', 'log', '--format=%H', '--', str(path)],
                       cwd=str(PROJECT_ROOT), capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return [c for c in r.stdout.split('\n') if c.strip()]


def restore_from_history(path: Path) -> bool:
    """
    从 git 历史找最后一个内容正常的版本恢复.
    找不到 (历史里也是坏的) 则返回 False.
    """
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    for commit in git_commits_for(path):
        r = subprocess.run(['git', 'show', f'{commit}:{rel}'],
                           cwd=str(PROJECT_ROOT), capture_output=True)
        data = r.stdout
        if not data:
            continue
        if data.count(0) > len(data) * 0.5:
            continue
        path.write_bytes(data)
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description='检测/修复 null bytes 损坏文件')
    ap.add_argument('--fix-git', action='store_true',
                    help='从 git 历史恢复 (找不到好版本则跳过)')
    ap.add_argument('--fix-untracked', action='store_true',
                    help='删除未跟踪的损坏探针脚本 (需人工确认)')
    args = ap.parse_args()

    bad = scan()
    print('=' * 66)
    print('  损坏文件检测 (内容大面积 null bytes)')
    print('=' * 66)

    if not bad:
        print('  ✅ 未发现损坏文件')
        return 0

    print(f'  发现 {len(bad)} 个损坏文件:')
    fixed, unfixable, untracked = [], [], []
    for p in bad:
        rel = p.relative_to(PROJECT_ROOT)
        tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', str(rel)],
                                 cwd=str(PROJECT_ROOT),
                                 capture_output=True).returncode == 0
        if not tracked:
            untracked.append(p)
            continue
        if args.fix_git:
            if restore_from_history(p):
                fixed.append(p)
                print(f'  ✅ 已从历史恢复: {rel}')
            else:
                unfixable.append(p)
                print(f'  ❌ 历史里也损坏, 无法恢复: {rel}')
        else:
            print(f'  ❌ {rel}  ({p.stat().st_size} bytes)')

    if untracked:
        print()
        print(f'  未跟踪的损坏文件 {len(untracked)} 个 (多为一次性探针):')
        for p in untracked:
            print(f'    {p.relative_to(PROJECT_ROOT)}')
        if args.fix_untracked:
            for p in untracked:
                try:
                    p.unlink()
                    print(f'    已删除: {p.relative_to(PROJECT_ROOT)}')
                except OSError as e:
                    print(f'    删除失败 {p.name}: {e}')

    print()
    if fixed:
        print(f'  恢复 {len(fixed)} 个, 仍损坏 {len(unfixable)} 个, '
              f'未跟踪 {len(untracked)} 个')
    else:
        print(f'  仍损坏 {len(unfixable)} 个, 未跟踪 {len(untracked)} 个')
    print()
    return 1 if (unfixable or (untracked and not args.fix_untracked)) else 0


if __name__ == '__main__':
    sys.exit(main() or 0)
