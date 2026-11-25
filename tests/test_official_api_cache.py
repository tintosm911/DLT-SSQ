"""
官方 API 缓存陈旧守卫 (v3.3.2)
================================
★ 背景 (实战踩到):
  2026-11-25 大乐透 26135 开奖后, verify_live_picks.py 一直报
  "暂无新开奖可核对" —— 但开奖明明已经出了。

  根因: 体彩官方 API 对**特定 pageSize 会返回过期缓存**。实测:
      pageSize = 1/2/3/5/6/30/100 → 最新 2026135  ✅
      pageSize = 8/10            → 最新 2026134  ❌ (陈旧)
  而 verify_live_picks.py 原本固定用 pageSize=8 → **正好踩中**。
  这个 bug 极阴险: 不报错, 只是让"实战闭环"永远差最后一步。

★ 修法:
  先用 pageSize=1 确认最新期号 (这条路径的缓存总是新鲜的),
  再用不同 pageSize 拉历史, 挑一个**含最新期号**的返回。

覆盖:
  T1 候选里有新鲜的 → 返回新鲜的
  T2 最新期号只在其中一个候选里 → 正确挑中
  T3 全部候选都陈旧 → 返回 None (由调用方重试)
  T4 空候选 → None
  T5 遍历顺序不影响结果 (小的 pageSize 优先但要真的新鲜)
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

from scripts.verify_live_picks import select_fresh_map


def test_note_1_picks_fresh_candidate():
    stale = {'2026134': ('2026-11-23', [1], [1])}
    fresh = {'2026135': ('2026-11-25', [2], [2]),
             '2026134': ('2026-11-23', [1], [1])}
    got = select_fresh_map({8: stale, 30: fresh}, '2026135')
    assert got is fresh
    assert '2026135' in got


def test_note_2_finds_the_one_fresh():
    cands = {
        8: {'2026134': ('d', [1], [1])},
        10: {'2026134': ('d', [1], [1])},
        100: {'2026135': ('d', [1], [1])},
    }
    got = select_fresh_map(cands, '2026135')
    assert got is cands[100]


def test_note_3_all_stale_returns_none():
    cands = {8: {'2026134': ('d', [1], [1])},
             10: {'2026134': ('d', [1], [1])}}
    assert select_fresh_map(cands, '2026135') is None


def test_note_4_empty_returns_none():
    assert select_fresh_map({}, '2026135') is None
    assert select_fresh_map({8: {}, 30: {}}, '2026135') is None


def test_note_5_order_independent():
    """先遍历到陈旧的不影响 —— 必须继续找下去"""
    cands = {
        8: {'2026134': ('d', [1], [1])},
        30: {'2026135': ('d', [1], [1])},
    }
    assert select_fresh_map(cands, '2026135') is cands[30]
    # 反转字典顺序也要拿到同一份
    cands2 = {30: cands[30], 8: cands[8]}
    assert select_fresh_map(cands2, '2026135') is cands[30]


def test_note_6_real_api_smoke():
    """真调一次官方 API: 返回的 map 必须含最新期号 (不许拿到陈旧缓存)

    ★ 这是唯一能真正防住"官方缓存异常"的测试 —— 纯函数测试只能测选择逻辑,
      测不了 API 到底返回什么。
    """
    import urllib.error
    from scripts.verify_live_picks import official_dlt_map
    try:
        m = official_dlt_map(8)
    except urllib.error.URLError as e:
        print(f'  [skip] 网络不可达: {e}')
        return
    assert m, '官方 API 返回空'
    newest = max(m)
    # 再用 pageSize=1 确认
    from scripts.verify_live_picks import _fetch_dlt
    one = _fetch_dlt(1)
    if one:
        assert max(one) in m, (
            f'拿到的 map 缺最新期号 {max(one)} (map 最新 {newest}) '
            f'→ API 缓存陈旧')
