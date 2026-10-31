"""
一键推送 (从 credential manager 取 token)
=========================================
公司网经常把 github.com:443 (git 协议) 挡掉, 但 api.github.com:443 走得通。
这个脚本自动从 **git credential manager** 取已存的 token, 交给
`push_via_api.py` 用 Git Data API 推送 —— token 不会出现在命令行里。

用法:
  python scripts/push_now.py                # 推最近一次 commit
  python scripts/push_now.py --dry-run      # 只看会推什么
  python scripts/push_now.py --since HEAD~3 # 推最近 3 个 commit 的变更

★ 已知限制: GitHub **禁止通过 API 写 workflow 文件**
  (POST /git/trees 遇到 .github/workflows/* 直接返回 404, 实测 2026-10-31)。
  workflow 文件只能走 `git push`, 且 token 必须带 `workflow` scope。
  → push_via_api.py 会自动跳过并提示。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass


def get_token() -> str:
    """从 git credential manager 取 token"""
    try:
        p = subprocess.run(
            ['git', 'credential', 'fill'],
            input='protocol=https\nhost=github.com\n\n',
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=30)
    except Exception:
        return ''
    for line in p.stdout.split('\n'):
        if line.startswith('password='):
            return line.split('=', 1)[1].strip()
    return ''


def main():
    tok = get_token()
    if not tok:
        print('❌ 未取到 credential (先 git push 一次让 credential manager 记住 token)')
        print('   或直接设环境变量 GITHUB_TOKEN')
        return 1
    print(f'  token 已取到 (长度 {len(tok)})')
    os.environ['GITHUB_TOKEN'] = tok

    sys.argv = ['push_via_api.py'] + sys.argv[1:]
    from scripts import push_via_api
    return push_via_api.main() or 0


if __name__ == '__main__':
    sys.exit(main() or 0)
