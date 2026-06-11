"""
v0.1.x → v0.2.x 数据迁移工具

检查 SQLite 数据库是否需要从 v0.1.x 迁移到 v0.2.x，
并通过 Database.initialize() 安全地应用新 schema（幂等）。

用法：
    python3 scripts/migrate_from_v01.py
    python3 scripts/migrate_from_v01.py --database path/to/db.sqlite3

注意：
    - initialize() 是幂等的，可以对已是 v0.2 的数据库安全重跑。
    - 迁移前建议手动备份数据库文件。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中，脚本可从任意工作目录调用
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.db.database import Database  # noqa: E402


# ──────────────────────────────────────────────
# 检查逻辑
# ──────────────────────────────────────────────

def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """检查指定表是否存在于数据库中。"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _needs_migration(db_path: str) -> bool:
    """
    判断数据库是否需要迁移。

    v0.1.x 的数据库缺少 v0.2.x 引入的 study_goals 表；
    v0.2.x 已包含该表，表示 schema 已是最新状态。
    """
    conn = sqlite3.connect(db_path)
    try:
        return not _table_exists(conn, "study_goals")
    finally:
        conn.close()


def _get_applied_migrations(db_path: str) -> list[str]:
    """获取已应用的迁移名列表，如果 schema_migrations 表不存在则返回空列表。"""
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "schema_migrations"):
            return []
        rows = conn.execute(
            "SELECT name FROM schema_migrations ORDER BY applied_at"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def run_migration(db_path: str) -> None:
    """执行迁移检查并在需要时应用新 schema。"""
    path = Path(db_path)

    print(f"[migrate] 目标数据库：{path.resolve()}")

    if not path.exists():
        print(f"[migrate] 数据库文件不存在，将由 initialize() 自动创建：{path}")

    # 记录迁移前状态
    pre_migrations = _get_applied_migrations(db_path) if path.exists() else []
    needs = _needs_migration(db_path) if path.exists() else True

    if needs:
        print("[migrate] 检测到 v0.1.x schema（缺少 study_goals 表），开始迁移...")
    else:
        print("[migrate] 数据库已是 v0.2.x schema，执行幂等重校验...")

    # 调用 Database.initialize() 应用完整 schema + 所有迁移
    db = Database(db_path)
    try:
        db.initialize()
    finally:
        db.close()

    # 记录迁移后状态
    post_migrations = _get_applied_migrations(db_path)
    new_migrations = [m for m in post_migrations if m not in pre_migrations]

    # ── 输出迁移报告 ──
    print()
    print("=" * 55)
    print("迁移报告 / Migration Report")
    print("=" * 55)
    print(f"  数据库路径  : {path.resolve()}")
    print(f"  迁移前状态  : {'v0.1.x（需迁移）' if needs else 'v0.2.x（已最新）'}")
    print(f"  已应用迁移数: {len(post_migrations)}")

    if new_migrations:
        print(f"  本次新增迁移:")
        for name in new_migrations:
            print(f"    + {name}")
    else:
        print("  本次新增迁移: 无（所有迁移已是最新）")

    print(f"  study_goals : {'存在 ✓' if not _needs_migration(db_path) else '缺失 ✗'}")
    print("=" * 55)
    print("[migrate] 完成。数据库已更新至 v0.2.x schema。")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="v0.1.x → v0.2.x 数据库迁移工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--database",
        default="data/companion.sqlite3",
        metavar="PATH",
        help="SQLite 数据库路径（默认：data/companion.sqlite3）",
    )
    args = parser.parse_args()

    try:
        run_migration(args.database)
    except Exception as exc:
        print(f"[migrate] 错误：{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
