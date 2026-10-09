# -*- coding: utf-8 -*-
"""业务库 ORM 模型。

对应 database/02_core_schema.sql 中的 10 张核心表 + data_sources 扩展表。
6 大业务场景的 22 张 biz_* 演示表不建 ORM 模型——分析引擎一律使用只读原生 SQL
查询它们（见 app/analysis/tools/db_query.py），这样新增业务场景无需改模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# 毫秒精度的 DATETIME。
# MySQL 的 DATETIME 默认 0 位小数秒，而一次分析通常只跑几百毫秒，
# 秒级精度会把 started_at 与 finished_at 记成同一秒，令 duration_ms 恒为 0。
DATETIME_MS = DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")

# ---------------------------------------------------------------------------
# 枚举常量（与 database/04_dict.sql 中的字典一致）
# ---------------------------------------------------------------------------

CONVERSATION_STATUS = ("active", "archived", "deleted")

TASK_STATUS = ("queued", "running", "success", "failed", "cancelled")
TASK_STATUS_TERMINAL = ("success", "failed", "cancelled")

MESSAGE_ROLE = ("user", "assistant", "system", "tool")
MESSAGE_TYPE = ("text", "tool_call", "tool_result", "result", "error")

PARSE_STATUS = ("pending", "parsing", "parsed", "failed")

USER_ROLE = ("analyst", "admin")

LOG_LEVEL = ("DEBUG", "INFO", "WARN", "ERROR")
LOG_TYPE = ("lifecycle", "tool", "llm", "db", "file", "error")


# ---------------------------------------------------------------------------
# 1. users 用户表
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="analyst")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def avatar_text(self) -> str:
        return (self.display_name or self.username or "?")[:1]


# ---------------------------------------------------------------------------
# 2. conversations 会话表
# ---------------------------------------------------------------------------

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新的分析会话")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    tasks: Mapped[list[AnalysisTask]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    results: Mapped[list[AnalysisResult]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    summaries: Mapped[list[ContextSummary]] = relationship(back_populates="conversation", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_user_status_time", "user_id", "status", "last_message_at"),)


# ---------------------------------------------------------------------------
# 3. messages 消息表
# ---------------------------------------------------------------------------

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(64))
    tool_status: Mapped[str | None] = mapped_column(String(16))
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="message")

    __table_args__ = (Index("idx_conv_seq", "conversation_id", "seq_no"),)


# ---------------------------------------------------------------------------
# 4. attachments 附件表
# ---------------------------------------------------------------------------

class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("messages.id", ondelete="SET NULL"))
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="attachments")
    message: Mapped[Message | None] = relationship(back_populates="attachments")


# ---------------------------------------------------------------------------
# 5. analysis_tasks 分析任务表
# ---------------------------------------------------------------------------

class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    task_status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    current_step: Mapped[str | None] = mapped_column(String(128))
    # 毫秒精度：一次分析通常只跑几百毫秒，DATETIME(0) 会让 duration_ms 恒为 0
    started_at: Mapped[datetime | None] = mapped_column(DATETIME_MS)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME_MS)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="tasks")
    logs: Mapped[list[TaskLog]] = relationship(back_populates="task", cascade="all, delete-orphan")
    result: Mapped[AnalysisResult | None] = relationship(back_populates="task", uselist=False)

    __table_args__ = (Index("idx_conv_status", "conversation_id", "task_status"),)

    @property
    def is_terminal(self) -> bool:
        return self.task_status in TASK_STATUS_TERMINAL

    @property
    def duration_ms(self) -> int | None:
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds() * 1000)
        return None


# ---------------------------------------------------------------------------
# 6. analysis_results 分析结果表
# ---------------------------------------------------------------------------

class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("analysis_tasks.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    problem_definition: Mapped[str] = mapped_column(Text, nullable=False)
    key_metrics_json: Mapped[Any | None] = mapped_column(JSON)
    evidence_list_json: Mapped[Any | None] = mapped_column(JSON)
    conclusion_text: Mapped[str] = mapped_column(Text, nullable=False)
    missing_data_text: Mapped[str | None] = mapped_column(Text)
    next_action_text: Mapped[str | None] = mapped_column(Text)
    result_markdown: Mapped[str | None] = mapped_column(Text)
    result_file_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="results")
    task: Mapped[AnalysisTask] = relationship(back_populates="result")

    @property
    def key_metrics(self) -> list[dict[str, Any]]:
        return list(self.key_metrics_json or [])

    @property
    def evidence_list(self) -> list[dict[str, Any]]:
        return list(self.evidence_list_json or [])


# ---------------------------------------------------------------------------
# 7. context_summaries 上下文摘要表
# ---------------------------------------------------------------------------

class ContextSummary(Base):
    __tablename__ = "context_summaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    start_seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    end_seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="summaries")


# ---------------------------------------------------------------------------
# 8. websocket_tokens 长连接令牌表
# ---------------------------------------------------------------------------

class WebsocketToken(Base):
    __tablename__ = "websocket_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None


# ---------------------------------------------------------------------------
# 9. system_configs 系统配置表
# ---------------------------------------------------------------------------

class SystemConfig(Base):
    __tablename__ = "system_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    config_value: Mapped[str | None] = mapped_column(Text)
    config_group: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    description: Mapped[str | None] = mapped_column(String(512))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# 10. task_logs 任务日志表
# ---------------------------------------------------------------------------

class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analysis_tasks.id", ondelete="CASCADE"), nullable=False
    )
    log_level: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    log_type: Mapped[str] = mapped_column(String(32), nullable=False, default="lifecycle")
    log_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped[AnalysisTask] = relationship(back_populates="logs")

    __table_args__ = (Index("idx_task_time", "task_id", "created_at"),)


# ---------------------------------------------------------------------------
# 11. data_sources 业务数据源表（扩展）
# ---------------------------------------------------------------------------

class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    ds_type: Mapped[str] = mapped_column(String(32), nullable=False, default="mysql")
    host: Mapped[str | None] = mapped_column(String(128))
    port: Mapped[int | None] = mapped_column(Integer)
    db_name: Mapped[str | None] = mapped_column(String(128))
    db_user: Mapped[str | None] = mapped_column(String(128))
    db_password: Mapped[str | None] = mapped_column(String(255))
    extra_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")
    description: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    @property
    def enabled(self) -> bool:
        return self.status == "enabled"


__all__ = [
    "CONVERSATION_STATUS",
    "LOG_LEVEL",
    "LOG_TYPE",
    "MESSAGE_ROLE",
    "MESSAGE_TYPE",
    "PARSE_STATUS",
    "TASK_STATUS",
    "TASK_STATUS_TERMINAL",
    "USER_ROLE",
    "AnalysisResult",
    "AnalysisTask",
    "Attachment",
    "ContextSummary",
    "Conversation",
    "DataSource",
    "Message",
    "SystemConfig",
    "TaskLog",
    "User",
    "WebsocketToken",
]
