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
  .dt-hint { background: #0f172a; border: 1px solid #1e293b; border-radius: 4px;
             padding: 8px 12px; font-size: 12px; color: #94a3b8; margin: 8px 0 12px 0; }
  .dt-grid .num-btn.dan { background: #dc2626; color: #fff; border-color: #fca5a5;
                          box-shadow: 0 0 0 2px #7f1d1d; }
  .dt-grid .num-btn.tuo { background: #1d4ed8; color: #fff; border-color: #93c5fd; }
  .dt-grid .num-btn.dan:hover { background: #b91c1c; }
  .dt-grid .num-btn.tuo:hover { background: #1e40af; }
  .dt-legend { display:flex; gap:14px; align-items:center; font-size:12px;
               color:#94a3b8; margin:4px 0 8px 0; }
  .dt-legend span.k { display:inline-block; padding:1px 8px; border-radius:3px;
                      margin-right:4px; font-size:11px; }
  .k-dan { background:#dc2626; color:#fff; }
  .k-tuo { background:#1d4ed8; color:#fff; }
  .k-none { background:#0f172a; border:1px solid #334155; }
  .card-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
               gap:10px; margin:10px 0; }
  .mini-card { background:#0f172a; border:1px solid #1e293b; border-radius:6px;
               padding:10px 12px; }
  .mini-card .lbl { font-size:11px; color:#94a3b8; }
  .mini-card .val { font-size:19px; font-weight:bold; margin-top:2px; }
  .val.neg { color:#f87171; }
  .val.pos { color:#4ade80; }
  .section-title.tight { margin-top:16px; }
</style>
</head>
<body>
<div class="container">
  <h1>🎰 号码实战评估器</h1>
  <div class="subtitle">基于真实历史数据 — 大乐透 / 双色球</div>

  <div class="tabs">
    <button class="tab active" data-tab="check">① 历史期验证</button>
    <button class="tab" data-tab="score">② 算法评分</button>
    <button class="tab" data-tab="dantuo">③ 胆拖分析</button>
    <button class="tab" data-tab="history">④ 历史记录</button>
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

  <!-- Tab 3: 胆拖分析 -->
  <div class="panel hidden" id="panel-dantuo">
    <div class="row">
      <label>彩种:</label>
      <select id="dt-game" onchange="dtRebuild()">
        <option value="dlt">大乐透</option>
        <option value="ssq">双色球</option>
      </select>
      <label>模拟次数:</label>
      <select id="dt-draws">
        <option value="0">跳过模拟 (只算期望)</option>
        <option value="50000">5 万次</option>
        <option value="100000" selected>10 万次</option>
        <option value="200000">20 万次</option>
        <option value="500000">50 万次</option>
      </select>
      <button onclick="dtAnalyze()">开始分析</button>
      <span id="dt-status" style="font-size:12px;color:#94a3b8"></span>
    </div>

    <div class="dt-hint">
      胆码 = 必选号 (每注都含) &nbsp;|&nbsp; 拖码 = 备选号 (系统自动补足)
    </div>

    <div class="section-title" id="dt-front-title">前区 — 点击号码切换: 无 → 胆 → 拖</div>
    <div id="dt-front-grid" class="num-grid dt-grid"></div>
    <div class="section-title" id="dt-back-title">后区</div>
    <div id="dt-back-grid" class="num-grid dt-grid"></div>

    <div class="row" style="margin-top:12px">
      <button class="secondary" onclick="dtClear()">清空</button>
      <button class="secondary" onclick="dtFillExample()">填入示例 (70 注 / 140 元)</button>
    </div>

    <div class="result" id="dt-result">选好胆码和拖码后点"开始分析"</div>
  </div>

  <!-- Tab 4: history -->
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

// ============================================================
// Tab 3: 胆拖分析 (三态号码网格: 无 → 胆 → 拖 → 无)
// ============================================================
function dtRebuild() {
  const game = GAMES[document.getElementById('dt-game').value];
  const mk = (containerId, range) => {
    const grid = document.getElementById(containerId);
    grid.innerHTML = '';
    for (let n = 1; n <= range; n++) {
      const btn = document.createElement('div');
      btn.className = 'num-btn';
      btn.dataset.num = n;
      btn.dataset.state = 'none';
      btn.textContent = n;
      btn.onclick = () => {
        // 三态循环: none → dan → tuo → none
        const s = btn.dataset.state;
        const next = s === 'none' ? 'dan' : (s === 'dan' ? 'tuo' : 'none');
        btn.dataset.state = next;
        btn.classList.remove('dan', 'tuo');
        if (next !== 'none') btn.classList.add(next);
        dtUpdateHint();
      };
      grid.appendChild(btn);
    }
  };
  mk('dt-front-grid', game.front_range);
  mk('dt-back-grid', game.back_range);
  document.getElementById('dt-front-title').textContent =
    `${game.front_label} — 点击切换: 无 → 胆码 → 拖码`;
  document.getElementById('dt-back-title').textContent =
    `${game.back_label} — 点击切换: 无 → 胆码 → 拖码`;
  dtUpdateHint();
}

function dtCollect() {
  const collect = (containerId) => {
    const dan = [], tuo = [];
    document.querySelectorAll(`#${containerId} .num-btn`).forEach(b => {
      const n = +b.dataset.num;
      if (b.dataset.state === 'dan') dan.push(n);
      else if (b.dataset.state === 'tuo') tuo.push(n);
    });
    return { dan: dan.sort((a,b)=>a-b), tuo: tuo.sort((a,b)=>a-b) };
  };
  return { front: collect('dt-front-grid'), back: collect('dt-back-grid') };
}

function dtUpdateHint() {
  const c = dtCollect();
  const g = GAMES[document.getElementById('dt-game').value];
  const needF = g.front_count - c.front.dan.length;
  const needB = g.back_count - c.back.dan.length;
  const status = document.getElementById('dt-status');
  const bits = [];
  bits.push(`前区: ${c.front.dan.length} 胆 ${c.front.tuo.length} 拖 (还需从拖里补 ${needF})`);
  bits.push(`后区: ${c.back.dan.length} 胆 ${c.back.tuo.length} 拖 (还需 ${needB})`);
  if (needF < 0 || needB < 0) {
    status.innerHTML = '<span style="color:#f87171">胆码超过要求, 请减少</span>';
  } else if (c.front.dan.length + c.front.tuo.length === 0 &&
             c.back.dan.length + c.back.tuo.length === 0) {
    status.textContent = '';
  } else {
    status.textContent = bits.join(' | ');
  }
}

function dtClear() {
  document.querySelectorAll('#dt-front-grid .num-btn, #dt-back-grid .num-btn')
    .forEach(b => { b.dataset.state = 'none'; b.classList.remove('dan', 'tuo'); });
  document.getElementById('dt-result').innerHTML = '选好胆码和拖码后点"开始分析"';
  dtUpdateHint();
}

function dtFillExample() {
  dtClear();
  const game = document.getElementById('dt-game').value;
  const sets = game === 'dlt'
    ? { fd: [4, 9],   ft: [2, 7, 12, 22, 23, 29, 32], bd: [4],  bt: [5, 8] }
    : { fd: [1, 7],   ft: [5, 12, 19, 23, 28, 31],    bd: [9],  bt: [3, 15] };
  const mark = (gridId, nums, state) => {
    document.querySelectorAll(`#${gridId} .num-btn`).forEach(b => {
      if (nums.includes(+b.dataset.num)) {
        b.dataset.state = state;
        b.classList.remove('dan', 'tuo');
        b.classList.add(state);
      }
    });
  };
  mark('dt-front-grid', sets.fd, 'dan');
  mark('dt-front-grid', sets.ft, 'tuo');
  mark('dt-back-grid', sets.bd, 'dan');
  mark('dt-back-grid', sets.bt, 'tuo');
  dtUpdateHint();
}

async function dtAnalyze() {
  const c = dtCollect();
  const g = GAMES[document.getElementById('dt-game').value];
  if (c.front.dan.length + c.front.tuo.length === 0 &&
      c.back.dan.length + c.back.tuo.length === 0) {
    document.getElementById('dt-result').innerHTML =
      '<span class="alert">请先选胆码或拖码</span>';
    return;
  }
  const status = document.getElementById('dt-status');
  const draws = parseInt(document.getElementById('dt-draws').value);
  status.textContent = draws > 0 ? `模拟 ${draws.toLocaleString()} 次开奖中...` : '计算中...';
  const t0 = Date.now();
  try {
    const r = await api('dan-tuo', {
      game: document.getElementById('dt-game').value,
      front_dan: c.front.dan, front_tuo: c.front.tuo,
      back_dan: c.back.dan,  back_tuo: c.back.tuo,
      draws: draws,
      seed: 42,
    });
    const dt = ((Date.now() - t0) / 1000).toFixed(1);
    status.textContent = `✓ 完成 (${dt}s)`;
    document.getElementById('dt-result').innerHTML = dtRender(r);
  } catch (e) {
    status.textContent = '';
    document.getElementById('dt-result').innerHTML =
      `<span class="alert">错误: ${e.message}</span>`;
  }
}

function dtRender(r) {
  const t = r.tickets, e = r.expected, s = r.simulation;
  const fmt = n => (n < 0 ? '' : '+') + n.toFixed(2);
  let h = '';

  h += `<b>${r.game_name}</b> 胆拖分析<br>`;
  h += `<span style="color:#64748b">前胆 ${r.parse.front_dan.map(n=>String(n).padStart(2,'0')).join(' ') || '无'}`;
  h += ` | 前拖 ${r.parse.front_tuo.map(n=>String(n).padStart(2,'0')).join(' ') || '无'}`;
  h += ` | 后胆 ${r.parse.back_dan.map(n=>String(n).padStart(2,'0')).join(' ') || '无'}`;
  h += ` | 后拖 ${r.parse.back_tuo.map(n=>String(n).padStart(2,'0')).join(' ') || '无'}</span><br><br>`;

  h += `<b style="color:#fbbf24">【展开成多少注 / 花多少钱】</b><br>`;
  h += `前区: ${r.parse.front_dan.length} 胆 + 从 ${r.parse.front_tuo.length} 拖选 ${t.need_front} = C(${r.parse.front_tuo.length},${t.need_front}) = ${t.n_front_combos} 种<br>`;
  h += `后区: ${r.parse.back_dan.length} 胆 + 从 ${r.parse.back_tuo.length} 拖选 ${t.need_back} = C(${r.parse.back_tuo.length},${t.need_back}) = ${t.n_back_combos} 种<br>`;
  h += `合计: <b>${t.count} 注</b> · 花费 <b>${t.total_cost} 元</b><br><br>`;

  h += `<b style="color:#fbbf24">【期望值】</b><br>`;
  h += `单注期望净收益: ${fmt(e.per_bet_net)} 元<br>`;
  h += `<b>${t.count} 注期望净收益: <span class="${e.total_net < 0 ? 'miss' : 'hit'}">${fmt(e.total_net)} 元</span></b><br>`;
  h += `凯利最优 f* = <b class="${e.kelly <= 0 ? 'miss' : 'hit'}">${e.kelly.toFixed(3)}</b>`;
  if (e.kelly <= 0) h += ` (公式说: 不下注)`;
  h += `<br>`;
  h += `一等奖概率: 单注 ${e.first_prize_odds} → ${t.count} 注 <b>${e.cover_first_prize_odds}</b> (${e.cover_multiple}x 覆盖)<br>`;
  h += `理论最好情况: ${r.best_case.toLocaleString()} 元 (完美预测)<br><br>`;

  if (s && s.draws > 0) {
    h += `<b style="color:#fbbf24">【模拟 ${s.draws.toLocaleString()} 次开奖】</b><br>`;
    h += `<div class="card-grid">`;
    h += `<div class="mini-card"><div class="lbl">中奖概率</div><div class="val">${s.win_rate}%</div></div>`;
    h += `<div class="mini-card"><div class="lbl">一次不中</div><div class="val neg">${s.lose_rate}%</div></div>`;
    h += `<div class="mini-card"><div class="lbl">含大奖净收益</div><div class="val ${s.net_with_big >= 0 ? 'pos' : 'neg'}">${fmt(s.net_with_big)}</div></div>`;
    h += `<div class="mini-card"><div class="lbl">剔除大奖后</div><div class="val ${s.net_no_big >= 0 ? 'pos' : 'neg'}">${fmt(s.net_no_big)}</div></div>`;
    h += `</div>`;
    h += `常态平均返奖: ${s.mean_return_no_big.toFixed(2)} 元/期<br>`;
    h += `大奖命中: ${s.big_count} 次 (占 ${s.big_pct}%)<br>`;
    if (s.big_count > 0) {
      h += `<br><span class="warning">[!] 上面 ${fmt(s.net_with_big)} 元是被 ${s.big_count} 次大奖拉高的假象.</span><br>`;
      h += `<span class="warning">　　一次大奖能掩盖 ${s.draws.toLocaleString()} 次亏损. 这就是彩票最有害的地方.</span><br>`;
    }
    h += `最坏情况: ${s.worst_case} 元 (一次不中)<br><br>`;
    if (s.prizes && s.prizes.length) {
      h += `<b>各奖级命中次数</b><br>`;
      for (const p of s.prizes) {
        h += `<span class="pill">${p.label} × ${p.count.toLocaleString()}</span>`;
      }
      h += `<br><br>`;
    }
  }

  if (r.scores && r.scores.front) {
    h += `<b style="color:#fbbf24">【7 算法评分 (最近 300 期)】</b><br>`;
    const danSet = new Set((r.scores.dan || []).map(Number));
    const line = (obj, label) => {
      const nums = Object.keys(obj).map(Number).sort((a, b) => a - b);
      if (!nums.length) return '';
      let line = `${label}: `;
      for (const n of nums) {
        const sc = obj[String(n)];
        const tag = danSet.has(n) ? '胆' : '拖';
        const cls = sc >= 70 ? 'hot' : (sc < 30 ? 'cold' : '');
        line += `<span class="pill ${cls}">${String(n).padStart(2,'0')}(${tag})=${Math.round(sc)}</span>`;
      }
      return line + '<br>';
    };
    h += line(r.scores.front, '前区');
    h += line(r.scores.back, '后区');
  }

  h += `<br><b style="color:#fbbf24">【关键对比】</b><br>`;
  h += `两种方式都花 ${t.total_cost} 元, 买 ${t.count} 注, 期望净收益都是 ${fmt(e.total_net)} 元.<br>`;
  h += `胆拖唯一的实际效果: 覆盖更多组合 → 一等奖概率提高 ${t.count} 倍, 中奖率升到 ${s ? s.win_rate + '%' : 'N/A'}.<br>`;
  h += `期望值一点没变 —— 数学上完全等价.`;

  return h;
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
dtRebuild();
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


@app.route('/api/dan-tuo', methods=['POST'])
def api_dan_tuo():
    """
    胆拖分析 (Tab ④)
    body: {game, front_dan:[], front_tuo:[], back_dan:[], back_tuo:[],
           draws:int, seed:int}
    """
    try:
        from data.dan_tuo_core import analyze_dan_tuo
        body = request.get_json() or {}
        game = body.get('game', 'dlt')
        draws = int(body.get('draws', 200_000))
        seed = body.get('seed')
        seed = int(seed) if seed is not None else 42
        # 上限保护: Web 单次最多 50 万次, 免得把机器跑满
        draws = max(0, min(draws, 500_000))

        result = analyze_dan_tuo(
            game,
            body.get('front_dan', []),
            body.get('front_tuo', []),
            body.get('back_dan', []),
            body.get('back_tuo', []),
            n_draws=draws,
            seed=seed,
        )
        # numpy 标量转原生类型, 否则 jsonify 序列化失败
        return jsonify(_jsonable(result))
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


def _jsonable(obj):
    """把 numpy 标量 / ndarray / set 递归转成原生 Python 类型"""
    import numpy as _np
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, _np.integer):
        return int(obj)
    if isinstance(obj, _np.floating):
        return float(obj)
    if isinstance(obj, _np.bool_):
        return bool(obj)
    if isinstance(obj, _np.ndarray):
        return _jsonable(obj.tolist())
    return obj


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
