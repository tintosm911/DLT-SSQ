"""
前端契约检查
============
CI 里加这道闸, 防止"页面看着正常、其实全挂了"这类静默故障。

★ 为什么需要 (2026-11-19 真实事故):
  `scripts/pick_gui.py` 里的 HTML 有一处嵌套反引号 bug:
      `...1/${format(Math.round(1 / (p / p))), '0'))}<br>`
  内部反引号提前结束了外层模板字面量 → **整个 <script> 块语法错误**
  → 页面上所有 JS 全挂: 点任何按钮都没反应、号码网格也不渲染。
  而当时的 CI "Web GUI 冒烟" 只检查了 HTTP 200 和 Tab 数 —— **静态 HTML 正常,
  JS 全死也照样通过**。用户点按钮才发现。

三道检查:
  ① JS 语法     提取 <script> → node --check (没装 node 就跳过并警告)
  ② DOM 契约    前端 JS 里引用的所有 getElementById(...) 必须在 HTML 里存在
  ③ 接口契约    前端会读的字段, 后端必须真的返回 (抓 {ok,result} 这类包装不匹配)

用法:
  python scripts/check_frontend.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 前端 JS 里 getElementById / querySelector('#xxx') 引用的 id
ID_RE = re.compile(r"getElementById\(\s*['\"]([\w-]+)['\"]")
QS_RE = re.compile(r"querySelector(?:All)?\(\s*['\"]#([\w-]+)")

# 前端会读的字段 (点路径, 用 -> 分隔)
API_CONTRACT = [
    # (端点, 请求体, 点路径列表)
    ('/api/check', {'game': 'dlt', 'period': '2026132',
                    'front': [2, 9, 16, 26, 35], 'back': [6, 11]},
     ['result.expected.prize_per_bet', 'result.expected.net_per_bet',
      'result.expected.kelly', 'result.expected.first_prize_odds',
      'result.pick.front', 'result.pick.back',
      'result.recommendation', 'result.verdict_label']),
    ('/api/score', {'game': 'dlt', 'front': [1, 2, 3, 4, 5], 'back': [1, 2],
                    'window_n': 100},
     ['result.expected.prize_per_bet', 'result.pick.front']),
    ('/api/latest-draw', None,
     ['period', 'front', 'back']),
    ('/api/dan-tuo-optimize',
     {'game': 'dlt', 'budget': 1680, 'goal': 'win'},
     ['goal_cn', 'searched', 'best.structure', 'best.n_bets', 'best.cost',
      'best.win_rate', 'best.expected_net', 'best.front_dan', 'best.front_tuo',
      'best.back_dan', 'best.back_tuo', 'best.prize_prob', 'candidates']),
]


def get_path(obj, path):
    cur = obj
    for part in path.split('.'):
        if isinstance(cur, dict):
            if part not in cur:
                return False, f'缺字段 {part}'
            cur = cur[part]
        elif isinstance(cur, list):
            if not cur:
                return False, f'空列表, 取不到 {part}'
            cur = cur[0]
            if isinstance(cur, dict) and part not in cur:
                return False, f'列表元素缺字段 {part}'
            if isinstance(cur, dict):
                cur = cur[part] if part in cur else cur
        else:
            return False, f'取 {part} 时不是容器 (实际 {type(cur).__name__})'
    return True, ''


def check_unwrap_rule(js: str, client) -> list:
    """
    规则: 凡后端返回 {'ok':True,'result':...} 的 API,
    前端调用点必须能解包到 .result。

    ★ 这条规则抓的是"前端拿错层级"的 bug:
      后端字段一直都在, 所以"接口契约检查"抓不到;
      但如果前端不解包, 页面就会报 "Cannot read properties of undefined"。
      2026-11-19 真实事故就是这样。
    """
    problems = []
    # 找出所有返回 {ok,result} 的 API (从后端源码里找)
    src = (PROJECT_ROOT / 'scripts' / 'pick_gui.py').read_text(encoding='utf-8')
    wrapped = set()
    for m in re.finditer(
            r"jsonify\(\{\s*'ok'\s*:\s*True\s*,\s*'result'\s*:", src):
        # 往前找最近的 @app.route
        head = src[:m.start()]
        rm = None
        for rm in re.finditer(r"@app\.route\(\s*['\"](/api/[\w-]+)['\"]", head):
            pass
        if rm:
            # '/api/check' → 'check' (前端调用名是 api('check'))
            name = rm.group(1).lstrip('/')
            if name.startswith('api/'):
                name = name[4:]
            wrapped.add(name)
    if not wrapped:
        # 用运行时探测兜底
        for ep in ('check', 'score', 'dan-tuo', 'dan-tuo-optimize'):
            try:
                if ep == 'dan-tuo-optimize':
                    d = client.post('/api/dan-tuo-optimize',
                                    json={'game': 'dlt', 'budget': 100}).get_json()
                elif ep == 'dan-tuo':
                    d = client.post('/api/dan-tuo', json={
                        'game': 'dlt', 'front_dan': [1], 'front_tuo': [2, 3, 4, 5, 6],
                        'back_dan': [1], 'back_tuo': [2, 3, 4], 'draws': 0}).get_json()
                else:
                    d = client.post(f'/api/{ep}', json={
                        'game': 'dlt', 'period': '2026132',
                        'front': [2, 9, 16, 26, 35], 'back': [6, 11],
                        'window_n': 50}).get_json()
                if isinstance(d, dict) and 'result' in d:
                    wrapped.add(ep)
            except Exception:
                continue

    # 前端每个 api('xxx') 调用点后, **紧跟的第一个赋值**必须能解包 .result
    # (只看紧邻赋值, 不能看大窗口 —— 否则会扫到下一个 api 的解包而漏放)
    for m in re.finditer(r"api\(\s*['\"]([\w-]+)['\"]", js):
        action = m.group(1)
        if action not in wrapped:
            continue
        seg = js[m.end():m.end() + 300]
        cm = re.search(r'const\s+\w+\s*=\s*([^;]+);', seg)
        if not cm:
            problems.append(
                f"前端调用 api('{action}') 后没找到赋值语句, 无法确认是否解包 .result")
            continue
        expr = cm.group(1)
        if '.result' not in expr:
            problems.append(
                f"前端调用 api('{action}') 后写成 `{expr.strip()[:60]}` —— "
                f"后端返回 {{ok, result}}, 必须解包 (如 resp.result || resp), "
                f"否则页面报 undefined 错误")
    return problems


TPL_RE = re.compile(r'`(?:[^`\\]|\\.|\$\{(?:[^{}`]|`[^`]*`)*\})*`', re.S)
LINE_COMMENT_RE = re.compile(r'//[^\n]*')
BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.S)


def _blank_template(m):
    """
    把模板字符串的**纯文本部分**换成空格, ${...} 表达式原样保留。

    ★ 关键: 换行必须保留 (换成 '\\n'), 否则行号会错位, 报错指向错误的位置。
    ★ 为什么要空白化: `C(${a},${b})` 里的 "C(" 是**数学记号的文本**,
      不是函数调用; 不处理会大面积误报。
    """
    inner = m.group(0)[1:-1]
    out = []
    i = 0
    while i < len(inner):
        if inner[i:i + 2] == '${':
            depth = 1
            j = i + 2
            while j < len(inner) and depth:
                if inner[j] == '{':
                    depth += 1
                elif inner[j] == '}':
                    depth -= 1
                j += 1
            out.append(inner[i:j])      # 表达式保留
            i = j
        else:
            out.append('\n' if inner[i] == '\n' else ' ')
            i += 1
    return '`' + ''.join(out) + '`'


def strip_js_noise(js: str) -> str:
    """
    去掉"不会执行"的文本, 只留下真正的代码:
      - 行注释 //...
      - 块注释 /* ... */
      - 模板字符串里的**纯文本部分** (保留 ${...} 里的表达式)

    ★ 必须做这一步, 否则会大面积误报:
      - `C(${a},${b})` 是数学记号的**文本**, 不是函数调用
      - 注释里举的例子也会被当成代码
    """
    js = BLOCK_COMMENT_RE.sub(lambda m: '\n' * m.group(0).count('\n'), js)
    js = LINE_COMMENT_RE.sub('', js)
    js = TPL_RE.sub(_blank_template, js)
    return js


def check_undefined_calls(js: str) -> list:
    """
    规则: 找出**调用了但没定义**的函数名。

    ★ 为什么需要 (2026-11-19 真实事故):
      `fmt` 原本定义在 dtRender() 内部 (局部 const), 而 Tab ⑩ 的 opRender
      也要用它 → 作用域外引用 → ReferenceError: fmt is not defined。
      node --check **查不出**这种错 (它只查语法不查作用域),
      只能靠"把每个 Tab 实际点一遍"发现 —— 有了这条规则就不用点了。

    实现: 收集定义 (function 声明 / const-let-var / 参数 / catch / for-of)
          再收集调用点, 差集减去 JS 内置白名单。
    """
    # JS 内置 + 关键字 (不算未定义)
    builtin = set('''
    console log warn error info debug table group time timeEnd count
    Math JSON Object Array String Number Boolean Date RegExp Error Promise
    Symbol Map Set WeakMap WeakSet BigInt Proxy Reflect Intl ArrayBuffer
    parseInt parseFloat isFinite isNaN isNaN encodeURIComponent
    decodeURIComponent decodeURI encodeURI escape unescape
    setTimeout setInterval clearTimeout clearInterval requestAnimationFrame
    fetch alert confirm prompt location history navigator localStorage
    sessionStorage document window self globalThis top parent
    undefined null true false NaN Infinity arguments
    if for while switch catch return function typeof new delete void in of
    do else try finally throw break continue case default class extends
    super yield async await let const var this instanceof
    '''.split())

    # --- 定义集合 ---
    defined = set()
    for m in re.finditer(r'\bfunction\s+([A-Za-z_$][\w$]*)', js):
        defined.add(m.group(1))
    for m in re.finditer(
            r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=', js):
        defined.add(m.group(1))
    # 解构
    for m in re.finditer(
            r'\b(?:const|let|var)\s*[\{\[]([^\}\]]*)[\}\]]\s*=', js):
        for part in re.split(r'[,\s]+', m.group(1)):
            part = part.strip().split(':')[-1].strip()
            if re.fullmatch(r'[A-Za-z_$][\w$]*', part or ''):
                defined.add(part)
    # 函数参数 / catch / for-of
    for m in re.finditer(r'function[^(]*\(([^)]*)\)', js):
        for part in m.group(1).split(','):
            part = part.strip().split('=')[0].strip()
            if re.fullmatch(r'[A-Za-z_$][\w$]*', part or ''):
                defined.add(part)
    for m in re.finditer(r'catch\s*\(\s*([A-Za-z_$][\w$]*)', js):
        defined.add(m.group(1))
    for m in re.finditer(r'for\s*\(\s*(?:const|let|var)?\s*\[([^\]]*)\]', js):
        for part in re.split(r'[,\s]+', m.group(1)):
            if re.fullmatch(r'[A-Za-z_$][\w$]*', part or ''):
                defined.add(part)

    # --- 调用点 (先剥掉注释和模板纯文本, 避免把展示文本当代码) ---
    code = strip_js_noise(js)
    problems = []
    unknown = {}
    for m in re.finditer(r'(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(', code):
        name = m.group(1)
        if name in defined or name in builtin:
            continue
        line = code[:m.start()].count('\n') + 1
        unknown.setdefault(name, []).append(line)

    for name, lines in sorted(unknown.items()):
        problems.append(f'调用了未定义的函数 `{name}()` (行 {lines[:3]})')
    return problems


def main():
    from scripts.pick_gui import INDEX_HTML, app
    from flask import render_template_string

    with app.app_context():
        html = render_template_string(INDEX_HTML, dlt_net=-0.9407, ssq_net=-0.8570)

    problems = []
    warnings = []

    # ---------- ① JS 语法 ----------
    print('=' * 74)
    print('  ① JS 语法检查')
    m = re.search(r'<script>(.*)</script>', html, re.S)
    if not m:
        problems.append('HTML 里找不到 <script> 块')
    else:
        js = m.group(1)
        node = shutil.which('node')
        if not node:
            warnings.append('没装 node, 跳过 JS 语法检查 (建议装 Node.js)')
            print('  ⚠ 没找到 node, 跳过')
        else:
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                             encoding='utf-8') as f:
                f.write(js)
                tmp = f.name
            r = subprocess.run([node, '--check', tmp], capture_output=True,
                               text=True, encoding='utf-8', errors='replace')
            Path(tmp).unlink(missing_ok=True)
            if r.returncode != 0:
                err = (r.stderr or '').strip()
                # 只摘关键行, node 的堆栈太长
                key = [ln for ln in err.split('\n')
                       if 'SyntaxError' in ln or ln.strip().startswith('^')]
                problems.append('JS 语法错误: ' + ' | '.join(key[:2] or [err[:200]]))
                print(f'  ❌ {problems[-1]}')
            else:
                print(f'  ✅ 语法正确 ({len(js.splitlines())} 行 JS)')

    # ---------- ② DOM 契约 ----------
    print()
    print('  ② DOM 契约 (JS 引用的 id 必须存在)')
    html_ids = set(re.findall(r'\bid="([\w-]+)"', html))
    used_ids = set(ID_RE.findall(html)) | set(QS_RE.findall(html))
    missing = sorted(i for i in used_ids if i not in html_ids)
    if missing:
        problems.append(f'JS 引用了不存在的 id: {missing}')
        print(f'  ❌ 缺 {len(missing)} 个: {missing[:10]}')
    else:
        print(f'  ✅ {len(used_ids)} 个 id 全部存在')

    # ---------- ③ 接口契约 ----------
    print()
    print('  ③ 接口契约 (前端读的字段后端必须返回)')
    client = app.test_client()
    for ep, body, paths in API_CONTRACT:
        try:
            if body is None:
                r = client.get(ep)
            else:
                r = client.post(ep, json=body)
            if r.status_code != 200:
                problems.append(f'{ep} HTTP {r.status_code}')
                print(f'  ❌ {ep} HTTP {r.status_code}')
                continue
            data = r.get_json()
            bad = []
            for p in paths:
                ok, why = get_path(data, p)
                if not ok:
                    bad.append(f'{p} ({why})')
            if bad:
                problems.append(f'{ep} 字段缺失: {bad}')
                print(f'  ❌ {ep}: {bad[:4]}')
            else:
                print(f'  ✅ {ep}  {len(paths)} 个字段齐全')
        except Exception as e:
            problems.append(f'{ep} 调用异常 {type(e).__name__}: {e}')
            print(f'  ❌ {ep} {type(e).__name__}: {e}')

    # ---------- ④ 解包规则 ----------
    print()
    print('  ④ 解包规则 (前端调用点必须能解包 .result)')
    try:
        bad = check_unwrap_rule(m.group(1) if m else '', client)
        if bad:
            for b in bad:
                problems.append(b)
                print(f'  ❌ {b}')
        else:
            print('  ✅ 所有 {ok,result} 型 API 都正确解包')
    except Exception as e:
        warnings.append(f'解包规则检查异常: {e}')
        print(f'  ⚠ {e}')

    # ---------- ⑤ 未定义函数 ----------
    print()
    print('  ⑤ 未定义函数扫描 (作用域外引用)')
    try:
        bad = check_undefined_calls(m.group(1) if m else '')
        if bad:
            for b in bad:
                problems.append(b)
                print(f'  ❌ {b}')
        else:
            print('  ✅ 没有调用未定义的函数')
    except Exception as e:
        warnings.append(f'未定义函数扫描异常: {e}')
        print(f'  ⚠ {e}')

    print()
    print('=' * 74)
    for w in warnings:
        print(f'  ⚠ {w}')
    if problems:
        print(f'  ❌ {len(problems)} 处问题:')
        for p in problems:
            print(f'     · {p}')
        print('=' * 74)
        return 1
    print('  ✅ 前端契约全部通过')
    print('=' * 74)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
