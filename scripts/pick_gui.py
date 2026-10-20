"""
号码实战评估器 — Web GUI (Flask 单页)
======================================
直接拿 advisor 核心库做后端; 前端是单 HTML + Vue-free vanilla JS (零依赖).

用法:
  python scripts/pick_gui.py
  浏览器开 http://127.0.0.1:9876
  三个 Tab:
    - 历史期验证 (check): 输入期号 + 选号, 看真实命中
    - 算法评分 (score): 输入任意号码, 看 7 算法温度分
    - 历史记录 (history): 看自己测过的所有号码 + 战绩

端口: 9876 (避开常见端口冲突)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from flask import Flask, jsonify, request, render_template_string

from data.games import get_game, list_games
from data.pick_advisor import Pick, PickAdvisor, DataSnapshot, PickHistory


HISTORY_PATH = PROJECT_ROOT / 'data-raw' / 'my_picks.jsonl'

app = Flask(__name__)


# ============================================================
# HTML 单页 (零依赖 vanilla JS)
# ============================================================
INDEX_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>号码实战评估器</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "Microsoft YaHei", sans-serif;
         background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
         min-height: 100vh; color: #e2e8f0; padding: 24px; }
  .container { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 24px; margin-bottom: 4px; }
  .subtitle { color: #94a3b8; font-size: 13px; margin-bottom: 24px; }
  .tabs { display: flex; gap: 4px; margin-bottom: 16px; border-bottom: 1px solid #334155; }
  .tab { padding: 10px 20px; cursor: pointer; background: transparent;
         border: none; color: #94a3b8; font-size: 14px; border-bottom: 2px solid transparent; }
  .tab.active { color: #fbbf24; border-bottom-color: #fbbf24; }
  .tab:hover { color: #fde68a; }
  .panel { background: #1e293b; border: 1px solid #334155; border-radius: 8px;
           padding: 24px; margin-bottom: 16px; }
  .panel.hidden { display: none; }
  .row { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
  .row > * { flex: 0 0 auto; }
  label { font-size: 13px; color: #94a3b8; }
  input, select, button { padding: 8px 12px; border-radius: 4px; border: 1px solid #334155;
                           background: #0f172a; color: #e2e8f0; font-size: 14px; }
  input[type=text] { min-width: 240px; }
  input.num { width: 50px; }
  button { cursor: pointer; background: #2563eb; border-color: #2563eb; color: white; }
  button:hover { background: #1d4ed8; }
  button.secondary { background: #475569; border-color: #475569; }
  button.secondary:hover { background: #334155; }
  .result { background: #0f172a; border: 1px solid #1e293b; border-radius: 4px;
            padding: 16px; font-size: 13px; line-height: 1.6; white-space: pre-wrap;
            font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
            max-height: 600px; overflow-y: auto; }
  .hit { color: #4ade80; font-weight: bold; }
  .miss { color: #f87171; }
  .warning { color: #fbbf24; }
  .alert { color: #f87171; font-weight: bold; }
  .history-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .history-table th, .history-table td { padding: 6px 8px; border-bottom: 1px solid #1e293b; text-align: left; }
  .history-table th { color: #94a3b8; font-weight: normal; background: #0f172a; }
  .num-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(48px, 1fr));
              gap: 4px; margin: 8px 0; }
  .num-btn { padding: 8px; background: #0f172a; border: 1px solid #334155;
             border-radius: 4px; cursor: pointer; font-size: 14px;
             color: #e2e8f0; text-align: center; user-select: none; }
  .num-btn.selected { background: #dc2626; color: white; border-color: #fca5a5; }
  .num-btn:hover { background: #475569; }
  .num-btn.selected:hover { background: #b91c1c; }
  .section-title { font-size: 14px; color: #fbbf24; margin: 12px 0 4px 0; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
          font-size: 11px; background: #1e293b; margin-right: 4px; }
  .pill.hot { background: #7f1d1d; color: #fecaca; }
  .pill.cold { background: #1e40af; color: #bfdbfe; }
  .stats { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
  .stat { background: #0f172a; padding: 12px 16px; border-radius: 6px; min-width: 120px; }
  .stat .label { font-size: 11px; color: #94a3b8; text-transform: uppercase; }
  .stat .value { font-size: 20px; font-weight: bold; margin-top: 4px; }
  .disclaimer { background: #422006; border: 1px solid #f59e0b; color: #fbbf24;
                padding: 12px; border-radius: 4px; font-size: 12px; margin-top: 16px; }
</style>
</head>
<body>
<div class="container">
  <h1>🎰 号码实战评估器</h1>
  <div class="subtitle">基于真实历史数据 — 大乐透 / 双色球</div>

  <div class="tabs">
    <button class="tab active" data-tab="check">① 历史期验证</button>
    <button class="tab" data-tab="score">② 算法评分</button>
    <button class="tab" data-tab="history">③ 历史记录</button>
  </div>

  <!-- Tab 1: check -->
  <div class="panel" id="panel-check">
    <div class="row">
      <label>彩种:</label>
      <select id="check-game">
        <option value="dlt">大乐透</option>
        <option value="ssq">双色球</option>
      </select>
      <label>期号:</label>
      <input type="text" id="check-period" placeholder="例如 26119" style="width:140px">
    </div>
    <div class="section-title" id="check-front-title">前区 (选 5 个, 1-35)</div>
    <div id="check-front-grid" class="num-grid"></div>
    <div class="section-title" id="check-back-title">后区 (选 2 个, 1-12)</div>
    <div id="check-back-grid" class="num-grid"></div>
    <div class="row">
      <button onclick="checkAction()">验证</button>
      <button class="secondary" onclick="checkSave()">保存到我的记录</button>
      <span id="check-status" style="font-size:12px;color:#94a3b8"></span>
    </div>
    <div class="result" id="check-result">点击"验证"开始...</div>
  </div>

  <!-- Tab 2: score -->
  <div class="panel hidden" id="panel-score">
    <div class="row">
      <label>彩种:</label>
      <select id="score-game" onchange="scoreGameChange()">
        <option value="dlt">大乐透</option>
        <option value="ssq">双色球</option>
      </select>
      <label>窗口:</label>
      <select id="score-window">
        <option value="50">最近 50 期</option>
        <option value="100">最近 100 期</option>
        <option value="200" selected>最近 200 期</option>
        <option value="500">最近 500 期</option>
      </select>
    </div>
    <div class="section-title" id="score-front-title">前区</div>
    <div id="score-front-grid" class="num-grid"></div>
    <div class="section-title" id="score-back-title">后区</div>
    <div id="score-back-grid" class="num-grid"></div>
    <div class="row">
      <button onclick="scoreAction()">评分</button>
      <button class="secondary" onclick="scoreSave()">保存到我的记录</button>
      <span id="score-status" style="font-size:12px;color:#94a3b8"></span>
    </div>
    <div class="result" id="score-result">点击"评分"开始...</div>
  </div>

  <!-- Tab 3: history -->
  <div class="panel hidden" id="panel-history">
    <div class="stats" id="history-stats"></div>
    <table class="history-table" id="history-table">
      <thead><tr>
        <th>时间</th><th>彩种</th><th>选号</th><th>期望净收益</th><th>实际命中</th><th>奖金</th><th>备注</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="disclaimer">
    ⚠️ <b>数学上必亏:</b> 大乐透期望净收益 -0.99 元/注, 双色球 -0.81 元/注。
    凯利公式 f*=0 — 期望你"不下注"。这是工具的诚实结论，不是 bug。<br>
    <b>号码频率 ≠ 未来开奖:</b> 历史开奖号码不会改变下一期的随机分布 (DrawScope DISCLAIMER)。
  </div>
</div>

<script>
// ============================================================
// 前端状态
// ============================================================
const GAMES = {
  dlt: { front_range: 35, front_count: 5, back_range: 12, back_count: 2,
         front_label: '前区', back_label: '后区', period_hint: '26119' },
  ssq: { front_range: 33, front_count: 6, back_range: 16, back_count: 1,
         front_label: '红球', back_label: '蓝球', period_hint: '2026119' },
};

let currentTab = 'check';
let lastCheckResult = null;
let lastScoreResult = null;

// 初始化号码网格
function buildGrids() {
  for (const tabId of ['check', 'score']) {
    const game = GAMES[document.getElementById(`${tabId}-game`).value];
    const renderNumGrid = (containerId, range, count) => {
      const grid = document.getElementById(containerId);
      grid.innerHTML = '';
      for (let n = 1; n <= range; n++) {
        const btn = document.createElement('div');
        btn.className = 'num-btn';
        btn.dataset.num = n;
        btn.textContent = n;
        btn.onclick = () => {
          const selected = grid.querySelectorAll('.selected').length;
          const wasSel = btn.classList.contains('selected');
          if (!wasSel && selected >= count) {
            // 已选满, 自动去掉最前一个
            const first = grid.querySelector('.selected');
            first.classList.remove('selected');
          }
          btn.classList.toggle('selected');
          updateGridsState(tabId);
        };
        grid.appendChild(btn);
      }
    };
    renderNumGrid(`${tabId}-front-grid`, game.front_range, game.front_count);
    renderNumGrid(`${tabId}-back-grid`, game.back_range, game.back_count);
    document.getElementById(`${tabId}-front-title`).textContent =
        `${game.front_label} (选 ${game.front_count} 个, 1-${game.front_range})`;
    document.getElementById(`${tabId}-back-title`).textContent =
        `${game.back_label} (选 ${game.back_count} 个, 1-${game.back_range})`;
  }
  updateGridsState('check');
  updateGridsState('score');
  document.getElementById('check-period').placeholder = GAMES.dlt.period_hint;
}

function updateGridsState(tabId) {
  const game = GAMES[document.getElementById(`${tabId}-game`).value];
  for (const part of ['front', 'back']) {
    const selected = document.querySelectorAll(`#${tabId}-${part}-grid .selected`).length;
    const needed = part === 'front' ? game.front_count : game.back_count;
    // 可视化: 选满后变色
  }
}

// 切换彩种时重建网格
document.getElementById('check-game').addEventListener('change', buildGrids);
document.getElementById('score-game').addEventListener('change', buildGrids);
function scoreGameChange() { /* buildGrids 已经绑在 change */ }

// Tab 切换
document.querySelectorAll('.tab').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    const tab = btn.dataset.tab;
    document.querySelectorAll('.panel').forEach(p => p.classList.add('hidden'));
    document.getElementById(`panel-${tab}`).classList.remove('hidden');
    currentTab = tab;
    if (tab === 'history') loadHistory();
  };
});

// 选号提取
function getSelected(tabId) {
  const game = GAMES[document.getElementById(`${tabId}-game`).value];
  const front = [...document.querySelectorAll(`#${tabId}-front-grid .selected`)]
                  .map(e => +e.dataset.num).sort((a, b) => a - b);
  const back = [...document.querySelectorAll(`#${tabId}-back-grid .selected`)]
                  .map(e => +e.dataset.num).sort((a, b) => a - b);
  return { game: game, front, back };
}

// ============================================================
// API 调用
// ============================================================
async function api(action, params) {
  const resp = await fetch(`/api/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

// 渲染 AssResult 为 HTML
function renderResult(r) {
  const exp = r.expected || {};
  const hh = r.historical_hit;
  let html = `<b>选号:</b> 前 ${r.pick.front} / 后 ${r.pick.back}<br>`;
  html += `<b>期望奖金:</b> ${exp.prize_per_bet.toFixed(4)} 元/注 | `;
  html += `<b>净收益:</b> <span class="${exp.net_per_bet < 0 ? 'miss' : 'hit'}">${exp.net_per_bet >= 0 ? '+' : ''}${exp.net_per_bet.toFixed(4)}</span> 元/注<br>`;
  html += `<b>凯利 f*:</b> ${exp.kelly.toFixed(3)} | `;
  html += `<b>一等奖概率:</b> ${exp.first_prize_odds}<br>`;
  html += `<b>建议:</b> ${r.recommendation} ${r.verdict_label}<br>`;

  if (hh) {
    html += `<br><b style="color:#fbbf24">--- 历史反查 ---</b><br>`;
    html += `<b>期号 ${hh.period} (${hh.draw_date || ''})</b> 开奖: 前 ${JSON.parse(JSON.stringify(r.pick.front)).constructor === Array ? '' : ''}`;
    // 注: actual_draw 在 result 里是 {period, draw_date, front, back} 但被 to_dict 嵌进 historical_hit 里
    // 为了清晰, 单独显示
    html += `<br><b>命中:</b> <span class="${hh.win_money > 0 ? 'hit' : 'miss'}">${hh.hit_prize}</span>`;
    html += `  前${hh.hit_count['前区命中']}/后${hh.hit_count['后区命中']} | `;
    html += `<b>奖金:</b> ${hh.win_money.toLocaleString()} 元<br>`;
  }

  if (r.algo_scores) {
    html += `<br><b style="color:#fbbf24">--- 7 算法百分位 ---</b><br>`;
    const picks = r.pick.front.concat(r.pick.back);
    const sorted = [...picks].sort((a, b) => a - b);
    html += '号码: ';
    for (const n of sorted) {
      const s = r.avg_score[n.toString()] ?? 50;
      const cls = s >= 70 ? 'hot' : (s < 30 ? 'cold' : '');
      html += `<span class="pill ${cls}">${n}=${Math.round(s)}</span>`;
    }
    html += '<br>';
    html += `<b>热号 (≥70):</b> ${r.algo_scores && picks.filter(n => (r.avg_score[n.toString()] ?? 50) >= 70).join(', ') || '无'}<br>`;
    html += `<b>冷号 (<30):</b> ${picks.filter(n => (r.avg_score[n.toString()] ?? 50) < 30).join(', ') || '无'}<br>`;
  }

  if (r.warnings) {
    html += `<br><b style="color:#fbbf24">--- 风险提示 ---</b><br>`;
    for (const w of r.warnings) {
      html += `<span class="warning">!</span> ${w}<br>`;
    }
  }
  return html;
}

async function checkAction() {
  const sel = getSelected('check');
  const period = document.getElementById('check-period').value.trim();
  if (!period) { alert('请输入期号'); return; }
  if (sel.front.length !== sel.game.front_count || sel.back.length !== sel.game.back_count) {
    alert(`需选 ${sel.game.front_count} 个前区 + ${sel.game.back_count} 个后区`);
    return;
  }
  document.getElementById('check-status').textContent = '查询中...';
  try {
    const r = await api('check', {
      game: document.getElementById('check-game').value,
      period: period,
      front: sel.front,
      back: sel.back,
    });
    lastCheckResult = r;
    document.getElementById('check-result').innerHTML = renderResult(r);
    document.getElementById('check-status').textContent = '✓ 完成';
  } catch (e) {
    document.getElementById('check-status').textContent = `✗ ${e.message}`;
    document.getElementById('check-result').innerHTML = `<span class="alert">错误: ${e.message}</span>`;
  }
}

async function checkSave() {
  if (!lastCheckResult) { alert('请先验证'); return; }
  try {
    await api('save', { result: lastCheckResult, note: 'web-check' });
    document.getElementById('check-status').textContent = '✓ 已保存';
  } catch (e) {
    document.getElementById('check-status').textContent = `✗ ${e.message}`;
  }
}

async function scoreAction() {
  const sel = getSelected('score');
  if (sel.front.length !== sel.game.front_count || sel.back.length !== sel.game.back_count) {
    alert(`需选 ${sel.game.front_count} 个前区 + ${sel.game.back_count} 个后区`);
    return;
  }
  document.getElementById('score-status').textContent = '计算中...';
  try {
    const r = await api('score', {
      game: document.getElementById('score-game').value,
      front: sel.front,
      back: sel.back,
      window_n: parseInt(document.getElementById('score-window').value),
    });
    lastScoreResult = r;
    document.getElementById('score-result').innerHTML = renderResult(r);
    document.getElementById('score-status').textContent = '✓ 完成';
  } catch (e) {
    document.getElementById('score-status').textContent = `✗ ${e.message}`;
    document.getElementById('score-result').innerHTML = `<span class="alert">错误: ${e.message}</span>`;
  }
}

async function scoreSave() {
  if (!lastScoreResult) { alert('请先评分'); return; }
  try {
    await api('save', { result: lastScoreResult, note: 'web-score' });
    document.getElementById('score-status').textContent = '✓ 已保存';
  } catch (e) {
    document.getElementById('score-status').textContent = `✗ ${e.message}`;
  }
}

async function loadHistory() {
  const data = await api('history', {});
  const stats = data.stats || {};
  document.getElementById('history-stats').innerHTML = `
    <div class="stat"><div class="label">测评次数</div><div class="value">${stats.count || 0}</div></div>
    <div class="stat"><div class="label">命中</div><div class="value hit">${stats.hits || 0}</div></div>
    <div class="stat"><div class="label">注金</div><div class="value">${(stats.total_stake || 0).toFixed(0)}</div></div>
    <div class="stat"><div class="label">奖金</div><div class="value hit">${(stats.total_win || 0).toFixed(0)}</div></div>
    <div class="stat"><div class="label">净收益</div>
      <div class="value ${(stats.net_profit || 0) >= 0 ? 'hit' : 'miss'}">${(stats.net_profit || 0) >= 0 ? '+' : ''}${(stats.net_profit || 0).toFixed(0)}</div></div>
  `;
  const tbody = document.querySelector('#history-table tbody');
  tbody.innerHTML = '';
  for (const r of (data.records || [])) {
    const tr = document.createElement('tr');
    const tr_front = r.pick.front.join(',');
    const tr_back = r.pick.back.join(',');
    const exp_net = r.expected ? r.expected.net_per_bet : 0;
    const hh = r.historical_hit;
    tr.innerHTML = `
      <td>${(r.timestamp || '').substring(0, 19)}</td>
      <td>${r.game}</td>
      <td>${tr_front} / ${tr_back}</td>
      <td><span class="${exp_net < 0 ? 'miss' : 'hit'}">${exp_net.toFixed(2)}</span></td>
      <td>${hh ? hh.hit_prize : '-'}</td>
      <td>${hh ? hh.win_money.toLocaleString() : '-'}</td>
      <td>${r.note || ''}</td>
    `;
    tbody.appendChild(tr);
  }
}

buildGrids();
</script>
</body>
</html>
"""


# ============================================================
# API 路由
# ============================================================
@app.route('/')
def index():
    return render_template_string(INDEX_HTML)


@app.route('/api/check', methods=['POST'])
def api_check():
    try:
        body = request.get_json()
        game = body['game']
        period = body['period']
        front = list(map(int, body['front']))
        back = list(map(int, body['back']))
        actual, history = DataSnapshot.from_period(game, period)
        advisor = PickAdvisor(game)
        result = advisor.assess(Pick(front=front, back=back),
                                period=period, actual_draw=actual, recent_history=history)
        return jsonify({'ok': True, 'result': result.to_dict()})
    except KeyError as e:
        return jsonify({'ok': False, 'error': f'缺少字段: {e}'}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/score', methods=['POST'])
def api_score():
    try:
        body = request.get_json()
        game = body['game']
        front = list(map(int, body['front']))
        back = list(map(int, body['back']))
        window_n = int(body.get('window_n', 200))
        history = DataSnapshot.latest_history(game, n=window_n)
        advisor = PickAdvisor(game)
        result = advisor.assess(Pick(front=front, back=back),
                                period=f'(window {window_n})',
                                recent_history=history)
        return jsonify({'ok': True, 'result': result.to_dict()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/history', methods=['POST'])
def api_history():
    try:
        h = PickHistory(HISTORY_PATH)
        return jsonify({'ok': True, 'stats': h.stats(), 'records': h.records[-50:]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/save', methods=['POST'])
def api_save():
    try:
        body = request.get_json()
        result_dict = body['result']
        note = body.get('note', '')
        # 重建 AssessResult 来 add (web 传过来的是 dict, 再 PickAdvisor 重建一次)
        # 直接重算即可 (因为 web 上点保存时已经算过)
        # 简化: 把 dict 转回 AssessResult-like 构造
        from data.pick_advisor import AssessResult
        pick = result_dict['pick']
        result = AssessResult(
            pick=Pick(front=pick['front'], back=pick['back'],
                      label=pick.get('label', ''), price=pick.get('price', 2.0)),
            game=result_dict.get('game', 'dlt'),
            period=result_dict.get('period'),
            expected_prize=result_dict['expected']['prize_per_bet'],
            expected_net=result_dict['expected']['net_per_bet'],
            kelly_fraction=result_dict['expected']['kelly'],
            first_prize_odds=0,
            ticket_price=result_dict['expected']['ticket_price'],
        )
        if result_dict.get('historical_hit'):
            hh = result_dict['historical_hit']
            result.actual_draw = {'period': hh.get('period'), 'draw_date': hh.get('draw_date')}
            result.hit_prize = hh.get('hit_prize', '-')
            result.hit_count = hh.get('hit_count', {})
            result.win_money = hh.get('win_money', 0)
        if result_dict.get('algo_scores'):
            result.algo_scores = result_dict['algo_scores']
        if result_dict.get('avg_score'):
            result.avg_score = {int(k): v for k, v in result_dict['avg_score'].items()}
        # hot/cold 已存到 result_dict.warnings 之外的字段 — 简化: 直接保存 dict
        PickHistory(HISTORY_PATH).add(result, note=note)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/games')
def api_games():
    return jsonify({'ok': True, 'games': [{
        'code': g.code, 'name': g.name,
        'front_range': g.front_range, 'front_count': g.front_count,
        'back_range': g.back_range, 'back_count': g.back_count,
    } for g in [get_game(c) for c in list_games()]]})


# ============================================================
# Main
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description='号码实战评估器 Web GUI')
    parser.add_argument('--host', default='127.0.0.1', help='监听地址 (默认 127.0.0.1)')
    parser.add_argument('--port', type=int, default=9876, help='监听端口 (默认 9876)')
    parser.add_argument('--debug', action='store_true', help='启用 Flask debug 模式')
    args = parser.parse_args()

    print(f'\n  🎰 号码实战评估器 Web GUI')
    print(f'  📍 浏览器打开:  http://{args.host}:{args.port}/')
    print(f'  📂 历史记录:    {HISTORY_PATH}')
    print(f'  数据库源:      data-raw/lottery.db')
    print()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
