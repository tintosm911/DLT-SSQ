"""
数据守卫 (data_guard) 故障注入测试
==================================
模拟 2026-10-22 那次真实事故:
    import_sources() 清空库 → 导入 zhcw/ttz 的 100 期局部数据
    → DLT 3037 + SSQ 3516 期 变成 201 + 201 期

本测试验证:
  1. 自动备份能正确生成
  2. 期数回归检查能检测出大幅下降
  3. 自动回滚能恢复原状
  4. 源完整性检查能拦截局部数据源
  5. 正常导入不受影响

跑法: python tests/test_data_guard.py
"""
import sys
import shutil
import sqlite3
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from data.data_guard import (
    backup_db, check_regression, check_sources, get_counts,
    guarded_import, list_backups, restore_backup,
)

PASS, FAIL = 0, 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [PASS] {name}')
    else:
        FAIL += 1
        print(f'  [FAIL] {name} {detail}')


def make_db(path: Path, dlt_n=100, ssq_n=100):
    """造一个测试库 (schema 与真实库一致)"""
    conn = sqlite3.connect(str(path))
    conn.execute('''CREATE TABLE IF NOT EXISTS draws (
        id INTEGER PRIMARY KEY,
        period TEXT, draw_date TEXT, game TEXT,
        front_1 INTEGER, front_2 INTEGER, front_3 INTEGER,
        front_4 INTEGER, front_5 INTEGER, front_6 INTEGER,
        back_1 INTEGER, back_2 INTEGER,
        prize_money REAL, sales REAL, notes TEXT,
        front_numbers TEXT, back_numbers TEXT,
        UNIQUE(period, game))''')
    conn.execute('DELETE FROM draws')
    for g, n in (('dlt', dlt_n), ('ssq', ssq_n)):
        for i in range(n):
            conn.execute(
                'INSERT INTO draws (period, draw_date, game, front_1, back_1) '
                'VALUES (?,?,?,?,?)',
                (f'26{i:04d}', '2026-01-01', g, i % 35 + 1, i % 12 + 1))
    conn.commit()
    conn.close()


def main():
    tmp = Path(tempfile.mkdtemp(prefix='guard_test_'))
    db = tmp / 'test.db'
    bdir = tmp / 'backups'
    print()
    print('=' * 66)
    print('  数据守卫故障注入测试')
    print('=' * 66)

    # ---------- 1. 备份 ----------
    print()
    print('【1】自动备份')
    make_db(db, dlt_n=3037, ssq_n=3516)
    bi = backup_db(db, bdir)
    check('备份文件已生成', bi is not None and bi.path.exists())
    check('备份期数正确', bi.counts.get('dlt') == 3037 and bi.counts.get('ssq') == 3516,
          f'实际 {bi.counts}')
    check('备份列表可见', len(list_backups(bdir)) >= 1)

    # ---------- 2. 回归检测 ----------
    print()
    print('【2】期数回归检测')
    probs = check_regression({'dlt': 3037, 'ssq': 3516}, {'dlt': 201, 'ssq': 201})
    check('检测到大幅下降', len(probs) == 2, f'实际 {probs}')
    check('提示含期数明细', '3037' in probs[0] and '201' in probs[0], probs[0])
    ok = check_regression({'dlt': 3037}, {'dlt': 3038})
    check('正常增长不报错', len(ok) == 0)
    small = check_regression({'dlt': 3037}, {'dlt': 2900})  # 掉 4.5%
    check('小幅下降(4.5%)不报错', len(small) == 0, f'实际 {small}')

    # ---------- 3. 自动回滚 ----------
    print()
    print('【3】自动回滚')
    # 模拟事故: 清空 + 灌 100 期
    conn = sqlite3.connect(str(db))
    conn.execute('DELETE FROM draws')
    for i in range(100):
        conn.execute('INSERT INTO draws (period, draw_date, game, front_1, back_1) '
                     'VALUES (?,?,?,?,?)', (f'26{i:04d}', '2026-01-01', 'dlt', i, i))
    conn.commit()
    conn.close()
    check('事故已模拟', get_counts(db) == {'dlt': 100}, f'实际 {get_counts(db)}')

    restored = restore_backup(bi, db)
    check('回滚执行成功', restored)
    check('回滚后期数恢复',
          get_counts(db).get('dlt') == 3037 and get_counts(db).get('ssq') == 3516,
          f'实际 {get_counts(db)}')

    # ---------- 4. 源完整性 ----------
    print()
    print('【4】源完整性检查')
    warns = check_sources(['gh'], ['dlt'], data_raw=tmp)
    check('缺文件时告警', len(warns) >= 1 and '不存在' in warns[0], f'实际 {warns}')

    # 造一个"局部数据源" (只有 100 期, 但 gh 要求 ≥2500)
    (tmp / 'gh_dlt.csv').write_text(
        'period,draw_date,front_1,front_2,front_3,front_4,front_5,back_1,back_2\n'
        + ''.join(f'26{i:04d},2026-01-01,{i},1,2,3,4,5,6\n' for i in range(100)),
        encoding='utf-8')
    warns2 = check_sources(['gh'], ['dlt'], data_raw=tmp)
    check('局部数据源被识别', len(warns2) >= 1 and '疑似局部数据' in warns2[0],
          f'实际 {warns2}')

    # 造一个正常期数的源
    (tmp / 'gh_dlt.csv').write_text(
        'period,draw_date,front_1,front_2,front_3,front_4,front_5,back_1,back_2\n'
        + ''.join(f'26{i:04d},2026-01-01,{i},1,2,3,4,5,6\n' for i in range(3000)),
        encoding='utf-8')
    warns3 = check_sources(['gh'], ['dlt'], data_raw=tmp)
    check('正常期数源放行', len(warns3) == 0, f'实际 {warns3}')

    # 规则 2: 局部源 (zhcw 100 期) vs 库里已有 3037 期 → 必须拦截
    (tmp / 'zhcw_dlt.csv').write_text(
        'period,draw_date,front_1,front_2,front_3,front_4,front_5,back_1,back_2\n'
        + ''.join(f'26{i:04d},2026-01-01,{i},1,2,3,4,5,6\n' for i in range(100)),
        encoding='utf-8')
    warns4 = check_sources(['zhcw'], ['dlt'], data_raw=tmp,
                            existing_counts={'dlt': 3037})
    check('局部源 vs 全量库被拦截', len(warns4) >= 1 and '局部源' in warns4[0],
          f'实际 {warns4}')
    warns5 = check_sources(['zhcw'], ['dlt'], data_raw=tmp,
                            existing_counts={'dlt': 0})
    check('空库时局部源放行', len(warns5) == 0, f'实际 {warns5}')
    # 有全量源 gh 在场时, 局部源只是补充最新期 → 应放行
    (tmp / 'gh_dlt.csv').write_text(
        'period,draw_date,front_1,front_2,front_3,front_4,front_5,back_1,back_2\n'
        + ''.join(f'25{i:04d},2025-01-01,{i},1,2,3,4,5,6\n' for i in range(3000)),
        encoding='utf-8')
    warns6 = check_sources(['gh', 'zhcw'], ['dlt'], data_raw=tmp,
                            existing_counts={'dlt': 3037})
    check('全量源在场时局部源放行', len(warns6) == 0, f'实际 {warns6}')

    # ---------- 5. guarded_import 端到端 ----------
    print()
    print('【5】guarded_import 端到端 (拦截场景)')
    # 恢复满库
    make_db(db, dlt_n=3037, ssq_n=3516)
    # 只给局部源 (100 期)
    (tmp / 'zhcw_dlt.csv').write_text(
        'period,draw_date,front_1,front_2,front_3,front_4,front_5,back_1,back_2\n'
        + ''.join(f'27{i:04d},2026-02-01,{i},1,2,3,4,5,6\n' for i in range(100)),
        encoding='utf-8')
    # 临时替换 import_csv 的 DATA_RAW 指向 tmp
    import data.import_csv as ic
    orig_data_raw = ic.DATA_RAW
    orig_db = ic.DB_PATH
    ic.DATA_RAW = tmp
    ic.DB_PATH = db

    try:
        res = guarded_import('dlt', ['zhcw'], verbose=False, db_path=db)
        check('局部源被拦截', not res.ok, f'实际 ok={res.ok}')
        check('拦截时库未被改动', get_counts(db).get('dlt') == 3037,
              f'实际 {get_counts(db)}')
        check('给出了提示信息', '局部数据' in res.message or '拒绝' in res.message,
              res.message)
    finally:
        ic.DATA_RAW = orig_data_raw
        ic.DB_PATH = orig_db

    # ---------- 6. 正常导入 ----------
    print()
    print('【6】guarded_import 正常导入')
    (tmp / 'gh_dlt.csv').write_text(
        'period,draw_date,front_1,front_2,front_3,front_4,front_5,back_1,back_2\n'
        + ''.join(f'28{i:04d},2026-03-01,{i},1,2,3,4,5,6\n' for i in range(3000)),
        encoding='utf-8')
    ic.DATA_RAW = tmp
    ic.DB_PATH = db
    try:
        res2 = guarded_import('dlt', ['gh'], verbose=False, db_path=db)
        check('正常导入成功', res2.ok, res2.message)
        check('期数未下降', get_counts(db).get('dlt', 0) >= 3037,
              f'实际 {get_counts(db)}')
        check('产生了备份', res2.backup is not None)
    finally:
        ic.DATA_RAW = orig_data_raw
        ic.DB_PATH = orig_db

    # 清理
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print('=' * 66)
    print(f'  {PASS}/{PASS + FAIL} passed' + ('  ✅' if FAIL == 0 else '  ❌'))
    print('=' * 66)
    print()
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
