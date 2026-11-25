"""
实买声明 · 实买/演练分离测试 (v3.3.2)
=====================================
★ 背景:
  存档 data-raw/live_picks.jsonl 里同一期并存两类方案:
    - **实买**: 用户真金白银买的 (A版/B版/C版, 合计 252 元)
    - **演练**: 优化器自动生成的演练方案 (840 注 / 84 注, 未购票)
  结算后若混在一起汇总, "总投入"会显示 2100 元, 而不是真实的 252 元 ——
  这会把用户的真实账户说成另一个数。

★ 设计:
  不在存档里加字段 (存档必须字节级不可变, 它是"事前定死"的证据),
  而是用**独立声明文件** data-raw/live_picks_purchased.jsonl 记录实买事实。

覆盖:
  T1 声明能被正确读取, 期号规范化 (5 位/7 位等价)
  T2 实买方案进实买组, 未声明的进演练组
  T3 声明缺失/空文件 → 空集合, 不崩
  T4 账本期号与声明期号位数不同也能配上
  T5 同一期多套实买方案 → 都在实买组, 一个都不能漏
"""
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.verify_live_picks as vlp


def _write_decl(tmp_path, rows):
    f = tmp_path / 'purchased.jsonl'
    f.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
                 encoding='utf-8')
    return f


def test_note_1_reads_and_normalizes_period(tmp_path, monkeypatch):
    f = _write_decl(tmp_path, [
        {'target_period': '26135', 'label': 'A版-90元-后区6个'},
        {'target_period': '2026135', 'label': 'B版-72元-后区9个'},
    ])
    monkeypatch.setattr(vlp, 'PURCHASED', f)
    got = vlp.load_purchased()
    assert ('2026135', 'A版-90元-后区6个') in got
    assert ('2026135', 'B版-72元-后区9个') in got
    assert len(got) == 2


def test_note_2_split_real_vs_paper(tmp_path, monkeypatch):
    f = _write_decl(tmp_path, [
        {'target_period': '2026135', 'label': 'A版-90元-后区6个'},
    ])
    monkeypatch.setattr(vlp, 'PURCHASED', f)
    purchased = vlp.load_purchased()
    ledger = [
        {'target_period': '2026135', 'label': 'A版-90元-后区6个'},
        {'target_period': '2026135', 'label': '方案C-1680元-最大中奖率'},
    ]
    real, paper = vlp.split_real_paper(ledger, purchased)
    assert len(real) == 1 and len(paper) == 1
    assert real[0]['label'] == 'A版-90元-后区6个'
    assert paper[0]['label'] == '方案C-1680元-最大中奖率'


def test_note_3_missing_or_empty_file(tmp_path, monkeypatch):
    monkeypatch.setattr(vlp, 'PURCHASED', tmp_path / 'nope.jsonl')
    assert vlp.load_purchased() == set()

    empty = tmp_path / 'empty.jsonl'
    empty.write_text('', encoding='utf-8')
    monkeypatch.setattr(vlp, 'PURCHASED', empty)
    assert vlp.load_purchased() == set()


def test_note_4_period_digits_differ_still_matches(tmp_path, monkeypatch):
    """声明写 5 位, 账本写 7 位 → 仍要配上"""
    f = _write_decl(tmp_path, [
        {'target_period': '26135', 'label': 'C版-90元-后区12个'},
    ])
    monkeypatch.setattr(vlp, 'PURCHASED', f)
    purchased = vlp.load_purchased()
    ledger = [{'target_period': '2026135', 'label': 'C版-90元-后区12个'}]
    real, paper = vlp.split_real_paper(ledger, purchased)
    assert len(real) == 1
    assert paper == []


def test_note_5_multiple_real_schemes_same_period(tmp_path, monkeypatch):
    """同一期 3 套实买方案 → 一个都不能漏"""
    labels = ['A版-90元-后区6个', 'B版-72元-后区9个', 'C版-90元-后区12个']
    f = _write_decl(tmp_path, [
        {'target_period': '2026135', 'label': lb} for lb in labels
    ])
    monkeypatch.setattr(vlp, 'PURCHASED', f)
    purchased = vlp.load_purchased()
    ledger = [
        {'target_period': '2026135', 'label': 'A版-90元-后区6个', 'cost': 90.0},
        {'target_period': '2026135', 'label': 'B版-72元-后区9个', 'cost': 72.0},
        {'target_period': '2026135', 'label': 'C版-90元-后区12个', 'cost': 90.0},
    ]
    real, paper = vlp.split_real_paper(ledger, purchased)
    assert len(real) == 3
    assert paper == []
    # 实买总额 = 90 + 72 + 90
    assert sum(r['cost'] for r in real) == 252.0
