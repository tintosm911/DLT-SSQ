# AnySport 接入指南

## 🎯 概述

`AnySportSource` 是商业体育数据 API 的接入层，覆盖 1000+ 联赛（中超、中甲、英超、西甲等），提供实时比分、赛程、积分榜、赛前/滚球赔率等能力。

## 📋 套餐选择

| 套餐 | 价格 | 限额/小时 | 关键能力 |
|------|------|-----------|----------|
| **Free Trial** | $0 | 120 | 实时比分、联赛、赛程、积分、H2H |
| Basic | $99 | 2,000 | +球员、球队、射手榜、阵容、赛季 |
| **Pro** ⭐ | $199 | 10,000 | +赛前赔率（Value Bet 核心） |
| Pro Max | $399 | 20,000 | +实时赔率 + WebSocket |

**推荐**: 先用 Free Trial 验证流程，确认后升级到 Pro（$199/月）以启用赔率分析。

## 🚀 接入步骤

### 1. 注册账号
访问 https://dashboard.anysport.io/register，邮箱注册即可（免费试用无需绑卡）。

### 2. 获取 API Key
登录 dashboard，进入 "API Keys" 页面，复制你的 key。

### 3. 配置环境变量

**方式 A：`.env` 文件**
```bash
# 复制模板
cp .env.example .env

# 编辑 .env
ANYSPORT_API_KEY=sk_xxxxxxxxxxxxxxxxx
```

**方式 B：环境变量**
```bash
# Windows PowerShell
$env:ANYSPORT_API_KEY="sk_xxxxxxxxxxxxxxxxx"

# Linux/macOS
export ANYSPORT_API_KEY="sk_xxxxxxxxxxxxxxxxx"
```

### 4. 填充 League ID 映射

第一次接入时，需要从 `AnySport` 获取真实 league_id：

```python
import asyncio
from sports.data_sources.anysport import AnySportSource

async def discover():
    async with AnySportSource(api_key="YOUR_KEY") as src:
        leagues = await src.list_leagues()
        for lg in leagues:
            if "Premier League" in lg.get("name", "") or "英超" in lg.get("name", ""):
                print(f"EPL: league_id = {lg['league_id']}")

asyncio.run(discover())
```

把输出填入 `sports/data_sources/anysport.py` 的 `LEAGUE_ID_MAP`：

```python
LEAGUE_ID_MAP: Dict[str, str] = {
    "asl_xxxxx": "epl",
    "asl_xxxxx": "laliga",
    ...
}
```

## 💻 使用示例

```python
from sports.data_sources import DataSourceRouter

# 自动从环境变量读 ANYSPORT_API_KEY
router = DataSourceRouter()

# 列出所有数据源 (按优先级排序)
print(router.list_sources())
# ['anysport', 'mock']

# 获取英超 2024-2025 赛季所有比赛
matches = router.fetch_matches("epl", "2024-2025")
print(f"获取 {len(matches)} 场比赛")

# 获取赛前赔率 (Pro+)
match_ids = [m.match_id for m in matches[:10]]
odds = router.fetch_odds(match_ids)
print(f"获取 {len(odds)} 个赔率快照")
```

## 🔧 故障排除

### Q: `AnySport API key 无效或过期 (401)`
检查 `ANYSPORT_API_KEY` 环境变量是否设置正确。

### Q: `Rate limited (429)`
Free Trial 限制 120 calls/hour。等待下小时或升级套餐。

### Q: `已用满 120 calls/hour 配额`
程序逻辑会自动抛错。需要等待下一小时重置，或升级到 Basic/Pro。

### Q: `联赛 XXX 未配置 AnySport league_id`
按上面第 4 步的 `discover()` 方法获取 league_id 后填入 `LEAGUE_ID_MAP`。

## 🔄 自动降级机制

`DataSourceRouter` 按优先级尝试数据源：

1. **AnySport** (priority=5) - 主源
2. **Mock** (priority=999) - 最终 fallback

如果 AnySport 失败（无 key、配额用完、网络问题），自动降级到 Mock 数据源。这意味着即使没注册 AnySport 账号，本地演示也不会断。

## 📊 与现有架构对接

`AnySportSource` 输出的 `Match` 和 `Odds` 对象直接对接：

- ✅ Elo 评分 (`sports.elo.EloSystem`)
- ✅ Value Bet 识别 (`sports.strategies.find_value_bets`)
- ✅ 凯利仓位回测 (`sports.strategies.backtest_kelly`)
- ✅ 组合优化 (`sports.strategies.find_best_parlays`)

切换数据源后无需改任何业务逻辑代码。

## 🌐 真实场景用法

```python
# scripts/anyport_live.py - 实时监听未来 24 小时 Value Bet
import asyncio
from sports.data_sources import DataSourceRouter
from sports.strategies import find_value_bets

async def scan_today():
    router = DataSourceRouter()
    # 拉今天 + 明天所有未完赛
    matches = router.fetch_matches("epl", "2024-2025")
    upcoming = [m for m in matches if m.status == "scheduled"][:20]

    # 拉赔率
    match_ids = [m.match_id for m in upcoming]
    odds_list = router.fetch_odds(match_ids)

    # 用 Elo 预测 fair_prob
    from sports.elo import EloSystem
    elo = EloSystem()
    elo.run_season([m for m in matches if m.is_finished])
    fair_probs = {
        m.match_id: dict(zip([1, 0, -1], elo.predict(m.league, m.home_team, m.away_team)))
        for m in upcoming
    }

    # 找 Value Bet
    picks = find_value_bets(upcoming, odds_list, fair_probs, min_edge_pct=3.0)
    print(f"找到 {len(picks)} 个 Value Bet (edge ≥ 3%):")
    for p in picks[:5]:
        print(f"  {p.home_team} vs {p.away_team} | {p.selection_label} @ {p.odds:.2f} | edge {p.edge_pct:+.2f}%")

asyncio.run(scan_today())
```