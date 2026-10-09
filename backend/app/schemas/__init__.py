# -*- coding: utf-8 -*-
"""后端请求 / 响应模型。

字段命名与 docs/API.md 严格一致。
成功响应不使用 code/message/data 外壳，直接返回业务字段。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ===========================================================================
# 认证
# ===========================================================================


class MeResponse(BaseModel):
    user_id: int
    username: str
    display_name: str
    role: str
    status: str
    avatar_text: str
    token_expires_in: int = Field(description="令牌剩余有效秒数")
    session_id: str | None = None


class LogoutResponse(BaseModel):
    status: str = "ok"
    message: str


# ===========================================================================
# 会话
# ===========================================================================


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255, description="会话标题，留空自动生成")


class ConversationCreateResponse(BaseModel):
    conversation_id: int
    title: str
    status: str
    created_at: str | None = None


class ConversationDeleteRequest(BaseModel):
    conversation_ids: list[int] = Field(min_length=1, description="待删除会话 ID 列表")


class ConversationDeleteResponse(BaseModel):
    deleted: int
    conversation_ids: list[int]
    removed_dirs: list[str]
    removed_files: int = 0
    freed_bytes: int = 0


class ConversationUpdateRequest(BaseModel):
    conversation_id: int
    title: str = Field(min_length=1, max_length=255)


class ConversationUpdateResponse(BaseModel):
    conversation_id: int
    title: str
    status: str
    updated_at: str | None = None


class ConversationItem(BaseModel):
    conversation_id: int
    title: str
    status: str
    last_message_at: str | None = None
    created_at: str | None = None
    message_count: int = 0
    last_message_preview: str | None = None


class AttachmentBrief(BaseModel):
    attachment_id: int
    file_name: str
    file_type: str
    file_size: int
    parse_status: str
    created_at: str | None = None


class MessageItem(BaseModel):
    message_id: int
    seq_no: int
    role: str
    message_type: str
    content: str
    tool_name: str | None = None
    tool_status: str | None = None
    task_id: int | None = None
    attachments: list[AttachmentBrief] = Field(default_factory=list)
    created_at: str | None = None


class MessageHistoryResponse(BaseModel):
    conversation_id: int
    total: int
    has_more: bool
    next_before_seq: int | None = None
    items: list[MessageItem]


# ===========================================================================
# 消息发送
# ===========================================================================


class SendMessageRequest(BaseModel):
    conversation_id: int
    content: str = Field(min_length=1, max_length=4000)
    attachment_ids: list[int] = Field(default_factory=list)

    @field_validator("content")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("提问内容不能为空")
        return v.strip()


class SendMessageResponse(BaseModel):
    conversation_id: int
    user_message_id: int
    assistant_message_id: int
    task_id: int
    task_status: str
    created_at: str | None = None


# ===========================================================================
# 附件
# ===========================================================================


class AttachmentUploadResponse(BaseModel):
    attachment_id: int
    conversation_id: int
    file_name: str
    file_path: str
    file_type: str
    file_size: int
    parse_status: str
    created_at: str | None = None


class AttachmentDeleteRequest(BaseModel):
    attachment_id: int | None = None
    attachment_ids: list[int] = Field(default_factory=list)


class AttachmentDeleteResponse(BaseModel):
    deleted: int
    attachment_ids: list[int]
    removed_files: int


class AttachmentDetail(BaseModel):
    attachment_id: int
    conversation_id: int
    message_id: int | None = None
    file_name: str
    file_path: str
    file_type: str
    file_size: int
    parse_status: str
    created_at: str | None = None
    preview: str | None = None


class AttachmentListItem(BaseModel):
    attachment_id: int
    file_name: str
    file_type: str
    file_size: int
    file_size_text: str
    parse_status: str
    parse_status_text: str
    message_id: int | None = None
    created_at: str | None = None


class AttachmentListResponse(BaseModel):
    conversation_id: int
    total: int
    items: list[AttachmentListItem]


# ===========================================================================
# 任务
# ===========================================================================


class ToolCallItem(BaseModel):
    seq: int
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    status: str
    summary: str = ""
    duration_ms: int = 0
    started_at: str | None = None
    finished_at: str | None = None


class TaskDetailResponse(BaseModel):
    task_id: int
    conversation_id: int
    user_id: int
    input_text: str
    task_status: str
    current_step: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    progress: int = 0
    step_index: int = 0
    step_total: int = 0
    tool_calls: list[ToolCallItem] = Field(default_factory=list)
    result_id: int | None = None
    created_at: str | None = None


class TaskListItem(BaseModel):
    task_id: int
    conversation_id: int
    input_text: str
    task_status: str
    current_step: str | None = None
    progress: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    result_id: int | None = None
    created_at: str | None = None


class TaskCancelResponse(BaseModel):
    task_id: int
    task_status: str
    message: str


class WsTokenRequest(BaseModel):
    conversation_id: int


class WsTokenResponse(BaseModel):
    websocket_token: str
    expires_in: int
    expires_at: str
    conversation_id: int


# ===========================================================================
# 分析结果
# ===========================================================================


class KeyMetric(BaseModel):
    metric_name: str
    metric_value: str
    metric_unit: str
    metric_period: str


class Evidence(BaseModel):
    source_type: str = Field(description="database/file/search/shell/attachment/knowledge")
    source_name: str
    evidence_text: str
    related_metric: str
    confidence: float = Field(ge=0.0, le=1.0)


class AnalysisResultResponse(BaseModel):
    result_id: int
    task_id: int
    conversation_id: int
    problem_definition: str
    key_metrics: list[KeyMetric]
    evidence_list: list[Evidence]
    conclusion_text: str
    missing_data_text: str | None = None
    next_action_text: str | None = None
    result_markdown: str | None = None
    result_file_path: str | None = None
    download_url: str
    created_at: str | None = None


# ===========================================================================
# 管理控制台
# ===========================================================================


class ConfigChangeItem(BaseModel):
    config_key: str
    old_value: str | None = None
    new_value: str | None = None


class ReloadRequest(BaseModel):
    groups: list[str] = Field(default_factory=list, description="留空表示全量重载")


class ReloadResponse(BaseModel):
    status: str
    message: str
    reloaded_groups: list[str]
    total_keys: int
    changed_keys: list[ConfigChangeItem]
    reloaded_at: str


class ConfigItem(BaseModel):
    config_key: str
    config_value: str | None = None
    config_group: str
    description: str | None = None
    updated_at: str | None = None


class ConfigListResponse(BaseModel):
    total: int
    groups: list[str]
    items: list[ConfigItem]


class ConfigUpdateRequest(BaseModel):
    config_key: str
    config_value: str


class ConfigUpdateResponse(BaseModel):
    status: str
    config_key: str
    old_value: str | None = None
    new_value: str
    need_reload: bool
    message: str


class LogItem(BaseModel):
    log_id: int
    task_id: int
    log_level: str
    log_type: str
    log_content: str
    created_at: str | None = None


class LogListResponse(BaseModel):
    total: int
    items: list[LogItem]


class OverviewCounters(BaseModel):
    users: int = 0
    conversations_active: int = 0
    messages: int = 0
    attachments: int = 0
    tasks_total: int = 0
    tasks_running: int = 0
    tasks_success: int = 0
    tasks_failed: int = 0
    tasks_cancelled: int = 0
    results: int = 0


class OverviewResponse(BaseModel):
    service: str
    version: str
    env: str
    server_time: str
    uptime_sec: int
    counters: OverviewCounters
    websocket: dict[str, Any]
    storage: dict[str, Any]
    auth_center: dict[str, Any]


class DataSourceItem(BaseModel):
    id: int
    name: str
    ds_type: str
    host: str | None = None
    port: int | None = None
    db_name: str | None = None
    status: str
    description: str | None = None
    updated_at: str | None = None


class DataSourceToggleRequest(BaseModel):
    id: int


class DataSourceToggleResponse(BaseModel):
    id: int
    name: str
    status: str
    message: str


class FeatureToggleItem(BaseModel):
    config_key: str
    name: str
    enabled: bool
    description: str | None = None


class FeatureToggleRequest(BaseModel):
    config_key: str
    enabled: bool


class AuthCenterStatusResponse(BaseModel):
    reachable: bool
    authorize_url: str
    token_url: str
    userinfo_url: str
    introspect_url: str
    client_id: str
    client_secret_masked: str
    redirect_uri: str
    introspect_cache_sec: int
    overview: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


# ===========================================================================
# WebSocket 报文（服务端 -> 客户端，需求 §12 的八种类型）
# ===========================================================================

WsMessageType = Literal[
    "message_start",
    "message_delta",
    "tool_start",
    "tool_finish",
    "task_status",
    "result_ready",
    "error",
    "done",
    "pong",
]


class WsEnvelope(BaseModel):
    """所有长连接报文的公共结构。"""

    type: str
    ts: str
    task_id: int | None = None
    conversation_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def flatten(self) -> dict[str, Any]:
        """把业务字段平铺到顶层，符合 docs/API.md §10.3 的报文形态。"""
        out: dict[str, Any] = {"type": self.type, "ts": self.ts}
        for key, value in self.payload.items():
            out[key] = value
        return out
