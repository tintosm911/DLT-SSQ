"""
前端契约检查 · 回归验证
========================
证明 `scripts/check_frontend.py` 真能抓到那些"页面看着正常、其实全挂了"的 bug,
而不是一道空跑的闸。

做法: 把已知 bug **注入回源码**, 跑检查, 断言它被拦住, 然后还原。

覆盖:
  ① JS 语法错误 (嵌套反引号)      → 2026-11-19 真实事故
  ② 前端不解包 {ok,result}        → 2026-11-19 真实事故
  ③ 干净版本必须通过

用法:
  python tests/test_frontend_guard.py
  python -m pytest tests/test_frontend_guard.py -v
"""
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

SRC = PROJECT_ROOT / 'scripts' / 'pick_gui.py'
GUARD = PROJECT_ROOT / 'scripts' / 'check_frontend.py'

# (名称, 好的代码, 坏代码, 期望在输出里出现的关键字)
INJECTIONS = [
    ('JS 语法错误 (嵌套反引号)',
     """  const bigOdds = Math.round(1 / bd.big_odds);
  h += `一等奖概率 1/${bigOdds.toLocaleString()}<br>`;""",
     """  h += `一等奖概率 1/${format(Math.round(1 / (bd.detail[0].prob / (bd.detail[0].prob))), '0'))}<br>`;""",
     'JS 语法错误'),
    ('前端不解包 {ok,result}',
     """    const r = resp.result || resp;
    lastCheckResult = r;""",
     """    const r = resp;
    lastCheckResult = r;""",
     '必须解包'),
    ('未定义函数 (fmt 局部化)',
     """// ★ fmt 必须是**全局**的: 原来它定义在 dtRender() 内部 (局部 const),
//   而 Tab ⑩ 的 opRender 也要用 → 作用域外引用 → ReferenceError。
//   (这个 bug 被"整个 script 语法错误"掩盖着, JS 修好后才暴露)
function fmt(n) {
  const v = Number(n);
  if (!isFinite(v)) return String(n);
  return (v < 0 ? '' : '+') + v.toFixed(2);
}""",
     """function dtRender(r) {
  const t = r.tickets, e = r.expected, s = r.simulation;
  const fmt = n => (n < 0 ? '' : '+') + n.toFixed(2);""",
     '未定义的函数'),
    ('Python format() 混进 JS',
     """${Math.round(s.net).toLocaleString()}""",
     """${format(Math.round(s.net), 0)}""",
     '未定义的函数'),
]


def run_guard():
    return subprocess.run([sys.executable, str(GUARD)],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=str(PROJECT_ROOT), timeout=180)


def main():
    orig = SRC.read_text(encoding='utf-8')
    failed = 0
    try:
        # ① 干净版本必须通过
        r = run_guard()
        ok = r.returncode == 0
        print(f'  {"OK  " if ok else "FAIL"} 干净版本通过检查')
        if not ok:
            failed += 1
            print(r.stdout[-800:])

        # ② 注入已知 bug, 必须被拦住
        for name, good, bad, keyword in INJECTIONS:
            if good not in orig:
                print(f'  FAIL {name} —— 注入点找不到 (源码可能已变)')
                failed += 1
                continue
            SRC.write_text(orig.replace(good, bad), encoding='utf-8')
            try:
                r = run_guard()
                caught = r.returncode != 0 and keyword in (r.stdout + r.stderr)
                print(f'  {"OK  " if caught else "FAIL"} {name} → '
                      f'{"被拦住" if caught else "没拦住!!"}')
                if not caught:
                    failed += 1
                    print('    期望输出含: ' + keyword)
            finally:
                SRC.write_text(orig, encoding='utf-8')
    finally:
        SRC.write_text(orig, encoding='utf-8')

    print()
    if failed:
        print(f'  {failed} 项未通过')
        return 1
    print('  全部通过 —— 检查有效, 不是空跑')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
