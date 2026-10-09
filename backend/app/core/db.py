# -*- coding: utf-8 -*-
"""业务库数据库连接与会话管理。"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """后台线程（分析任务）使用的数据库会话上下文。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ping() -> tuple[bool, str]:
    """健康检查：返回 (是否可用, 版本或错误信息)。"""
    try:
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT VERSION()")).scalar_one()
        return True, str(ver)
    except Exception as exc:  # noqa: BLE001
        logger.error("数据库连通性检查失败: %s", exc)
        return False, str(exc)
