"""
大乐透数字冷热度工具 - 主入口

用法:
  python main.py fetch              # 全量拉取历史数据
  python main.py update             # 增量更新
  python main.py analyze            # CLI 模式分析
  python main.py dashboard          # 启动 Web 仪表盘
  python main.py backtest           # 跑回测
"""
from __future__ import annotations
import sys
import os
# 强制 UTF-8 输出（解决 Windows GBK 终端乱码）
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import logging
from pathlib import Path
import yaml
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_config(path: Path = None) -> dict:
    """加载配置文件"""
    path = path or (PROJECT_ROOT / "config.yaml")
    if not path.exists():
        print(f"❌ 配置文件不存在: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
# 命令 1: fetch - 全量拉取
# ============================================================
def cmd_fetch(args):
    from data.games import get_game
    game = get_game(args.game)

    print("=" * 60)
    print(f"{game.name}历史数据全量拉取")
    print("=" * 60)

    if args.game == "ssq":
        from data.data_source import DataSourceRouter
        router = DataSourceRouter(game="ssq")
        # 双色球每次只能查单期，循环查
        from data.data_fetcher import Draw
        from data.sqlite_storage import SQLiteStorage
        from data.data_source import WelfareSSQSource

        source = WelfareSSQSource()
        latest = source.fetch_latest()
        if not latest:
            print("❌ 无法获取最新期号")
            return

        start = int(latest.period) - args.pages * 50  # 每页 50 期
        end = int(latest.period)

        # 批量拉取（每次一页 50 期）
        all_draws = []
        for page in range(args.pages):
            page_end = end - page * 50
            page_start = max(2003001, page_end - 49)
            if page_start > page_end:
                break
            draws = source._fetch_range(page_start, page_end)
            all_draws.extend(draws)
            print(f"  已拉取期号 {page_start}-{page_end}: {len(draws)} 期")

        if all_draws:
            storage = SQLiteStorage()
            storage.save_draws(all_draws, game="ssq")
            print(f"\n✅ 全量拉取完成: {len(all_draws)} 期")
    else:
        from data import DataFetcher
        fetcher = DataFetcher()
        draws = fetcher.fetch_all(max_pages=args.pages)
        fetcher.save_csv(draws, append=False)
        print(f"\n✅ 全量拉取完成: {len(draws)} 期")
        print(f"数据已保存到: {fetcher.cache_path}")


# ============================================================
# 命令 2: update - 增量更新
# ============================================================
def cmd_update(args):
    from data.games import get_game
    game = get_game(args.game)

    if args.game == "ssq":
        from data.data_source import WelfareSSQSource
        from data.sqlite_storage import SQLiteStorage

        source = WelfareSSQSource()
        latest_remote = source.fetch_latest()
        if not latest_remote:
            print("❌ 无法获取最新期号")
            return

        storage = SQLiteStorage()
        latest_local = storage.get_latest_period("ssq")

        if latest_local and int(latest_remote.period) <= int(latest_local):
            print(f"\n✅ 已是最新: 本地 {latest_local}, 远程 {latest_remote.period}")
            return

        # 拉取最新几期
        start = (int(latest_local) + 1) if latest_local else int(latest_remote.period) - 10
        new_draws = source._fetch_range(start, int(latest_remote.period))

        if new_draws:
            storage.save_draws(new_draws, game="ssq")
            print(f"\n✅ 增量更新完成: 新增 {len(new_draws)} 期")
        else:
            print("\n✅ 已是最新，无需更新")
    else:
        from data import DataFetcher
        fetcher = DataFetcher()
        new_draws = fetcher.fetch_incremental()

        if new_draws:
            fetcher.save_csv(new_draws, append=True)
            print(f"\n✅ 增量更新完成: 新增 {len(new_draws)} 期")
        else:
            print("\n✅ 已是最新，无需更新")


# ============================================================
# 命令 3: analyze - CLI 分析
# ============================================================
def cmd_analyze(args):
    from data import load_lottery_data
    from core import compute_all_heat_scores, classify_hot_cold
    from ui import CLIReport, HeatmapVisualizer

    config = load_config()

    CLIReport.header("大乐透数字冷热度分析")
    print(f"  配置文件: {PROJECT_ROOT / 'config.yaml'}")
    print(f"  数据: {PROJECT_ROOT / 'data-raw' / 'lottery_history.csv'}")

    df = load_lottery_data(game=args.game)
    print(f"  历史期数: {len(df)}")
    # 期号转数值后取 min/max（避免字符串字典序错乱）
    period_num = pd.to_numeric(df["period"], errors="coerce")
    print(f"  期号范围: {int(period_num.min())} ~ {int(period_num.max())}")

    # ---------- 前区 ----------
    CLIReport.section("前区 1-35 热度分析")
    front_cols = [c for c in df.columns if c.startswith("front_")]
    front_onehot = np.zeros((len(df), 35), dtype=np.int8)
    for col in front_cols:
        nums = df[col].values - 1
        np.put_along_axis(front_onehot, nums[:, None], 1, axis=1)

    front_scores = compute_all_heat_scores(front_onehot, 35)
    front_classification = classify_hot_cold(front_scores["composite"], config.get("thresholds"))

    CLIReport.hot_cold_summary(
        front_scores["composite"], list(range(1, 36)),
        "前区", config.get("thresholds")
    )
    CLIReport.all_algorithms_table(front_scores, list(range(1, 36)), top_n=12)

    # ---------- 后区 ----------
    CLIReport.section("后区 1-12 热度分析")
    back_cols = [c for c in df.columns if c.startswith("back_")]
    back_onehot = np.zeros((len(df), 12), dtype=np.int8)
    for col in back_cols:
        nums = df[col].values - 1
        np.put_along_axis(back_onehot, nums[:, None], 1, axis=1)

    back_scores = compute_all_heat_scores(back_onehot, 12)
    back_classification = classify_hot_cold(back_scores["composite"], config.get("thresholds"))

    CLIReport.hot_cold_summary(
        back_scores["composite"], list(range(1, 13)),
        "后区", config.get("thresholds")
    )
    CLIReport.all_algorithms_table(back_scores, list(range(1, 13)), top_n=6)

    # ---------- 遗漏值 ----------
    CLIReport.section("号码遗漏值分析")
    front_missing = compute_missing(front_onehot)
    back_missing = compute_missing(back_onehot)

    print(f"\n  【前区遗漏 Top 5】")
    front_idx = np.argsort(front_missing)[::-1][:5]
    for i in front_idx:
        print(f"    号码 {i+1:02d}: 遗漏 {int(front_missing[i])} 期")

    print(f"\n  【后区遗漏 Top 3】")
    back_idx = np.argsort(back_missing)[::-1][:3]
    for i in back_idx:
        print(f"    号码 {i+1:02d}: 遗漏 {int(back_missing[i])} 期")

    # ---------- 生成 HTML 图表 ----------
    if args.html:
        CLIReport.section("生成 HTML 图表")
        viz = HeatmapVisualizer()

        # 多窗口热度对比
        windows_config = config.get("windows", {})
        windows_to_test = []
        for w_name, w_val in windows_config.items():
            if isinstance(w_val, int) and w_val > 0:
                windows_to_test.append((w_name, w_val))
        windows_to_test.append(("全部", 0))

        # 算每个窗口下的综合热度
        scores_matrix = []
        window_labels = []
        for w_name, w_val in windows_to_test:
            if w_val > 0:
                data = front_onehot[-w_val:] if w_val < len(front_onehot) else front_onehot
            else:
                data = front_onehot
            scores_w = compute_all_heat_scores(data, 35)
            scores_matrix.append(scores_w["composite"])
            window_labels.append(f"{w_name}期" if w_val > 0 else "全部")

        scores_matrix = np.array(scores_matrix)

        heatmap_path = viz.render_heatmap(
            scores_matrix, list(range(1, 36)), window_labels,
            title="前区号码热度 - 多窗口对比", filename="heatmap_front.html"
        )
        print(f"  ✅ 热力图: {heatmap_path}")

        ranking_path = viz.render_number_ranking(
            front_scores["composite"], list(range(1, 36)),
            title="前区号码热度排行榜", filename="ranking_front.html"
        )
        print(f"  ✅ 排行榜: {ranking_path}")

        missing_path = viz.render_missing_chart(
            front_missing, list(range(1, 36)),
            title="前区号码遗漏值", filename="missing_front.html"
        )
        print(f"  ✅ 遗漏图: {missing_path}")

        dashboard_path = viz.render_dashboard(
            front_scores["composite"], back_scores["composite"], config,
            filename="dashboard.html"
        )
        print(f"  ✅ 综合仪表盘: {dashboard_path}")

    CLIReport.footer()


def compute_missing(onehot: np.ndarray) -> np.ndarray:
    """计算遗漏值"""
    n_periods = len(onehot)
    n_range = onehot.shape[1]
    missing = np.zeros(n_range, dtype=float)
    for num in range(n_range):
        col = onehot[::-1, num]  # 倒序
        idx = np.argmax(col)
        if col[idx] == 1:
            missing[num] = idx
        else:
            missing[num] = n_periods
    return missing


# ============================================================
# 命令 4: dashboard - Web 仪表盘
# ============================================================
def cmd_dashboard(args):
    from ui import create_app
    import uvicorn

    print("=" * 60)
    print("大乐透冷热度仪表盘 - Web 服务")
    print("=" * 60)
    print(f"\n访问地址: http://127.0.0.1:{args.port}")
    print("按 Ctrl+C 停止\n")

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


# ============================================================
# 命令 4.5: watch - 持续监控新开奖并推送
# ============================================================
def cmd_watch(args):
    """
    持续监控新开奖，开奖后自动推送
    用法:
      python main.py watch                           # 只打印到控制台
      python main.py watch --interval 60             # 每 60 秒检查一次
      python main.py watch --webhook <url>           # 同时 POST 到 webhook
      python main.py watch --dingtalk <url> --secret <key>  # 钉钉
      python main.py watch --wecom <url>             # 企业微信
      python main.py watch --log logs/push.log       # 同时写文件
    """
    from data import DataFetcher, PushNotifier

    print("=" * 60)
    print("大乐透开奖实时监控 - 推送服务")
    print("=" * 60)
    print(f"  监控间隔: {args.interval} 秒")
    print(f"  日志文件: {args.log or '（未设置）'}")

    # 构建推送渠道
    channels = [{"type": "console"}]
    if args.log:
        channels.append({"type": "file", "path": args.log})
    if args.webhook:
        channels.append({"type": "webhook", "webhook": args.webhook})
    if args.dingtalk:
        channels.append({
            "type": "dingtalk",
            "webhook": args.dingtalk,
            "secret": args.secret,
        })
    if args.wecom:
        channels.append({"type": "wecom", "webhook": args.wecom})

    notifier = PushNotifier(channels=channels)
    fetcher = DataFetcher()

    print(f"\n  启用渠道: {[c['type'] for c in channels]}")
    print(f"\n  按 Ctrl+C 停止监控\n")

    # 启动轮询
    fetcher.poll_for_new_draws(
        on_new_draw=notifier.notify,
        interval_seconds=args.interval,
    )


# ============================================================
# 命令 5: backtest - 回测
# ============================================================
def cmd_backtest(args):
    from data import load_lottery_data
    from analytics import Backtester

    config = load_config()
    df = load_lottery_data()

    print("=" * 60)
    print("大乐透策略回测")
    print("=" * 60)
    print(f"  历史数据: {len(df)} 期")

    bt_config = config.get("backtest", {})
    train_window = args.train or bt_config.get("train_window", 500)
    test_periods = args.test or bt_config.get("test_periods", 100)
    top_k = args.top_k or 12

    print(f"  训练窗口: {train_window} 期")
    print(f"  测试期数: {test_periods} 期")
    print(f"  Top K: {top_k}")

    for zone in ["front", "back"]:
        print(f"\n{'─' * 60}")
        print(f"  【{zone.upper()}】")
        print(f"{'─' * 60}")

        bt = Backtester(df, config, zone=zone)
        results = bt.run(train_window=train_window, test_periods=test_periods, top_k=top_k)
        summary = bt.summarize(results)

        print(f"  测试期数: {summary['n_periods']}")
        print(f"  平均命中: {summary['avg_hits']:.3f} / 期")
        print(f"  平均覆盖率: {summary['avg_coverage']:.3f}")
        print(f"  最大命中: {summary['max_hits']}")
        print(f"  理论随机覆盖率: {summary['theoretical_random_coverage']:.3f}")
        print(f"  命中分布: {summary['hit_rate_distribution']}")

    print("\n" + "=" * 60)


# ============================================================
# 命令 6: report-image - 生成 PNG 热度热力图 + 推送
# ============================================================
def cmd_report_image(args):
    """
    生成 PNG 热度热力图，可选推送到钉钉/企微
    用法:
      python main.py report-image                          # 只生成本地 PNG
      python main.py report-image --notify                 # 推送到所有启用渠道
      python main.py report-image --period 26117           # 指定期号标签
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    import numpy as np
    from data import load_lottery_data, DataFetcher, PushNotifier
    from core import compute_all_heat_scores
    from ui import ImageRenderer

    print("=" * 60)
    print("生成热度热力图 PNG")
    print("=" * 60)

    # 1. 拿最新期号
    fetcher = DataFetcher()
    latest = fetcher.get_latest_draw()
    period = args.period or (latest.period if latest else "latest")

    # 2. 加载历史 + 算热度
    df = load_lottery_data()
    front_cols = [c for c in df.columns if c.startswith("front_")]
    front_onehot = np.zeros((len(df), 35), dtype=np.int8)
    for col in front_cols:
        nums = df[col].values - 1
        np.put_along_axis(front_onehot, nums[:, None], 1, axis=1)
    front_scores = compute_all_heat_scores(front_onehot, 35)["composite"]

    back_cols = [c for c in df.columns if c.startswith("back_")]
    back_onehot = np.zeros((len(df), 12), dtype=np.int8)
    for col in back_cols:
        nums = df[col].values - 1
        np.put_along_axis(back_onehot, nums[:, None], 1, axis=1)
    back_scores = compute_all_heat_scores(back_onehot, 12)["composite"]

    # 3. 生成 PNG（如果是最新的，包含命中评估）
    renderer = ImageRenderer()

    if latest and args.hit_report:
        # 算命中评估并嵌入
        from data import HeatComparator
        cmp = HeatComparator()
        hr = cmp.evaluate_new_draw(latest)
        hit_dict = {
            "summary": hr.summary,
            "front_hit_count": hr.front_hit_count,
            "back_hit_count": hr.back_hit_count,
            "back_top_k": hr.back_top_k,
        }
        img_path = renderer.render_combined_png(
            front_scores, back_scores, hit_report=hit_dict, period=period,
            filename=f"report_{period}.png"
        )
    else:
        img_path = renderer.render_heatmap_png(
            front_scores, back_scores, period=period,
            filename=f"heatmap_{period}.png"
        )

    print(f"\n  [OK] PNG 已生成: {img_path}")
    print(f"       大小: {img_path.stat().st_size // 1024} KB")

    # 4. 推送
    if args.notify:
        print(f"\n  开始推送...")
        channels = [{"type": "console"}]
        if args.log:
            channels.append({"type": "file", "path": args.log})
        if args.webhook:
            channels.append({
                "type": "webhook",
                "webhook": args.webhook,
                "include_image": True,
            })
        if args.dingtalk:
            channels.append({
                "type": "dingtalk",
                "webhook": args.dingtalk,
                "secret": args.secret,
                "include_image": True,
            })
        if args.wecom:
            channels.append({
                "type": "wecom",
                "webhook": args.wecom,
                "include_image": True,
            })

        notifier = PushNotifier(channels=channels, enable_hit_report=False)

        if latest:
            notifier.notify(
                latest,
                is_first=False,
                image_path=str(img_path),
            )
            print(f"  [OK] 推送完成，渠道: {[c['type'] for c in channels]}")
        else:
            print("  [!] 无最新开奖数据，跳过推送")

    print("\n" + "=" * 60)


# ============================================================
# 命令 7: recommend - 号码组合推荐
# ============================================================
def cmd_recommend(args):
    """号码组合推荐"""
    from analytics import Recommender, DecisionLog
    from data.games import get_game
    game = get_game(args.game)

    print("=" * 70)
    print(f"  号码组合推荐 - {game.name}")
    print("=" * 70)

    r = Recommender(seed=args.seed, game=args.game)

    if args.strategy == "mixed":
        # 按 args.n 比例分配，确保总数 ≈ args.n
        # 例如 n=10: 守热 4 + 均衡 3 + 追冷 1 + 频次 2 = 10
        weights = {"top_heat": 0.4, "balanced": 0.3, "cold": 0.1, "most_freq": 0.2}
        tickets = r.recommend_mixed_portfolio(
            n_top_heat=max(1, int(args.n * weights["top_heat"])),
            n_balanced=max(1, int(args.n * weights["balanced"])),
            n_cold=max(1, int(args.n * weights["cold"])),
            n_most_freq=max(1, int(args.n * weights["most_freq"])),
        )
        # 微调：如果总注数不等于 args.n，补充到正确数量
        while len(tickets) < args.n:
            tickets.append(r.recommend_top_heat(n_tickets=1)[0])
        tickets = tickets[:args.n]
    elif args.strategy == "TopHeat":
        tickets = r.recommend_top_heat(n_tickets=args.n)
    elif args.strategy == "ColdRebound":
        tickets = r.recommend_cold_rebound(n_tickets=args.n)
    elif args.strategy == "Balanced":
        tickets = r.recommend_balanced(n_tickets=args.n)
    elif args.strategy == "MostFrequent":
        tickets = r.recommend_most_frequent(n_tickets=args.n)
    else:
        tickets = r.recommend_top_heat(n_tickets=args.n)

    # 重置 index
    for i, t in enumerate(tickets, 1):
        t.index = i

    r.print_recommendations(tickets)

    cost = len(tickets) * 2
    expected_net = cost * -0.495  # 每注期望净收益 -0.99 元（边际 49.5%）
    print(f"\n  总注数: {len(tickets)}")
    print(f"  总投入: {cost} 元")
    print(f"  期望净收益: {expected_net:.2f} 元（数学保证亏损 {abs(expected_net):.2f} 元）")

    if args.log:
        period = args.period or str(r.df["period"].iloc[-1])
        log = DecisionLog()
        count = log.log_recommendation(period, [t.to_dict() for t in tickets])
        print(f"\n  ✅ 已记录到决策日志: {count} 条（期号 {period}, 彩种 {game.code}）")

    print()


# ============================================================
# 命令 8: decision-stats - 决策日志统计
# ============================================================
def cmd_decision_stats(args):
    """决策日志统计"""
    from analytics import DecisionLog

    log = DecisionLog()
    if args.backfill:
        print("正在回填所有未开奖期...")
        filled = log.backfill_results()
        print(f"回填完成: {filled} 条\n")

    log.print_stats(last_n_periods=args.periods)


# ============================================================
# 命令 9: tests - 跑测试
# ============================================================
def cmd_tests(args):
    """跑 pytest 测试"""
    import subprocess
    cmd = ["python", "-m", "pytest", "tests/", "-v" if args.verbose else ""]
    cmd = [c for c in cmd if c]
    subprocess.run(cmd, cwd=PROJECT_ROOT)


# ============================================================
# 命令 10: migrate - CSV → SQLite 迁移
# ============================================================
def cmd_migrate(args):
    """从 CSV 迁移到 SQLite"""
    from data import SQLiteStorage

    storage = SQLiteStorage()
    if args.csv:
        n = storage.migrate_from_csv(Path(args.csv))
    else:
        n = storage.migrate_from_csv()

    print()
    print("=" * 60)
    print("  CSV → SQLite 迁移")
    print("=" * 60)
    print(f"  迁移记录数: {n}")
    print(f"  数据库: {storage.db_path}")

    health = storage.health_check()
    print(f"  当前总记录: {health['total_records']}")
    print(f"  数据库大小: {health['db_size_mb']} MB")
    print(f"  最新期号: {health['latest_period']}")
    print()


# ============================================================
# 命令 11: health - 健康检查
# ============================================================
def cmd_health(args):
    """健康检查"""
    # 复用 scripts/health_check.py 的逻辑
    from scripts.health_check import main as health_main
    import sys
    new_argv = ["health_check.py"]
    if args.auto_fix:
        new_argv.append("--auto-fix")
    if args.watch > 0:
        new_argv.extend(["--watch", str(args.watch)])
    if args.json:
        new_argv.append("--json")
    sys.argv = new_argv
    health_main()


# ============================================================
# 命令 0: games - 列出彩种
# ============================================================
def cmd_crawl(args):
    """
    多源采集 + 合并 + 导入 SQLite

    流程:
      1. zhcw.com 采集 (含真实开奖日期, 100 期)
      2. chart.ttzoushi.com 采集 (最新数据, 100 期)
      3. 合并两个源 (真实日期优先)
      4. 导入 lottery.db, 让 load_lottery_data() 端到端可用
    """
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent / "third_party"))

    games = ["dlt", "ssq"] if args.game == "all" else [args.game]
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    print("=" * 70)
    print(f"  多源采集  (sources: {', '.join(sources)})")
    print("=" * 70)

    for g in games:
        print(f"\n>>> 彩种: {g}")
        for src in sources:
            if src == "zhcw":
                mod = importlib.import_module("data.zhcw_fetcher")
                fn = getattr(mod, "collect", None)
                if fn:
                    fn(g)
            elif src == "ttz":
                mod = importlib.import_module("data.ttz_fetcher")
                fn = getattr(mod, "collect", None)
                if fn:
                    fn(g)
            elif src == "gh":
                # GitHub 开源数据集 (主力源, 提供全量历史 2937+3516 期)
                mod = importlib.import_module("data.github_fetcher")
                fn = getattr(mod, "collect", None) or getattr(mod, "fetch", None)
                if fn:
                    fn(g)
            else:
                print(f"  跳过未知源: {src}")

        if args.merge:
            from data.merge_sources import merge, validate as validate_merged
            print(f"\n--- 合并 ---")
            recs = merge(g, sources, verbose=True)
            validate_merged(g, recs)

        if args.import_db:
            from data.data_guard import guarded_import
            print(f"\n--- 导入 SQLite (带数据保护) ---")
            result = guarded_import(g, sources, verbose=True)
            if not result.ok:
                print(f"\n  ⚠️  {result.message}")
                if not args.force:
                    print(f"  已中止。确认要强制导入请加 --force")
                    continue
                print(f"  --force 已指定, 强制继续导入")
                from data.import_csv import import_sources
                import_sources(g, sources, verbose=True)

            from data.import_csv import verify
            verify(g)

    print("\n完成。下一步: python run_lab.py <game> 或 python main.py analyze")


def cmd_lab(args):
    """跑 12+1 步概率统计实验室 (含 Step 13 DrawScope)"""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "third_party"))
    from analytics.probability_lab import run_full_lab
    run_full_lab(game=args.game)


def cmd_games(args):
    """列出支持的彩种"""
    from data.games import GAMES

    print("=" * 60)
    print("  支持的彩种")
    print("=" * 60)

    for code, cfg in GAMES.items():
        print(f"\n  [{code}] {cfg.name}")
        if args.details:
            print(f"    前区: {cfg.front_count} 选 {cfg.front_range} ({cfg.front_label})")
            print(f"    后区: {cfg.back_count} 选 {cfg.back_range} ({cfg.back_label})")
            print(f"    单注价格: {cfg.ticket_price} 元")
            print(f"    总组合数: {cfg.total_combinations:,}")
            print(f"    一等奖概率: 1/{cfg.total_combinations:,}")

    print()


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="🎯 大乐透数字冷热度工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py fetch
  python main.py analyze --html
  python main.py dashboard --port 8765
  python main.py backtest --top-k 12
  python main.py recommend --strategy mixed --n 8 --log
  python main.py decision-stats --backfill --periods 50
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # games - 列出支持的彩种
    p_games = subparsers.add_parser("games", help="列出支持的彩种")
    p_games.add_argument("--details", "-d", action="store_true", help="显示详细信息")

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="全量拉取历史数据")
    p_fetch.add_argument("--pages", type=int, default=80, help="最多翻多少页")
    p_fetch.add_argument("--game", type=str, default="dlt", choices=["dlt", "ssq"], help="彩种: dlt=大乐透, ssq=双色球")

    # update
    p_update = subparsers.add_parser("update", help="增量更新数据")
    p_update.add_argument("--game", type=str, default="dlt", choices=["dlt", "ssq"], help="彩种: dlt=大乐透, ssq=双色球")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="CLI 模式分析")
    p_analyze.add_argument("--html", action="store_true", help="同时生成 HTML 图表")
    p_analyze.add_argument("--game", type=str, default="dlt", choices=["dlt", "ssq"], help="彩种")

    # dashboard
    p_dash = subparsers.add_parser("dashboard", help="启动 Web 仪表盘")
    p_dash.add_argument("--port", type=int, default=8765, help="端口")

    # watch - 持续监控新开奖 + 推送
    p_watch = subparsers.add_parser("watch", help="持续监控新开奖 + 多渠道推送")
    p_watch.add_argument("--interval", type=int, default=300, help="轮询间隔（秒），默认 300")
    p_watch.add_argument("--log", type=str, help="日志文件路径，如 logs/push.log")
    p_watch.add_argument("--webhook", type=str, help="通用 webhook URL")
    p_watch.add_argument("--dingtalk", type=str, help="钉钉机器人 webhook URL")
    p_watch.add_argument("--secret", type=str, help="钉钉签名密钥")
    p_watch.add_argument("--wecom", type=str, help="企业微信机器人 webhook URL")

    # backtest
    p_bt = subparsers.add_parser("backtest", help="跑历史回测")
    p_bt.add_argument("--train", type=int, help="训练窗口大小")
    p_bt.add_argument("--test", type=int, help="测试期数")
    p_bt.add_argument("--top-k", type=int, help="选 Top K 个号码")

    # report-image - 生成 PNG 热度图 + 推送
    p_img = subparsers.add_parser("report-image", help="生成 PNG 热度热力图 + 推送")
    p_img.add_argument("--period", type=str, help="期号标签（默认最新）")
    p_img.add_argument("--notify", action="store_true", help="推送（需要配置渠道）")
    p_img.add_argument("--hit-report", action="store_true", help="嵌入命中评估摘要")
    p_img.add_argument("--log", type=str, help="日志文件路径")
    p_img.add_argument("--webhook", type=str, help="通用 webhook URL（含图）")
    p_img.add_argument("--dingtalk", type=str, help="钉钉机器人 webhook URL")
    p_img.add_argument("--secret", type=str, help="钉钉签名密钥")
    p_img.add_argument("--wecom", type=str, help="企业微信机器人 webhook URL")

    # recommend - 号码组合推荐
    p_rec = subparsers.add_parser("recommend", help="号码组合推荐（多策略）")
    p_rec.add_argument("--period", type=str, help="针对的期号（默认最新）")
    p_rec.add_argument("--strategy", type=str, default="mixed",
                       choices=["mixed", "TopHeat", "ColdRebound", "Balanced", "MostFrequent"],
                       help="推荐策略")
    p_rec.add_argument("--n", type=int, default=10, help="推荐注数")
    p_rec.add_argument("--log", action="store_true", help="记录到决策日志")
    p_rec.add_argument("--seed", type=int, default=42, help="随机种子")
    p_rec.add_argument("--game", type=str, default="dlt", choices=["dlt", "ssq"], help="彩种")

    # decision-stats - 决策日志统计
    p_stats = subparsers.add_parser("decision-stats", help="决策日志统计")
    p_stats.add_argument("--periods", type=int, default=50, help="最近 N 期")
    p_stats.add_argument("--backfill", action="store_true", help="先回填所有未开奖期")

    # tests - 跑测试
    p_tests = subparsers.add_parser("tests", help="跑 pytest 测试")
    p_tests.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    # migrate - CSV → SQLite 一次性迁移
    p_mig = subparsers.add_parser("migrate", help="从 CSV 迁移到 SQLite")
    p_mig.add_argument("--csv", type=str, help="CSV 文件路径")

    # health - 健康检查
    p_health = subparsers.add_parser("health", help="健康检查")
    p_health.add_argument("--auto-fix", action="store_true", help="自动修复")
    p_health.add_argument("--watch", type=int, default=0, help="持续监控间隔（秒）")
    p_health.add_argument("--json", action="store_true", help="JSON 输出")

    # crawl - 多源采集 (gh 主力 + zhcw + ttz)
    p_crawl = subparsers.add_parser("crawl", help="多源采集 + 合并 + 导入 SQLite (带数据保护)")
    p_crawl.add_argument("--game", type=str, default="all",
                         choices=["dlt", "ssq", "all"], help="彩种")
    p_crawl.add_argument("--sources", type=str, default="gh,zhcw,ttz",
                         help="数据源 (逗号分隔: gh=GitHub主力全量, zhcw, ttz)")
    p_crawl.add_argument("--merge", action="store_true", default=True, help="合并多源")
    p_crawl.add_argument("--no-merge", dest="merge", action="store_false", help="跳过合并")
    p_crawl.add_argument("--import-db", action="store_true", default=True, help="导入 SQLite")
    p_crawl.add_argument("--no-import", dest="import_db", action="store_false", help="跳过导入")
    p_crawl.add_argument("--force", action="store_true",
                         help="守卫拦截时强制导入 (危险, 会覆盖全量历史)")

    # lab - 概率统计实验室 (12+1 步)
    p_lab = subparsers.add_parser("lab", help="跑 12+1 步概率统计实验室")
    p_lab.add_argument("--game", type=str, default="dlt", choices=["dlt", "ssq"], help="彩种")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # 路由到对应命令
    commands = {
        "games": cmd_games,
        "fetch": cmd_fetch,
        "update": cmd_update,
        "analyze": cmd_analyze,
        "dashboard": cmd_dashboard,
        "watch": cmd_watch,
        "backtest": cmd_backtest,
        "report-image": cmd_report_image,
        "recommend": cmd_recommend,
        "decision-stats": cmd_decision_stats,
        "tests": cmd_tests,
        "migrate": cmd_migrate,
        "health": cmd_health,
        "crawl": cmd_crawl,
        "lab": cmd_lab,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
