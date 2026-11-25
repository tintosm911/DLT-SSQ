"""
校验远端 tree 是否真等于本地 HEAD (推送后必跑)
==============================================
★ 为什么要有这个脚本:
  v3.3.2 之前, push_via_api.py 重建 tree 的逻辑是
  「远端现有文件 + 本次 diff 的变更」→ **本地有、远端无、且不在本次 diff 里的
  文件永远补不上**。实测远端 HEAD 的 commit message 是 v3.3.1, 实际内容却
  停在很早的状态 (缺 29 个文件、14 个核心文件是旧版) —— 而且**不报任何错**。

  推送"成功"不等于"内容同步"。这个脚本就是那个缺失的验收环节。

用法:
  python scripts/verify_remote_sync.py           # 对比当前远端 HEAD 与本地 HEAD
  python scripts/verify_remote_sync.py --repo owner/name
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'lottery-lab'})
    with _opener.open(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def git(*args) -> str:
    return subprocess.run(['git', *args], cwd=str(PROJECT_ROOT),
                          capture_output=True, text=True,
                          encoding='utf-8', errors='replace').stdout


def local_tree() -> dict:
    out = git('-c', 'core.quotePath=false', 'ls-tree', '-r', 'HEAD')
    files = {}
    for line in out.splitlines():
        if '\t' not in line:
            continue
        meta, path = line.split('\t', 1)
        parts = meta.split(' ', 2)
        if len(parts) != 3:
            continue
        files[path] = parts[2]
    return files


def main():
    ap = argparse.ArgumentParser(description='校验远端与本地是否一致')
    ap.add_argument('--repo', default='tintosm911/DLT-SSQ')
    ap.add_argument('--branch', default='main')
    args = ap.parse_args()

    local = local_tree()
    head = git('rev-parse', 'HEAD')
    msg = git('log', '-1', '--pretty=%s')

    c = api(f'https://api.github.com/repos/{args.repo}/commits?per_page=1')[0]
    remote_sha = c['sha']
    print(f'  本地 HEAD: {head[:10]}  {msg}')
    print(f'  远端 HEAD: {remote_sha[:10]}  {c["commit"]["message"].splitlines()[0]}')
    print()

    tree = api(f'https://api.github.com/repos/{args.repo}/git/trees/'
               f'{remote_sha}?recursive=1')
    remote = {e['path']: e['sha'] for e in tree.get('tree', [])
              if e.get('type') == 'blob'}

    only_local = sorted(set(local) - set(remote))
    only_remote = sorted(set(remote) - set(local))
    diff = sorted(p for p in set(local) & set(remote)
                  if local[p] != remote[p])

    # workflow 是已知例外: GitHub 禁止通过 API 写 workflow 文件
    wf = [p for p in only_local if p.startswith('.github/workflows/')]
    only_local = [p for p in only_local if p not in wf]

    print(f'  本地 {len(local)} 个文件 | 远端 {len(remote)} 个')
    print()

    if only_local:
        print(f'  ❌ 本地有、远端没有 ({len(only_local)}):')
        for p in only_local[:40]:
            print(f'      {p}')
    if only_remote:
        print(f'  ❌ 远端有、本地没有 ({len(only_remote)}):')
        for p in only_remote[:40]:
            print(f'      {p}')
    if diff:
        print(f'  ❌ 两边都有但内容不同 ({len(diff)}):')
        for p in diff[:40]:
            print(f'      {p}')

    if wf:
        print(f'\n  ⚠️  {len(wf)} 个 workflow 文件未同步 (GitHub 禁止 API 写):')
        for p in wf:
            print(f'      {p}')
        print(f'      → 需要带 workflow scope 的 classic PAT: '
              f'git push origin {args.branch}')

    if not (only_local or only_remote or diff):
        print('  ✅ 远端内容与本地 HEAD 完全一致 (workflow 除外)')
        return 0
    print('\n  ❌ 远端与本地不一致 —— 推送逻辑可能又漏了东西')
    return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
