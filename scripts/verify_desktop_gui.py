"""
Desktop GUI 端到端启动验证
==========================
验证 Tauri 壳能否真正把后端拉起来、窗口能否加载到正确的动态端口。

流程:
  1. 启动 lottery-desktop.exe
  2. 找出它派生的 python 子进程, 从命令行解析 --port
  3. HTTP 请求该端口, 检查首页 200 + Tab 数
  4. 关闭 exe, 验证 python sidecar 无残留 (kill_on_drop)

用法:
  python scripts/verify_desktop_gui.py
  python scripts/verify_desktop_gui.py --exe "C:\\path\\to\\lottery-desktop.exe"
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

DEFAULT_EXE = r'C:\cargo_target\lottery\release\lottery-desktop.exe'


def _sidecar_procs() -> list:
    """
    列出所有 pick_gui sidecar 进程 (pid, cmdline)。

    ★ 只看 Name='python.exe' 的进程:
      用 `CommandLine -like '*pick_gui*'` 全局过滤会**把执行这条命令的
      PowerShell 自己也算进去** (它的命令行里就含 'pick_gui' 这个模式串),
      导致统计多 1、Stop-Process 杀自己失败。
    """
    out = []
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*pick_gui*' } | "
             "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=40)
        for line in (r.stdout or '').split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split('\t', 1)
            if len(parts) == 2:
                out.append((int(parts[0]), parts[1]))
    except Exception:
        pass
    return out


def find_python_children(parent_pid: int) -> list:
    """找出父进程为 parent_pid 的 python 进程 (取命令行)"""
    out = []
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             'Get-CimInstance Win32_Process | '
             'Where-Object { $_.ParentProcessId -eq ' + str(parent_pid) + ' } | '
             'ForEach-Object { '
             '"$($_.ProcessId)`t$($_.CommandLine)" }'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=40)
        for line in (r.stdout or '').split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split('\t', 1)
            if len(parts) != 2:
                continue
            pid_s, cl = parts
            if 'python' in cl.lower() and 'pick_gui' in cl:
                out.append((int(pid_s), cl))
    except Exception as e:
        print(f'  ⚠ 枚举子进程失败: {e}')
    return out


def count_orphan_sidecars() -> int:
    """全局统计还在跑的 pick_gui sidecar 进程数"""
    return len(_sidecar_procs())


def kill_sidecars() -> int:
    """清理所有 pick_gui sidecar 进程, 返回清理数量"""
    procs = _sidecar_procs()
    for pid, _ in procs:
        try:
            subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                           capture_output=True, timeout=20)
        except Exception:
            pass
    return len(procs)


def main():
    ap = argparse.ArgumentParser(description='Desktop GUI 端到端验证')
    ap.add_argument('--exe', default=DEFAULT_EXE)
    ap.add_argument('--timeout', type=int, default=60)
    args = ap.parse_args()

    exe = Path(args.exe)
    if not exe.exists():
        print(f'❌ exe 不存在: {exe}')
        print('   构建: cd desktop/src-tauri && cargo build --release '
              '(CARGO_TARGET_DIR 必须指向 C 盘)')
        return 1

    env = dict(os.environ)
    env.setdefault('LOTTERY_PROJECT_ROOT', str(PROJECT_ROOT))
    env.setdefault('LOTTERY_PYTHON', sys.executable)

    print('=' * 70)
    print('  Desktop GUI 端到端验证')
    print('=' * 70)
    print(f'  exe: {exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)')
    print(f'  项目根: {PROJECT_ROOT}')
    print(f'  Python: {env["LOTTERY_PYTHON"]}')
    print()

    proc = subprocess.Popen([str(exe)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f'  已启动, PID={proc.pid}, 等待后端就绪 (最多 {args.timeout}s)...')

    port = None
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f'  ❌ exe 提前退出, returncode={proc.returncode}')
            out, err = b'', b''
            try:
                out, err = proc.communicate(timeout=5)
            except Exception:
                pass
            if err:
                print('  stderr:', err.decode('utf-8', 'replace')[:600])
            return 1
        kids = find_python_children(proc.pid)
        if kids:
            m = re.search(r'--port\s+(\d+)', kids[0][1])
            if m:
                port = int(m.group(1))
                print(f'  ✅ sidecar python PID={kids[0][0]}  --port {port}')
                break
        time.sleep(1.5)

    if not port:
        print('  ❌ 未发现 sidecar 或未解析出端口')
        proc.kill()
        return 1

    # HTTP 验证
    url = f'http://127.0.0.1:{port}/'
    ok = False
    for _ in range(20):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'verify'})
            with urllib.request.build_opener(
                    urllib.request.ProxyHandler({})).open(req, timeout=8) as r:
                html = r.read().decode('utf-8', 'replace')
                tabs = html.count('data-tab=')
                print(f'  ✅ 首页 {r.status_code}  Tab 数={tabs}  '
                      f'长度={len(html)}')
                ok = r.status_code == 200 and tabs >= 10
                if not ok:
                    print(f'     ⚠ Tab 数 {tabs} < 10')
                break
        except Exception as e:
            time.sleep(1.0)
    if not ok and 'html' not in dir():
        print(f'  ❌ 首页请求失败: {url}')

    # 关闭后清理 —— 故意**强制结束** exe (模拟用户用任务管理器杀进程),
    # 验证 sidecar 的父进程看门狗能不能自动清理孤儿
    print('  强制结束 exe (模拟崩溃/任务管理器杀进程)...')
    try:
        proc.kill()
        proc.wait(timeout=15)
    except Exception:
        pass
    time.sleep(12.0)      # 看门狗轮询间隔 5s, 给它时间自杀

    left = count_orphan_sidecars()
    print(f'  残留 pick_gui 进程: {left} 个')
    if left > 0:
        ok = False
        print('  ⚠ 看门狗未生效, 手动清理')
        kill_sidecars()
        time.sleep(2)
        print(f'  清理后剩余: {count_orphan_sidecars()} 个')

    print()
    print('=' * 70)
    print('  ✅ 通过' if ok else '  ❌ 未通过')
    print('=' * 70)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main() or 0)
