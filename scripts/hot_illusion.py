"""热号幻觉演示器 CLI — 验证热号有无预测力"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.hot_illusion import analyze_hot_illusion

SEP = '=' * 76


def main():
    game = sys.argv[1] if len(sys.argv) > 1 else 'dlt'
    train = sys.argv[2].split(',') if len(sys.argv) > 2 else None
    test = sys.argv[3].split(',') if len(sys.argv) > 3 else None

    r = analyze_hot_illusion(game, train, test)
    p = r['predictive']
    c = r['continuity']
    s = r['scan']

    print()
    print(SEP)
    print(f'  热号幻觉演示  —  {r["game_name"]} ({game.upper()})')
    print(SEP)
    print(f'  训练期: {p["train_years"][0]}-{p["train_years"][-1]} '
          f'({p["train_draws"]} 期)')
    print(f'  测试期: {p["test_years"][0]}-{p["test_years"][-1]} '
          f'({p["test_draws"]} 期)')

    print()
    print('  【1】训练期热号在测试期的真实表现')
    print(f'      {"号码":<6}{"训练次数":>9}{"测试出现":>9}{"随机期望":>10}{"z分数":>9}')
    for x in p['per_num']:
        flag = ' ★高于随机' if x['above'] else ''
        print(f'      {x["num"]:<6}{x["train_count"]:>9}{x["test_count"]:>9}'
              f'{x["expected"]:>10.1f}{x["z"]:>+9.2f}{flag}')
    print(f'      热号平均出现 {p["hot_avg_count"]} 次 vs 随机期望 '
          f'{p["hot_expected"]} 次 (z={p["hot_z"]:+.2f})')

    print()
    print('  【2】预测力检验 (每期都买 Top-5 热号)')
    print(f'      买入号码: {p["pick_set"]}')
    print(f'      实际命中 {p["actual_hits"]} 个 vs 随机期望 {p["expected_hits"]} 个 '
          f'(z={p["hit_z"]:+.2f})')
    verdict = ('✅ 与随机无显著差异 — 热号无预测力'
               if abs(p['hit_z']) < 2
               else ('⚠️ 显著优于随机' if p['hit_z'] > 0 else '⚠️ 显著低于随机'))
    print(f'      {verdict}')

    print()
    print('  【3】照着热号买满测试期会怎样')
    print(f'      投入 {p["stake"]:,.0f} 元, 返奖 {p["returns"]:,.0f} 元, '
          f'净收益 {p["net"]:,.0f} 元')
    print(f'      ROI {p["roi"]:+.1f}%  (剔除大奖后 {p["roi_ex_big"]:+.1f}%, '
          f'中了 {p["big_prizes"]} 次大奖)')
    if p['prizes']:
        print(f'      奖级命中: {", ".join(f"{k}×{v}" for k, v in p["prizes"])}')

    print()
    print('  【4】排名延续性 (相邻年份热号有没有相关性)')
    print(f'      Top-{c["top_k"]} 重合度: 实测均值 {c["overlap_mean"]} vs '
          f'随机期望 {c["overlap_expected"]} (z={c["overlap_z"]:+.2f})')
    print(f'      Spearman ρ: 实测均值 {c["rho_mean"]:+.4f} vs 随机 0 '
          f'(z={c["rho_z"]:+.2f})')
    print(f'      → {c["verdict"]}')

    print()
    print('  【5】稳定性扫描 (遍历所有年份切分 — 击碎幻觉的关键)')
    if s.get('splits'):
        print(f'      {"训练期":<20}{"测试期":<20}{"z":>8}{"ROI%":>10}{"剔大奖ROI%":>13}')
        for x in s['splits']:
            mark = '  ★显著' if x['significant'] else ''
            print(f'      {"-".join(x["train"]):<20}{"-".join(x["test"]):<20}'
                  f'{x["hit_z"]:>+8.2f}{x["roi"]:>+10.1f}{x["roi_ex_big"]:>+13.1f}{mark}')
        print()
        print(f'      {s["verdict"]}')
        print()
        print(f'      → 如果换成任何别的切分, 结论都是"和随机一样",')
        print(f'        那么"这次有效"就纯粹是挑数据挑出来的.')

    print()
    print(SEP)
    for line in r['conclusion'].split(' | '):
        print(f'  • {line}')
    print(SEP)
    print()


if __name__ == '__main__':
    main()
