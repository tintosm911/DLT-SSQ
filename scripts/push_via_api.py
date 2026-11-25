"""
用 GitHub API 推送 (绕过 git 协议)
==================================
公司网经常把 github.com:443 (git 协议) 挡掉, 但 api.github.com:443 走得通.
这个脚本用 **Git Data API** 完成推送:

  1. POST /git/blobs       上传每个变更文件
  2. POST /git/trees       用 blob sha 组装 tree
  3. POST /git/commits     创建 commit
  4. PATCH /git/refs/...   更新分支指针

用法:
  python scripts/push_via_api.py --token ghp_xxx
  python scripts/push_via_api.py --token ghp_xxx --message "commit msg"
  python scripts/push_via_api.py --token ghp_xxx --branch main --dry-run

只推**已提交**的变更 (git diff --name-status HEAD~1), 不碰工作区未提交内容.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_api = 'https://api.github.com'


def _req(method: str, url: str, token: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={'Authorization': f'Bearer {token}',
                 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json',
                 'User-Agent': 'lottery-lab'})
    try:
        with _opener.open(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw.decode()) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        raise RuntimeError(
            f'{method} {url.split("/repos/")[-1]} -> HTTP {e.code} {detail}') from e


def git(*args) -> str:
    return subprocess.run(['git', *args], cwd=str(PROJECT_ROOT),
                          capture_output=True, text=True,
                          encoding='utf-8', errors='replace').stdout.strip()


def git_bytes(*args) -> bytes:
    return subprocess.run(['git', *args], cwd=str(PROJECT_ROOT),
                          capture_output=True).stdout


def list_local_tree() -> List[dict]:
    """本地 HEAD 的**全量**文件清单 (path, mode, type, blob sha)

    ★ core.quotePath=false → 中文路径原样输出 (默认会把中文转义成 \\345\\220...)
    """
    out = git('-c', 'core.quotePath=false', 'ls-tree', '-r', 'HEAD')
    files = []
    for line in out.splitlines():
        if '\t' not in line:
            continue
        meta, path = line.split('\t', 1)
        parts = meta.split(' ', 2)
        if len(parts) != 3:
            continue
        mode, typ, sha = parts
        files.append({'path': path, 'mode': mode, 'type': typ, 'sha': sha})
    return files


def get_remote_head(token: str, owner: str, repo: str, branch: str) -> Optional[str]:
    try:
        r = _req('GET', f'{_api}/repos/{owner}/{repo}/git/ref/heads/{branch}',
                 token)
        return r['object']['sha']
    except Exception:
        return None


def get_commit_tree(token: str, owner: str, repo: str, sha: str) -> Optional[str]:
    """
    取 commit 的 tree sha.

    ⚠ GitHub API 要求**完整 40 位 SHA**, 短 SHA 会 404.
    """
    try:
        r = _req('GET', f'{_api}/repos/{owner}/{repo}/git/commits/{sha}', token)
        return r['tree']['sha']
    except Exception:
        return None


def get_full_tree(token: str, owner: str, repo: str,
                  tree_sha: str) -> List[dict]:
    """
    递归列出远端 tree 的所有 blob 条目 (含路径 + sha).

    用于构造"完整新 tree"—— 因为 GitHub Trees API **不支持 sha:null 删文件**,
    删文件只能靠"重建 tree 时不列这个路径".
    """
    r = _req('GET',
             f'{_api}/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1',
             token)
    out = []
    for e in r.get('tree', []):
        if e.get('type') == 'blob':
            out.append({'path': e['path'], 'mode': e.get('mode', '100644'),
                        'type': 'blob', 'sha': e['sha']})
    return out


def upload_blob(token: str, owner: str, repo: str,
                content: bytes, retries: int = 4) -> str:
    enc = base64.b64encode(content).decode()
    body = {'content': enc, 'encoding': 'base64'}
    last = None
    for attempt in range(retries):
        try:
            r = _req('POST', f'{_api}/repos/{owner}/{repo}/git/blobs', token, body)
            return r['sha']
        except Exception as e:
            last = e
            msg = str(e)
            # 网络抖动 / 422 超时 → 重试; 401/403/404 → 不重试
            if any(k in msg for k in ('401', '403', '404', 'Bad credentials',
                                     'Resource not accessible')):
                raise
            wait = 3 * (attempt + 1)
            print(f'    [retry {attempt + 1}/{retries}] blob 上传失败 '
                  f'({msg[:90]}), {wait}s 后重试')
            import time
            time.sleep(wait)
    raise last


def create_tree(token: str, owner: str, repo: str, base_tree: str,
                entries: List[dict]) -> str:
    # ⚠ base_tree 为空时必须**完全省略**该字段, 传空字符串会 404
    body: Dict = {'tree': entries}
    if base_tree:
        body['base_tree'] = base_tree
    r = _req('POST', f'{_api}/repos/{owner}/{repo}/git/trees', token, body)
    return r['sha']


def create_commit(token: str, owner: str, repo: str, tree: str,
                  parents: List[str], message: str) -> str:
    r = _req('POST', f'{_api}/repos/{owner}/{repo}/git/commits', token,
             {'message': message, 'tree': tree, 'parents': parents})
    return r['sha']


def update_ref(token: str, owner: str, repo: str, branch: str, sha: str,
               force: bool = False) -> bool:
    body = {'sha': sha, 'force': force}
    try:
        _req('PATCH', f'{_api}/repos/{owner}/{repo}/git/refs/heads/{branch}',
             token, body)
        return True
    except Exception as e:
        print(f'  更新 ref 失败: {e}')
        return False


def main():
    ap = argparse.ArgumentParser(description='用 GitHub API 推送 (绕过 git 协议)')
    ap.add_argument('--token', default=os.environ.get('GITHUB_TOKEN', ''),
                    help='GitHub token (或设 GITHUB_TOKEN 环境变量)')
    ap.add_argument('--repo', default='tintosm911/DLT-SSQ', help='owner/repo')
    ap.add_argument('--branch', default='main')
    ap.add_argument('--message', default='', help='commit message')
    ap.add_argument('--since', default='HEAD~1',
                    help='对比基线 (默认 HEAD~1, 即推最近一次 commit)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if not args.token:
        print('需要 --token (或设 GITHUB_TOKEN 环境变量)')
        return 1

    owner, repo = args.repo.split('/')

    # 本地 HEAD
    local_head = git('rev-parse', 'HEAD')
    local_msg = git('log', '-1', '--pretty=%s')
    if not local_head:
        print('没有本地 commit')
        return 1

    # 远端 HEAD
    remote_head = get_remote_head(args.token, owner, repo, args.branch)
    print(f'  本地 HEAD: {local_head[:10]}  {local_msg}')
    print(f'  远端 HEAD: {remote_head[:10] if remote_head else "(无)"}')

    if remote_head == local_head:
        print('  已同步, 无需推送')
        return 0

    # 找出变更文件 (相对基线)
    base = git('rev-parse', args.since) if args.since else local_head
    diff = git('diff', '--name-status', base, local_head)
    changes = []
    for line in diff.split('\n'):
        if not line.strip():
            continue
        parts = line.split('\t')
        status = parts[0]
        path = parts[-1]
        changes.append((status, path))

    if not changes:
        print('  没有文件变更')
        return 0

    print(f'\n  变更文件 {len(changes)} 个:')
    for s, p in changes:
        print(f'    {s:<2} {p}')

    if args.dry_run:
        print('\n  --dry-run, 不实际上传')
        return 0

    # ─────────────────────────────────────────────────────────────
    # ★★ 重建 tree 的正确做法 (v3.3.2 修复)
    #
    # 旧逻辑: tree = (远端现有文件) + (本次 diff 的变更)
    #   → **本地有、远端无、且不在本次 diff 里的文件永远补不上**。
    #     历次 push 累积下来, 远端会停在很早的状态 (实测: 缺 29 个文件、
    #     14 个核心文件内容还是旧版), 而 commit message 却显示最新版本。
    #
    # 新逻辑: tree = **本地 HEAD 的全量清单** (缺失的补传, 多余的删掉)
    #   → 推完远端必然 == 本地 HEAD, 不依赖 --since 基线, 也不会漏历史文件。
    # ─────────────────────────────────────────────────────────────
    local_files = list_local_tree()
    remote_tree_sha = (get_commit_tree(args.token, owner, repo, remote_head)
                       if remote_head else None)

    remote_map: Dict[str, str] = {}
    if remote_tree_sha:
        try:
            existing = get_full_tree(args.token, owner, repo, remote_tree_sha)
            remote_map = {e['path']: e['sha'] for e in existing}
            print(f'\n  远端现有 {len(remote_map)} 个文件')
        except Exception as e:
            print(f'  [warn] 取全量 tree 失败 ({e})')

    local_paths = {f['path'] for f in local_files}
    to_upload = [f for f in local_files
                 if remote_map.get(f['path']) != f['sha']]
    to_delete = sorted(set(remote_map) - local_paths)

    print(f'  本地 {len(local_files)} 个文件 | 远端 {len(remote_map)} 个'
          f' | 需上传 {len(to_upload)} | 需删除 {len(to_delete)}')

    # ---- 上传 blob ----
    # ★ 用 `git cat-file blob` 取 git 内部存的**原始内容**, 而不是读磁盘文件:
    #   这样 GitHub 侧算出的 blob sha 与本地 sha 完全一致, tree 能精确还原。
    uploaded: Dict[str, str] = {}
    if to_upload:
        print('\n  上传 blob...')
    for f in to_upload:
        if f['path'].startswith('.github/workflows/'):
            continue
        data = git_bytes('cat-file', 'blob', f['sha'])
        try:
            sha = upload_blob(args.token, owner, repo, data)
        except Exception as e:
            print(f'    ✗ {f["path"]}: {e}')
            raise
        if sha != f['sha']:
            print(f'    ! {f["path"]}: blob sha 不一致 '
                  f'{f["sha"][:8]} → {sha[:8]}')
        uploaded[f['path']] = sha
        print(f'    A {f["path"]}  {len(data)/1024:.1f}KB  blob={sha[:8]}')

    # ---- workflow: GitHub 禁止 API 写 ----
    api_skipped = [f['path'] for f in local_files
                   if f['path'].startswith('.github/workflows/')]
    for p in api_skipped:
        print(f'    ⚠️ {p} 需用 git push (GitHub 禁止 API 写 workflow)')

    # ---- 组装完整 tree (本地全量, 不含 workflow) ----
    entries: List[dict] = []
    for f in local_files:
        if f['path'] in api_skipped:
            continue
        entries.append({'path': f['path'], 'mode': f['mode'], 'type': 'blob',
                        'sha': uploaded.get(f['path'], f['sha'])})

    # 删除远端多余的路径 (sha:null)
    for p in to_delete:
        entries.append({'path': p, 'mode': '100644', 'type': 'blob',
                        'sha': None})

    tree = None
    last_err = ''
    for attempt in range(3):
        try:
            tree = create_tree(args.token, owner, repo,
                               remote_tree_sha or '', entries)
            break
        except Exception as e:
            last_err = str(e)
            print(f'  [retry {attempt + 1}] 建 tree 失败: {last_err[:120]}')
            import time
            time.sleep(3)
    if tree is None:
        # 最后再试一次: 去掉删除项 (有些情况下 sha:null 会让整棵树被拒)
        entries = [e for e in entries if e.get('sha') is not None]
        tree = create_tree(args.token, owner, repo, remote_tree_sha or '',
                           entries)
        print(f'  [warn] 已跳过删除项 (最后错误: {last_err[:100]})')

    print(f'\n  tree: {tree[:10]}  ({len(entries)} 条)')

    # 建 commit
    msg = args.message or f'{local_msg}\n\n(通过 GitHub API 推送)'
    parents = [remote_head] if remote_head else []
    commit = create_commit(args.token, owner, repo, tree, parents, msg)
    print(f'  commit: {commit[:10]}')

    # 更新 ref
    if update_ref(args.token, owner, repo, args.branch, commit):
        print(f'\n  ✅ 推送成功: {args.branch} -> {commit[:10]}')
        print(f'  https://github.com/{owner}/{repo}/commit/{commit}')
        if api_skipped:
            print(f'\n  ⚠️  {len(api_skipped)} 个 workflow 文件未推 (需 git push):')
            for p in api_skipped:
                print(f'      {p}')
            print(f'  命令: git push origin {args.branch}')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
