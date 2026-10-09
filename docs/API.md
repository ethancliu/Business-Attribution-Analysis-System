# 经营多轮归因分析系统 —— 接口说明文档

> 版本 v1.0.0 ｜ 后端服务 FastAPI ｜ 认证中心 OAuth2 授权码模式
>
> 本文档是**前后端唯一契约**。所有请求参数、响应字段均以下文为准。

## 目录

- [一、通用约定](#一通用约定)
- [二、枚举与数据结构](#二枚举与数据结构)
- [三、认证接口](#三认证接口)
- [四、会话接口](#四会话接口)
- [五、消息与分析触发接口](#五消息与分析触发接口)
- [六、附件接口](#六附件接口)
- [七、分析任务接口](#七分析任务接口)
- [八、分析结果接口](#八分析结果接口)
- [九、管理接口](#九管理接口)
- [十、长连接 WebSocket 协议](#十长连接-websocket-协议)
- [十一、附录：扩展接口清单](#十一附录扩展接口清单)

---

## 一、通用约定

### 1.1 服务地址

| 服务 | 默认地址 | 说明 |
| --- | --- | --- |
| 认证中心 auth-server | `http://localhost:9000` | OAuth2 授权码模式，独立部署 |
| 后端服务 backend | `http://localhost:8000` | 全部 `/api/**` 与 `/auth/**` |
| 前端 frontend | `http://localhost:5173` | Vue3 + Vite 开发服务器 |

### 1.2 鉴权方式

**登录态通过 HttpOnly Cookie 承载**，Cookie 名为 `jy_access_token`，值为认证中心签发的访问令牌。

```
Cookie: jy_access_token=at_xxxxxxxx
```

- 后端每次请求都会校验该令牌；校验结果在内省缓存有效期内复用（默认 60 秒）。
- 浏览器端**无需**手工附加 `Authorization` 头，同源请求会自动携带 Cookie。
- 跨域场景（前端 5173 → 后端 8000）由后端 CORS 中间件放行，需 `credentials: 'include'`。
- 同时兼容 `Authorization: Bearer <token>` 头方式，便于 curl / Postman 调试。

### 1.3 统一响应约定

**成功响应**：直接返回业务字段的 JSON 对象或数组，**不套 `code/message/data` 外壳**。

```json
{ "conversation_id": 1, "title": "美妆个护下滑归因", "status": "active" }
```

**错误响应**：使用 HTTP 状态码 + FastAPI 标准结构。

```json
{ "detail": "会话不存在或无权访问" }
```

| 状态码 | 含义 |
| --- | --- |
| 200 | 成功 |
| 400 | 参数错误 / 业务规则拒绝（如并发任务冲突） |
| 401 | 未登录或令牌失效 |
| 403 | 已登录但无权限（如非管理员访问 `/api/admin/**`） |
| 404 | 资源不存在 |
| 409 | 状态冲突（如重复删除） |
| 413 | 上传文件超过大小限制 |
| 500 | 服务端异常 |

### 1.4 时间格式

所有时间字段为 ISO 8601 本地时间字符串，精度到秒或微秒：

```
"2026-10-08T14:23:07"
"2026-10-08T14:23:07.123456"
```

### 1.5 分页约定

历史消息使用**游标分页**（基于 `seq_no` 倒序向前翻页），避免深分页性能问题。

请求：`?page_size=20&before_seq=57`
响应：`{ "items": [...], "total": 128, "has_more": true, "next_before_seq": 37 }`

---

## 二、枚举与数据结构

### 2.1 会话状态 `conversation.status`

| 值 | 含义 |
| --- | --- |
| `active` | 正常活跃 |
| `archived` | 已归档 |
| `deleted` | 已删除 |

> 删除会话为**软删除 + 级联清理**：`conversations.status` 置为 `deleted`，
> 同时硬删除该会话下的消息、附件、任务、结果、上下文摘要记录，
> 并清理 `uploads/`、`exports/`、`workspace/` 三个物理目录。

### 2.2 分析任务状态 `task_status`

| 值 | 含义 |
| --- | --- |
| `queued` | 排队中 |
| `running` | 运行中 |
| `success` | 执行成功 |
| `failed` | 执行失败 |
| `cancelled` | 已取消 |

### 2.3 消息角色 `role`

| 值 | 含义 |
| --- | --- |
| `user` | 用户 |
| `assistant` | 智能分析助手 |
| `system` | 系统 |
| `tool` | 工具执行结果 |

### 2.4 消息类型 `message_type`

| 值 | 含义 |
| --- | --- |
| `text` | 普通文本 |
| `tool_call` | 工具调用 |
| `tool_result` | 工具执行结果 |
| `result` | 结构化分析结果 |
| `error` | 错误提示 |

### 2.5 附件解析状态 `parse_status`

| 值 | 含义 |
| --- | --- |
| `pending` | 待解析 |
| `parsing` | 解析中 |
| `parsed` | 已解析 |
| `failed` | 解析失败 |

### 2.6 用户角色 `role`

| 值 | 含义 |
| --- | --- |
| `analyst` | 分析用户（普通业务用户） |
| `admin` | 系统管理员 |

### 2.7 关键指标对象 `KeyMetric`

```json
{
  "metric_name": "美妆个护点击率",
  "metric_value": "2.09",
  "metric_unit": "%",
  "metric_period": "2026-09-16 ~ 2026-09-30"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `metric_name` | string | 指标名称 |
| `metric_value` | string | 指标值（字符串，保留原始精度） |
| `metric_unit` | string | 单位，如 `%`、`万元`、`次`、`元` |
| `metric_period` | string | 统计周期描述 |

### 2.8 证据对象 `Evidence`

```json
{
  "source_type": "database",
  "source_name": "analysis_sys.biz_product",
  "evidence_text": "C01 类目 12 个在售商品的平均标题长度仅 11.4 字，主图 1.25 张，属性填充率 36.3%",
  "related_metric": "美妆个护点击率",
  "confidence": 0.92
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_type` | string | 来源类型：`database` / `file` / `search` / `shell` / `attachment` / `knowledge` |
| `source_name` | string | 来源名称（表名、文件名、命令名等） |
| `evidence_text` | string | 证据原文 |
| `related_metric` | string | 关联指标名称 |
| `confidence` | number | 置信度 0~1 |

---

## 三、认证接口

### 3.1 `GET /auth/login` 跳转认证中心发起授权登录

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `redirect` | query | 否 | 登录成功后前端落地页，默认 `/` |

**响应**：`302` 重定向至认证中心

```
Location: http://localhost:9000/oauth/authorize
          ?response_type=code
          &client_id=jingying-web
          &redirect_uri=http://localhost:8000/auth/callback
          &scope=openid profile analysis
          &state=<随机防CSRF串>
```

> 若 `state` 已存在于当前浏览器会话中则复用，避免多次点击产生堆积。

**curl 示例**

```bash
curl -i "http://localhost:8000/auth/login"
```

---

### 3.2 `GET /auth/callback` 处理授权回调、换取令牌、建立登录态

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `code` | query | 是 | 认证中心下发的授权码 |
| `state` | query | 是 | 必须与发起时一致 |

**处理流程**

1. 校验 `state` 防 CSRF；
2. 用 `code` 向认证中心 `POST /oauth/token` 换取访问令牌；
3. 调用 `POST /oauth/introspect` 校验令牌并获取用户身份；
4. 在业务库 `users` 表**自动注册或更新**用户镜像（`external_user_id` = 认证中心用户 ID）；
5. 签发本系统会话，写入 HttpOnly Cookie `jy_access_token`；
6. 302 重定向到前端回调页。

**响应**：`302`

```
Location: http://localhost:5173/#/callback?status=ok
Location: http://localhost:5173/#/callback?status=error&reason=state%20校验失败
```

同时下发 Cookie：

```
Set-Cookie: jy_access_token=at_xxxxxxxx; Path=/; HttpOnly; SameSite=Lax
```

---

### 3.3 `GET /api/auth/me` 获取当前登录用户

**响应** `200`

```json
{
  "user_id": 2,
  "username": "analyst",
  "display_name": "张分析（运营）",
  "role": "analyst",
  "status": "active",
  "avatar_text": "张",
  "token_expires_in": 6842,
  "session_id": "sess_9f2c1a..."
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `user_id` | int | 业务库用户 ID |
| `username` | string | 登录账号 |
| `display_name` | string | 显示名称 |
| `role` | string | `analyst` / `admin` |
| `status` | string | `active` / `disabled` |
| `avatar_text` | string | 头像占位文字（取 display_name 首字） |
| `token_expires_in` | int | 令牌剩余有效秒数 |
| `session_id` | string | 认证中心登录会话 ID |

---

### 3.4 `POST /api/auth/logout` 登出

**请求**：无请求体。

**响应** `200`

```json
{ "status": "ok", "message": "已登出，令牌已吊销" }
```

副作用：调用认证中心 `POST /oauth/logout` 吊销该登录会话及其下全部令牌，并清除本地 Cookie。

---

## 四、会话接口

### 4.1 `POST /api/chat/create` 新建会话

**请求体**

```json
{ "title": "美妆个护销量下滑归因" }
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 否 | 会话标题，留空则自动生成「新的分析会话」 |

**响应** `200`

```json
{
  "conversation_id": 12,
  "title": "美妆个护销量下滑归因",
  "status": "active",
  "created_at": "2026-10-08T14:23:07"
}
```

---

### 4.2 `POST /api/chat/delete` 批量删除会话

**请求体**

```json
{ "conversation_ids": [12, 13] }
```

**响应** `200`

```json
{
  "deleted": 2,
  "conversation_ids": [12, 13],
  "removed_dirs": [
    "uploads/2/12", "exports/2/12", "workspace/2/12",
    "uploads/2/13", "exports/2/13", "workspace/2/13"
  ]
}
```

**级联清理范围**（会话状态置 `deleted`，下列数据硬删除）：

| 数据 | 位置 |
| --- | --- |
| 消息记录 | `messages` |
| 附件记录 | `attachments` |
| 任务记录 | `analysis_tasks` |
| 结果记录 | `analysis_results` |
| 上下文摘要 | `context_summaries` |
| 长连接令牌 | `websocket_tokens` |
| 附件目录 | `backend/data/uploads/{user_id}/{conversation_id}/` |
| 导出目录 | `backend/data/exports/{user_id}/{conversation_id}/` |
| 临时目录 | `backend/data/workspace/{user_id}/{conversation_id}/` |

> 仅能删除属于当前登录用户的会话；越权删除返回 `404`。

---

### 4.3 `POST /api/chat/update` 修改会话名称

**请求体**

```json
{ "conversation_id": 12, "title": "美妆个护 CTR 下滑归因（已定稿）" }
```

**响应** `200`

```json
{
  "conversation_id": 12,
  "title": "美妆个护 CTR 下滑归因（已定稿）",
  "status": "active",
  "updated_at": "2026-10-08T14:31:52"
}
```

---

### 4.4 `GET /api/chat/ls` 获取会话列表

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `status` | query | 否 | 过滤状态，默认返回 `active` + `archived` |
| `keyword` | query | 否 | 标题模糊搜索 |

**响应** `200`（数组，按 `last_message_at` 倒序）

```json
[
  {
    "conversation_id": 12,
    "title": "美妆个护销量下滑归因",
    "status": "active",
    "last_message_at": "2026-10-08T14:31:52",
    "created_at": "2026-10-08T14:23:07",
    "message_count": 9,
    "last_message_preview": "从目录质量角度继续归因..."
  }
]
```

---

### 4.5 `GET /api/chat/ls/{conversation_id}` 获取会话历史消息

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page_size` | query | 否 | 默认 20，最大 200 |
| `before_seq` | query | 否 | 游标：只返回 `seq_no < before_seq` 的消息；不传则取最新一页 |

**响应** `200`

```json
{
  "conversation_id": 12,
  "total": 128,
  "has_more": true,
  "next_before_seq": 37,
  "items": [
    {
      "message_id": 57,
      "seq_no": 57,
      "role": "user",
      "message_type": "text",
      "content": "美妆个护类目近半个月销量为什么下滑？",
      "tool_name": null,
      "tool_status": null,
      "task_id": 31,
      "attachments": [
        {
          "attachment_id": 8,
          "file_name": "美妆类目9月经营明细.csv",
          "file_type": "csv",
          "file_size": 20480,
          "parse_status": "parsed",
          "created_at": "2026-10-08T14:24:10"
        }
      ],
      "created_at": "2026-10-08T14:24:12"
    }
  ]
}
```

> `items` 按 `seq_no` **升序**返回（便于前端直接追加渲染），
> 但分页游标按倒序取最新 N 条，即「先取最新一页，向上翻页加载更早的消息」。

---

## 五、消息与分析触发接口

### 5.1 `POST /api/chat/send` 发送提问消息并触发分析任务

> **说明**：本接口为规范外扩展接口。规范 §6.3 要求「用户每发送一条提问消息，对应触发一次独立的分析任务」，
> 但 §11 接口清单未列出触发入口，故新增本接口作为唯一触发点。

**请求体**

```json
{
  "conversation_id": 12,
  "content": "为什么美妆个护类目点击率腰斩？",
  "attachment_ids": [8, 9]
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | int | 是 | 目标会话 |
| `content` | string | 是 | 提问内容，1~4000 字 |
| `attachment_ids` | int[] | 否 | 随消息一并关联的附件 ID |

**响应** `200`

```json
{
  "conversation_id": 12,
  "user_message_id": 58,
  "assistant_message_id": 59,
  "task_id": 32,
  "task_status": "queued",
  "created_at": "2026-10-08T14:35:01"
}
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| `400` | 该会话已有 `running` 状态任务 → `{"detail":"该会话存在运行中的分析任务，请等待完成或先取消"}` |
| `400` | 维护模式开启且当前用户非管理员 |
| `404` | 会话不存在或不属于当前用户 |

> 触发后，**务必**先通过 `POST /api/chat/ws-token` 建立长连接，
> 否则实时事件将无处接收（任务仍会照常执行并落库，可事后通过
> `GET /api/tasks/{task_id}` 与 `GET /api/results/{task_id}` 补取）。

---

## 六、附件接口

### 6.1 `POST /api/attachment/upload` 上传附件

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | int | 是 | 所属会话 |
| `file` | file | 是 | 文件本体 |

**响应** `200`

```json
{
  "attachment_id": 21,
  "conversation_id": 12,
  "file_name": "美妆类目9月经营明细.csv",
  "file_path": "uploads/2/12/20261008_143510_美妆类目9月经营明细.csv",
  "file_type": "csv",
  "file_size": 20480,
  "parse_status": "parsed",
  "created_at": "2026-10-08T14:35:10"
}
```

**约束**

| 项 | 规则 |
| --- | --- |
| 大小上限 | `system.max_upload_mb`，默认 50 MB，超出返回 `413` |
| 允许扩展名 | `system.allow_extensions`，默认 `txt,md,csv,json,xlsx,xls,pdf,log` |
| 文件名安全 | 过滤 `..`、路径分隔符、控制字符；落盘时加时间戳前缀防覆盖 |
| 存储路径 | `backend/data/uploads/{user_id}/{conversation_id}/` |
| 解析状态 | 上传后立即触发解析；`csv/json/txt/md/log` 读入内容供分析引擎引用，其余标记 `parsed` 但仅登记元信息 |

**curl 示例**

```bash
curl -X POST "http://localhost:8000/api/attachment/upload" \
  -H "Cookie: jy_access_token=at_xxx" \
  -F "conversation_id=12" \
  -F "file=@./美妆类目9月经营明细.csv"
```

---

### 6.2 `POST /api/attachment/delete` 删除附件

**请求体**（支持单个与批量，二选一）

```json
{ "attachment_id": 21 }
```

```json
{ "attachment_ids": [21, 22, 23] }
```

**响应** `200`

```json
{ "deleted": 3, "attachment_ids": [21, 22, 23], "removed_files": 3 }
```

同时删除数据库记录与物理文件；物理文件不存在时 `removed_files` 小于 `deleted`，不视为错误。

---

### 6.3 `GET /api/attachment/get` 获取附件详情 / 下载

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `attachment_id` | query | 是 | 附件 ID |
| `meta` | query | 否 | `meta=true` 返回 JSON 详情；缺省则以附件流下载 |

**响应 A：`meta=true`**

```json
{
  "attachment_id": 21,
  "conversation_id": 12,
  "message_id": 57,
  "file_name": "美妆类目9月经营明细.csv",
  "file_path": "uploads/2/12/20261008_143510_美妆类目9月经营明细.csv",
  "file_type": "csv",
  "file_size": 20480,
  "parse_status": "parsed",
  "created_at": "2026-10-08T14:35:10",
  "preview": "类目,商品数,曝光,点击,下单\n美妆个护,12,33600,703,21\n..."
}
```

`preview` 为文本类附件的首 500 字预览，二进制附件为 `null`。

**响应 B：默认下载**

```
HTTP/1.1 200 OK
Content-Type: text/csv
Content-Disposition: attachment; filename*=UTF-8''%E7%BE%8E%E5%A6%86...
Content-Length: 20480
```

> 路径安全：下载前校验解析后的绝对路径必须位于 `uploads/` 根目录内，
> 防止 `../../` 路径穿越。

---

### 6.4 `GET /api/attachment/ls` 获取会话附件列表

> **说明**：规范外扩展接口。§5.4 要求「附件侧栏」展示当前会话下全部附件，
> 但 §11 未提供列表接口，故新增。

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | query | 是 | 会话 ID |
| `parse_status` | query | 否 | 按解析状态过滤 |

**响应** `200`

```json
{
  "conversation_id": 12,
  "total": 3,
  "items": [
    {
      "attachment_id": 21,
      "file_name": "美妆类目9月经营明细.csv",
      "file_type": "csv",
      "file_size": 20480,
      "file_size_text": "20.0 KB",
      "parse_status": "parsed",
      "parse_status_text": "已解析",
      "message_id": 57,
      "created_at": "2026-10-08T14:35:10"
    }
  ]
}
```

---

## 七、分析任务接口

### 7.1 `GET /api/tasks/{task_id}` 获取任务详情

**响应** `200`

```json
{
  "task_id": 32,
  "conversation_id": 12,
  "user_id": 2,
  "input_text": "为什么美妆个护类目点击率腰斩？",
  "task_status": "success",
  "current_step": "分析完成，结构化结果已生成",
  "started_at": "2026-10-08T14:35:01",
  "finished_at": "2026-10-08T14:35:06",
  "error_message": null,
  "duration_ms": 5120,
  "progress": 100,
  "step_index": 8,
  "step_total": 8,
  "tool_calls": [
    {
      "seq": 1,
      "tool_name": "db_query",
      "tool_args": { "sql": "SELECT ..." },
      "status": "success",
      "summary": "返回 5 行，耗时 42ms",
      "duration_ms": 42,
      "started_at": "2026-10-08T14:35:01",
      "finished_at": "2026-10-08T14:35:02"
    }
  ],
  "result_id": 17,
  "created_at": "2026-10-08T14:35:01"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_status` | string | 见 §2.2 |
| `current_step` | string | 当前执行步骤描述 |
| `started_at` | string\|null | 开始执行时间 |
| `finished_at` | string\|null | 结束时间 |
| `error_message` | string\|null | 失败原因 |
| `progress` | int | 进度百分比 0~100 |
| `step_index` / `step_total` | int | 步骤进度 |
| `tool_calls` | array | 工具调用流水 |
| `result_id` | int\|null | 成功时对应的结果 ID |

---

### 7.2 `GET /api/tasks` 获取任务列表

> **说明**：规范外扩展接口，用于「实时任务区」回溯历史任务。

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | query | 否 | 按会话过滤 |
| `task_status` | query | 否 | 按状态过滤 |
| `limit` | query | 否 | 默认 20，最大 200 |

**响应** `200`：任务对象数组（字段同 7.1 的精简版：`task_id`、`conversation_id`、`input_text`、`task_status`、`current_step`、`progress`、`started_at`、`finished_at`、`error_message`、`result_id`）。

---

### 7.3 `POST /api/tasks/{task_id}/cancel` 取消分析任务

> **说明**：规范外扩展接口。§6.2 定义了 `cancelled` 状态、§7.3 要求「分析任务取消」，
> §11 未提供取消接口，故新增。

**响应** `200`

```json
{ "task_id": 32, "task_status": "cancelled", "message": "任务已取消" }
```

**错误**

| 状态码 | 场景 |
| --- | --- |
| `409` | 任务已处于 `success` / `failed` / `cancelled` 终态 |

---

### 7.4 `POST /api/chat/ws-token` 获取长连接令牌

**请求体**

```json
{ "conversation_id": 12 }
```

**响应** `200`

```json
{
  "websocket_token": "wst_7f3a9c2e8b1d4a6f...",
  "expires_in": 300,
  "expires_at": "2026-10-08T14:40:01",
  "conversation_id": 12
}
```

**规则**

- 令牌**一次性消费**：WebSocket 握手成功后立即写入 `consumed_at`。
- 有效期默认 300 秒，未消费即过期需重新签发。
- 令牌与 `user_id`、`conversation_id` 强绑定，跨会话使用返回 `403`。
- 断线重连必须重新调用本接口获取新令牌。

---

## 八、分析结果接口

### 8.1 `GET /api/results/{task_id}` 获取结构化分析结果

**响应** `200`

```json
{
  "result_id": 17,
  "task_id": 32,
  "conversation_id": 12,
  "problem_definition": "定位 2026-09-16 至 2026-09-30 期间美妆个护类目点击率腰斩的核心原因，评估其对整体 GMV 的影响范围。",
  "key_metrics": [
    {
      "metric_name": "美妆个护点击率",
      "metric_value": "2.09",
      "metric_unit": "%",
      "metric_period": "2026-09-16 ~ 2026-09-30"
    },
    {
      "metric_name": "对照组（其它类目）点击率",
      "metric_value": "5.48",
      "metric_unit": "%",
      "metric_period": "2026-09-16 ~ 2026-09-30"
    }
  ],
  "evidence_list": [
    {
      "source_type": "database",
      "source_name": "analysis_sys.biz_product_click",
      "evidence_text": "美妆个护 CTR 由基准期 4.20% 降至异常期 2.09%，同期其它类目稳定在 5.45%~5.52%",
      "related_metric": "美妆个护点击率",
      "confidence": 0.95
    }
  ],
  "conclusion_text": "美妆个护类目点击率腰斩属于「类目内商品目录质量退化 + 高意图搜索词供给缺失」的复合型问题……",
  "missing_data_text": "1. 缺少商品详情页的跳出率与停留时长数据，无法判断详情页承接能力；\n2. 缺少竞品同期价格与活动数据，无法排除外部竞争因素。",
  "next_action_text": "1. 【目录优化】对 C01 类目 12 个商品批量重写标题至 25 字以上、补足 5 张主图、属性填充率提升至 85% 以上，预计 CTR 可回升至 4.5% 以上；\n2. 【供给补齐】针对「氨基酸洁面」「玻尿酸精华」「神经酰胺」3 个空搜索量放大 3.7~3.9 倍的高意图词，优先招商上架对应商品；\n3. 【监控机制】建立类目目录质量日报，标题字数 <15 或主图 <3 张的 SKU 自动告警。",
  "result_markdown": "# 美妆个护类目点击率腰斩归因分析报告\n\n## 一、问题定义\n...",
  "result_file_path": "exports/2/12/20261008_143506_task32_归因分析报告.md",
  "download_url": "/api/results/17/download",
  "created_at": "2026-10-08T14:35:06"
}
```

**六大固定模块**（规范 §13 强制）：

| 序号 | 字段 | 类型 | 说明 |
| --- | --- | --- | --- |
| 1 | `problem_definition` | string | 问题定义 |
| 2 | `key_metrics` | KeyMetric[] | 关键指标 |
| 3 | `evidence_list` | Evidence[] | 证据列表 |
| 4 | `conclusion_text` | string | 归因结论 |
| 5 | `missing_data_text` | string | 待补充数据 |
| 6 | `next_action_text` | string | 下一步建议（**至少 2 条**） |

**错误**：任务未成功完成时返回 `404` `{"detail":"该任务尚未生成分析结果"}`。

---

### 8.2 `GET /api/results/download` 下载结果文件

> **说明**：规范外扩展接口，对应 §5.6「报告文件导出」与验收标准 6「支持分析结果导出、文件重新下载」。

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `result_id` | query | 是 | 结果 ID |
| `format` | query | 否 | `md`（默认）/ `json` / `xlsx` |

**响应**：文件流

```
Content-Type: text/markdown; charset=utf-8
Content-Disposition: attachment; filename*=UTF-8''...归因分析报告.md
```

| `format` | Content-Type | 内容 |
| --- | --- | --- |
| `md`（默认） | `text/markdown; charset=utf-8` | 完整分析报告，六段式 Markdown |
| `json` | `application/json; charset=utf-8` | 六模块完整 JSON，便于二次加工 |
| `xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | 多工作表 Excel：概览、关键指标、证据列表（由 openpyxl 生成） |

**等价别名**：`GET /api/results/{result_id}/download?format=...` 与上表接口完全等价，
`result_id` 走路径参数而非查询参数，仅为兼容不同调用习惯。

> 注册顺序提醒：`/api/results/download` 必须早于 `/api/results/{task_id}` 注册，
> 否则 FastAPI 会把字面量 `download` 当作 `task_id` 去解析成 int 而返回 422。

---

## 九、管理接口

> 以下接口全部要求当前用户 `role == admin`，否则返回 `403`。

### 9.1 `POST /api/admin/reload` 配置热重载

**请求体**：无。可选 `{ "groups": ["analysis", "feature"] }` 只重载指定分组。

**响应** `200`

```json
{
  "status": "ok",
  "message": "配置热重载完成，共加载 48 项配置（其中 12 项发生变化），无需重启服务",
  "reloaded_groups": ["all"],
  "total_keys": 48,
  "changed_keys": [
    { "config_key": "analysis.step_interval_ms", "old_value": "300", "new_value": "120" }
  ],
  "reloaded_at": "2026-10-08T14:40:12"
}
```

**生效范围**：配置写入 `system_configs` 表后调用本接口，内存缓存立即刷新，
后续请求读取新值，**无需重启后端进程**。

---

### 9.2 `GET /api/admin/configs` 查看系统配置

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `group` | query | 否 | `system` / `analysis` / `auth` / `storage` / `llm` / `feature` / `security` / `dict` |

**响应** `200`

```json
{
  "total": 48,
  "groups": ["analysis", "auth", "dict", "feature", "llm", "security", "storage", "system"],
  "items": [
    {
      "config_key": "analysis.tool_timeout_sec",
      "config_value": "60",
      "config_group": "analysis",
      "description": "单个工具执行超时时间（秒）",
      "updated_at": "2026-10-08T12:00:00"
    }
  ]
}
```

**`secret_fields`**：`auth.client_secret`、`llm.api_key` 等敏感项返回时以 `******` 脱敏。

---

### 9.3 `POST /api/admin/configs/update` 修改系统配置

**请求体**

```json
{ "config_key": "analysis.step_interval_ms", "config_value": "120" }
```

**响应** `200`

```json
{
  "status": "ok",
  "config_key": "analysis.step_interval_ms",
  "old_value": "300",
  "new_value": "120",
  "need_reload": true,
  "message": "已写入数据库，调用 POST /api/admin/reload 后生效"
}
```

---

### 9.4 `GET /api/admin/logs` 查询系统运行日志

**请求**

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_id` | query | 否 | 按任务过滤 |
| `log_level` | query | 否 | `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `log_type` | query | 否 | `lifecycle` / `tool` / `llm` / `db` / `file` / `error` |
| `keyword` | query | 否 | 日志内容模糊搜索 |
| `limit` | query | 否 | 默认 100，最大 1000 |

**响应** `200`

```json
{
  "total": 42,
  "items": [
    {
      "log_id": 318,
      "task_id": 32,
      "log_level": "INFO",
      "log_type": "tool",
      "log_content": "[db_query] 执行成功，返回 5 行，耗时 42ms",
      "created_at": "2026-10-08T14:35:02"
    }
  ]
}
```

---

### 9.5 `GET /api/admin/overview` 系统运行状态总览

**响应** `200`

```json
{
  "service": "经营多轮归因分析系统",
  "version": "1.0.0",
  "env": "dev",
  "server_time": "2026-10-08T14:41:00",
  "uptime_sec": 3620,
  "counters": {
    "users": 3,
    "conversations_active": 5,
    "messages": 128,
    "attachments": 6,
    "tasks_total": 21,
    "tasks_running": 1,
    "tasks_success": 18,
    "tasks_failed": 1,
    "tasks_cancelled": 1,
    "results": 18
  },
  "websocket": {
    "active_connections": 1,
    "total_connections": 34,
    "bound_conversations": [12]
  },
  "storage": {
    "uploads_files": 6,
    "uploads_size_mb": 0.42,
    "exports_files": 18,
    "exports_size_mb": 0.11,
    "workspace_files": 12,
    "workspace_size_mb": 0.03
  },
  "auth_center": {
    "reachable": true,
    "authorize_url": "http://localhost:9000/oauth/authorize"
  }
}
```

---

### 9.6 `GET /api/admin/datasources` / `POST /api/admin/datasources/toggle` 业务数据源管理

**`GET /api/admin/datasources` 响应** `200`

```json
[
  {
    "id": 1,
    "name": "主业务库",
    "ds_type": "mysql",
    "host": "127.0.0.1",
    "port": 3306,
    "db_name": "analysis_sys",
    "status": "enabled",
    "description": "经营分析主业务库，承载全部演示场景数据",
    "updated_at": "2026-10-08T12:00:00"
  }
]
```

**`POST /api/admin/datasources/toggle` 请求体**

```json
{ "id": 1 }
```

**响应**

```json
{ "id": 1, "name": "主业务库", "status": "disabled", "message": "数据源状态已切换为 disabled" }
```

> 停用后分析引擎的 `db_query` 工具将以 `[WARN]` 记录并降级为「无数据库证据」结论分支。

---

### 9.7 `GET /api/admin/feature-toggles` / `POST /api/admin/feature-toggles/toggle` 功能开关

**`GET /api/admin/feature-toggles` 响应** `200`

```json
[
  { "config_key": "feature.enable_shell_tool", "name": "命令执行工具", "enabled": true, "description": "是否启用命令执行工具（白名单受控）" },
  { "config_key": "feature.enable_file_write", "name": "文件写入工具", "enabled": true, "description": "是否启用文件写入工具" },
  { "config_key": "feature.enable_export", "name": "结果导出", "enabled": true, "description": "是否启用分析结果导出" },
  { "config_key": "feature.enable_ws_stream", "name": "长连接实时推送", "enabled": true, "description": "是否启用长连接实时推送" },
  { "config_key": "feature.enable_multi_turn", "name": "多轮追问", "enabled": true, "description": "是否启用多轮追问" },
  { "config_key": "feature.maintenance_mode", "name": "维护模式", "enabled": false, "description": "维护模式，开启后除管理员外禁止发起分析" }
]
```

**`POST /api/admin/feature-toggles/toggle` 请求体**

```json
{ "config_key": "feature.enable_shell_tool", "enabled": false }
```

---

### 9.8 `GET /api/admin/auth-center` 认证中心状态

**响应** `200`

```json
{
  "reachable": true,
  "authorize_url": "http://localhost:9000/oauth/authorize",
  "token_url": "http://localhost:9000/oauth/token",
  "userinfo_url": "http://localhost:9000/oauth/userinfo",
  "introspect_url": "http://localhost:9000/oauth/introspect",
  "client_id": "jingying-web",
  "client_secret_masked": "jing****2026",
  "redirect_uri": "http://localhost:8000/auth/callback",
  "introspect_cache_sec": 60,
  "overview": {
    "users": 3,
    "active_users": 3,
    "sessions_active": 2,
    "tokens_alive": 4
  }
}
```

### 9.9 `GET /api/admin/scenarios` / `GET /api/admin/tools` 场景与工具清单

> **说明**：本组接口为规范外扩展，用于让管理控制台（以及文档）直接读到运行时**实际注册**的场景与工具，
> 避免「文档里写了、代码里没有」这类漂移。两个接口都要求 `role == admin`。

**`GET /api/admin/scenarios` 响应** `200`

```json
{
  "total": 7,
  "items": [
    {
      "key": "catalog",
      "name": "商品目录质量归因",
      "description": "定位品类级曝光转化下滑，归因到商品标题、主图、属性、搜索承接等目录质量问题",
      "strong_keywords": ["目录质量", "商品标题", "主图", "属性填充", "商品卡"],
      "keywords": ["点击率", "ctr", "曝光", "转化下滑", "..."],
      "is_fallback": false
    }
  ]
}
```

`is_fallback` 标识该场景是否为兜底场景（当前仅 `generic` 为 `true`）。

**`GET /api/admin/tools` 响应** `200`

```json
{
  "total": 6,
  "items": [
    {
      "name": "db_query",
      "description": "对业务库执行只读 SQL 查询",
      "signature": {
        "sql": "只读 SELECT/WITH 语句，只能查询 biz_* 业务表",
        "limit": "最大返回行数，默认 100，上限 500"
      }
    }
  ]
}
```

`signature` 是「参数名 → 参数说明」的字典，供前端工具卡片逐项展示。当前注册 6 个工具：
`db_query` / `file_read` / `file_write` / `text_search` / `shell_exec` / `result_generate`。

---

## 附：服务可用性探针（非业务接口）

以下两个接口**无需认证**，供部署探活与前端启动自检使用。

### `GET /healthz` 健康检查

```json
{
  "status": "ok",
  "database": "ok",
  "websocket_connections": 0,
  "uptime_sec": 888,
  "config_source": "database",
  "auth_center": { "reachable": true, "message": "经营多轮归因分析系统-认证中心 v1.0.0" },
  "time": "2026-10-08T19:27:15.712026"
}
```

注意本接口**始终返回 `200`**，健康状态靠响应体表达，而不是靠 HTTP 状态码：

| 字段 | 取值 | 含义 |
| --- | --- | --- |
| `status` | `ok` / `degraded` | `degraded` 表示数据库探测失败 |
| `database` | `ok` / `error` | 数据库连通性 |
| `auth_center.reachable` | `true` / `false` | 认证中心是否可达；为 `false` **不影响**本接口返回 200，也不影响已登录会话，只影响新的登录 |

`config_source` 为 `env` 或 `database`，可用于确认配置实际来自哪一层。

### `GET /` 服务根路径

```json
{
  "service": "经营多轮归因分析系统",
  "version": "1.0.0",
  "docs": "/docs",
  "websocket": "/api/chat/ws/chat",
  "time": "2026-10-08T19:27:15.712026"
}
```

用于确认目标端口上跑的确实是本服务（以及它的 WebSocket 路径）。

---

## 十、长连接 WebSocket 协议

### 10.1 连接

```
ws://localhost:8000/api/chat/ws/chat?websocket_token=<wst_xxx>&conversation_id=12
```

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `websocket_token` | 是 | 由 `POST /api/chat/ws-token` 签发 |
| `conversation_id` | 是 | 必须与签发时的绑定一致 |

**握手校验顺序**

1. 令牌不存在 / 已过期 → 关闭码 `4001`，原因 `invalid_token`
2. 令牌已被消费 → 关闭码 `4001`，原因 `token_consumed`
3. `conversation_id` 与令牌绑定不一致 → 关闭码 `4003`，原因 `conversation_mismatch`
4. 会话不属于该用户 → 关闭码 `4003`，原因 `forbidden`

校验通过后写入 `consumed_at`，**令牌立即失效**；断线重连需重新申请。

**关闭码约定**

| 关闭码 | 含义 | 前端处理 |
| --- | --- | --- |
| `1000` | 正常关闭 | 不重连 |
| `4001` | 令牌无效/已消费/过期 | 重新调用 `/api/chat/ws-token` 后重连 |
| `4003` | 会话不匹配或无权限 | 不重连，提示用户 |
| `1011` | 服务端异常 | 3 秒后重连 |

### 10.2 客户端 → 服务端

| 类型 | 报文 | 说明 |
| --- | --- | --- |
| 心跳 | `{"type":"ping"}` | 建议 25 秒一次；服务端回 `{"type":"pong","ts":"..."}` |

### 10.3 服务端 → 客户端

所有报文均为 JSON 对象，`type` 字段区分类型，并统一带 `ts`（服务端时间戳）。

#### 1. `message_start` —— 分析开始

```json
{
  "type": "message_start",
  "task_id": 32,
  "conversation_id": 12,
  "message_id": 59,
  "user_message_id": 58,
  "input_text": "为什么美妆个护类目点击率腰斩？",
  "scenario": "商品目录优化",
  "step_total": 8,
  "ts": "2026-10-08T14:35:01"
}
```

#### 2. `message_delta` —— 文本增量输出

```json
{
  "type": "message_delta",
  "task_id": 32,
  "delta_text": "正在识别业务场景：商品目录优化\n",
  "seq": 3,
  "ts": "2026-10-08T14:35:01"
}
```

> 前端按到达顺序拼接 `delta_text` 即为流式正文；`seq` 用于乱序检测。

#### 3. `tool_start` —— 工具开始执行

```json
{
  "type": "tool_start",
  "task_id": 32,
  "tool_name": "db_query",
  "tool_args": { "sql": "SELECT category_id, SUM(click_cnt)...", "purpose": "对比类目点击率两期变化" },
  "tool_call_seq": 1,
  "ts": "2026-10-08T14:35:01"
}
```

#### 4. `tool_finish` —— 工具执行完成

```json
{
  "type": "tool_finish",
  "task_id": 32,
  "tool_name": "db_query",
  "tool_call_seq": 1,
  "status": "success",
  "tool_result_summary": "返回 5 行，耗时 42ms：美妆个护 CTR 4.20% → 2.09%",
  "duration_ms": 42,
  "rows": 5,
  "ts": "2026-10-08T14:35:02"
}
```

`status` 取值：`success` / `failed`。

#### 5. `task_status` —— 任务状态变更

```json
{
  "type": "task_status",
  "task_id": 32,
  "task_status": "running",
  "current_step": "步骤 3/8：对比类目点击率两期变化",
  "progress": 37,
  "step_index": 3,
  "step_total": 8,
  "ts": "2026-10-08T14:35:02"
}
```

#### 6. `result_ready` —— 结构化结果生成完成

```json
{
  "type": "result_ready",
  "task_id": 32,
  "result_id": 17,
  "conversation_id": 12,
  "download_url": "/api/results/17/download",
  "ts": "2026-10-08T14:35:06"
}
```

#### 7. `error` —— 任务执行失败

```json
{
  "type": "error",
  "task_id": 32,
  "error_message": "[db_query] 数据源「主业务库」已停用，无法获取数据库证据",
  "error_stage": "tool_execute",
  "ts": "2026-10-08T14:35:03"
}
```

#### 8. `done` —— 本轮分析彻底结束

```json
{
  "type": "done",
  "task_id": 32,
  "conversation_id": 12,
  "task_status": "success",
  "finished_at": "2026-10-08T14:35:06",
  "duration_ms": 5120,
  "ts": "2026-10-08T14:35:06"
}
```

> `done` 是**每轮分析的最后一个报文**，无论成功、失败还是取消都会下发。
> 前端收到 `done` 后应关闭本轮 loading、刷新会话列表与结果区。
> `error` 之后仍会跟一个 `done`（`task_status = failed`）。

### 10.4 一轮分析的完整报文时序

```
客户端                          服务端
  │  POST /api/chat/send          │
  │ ──────────────────────────────▶│  创建 user/assistant 消息 + task(queued)
  │  POST /api/chat/ws-token      │
  │ ──────────────────────────────▶│  签发一次性令牌
  │  WS 握手                       │
  │ ──────────────────────────────▶│  校验并消费令牌
  │                               │
  │ ◀── message_start             │  task: queued → running
  │ ◀── task_status (5%, step1)   │
  │ ◀── message_delta × N         │  流式思考文本
  │ ◀── tool_start  (db_query)    │
  │ ◀── tool_finish (db_query)    │
  │ ◀── task_status (37%, step3)  │
  │ ◀── tool_start  (file_read)   │
  │ ◀── tool_finish (file_read)   │
  │ ◀── ...                       │
  │ ◀── message_delta × N         │
  │ ◀── result_ready              │  六大模块结果落库 + 导出文件生成
  │ ◀── task_status (100%, 完成)  │
  │ ◀── done                      │  task: running → success
```

---

## 十一、附录：扩展接口清单

规范 §11 列出的 15 个接口**全部实现**。此外为满足规范其它条款的完整闭环，
新增以下 10 个扩展接口，均已在正文中标注：

| # | 接口 | 对应规范条款 | 新增原因 |
| --- | --- | --- | --- |
| 1 | `POST /api/chat/send` | §6.3 一条提问一条任务 | 规范未提供分析触发入口 |
| 2 | `GET /api/attachment/ls` | §5.4 附件侧栏 | 规范未提供附件列表接口 |
| 3 | `POST /api/tasks/{task_id}/cancel` | §6.2 `cancelled` 状态、§7.3 任务取消 | 规范未提供取消接口 |
| 4 | `GET /api/tasks` | §5.5 实时任务区 | 任务区需回溯历史任务 |
| 5 | `GET /api/results/download` | §5.6 报告导出、验收标准 6 | 规范未提供文件下载接口 |
| 6 | `GET /api/auth/me` | §5.2 登录态校验 | 前端需获取当前用户与角色 |
| 7 | `POST /api/auth/logout` | §3.1 会话全生命周期 | 需提供登出闭环 |
| 8 | `GET /api/admin/configs` | §4.2 维护系统配置 | 需查看配置才能维护 |
| 9 | `POST /api/admin/configs/update` | §4.2 维护系统配置 | 需修改配置才能热重载 |
| 10 | `GET /api/admin/overview` / `datasources` / `feature-toggles` / `auth-center` | §4.2 管控系统运行状态、管理数据源、启停功能开关 | 管理员控制台数据来源 |

### 认证中心接口（独立服务，端口 9000）

| 接口 | 说明 |
| --- | --- |
| `GET /oauth/authorize` | 授权入口，未登录返回登录页，已登录 302 带授权码回跳 |
| `POST /oauth/login` | 提交账号口令，建立登录会话，302 带授权码回跳 |
| `POST /oauth/token` | 授权码 / 刷新令牌换取访问令牌 |
| `GET /oauth/userinfo` | 依据 Bearer 令牌返回用户信息 |
| `POST /oauth/introspect` | 令牌内省，返回 `active` 及身份信息 |
| `POST /oauth/revoke` | 吊销单个访问令牌 |
| `POST /oauth/logout` | 登出，吊销会话及其下全部令牌 |
| `GET /oauth/sessions` | 登录会话列表（全生命周期管理） |
| `GET /oauth/healthz` | 健康检查 |
| `GET /admin/overview` 等 | 认证中心自管理接口，需请求头 `X-Admin-Key` |
