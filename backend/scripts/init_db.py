#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
经营多轮归因分析系统 —— 数据库一键初始化脚本

按顺序执行 database 目录下的 5 个 SQL 脚本，完成认证中心库与业务库的建库、建表、
字典写入与示例数据导入。

用法:
    cd backend
    uv run python scripts/init_db.py
    uv run python scripts/init_db.py --host 127.0.0.1 --port 3306 --user root --password root
    uv run python scripts/init_db.py --skip-data     # 只建表，不导入约 5MB 示例数据

注意:
    脚本会先 DROP 再重建 analysis_auth / analysis_sys 两个库，
    请勿在存有真实数据的实例上执行。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

try:
    import pymysql
except ImportError:  # pragma: no cover
    print("[ERROR] 缺少 pymysql，请先执行: uv sync")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
DB_DIR = ROOT / "database"

SCRIPTS = [
    ("01_auth_schema.sql", "认证中心库 analysis_auth（用户/客户端/授权码/令牌/会话/日志）", True),
    ("02_core_schema.sql", "业务库 analysis_sys 核心 10 张表", True),
    ("03_business_schema.sql", "业务库 6 大场景 22 张演示表", True),
    ("04_dict.sql", "基础字典（用户镜像/系统配置/数据源/枚举）", True),
    ("05_demo_data.sql", "业务示例场景数据（约 5 MB）", False),
]

# 建库语句需要单独执行，不能与其它语句混在一个多语句批次里
CREATE_AUTH_DB = (
    "CREATE DATABASE IF NOT EXISTS `analysis_auth` "
    "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_general_ci"
)
CREATE_SYS_DB = (
    "CREATE DATABASE IF NOT EXISTS `analysis_sys` "
    "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_general_ci"
)


# ---------------------------------------------------------------------------
# SQL 语句切分
# ---------------------------------------------------------------------------

def split_sql(sql: str) -> list[str]:
    """把 SQL 文件切成单条语句。

    正确处理：
      - `-- ` 行注释、`#` 行注释、`/* */` 块注释
      - 单引号 / 双引号 / 反引号字符串，含反斜杠转义与 '' 双写转义
      - 语句间的分号分隔
    """
    stmts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    quote: str | None = None

    while i < n:
        ch = sql[i]

        if quote:
            buf.append(ch)
            if ch == "\\" and quote in ("'", '"') and i + 1 < n:
                buf.append(sql[i + 1])
                i += 2
                continue
            if ch == quote:
                # 双写转义：'' 或 ""
                if i + 1 < n and sql[i + 1] == quote:
                    buf.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        # 行注释
        if ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if ch == "#":
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        # 块注释
        if ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue

        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------

def connect(host: str, port: int, user: str, password: str, db: str | None = None):
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db,
        charset="utf8mb4",
        autocommit=True,
        max_allowed_packet=64 * 1024 * 1024,
        connect_timeout=10,
    )


def run_script(conn, path: Path, verbose: bool = True) -> tuple[int, float]:
    sql = path.read_text(encoding="utf-8")
    stmts = split_sql(sql)
    t0 = time.time()
    cur = conn.cursor()
    for idx, stmt in enumerate(stmts, 1):
        try:
            cur.execute(stmt)
        except Exception as exc:  # noqa: BLE001
            head = " ".join(stmt.split())[:160]
            print(f"\n[ERROR] {path.name} 第 {idx}/{len(stmts)} 条语句执行失败")
            print(f"        语句: {head} ...")
            print(f"        错误: {exc}")
            raise
        # 消费掉可能存在的额外结果集
        while cur.nextset():
            pass
    cur.close()
    return len(stmts), time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description="经营多轮归因分析系统数据库初始化")
    ap.add_argument("--host", default=os.getenv("DB_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("DB_PORT", "3306")))
    ap.add_argument("--user", default=os.getenv("DB_USER", "root"))
    ap.add_argument("--password", default=os.getenv("DB_PASSWORD", "root"))
    ap.add_argument("--skip-data", action="store_true", help="跳过示例数据导入（05_demo_data.sql）")
    ap.add_argument("--only", default="", help="只执行指定脚本，如 05_demo_data.sql")
    args = ap.parse_args()

    print("=" * 78)
    print("  经营多轮归因分析系统 —— 数据库初始化")
    print("=" * 78)
    print(f"  目标实例 : {args.host}:{args.port} (user={args.user})")
    print(f"  脚本目录 : {DB_DIR}")
    print()

    # 1. 连通性检查
    try:
        conn = connect(args.host, args.port, args.user, args.password)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 无法连接 MySQL: {exc}")
        print("        请确认 MySQL 已启动，且账号口令正确。")
        return 2

    with conn:
        ver = conn.cursor()
        ver.execute("SELECT VERSION()")
        print(f"[OK] 连接成功，MySQL 版本 {ver.fetchone()[0]}")
        ver.close()

    # 2. 建库（保证 01/02 脚本内的 DROP DATABASE 有落脚点）
    with connect(args.host, args.port, args.user, args.password) as conn:
        cur = conn.cursor()
        cur.execute(CREATE_AUTH_DB)
        cur.execute(CREATE_SYS_DB)
        cur.close()
        print("[OK] 基础库 analysis_auth / analysis_sys 已就绪\n")

    # 3. 逐脚本执行
    targets = SCRIPTS
    if args.only:
        targets = [s for s in SCRIPTS if s[0] == args.only]
        if not targets:
            print(f"[ERROR] --only 指定的脚本不存在: {args.only}")
            return 2
    elif args.skip_data:
        targets = [s for s in SCRIPTS if s[2]]

    total_stmts = 0
    total_sec = 0.0
    for fname, desc, _ in targets:
        path = DB_DIR / fname
        if not path.exists():
            print(f"[ERROR] 缺少脚本 {path}")
            return 2
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"[..] {fname}  ({size_mb:.2f} MB)  {desc}")
        # 05 数据脚本需要连到 analysis_sys 以便 USE 语句生效
        dbname = "analysis_sys" if fname.startswith(("02", "03", "04", "05")) else None
        with connect(args.host, args.port, args.user, args.password, dbname) as conn:
            n, sec = run_script(conn, path)
        total_stmts += n
        total_sec += sec
        print(f"[OK] 完成，{n} 条语句，耗时 {sec:.1f}s\n")

    # 4. 自检
    print("-" * 78)
    print("  数据自检")
    print("-" * 78)
    checks = [
        ("analysis_auth", "auth_users", "认证中心用户"),
        ("analysis_auth", "auth_clients", "认证中心客户端"),
        ("analysis_sys", "users", "业务用户镜像"),
        ("analysis_sys", "system_configs", "系统配置项"),
        ("analysis_sys", "data_sources", "业务数据源"),
        ("analysis_sys", "biz_product", "演示商品"),
        ("analysis_sys", "biz_order", "演示订单"),
        ("analysis_sys", "biz_review", "演示评论"),
        ("analysis_sys", "biz_refund_apply", "演示退款申请"),
    ]
    with connect(args.host, args.port, args.user, args.password) as conn:
        cur = conn.cursor()
        for db, table, label in checks:
            try:
                cur.execute(f"SELECT COUNT(*) FROM `{db}`.`{table}`")
                print(f"  {label:<16} {cur.fetchone()[0]:>10,}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {label:<16} [读取失败] {exc}")
        cur.close()

    print()
    print("=" * 78)
    print(f"  初始化完成：共 {total_stmts} 条语句，总耗时 {total_sec:.1f}s")
    print("=" * 78)
    print("  演示账号:")
    print("    admin    / Admin@123     系统管理员")
    print("    analyst  / Analyst@123   分析用户")
    print("    zhangyun / Zhang@123     分析用户（商品运营）")
    print()
    print("  下一步:")
    print("    1) 启动认证中心  cd auth-server  && uv run uvicorn app.main:app --port 9000 --reload")
    print("    2) 启动后端服务  cd backend      && uv run uvicorn app.main:app --port 8000 --reload")
    print("    3) 启动前端      cd frontend     && npm run dev")
    return 0


if __name__ == "__main__":
    sys.exit(main())
