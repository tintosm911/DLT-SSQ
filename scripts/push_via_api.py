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
                content: bytes) -> str:
    enc = base64.b64encode(content).decode()
    r = _req('POST', f'{_api}/repos/{owner}/{repo}/git/blobs', token,
             {'content': enc, 'encoding': 'base64'})
    return r['sha']


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

    # 上传 blob (只传变更的)
    print('\n  上传 blob...')
    uploaded: Dict[str, str] = {}
    deleted: set = set()
    for status, path in changes:
        full = PROJECT_ROOT / path
        if status.startswith('D') or not full.exists():
            deleted.add(path)
            print(f'    D {path}')
            continue
        data = full.read_bytes()
        try:
            sha = upload_blob(args.token, owner, repo, data)
        except Exception as e:
            print(f'    ✗ {path}: {e}')
            raise
        uploaded[path] = sha
        print(f'    A {path}  {len(data)/1024:.1f}KB  blob={sha[:8]}')

    # 建 tree
    # ⚠ GitHub Trees API 不支持 sha:null 删文件 (422 BadObjectState),
    #   所以改成: 拿远端全量 blob 清单, 应用变更 (改的换 sha / 删的剔除), 整体重建
    # ⚠ GitHub **禁止通过 API 创建 .github/workflows/ 下的文件** (防 CI 注入),
    #   单独出现时会 404. 这些文件必须用 git push 推.
    api_skipped = [p for p in uploaded if p.startswith('.github/workflows/')]
    for p in api_skipped:
        uploaded.pop(p)
        print(f'    ⚠️ {p} 需用 git push (GitHub 禁止 API 写 workflow)')

    base_tree = (get_commit_tree(args.token, owner, repo, remote_head)
                 if remote_head else None)
    if base_tree:
        try:
            existing = get_full_tree(args.token, owner, repo, base_tree)
            print(f'\n  远端现有 {len(existing)} 个文件, 重建完整 tree...')
        except Exception as e:
            print(f'  [warn] 取全量 tree 失败 ({e}), 退回增量模式')
            existing = None
    else:
        existing = None

    if existing is not None:
        entries_map = {e['path']: e for e in existing}
        for path, sha in uploaded.items():
            entries_map[path] = {'path': path, 'mode': '100644',
                                 'type': 'blob', 'sha': sha}
        for path in deleted:
            entries_map.pop(path, None)
        entries = list(entries_map.values())
        print(f'  tree 请求: {len(entries)} 条, 示例: '
              f'{[e["path"] for e in entries[:2]]}')
        tree = create_tree(args.token, owner, repo, '', entries)
    else:
        # 增量模式 (无 base_tree)
        entries = [{'path': p, 'mode': '100644', 'type': 'blob', 'sha': s}
                   for p, s in uploaded.items()]
        tree = create_tree(args.token, owner, repo, base_tree or '', entries)
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
