"""
Windows 脚本编码检查 / 修复
============================
PowerShell 5.1 读取 .ps1 文件时:
  - 有 UTF-8 BOM  → 正确按 UTF-8 解码, 中文正常
  - 无 BOM        → 按系统 ANSI 代码页 (简体中文 = GBK/936) 解码
                   → 中文字节变成乱码, 引号/括号被破坏 → **语法错误, 脚本完全跑不了**

这个坑很隐蔽: 脚本逻辑写对了、GitHub 上也能看、但在你机器上一跑就报
"The string is missing the terminator"。

用法:
  python scripts/check_script_encoding.py          # 只检查
  python scripts/check_script_encoding.py --fix    # 检查并补 BOM
  python scripts/check_script_encoding.py --fix --all  # 递归扫描整个项目

★ 已被这个坑坑过的真实案例:
  scripts/schedule_snapshot.ps1 —— v2.4.0 交付后**从未成功执行过**,
  导致竞彩快照存档计划任务一直不存在, 8 天一条新数据都没攒下。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 需要 BOM 的脚本类型 (由 PowerShell/CMD 直接执行)
NEEDS_BOM = {'.ps1', '.psm1', '.bat', '.cmd'}

# 这些目录不扫
SKIP_DIRS = {'.git', 'node_modules', 'target', '__pycache__', '.pytest_cache',
             'desktop/src-tauri/target', 'third_party', 'archive', 'venv', '.venv'}

BOM = b'\xef\xbb\xbf'


def scan(root: Path, exts=None) -> list:
    """返回 [(路径, 是否有BOM, 是否有中文, 是否含ASCII引号), ...]"""
    exts = exts or NEEDS_BOM
    out = []
    for p in root.rglob('*'):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if any(rel.startswith(d) or f'/{d}/' in f'/{rel}' for d in SKIP_DIRS):
            continue
        if p.suffix.lower() not in exts:
            continue
        raw = p.read_bytes()
        has_bom = raw[:3] == BOM
        body = raw[3:] if has_bom else raw
        try:
            text = body.decode('utf-8')
            has_cn = any('\u4e00' <= ch <= '\u9fff' for ch in text)
            dec = 'utf-8'
        except UnicodeDecodeError:
            has_cn = True
            dec = 'gbk?'
        out.append((p, has_bom, has_cn, dec, len(raw)))
    return out


def fix(paths) -> int:
    """给缺 BOM 的文件补上 UTF-8 BOM"""
    n = 0
    for p in paths:
        raw = p.read_bytes()
        if raw[:3] == BOM:
            continue
        p.write_bytes(BOM + raw)
        print(f'  ✅ 补 BOM: {p.relative_to(PROJECT_ROOT)}')
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description='Windows 脚本编码检查')
    ap.add_argument('--fix', action='store_true', help='补上缺失的 UTF-8 BOM')
    ap.add_argument('--all', action='store_true', help='递归扫描整个项目')
    args = ap.parse_args()

    roots = [PROJECT_ROOT] if args.all else [
        PROJECT_ROOT / 'scripts', PROJECT_ROOT / 'desktop',
        PROJECT_ROOT / 'data', PROJECT_ROOT / 'core',
    ]
    items = []
    for r in roots:
        if r.exists():
            items.extend(scan(r))

    print()
    print('=' * 78)
    print('  Windows 脚本编码检查 (PowerShell 5.1 需要 UTF-8 BOM 才能正确读中文)')
    print('=' * 78)
    print()
    print(f'  {"脚本":<52}{"BOM":<8}{"中文":<6}{"解码"}')
    print('  ' + '-' * 74)
    bad = []
    for p, has_bom, has_cn, dec, size in items:
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        flag = '✅' if has_bom else ('❌' if has_cn else '-')
        print(f'  {rel:<52}{flag:<8}{"有" if has_cn else "无":<6}{dec}')
        if has_cn and not has_bom:
            bad.append(p)

    print('  ' + '-' * 74)
    print()
    if bad:
        print(f'  ❌ {len(bad)} 个含中文的脚本缺少 UTF-8 BOM —— '
              f'PowerShell 5.1 执行时会报语法错误')
        if args.fix:
            n = fix(bad)
            print(f'  ✅ 已修复 {n} 个')
            return 0
        print(f'  修复: python scripts/check_script_encoding.py --fix')
        return 1
    print('  ✅ 全部脚本编码正常')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
