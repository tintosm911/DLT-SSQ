"""
数据保护模块 (Data Guard)
=========================
防止"跑一次采集, 6553 期历史变 402 期"这类灾难重演。

三层防护:

  1. **自动备份** — 任何写 DB 之前先备份, 备份带时间戳
  2. **期数回归检查** — 导入后如果期数掉了超过阈值, 自动回滚
  3. **源完整性检查** — 导入前检查各源 CSV 的期数, 主力源缺失时告警

历史教训 (2026-10-22):
    import_sources() 早期硬编码 DELETE FROM draws, 跑一次
    `main.py crawl --game all` 就把 DLT 3037 + SSQ 3516 期
    全量历史覆盖成 201 + 201 期, 靠 CSV 备份才救回来。
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = PROJECT_ROOT / 'data-raw'
BACKUP_DIR = DATA_RAW / 'backups'
DB_PATH = DATA_RAW / 'lottery.db'

# 期数下降超过这个比例就判定为异常, 触发回滚
REGRESSION_RATIO = 0.20

# 各源的"正常期数下界" (低于这个值说明该源只拿到局部数据)
SOURCE_MIN_PERIODS = {
    'gh':   2500,   # GitHub 开源数据集: DLT 2937 / SSQ 3516
    'merged': 150,
    'ttz':  50,
    'zhcw': 50,
}

# 各源的"权威期数" (用于判断某源相对全量库是否明显残缺)
# 当库里有全量历史时, 用 zhcw/ttz 这类 100 期局部源去导入是危险的
SOURCE_IS_PARTIAL = {'zhcw', 'ttz', 'merged'}


@dataclass
class BackupInfo:
    path: Path
    created_at: str
    size: int
    counts: Dict[str, int]

    def summary(self) -> str:
        counts = ', '.join(f'{k.upper()} {v}期' for k, v in self.counts.items())
        return f'{self.path.name} ({self.size/1024:.0f}KB, {counts})'


@dataclass
class GuardResult:
    ok: bool
    before: Dict[str, int]
    after: Dict[str, int]
    backup: Optional[BackupInfo] = None
    rolled_back: bool = False
    message: str = ''

    def summary(self) -> str:
        return self.message


# ============================================================
# 底层工具
# ============================================================
def get_counts(db_path: Path = DB_PATH) -> Dict[str, int]:
    """读各彩种当前期数"""
    if not Path(db_path).exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            'SELECT game, COUNT(*) FROM draws GROUP BY game').fetchall()
        return {g: n for g, n in rows}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _fmt_counts(counts: Dict[str, int]) -> str:
    if not counts:
        return '空库'
    return ', '.join(f'{k.upper()} {v}期' for k, v in sorted(counts.items()))


# ============================================================
# 1. 自动备份
# ============================================================
def backup_db(db_path: Path = DB_PATH,
               backup_dir: Path = BACKUP_DIR,
               keep: int = 20) -> Optional[BackupInfo]:
    """
    备份 SQLite 数据库 (带时间戳), 只保留最近 keep 份。
    返回 None 表示库不存在 (无需备份)。
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return None

    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    dest = backup_dir / f'lottery-{stamp}.db'
    # SQLite WAL 模式: 用 backup API 保证一致性
    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(dest))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
    except sqlite3.Error:
        # 退回到文件复制
        shutil.copy2(db_path, dest)

    # 清理旧备份
    backups = sorted(backup_dir.glob('lottery-*.db'),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError:
            pass

    return BackupInfo(
        path=dest,
        created_at=datetime.now().isoformat(timespec='seconds'),
        size=dest.stat().st_size,
        counts=get_counts(db_path),
    )


def restore_backup(backup: BackupInfo, db_path: Path = DB_PATH) -> bool:
    """从备份恢复数据库"""
    db_path = Path(db_path)
    try:
        shutil.copy2(backup.path, db_path)
        return True
    except OSError:
        return False


def list_backups(backup_dir: Path = BACKUP_DIR) -> List[Path]:
    """列出所有备份 (新→旧)"""
    if not Path(backup_dir).exists():
        return []
    return sorted(Path(backup_dir).glob('lottery-*.db'),
                  key=lambda p: p.stat().st_mtime, reverse=True)


# ============================================================
# 2. 期数回归检查
# ============================================================
def check_regression(before: Dict[str, int], after: Dict[str, int],
                     ratio: float = REGRESSION_RATIO) -> List[str]:
    """
    对比导入前后期数, 返回异常描述列表 (空 = 正常)
    """
    problems = []
    for game, n_before in before.items():
        n_after = after.get(game, 0)
        if n_before == 0:
            continue
        drop = n_before - n_after
        if drop <= 0:
            continue
        pct = drop / n_before
        if pct > ratio:
            problems.append(
                f'{game.upper()} 期数从 {n_before} 掉到 {n_after} '
                f'(减少 {drop} 期, {pct*100:.1f}%, 阈值 {ratio*100:.0f}%)')
    return problems


# ============================================================
# 3. 源完整性检查
# ============================================================
def check_sources(sources: List[str], games: List[str],
                  data_raw: Path = DATA_RAW,
                  existing_counts: Dict[str, int] = None) -> List[str]:
    """
    检查各源 CSV 是否存在且期数达标。返回告警列表。

    existing_counts: 库当前期数。用于识别"局部源覆盖全量"这种危险组合。
    """
    warnings = []
    for game in games:
        lib_n = (existing_counts or {}).get(game, 0)
        # 有全量源 (gh) 在场时, 局部源只是补充最新期, 不会造成数据损失
        has_full_source = any(
            s not in SOURCE_IS_PARTIAL for s in sources)

        for src in sources:
            path = Path(data_raw) / f'{src}_{game}.csv'
            if not path.exists():
                warnings.append(f'{src}_{game}.csv 不存在')
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    n = max(0, sum(1 for _ in f) - 1)  # 减表头
            except OSError as e:
                warnings.append(f'{path.name} 读取失败: {e}')
                continue

            # 规则 1: 绝对下界 (源本身就该有多少期)
            minimum = SOURCE_MIN_PERIODS.get(src, 0)
            if minimum > 0 and n < minimum:
                warnings.append(
                    f'{path.name} 只有 {n} 期 (期望 ≥{minimum}), '
                    f'疑似局部数据, 不要用它覆盖全量库')
                continue

            # 规则 2: 相对判据 — 没有全量源时, 局部源不足以替换全量库
            if (not has_full_source and src in SOURCE_IS_PARTIAL
                    and lib_n > 0
                    and n < lib_n * (1 - REGRESSION_RATIO)):
                warnings.append(
                    f'{path.name} 只有 {n} 期, 而库里已有 {lib_n} 期 '
                    f'(该源是局部源, 导入会把全量历史覆盖成局部)')
    return warnings


def check_structure(db_path: Path = DB_PATH) -> List[str]:
    """
    库内结构完整性检查 (第 4 层防护):
      - 重复期号 (同一期被当成多期入库)
      - 期号长度不统一 (不同源期号体系不一致)
      - 同一开奖日期出现多条记录
    """
    import collections
    import json

    problems = []
    db_path = Path(db_path)
    if not db_path.exists():
        return problems

    conn = sqlite3.connect(str(db_path))
    try:
        for game, in conn.execute('SELECT DISTINCT game FROM draws'):
            rows = conn.execute(
                'SELECT period, draw_date, front_numbers FROM draws WHERE game=?',
                (game,)).fetchall()
            if not rows:
                continue

            # 重复期号
            cnt = collections.Counter(str(r[0]) for r in rows)
            dups = {p: n for p, n in cnt.items() if n > 1}
            if dups:
                problems.append(
                    f'{game.upper()} 有 {len(dups)} 个重复期号 '
                    f'(如 {list(dups)[:3]}), 同一期被当成多期入库')

            # 期号长度不统一
            lens = collections.Counter(len(str(r[0])) for r in rows)
            if len(lens) > 1:
                problems.append(
                    f'{game.upper()} 期号长度不统一 {dict(lens)}, '
                    f'不同数据源期号体系不一致, 会导致重复入库')

            # 同日期多期 (期号体系错位的信号)
            by_date = collections.Counter(
                r[1] for r in rows if r[1] and r[1].startswith('20'))
            multi = {d: n for d, n in by_date.items() if n > 1}
            if multi:
                problems.append(
                    f'{game.upper()} 有 {len(multi)} 个开奖日期对应多条记录 '
                    f'(如 {list(multi)[:3]}), 可能存在期号错位')
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return problems


# ============================================================
# 守卫主流程
# ============================================================
def guarded_import(game: str, sources: List[str], verbose: bool = True,
                   db_path: Path = DB_PATH,
                   ratio: float = REGRESSION_RATIO,
                   data_raw: Path = None) -> GuardResult:
    """
    带保护的导入流程:
      1. 检查源完整性
      2. 备份数据库
      3. 执行导入
      4. 期数回归检查 → 异常则自动回滚
    """
    from data.import_csv import import_sources, DATA_RAW as _IC_DATA_RAW

    if data_raw is None:
        data_raw = _IC_DATA_RAW

    db_path = Path(db_path)
    before = get_counts(db_path)

    if verbose:
        print(f'  [Guard] 导入前: {_fmt_counts(before)}')

    # --- 源完整性 ---
    warns = check_sources(sources, [game], data_raw=data_raw,
                          existing_counts=before)
    if warns:
        for w in warns:
            print(f'  [Guard] ⚠️  {w}')
        # 致命级: 局部数据源 / 会覆盖全量历史
        fatal = [w for w in warns
                 if '疑似局部数据' in w or '局部源' in w or '覆盖全量历史' in w]
        if fatal:
            print(f'  [Guard] 🛑 检测到局部数据源, 已阻止导入 (防数据丢失)')
            print(f'         提示: 主力源 gh (GitHub) 提供全量历史, '
                  f'请跑 main.py crawl --sources gh')
            return GuardResult(
                ok=False, before=before, after=before,
                message=f'源完整性检查未通过, 已拒绝导入: {fatal[0]}')

    # --- 备份 ---
    backup = backup_db(db_path)
    if verbose and backup:
        print(f'  [Guard] 已备份: {backup.summary()}')

    # --- 导入 ---
    n = import_sources(game, sources, verbose=verbose)

    # --- 回归检查 ---
    after = get_counts(db_path)
    problems = check_regression(before, after, ratio)

    # --- 结构检查 (重复期号 / 期号体系不一致 / 同日多期) ---
    struct = check_structure(db_path)
    if struct:
        for s in struct:
            print(f'  [Guard] ⚠️  {s}')

    if problems:
        print(f'  [Guard] 🛑 期数回归异常:')
        for p in problems:
            print(f'         - {p}')
        rolled = False
        if backup:
            rolled = restore_backup(backup, db_path)
            print(f'  [Guard] {"已自动回滚到备份" if rolled else "回滚失败, 请手动恢复"}'
                  f': {backup.path.name}')
        return GuardResult(
            ok=False, before=before, after=after, backup=backup,
            rolled_back=rolled,
            message=f'期数回归异常, 已回滚: {"; ".join(problems)}')

    if verbose:
        print(f'  [Guard] 导入后: {_fmt_counts(after)}  ✅ 无异常')
    if struct:
        print(f'  [Guard] ⚠️  结构警告 {len(struct)} 项 (不影响导入, 但需要修数据源)')
    return GuardResult(
        ok=True, before=before, after=after, backup=backup,
        message=f'导入 {n} 条成功, 期数 {_fmt_counts(before)} → {_fmt_counts(after)}')


# ============================================================
# CLI 辅助
# ============================================================
def restore_latest(db_path: Path = DB_PATH) -> bool:
    """恢复最近一份备份"""
    backups = list_backups()
    if not backups:
        print('没有可用备份')
        return False
    latest = backups[0]
    shutil.copy2(latest, db_path)
    print(f'已恢复: {latest.name}  ({_fmt_counts(get_counts(db_path))})')
    return True


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    print('=' * 66)
    print('  数据保护 / 备份管理')
    print('=' * 66)
    print(f'  当前库: {_fmt_counts(get_counts())}')
    print()
    bl = list_backups()
    print(f'  备份列表 ({len(bl)} 份):')
    for b in bl[:10]:
        print(f'    {b.name}  ({b.stat().st_size/1024:.0f}KB)')
    if not bl:
        print('    (无)')
    print()
    print('  用法:')
    print('    python -m data.data_guard            # 查看状态')
    print('    python -m data.data_guard restore    # 恢复最近备份')
