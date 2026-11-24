"""
实战闭环 · 账本配对键测试 (v3.3.1)
===================================
★ 背景:
  存档里期号是 5 位 ('26133'), 账本里是 7 位 ('2026133') —— 
  之前直接比字符串, **永远匹配不上** → 每跑一次 verify 就把同一期
  **重复结算一次**, 战绩汇总的投入/返奖被翻倍污染。
  (实测: 26133 被核对了 2 次, 总投入显示 3360 元, 实际只有 1680 元)

覆盖:
  T1 5 位与 7 位期号规范化后配对键相同
  T2 dedup_ledger 去掉重复结算, 只留第一条
  T3 同一期不同 ts (多套方案) → **不能**去重
  T4 不同期同 ts → 不能去重
  T5 规范化后归档/账本能互相对上
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.verify_live_picks import _key, dedup_ledger


def test_note_1_period_format_normalized():
    a = {'target_period': '26133', 'ts': '2026-11-19T19:50:22'}
    b = {'target_period': '2026133', 'ts': '2026-11-19T19:50:22'}
    assert _key(a) == _key(b)
    assert _key(a)[0] == '2026133'


def test_note_2_dedup_removes_duplicate_settlement():
    rec = {'target_period': '26133', 'ts': 'T1', 'cost': 1680.0}
    rec2 = {'target_period': '2026133', 'ts': 'T1', 'cost': 1680.0}
    out = dedup_ledger([rec, rec2])
    assert len(out) == 1
    assert out[0]['cost'] == 1680.0


def test_note_3_same_period_different_ts_kept():
    """同一期并存多套方案 (A/B/C) → 都要结算, 不能去重"""
    out = dedup_ledger([
        {'target_period': '26135', 'ts': 'T1'},
        {'target_period': '26135', 'ts': 'T2'},
        {'target_period': '26135', 'ts': 'T3'},
    ])
    assert len(out) == 3


def test_note_4_different_period_same_ts_kept():
    out = dedup_ledger([
        {'target_period': '26134', 'ts': 'T1'},
        {'target_period': '26135', 'ts': 'T1'},
    ])
    assert len(out) == 2


def test_note_5_archive_and_ledger_match():
    """存档 (5位) 与账本 (7位) 必须能配对上"""
    archive = {'target_period': '26135', 'ts': '2026-11-24T16:59:11'}
    ledger = {'target_period': '2026135', 'ts': '2026-11-24T16:59:11'}
    assert _key(archive) == _key(ledger)
    # 已经结算过的就不该再进 pending
    done = {_key(ledger)}
    assert _key(archive) in done
