# -*- coding: utf-8 -*-
"""认证中心安全工具：口令摘要、随机令牌生成、时间工具。

口令算法: sha256(salt + password)，与 database/01_auth_schema.sql 中
          SHA2(CONCAT(salt, password), 256) 完全一致，保证 SQL 种子数据
          与运行时校验口径统一。

安全说明:
    该算法为演示级实现，仅用于「离线可复现的课程演示」。
    生产环境请替换 hash_password / verify_password 两个函数为 bcrypt / argon2，
    其余调用方无需改动（本模块是唯一的口令算法出入口）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta


# ---------------------------------------------------------------------------
# 口令
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: str) -> str:
    """返回 sha256(salt + password) 的十六进制摘要。"""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """恒定时间比较，避免时序侧信道。"""
    actual = hash_password(password, salt)
    return hmac.compare_digest(actual, (expected_hash or "").lower())


def gen_salt(length: int = 16) -> str:
    return secrets.token_hex(length // 2)


# ---------------------------------------------------------------------------
# 令牌
# ---------------------------------------------------------------------------

def gen_token(prefix: str = "") -> str:
    """生成 URL 安全的随机令牌。"""
    return f"{prefix}{secrets.token_urlsafe(32)}"


def gen_session_id() -> str:
    return f"sess_{secrets.token_hex(12)}"


def gen_code() -> str:
    return f"code_{secrets.token_urlsafe(24)}"


# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------

def now() -> datetime:
    """当前本地时间（naive），与 MySQL DATETIME 列对齐。"""
    return datetime.now()


def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def seconds_later(seconds: int) -> datetime:
    return now() + timedelta(seconds=seconds)


def is_expired(dt: datetime | None) -> bool:
    if dt is None:
        return True
    return dt < now()
