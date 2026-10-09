# 架构设计说明

本文说明「经营多轮归因分析系统」的总体结构、模块划分、关键链路与设计取舍。接口字段级约定见 [API.md](API.md)，部署步骤见 [DEPLOY.md](DEPLOY.md)，业务演示见 [DEMO.md](DEMO.md)。

---

## 一、总体架构

系统由三个可独立部署的服务与一个数据库构成，前端不直连数据库、也不直连认证中心。

```
                        ┌───────────────────────────────┐
   浏览器  ──────────►  │  前端 frontend/  :5173        │
                        │  Vue 3 + Vite + Element Plus  │
                        └───────┬───────────────┬───────┘
              HTTP /api /auth   │               │  WebSocket /api/chat/ws/chat
              (Vite Dev 代理)    │               │  (Vite Dev 代理, ws: true)
                                ▼               ▼
                        ┌───────────────────────────────┐        ┌──────────────────────────┐
                        │  业务后端 backend/  :8000      │        │  认证中心 auth-server/    │
                        │  FastAPI + SQLAlchemy          │───────►│  :9000  FastAPI           │
                        │                                │ OAuth2 │  授权 / 令牌 / 内省       │
                        │  api / services / analysis /   │  HTTP  │                          │
                        │  ws / core                     │        └──────────┬───────────────┘
                        └───────┬────────────────┬───────┘                   │
                                │                │                           │
                        SQLAlchemy (PyMySQL)      │ 文件落盘                   │ SQLAlchemy
                                ▼                ▼                           ▼
                        ┌────────────────────────────────┐      ┌────────────────────────┐
                        │  MySQL 8.0  @127.0.0.1:3306     │      │  MySQL `analysis_auth` │
                        │  analysis_sys  业务库           │      └────────────────────────┘
                        │  data/uploads|exports|workspace │
                        └────────────────────────────────┘
```

| 服务 | 技术栈 | 端口 | 职责 |
| --- | --- | --- | --- |
| `auth-server/` | FastAPI + SQLAlchemy | 9000 | 独立的认证中心：登录、签发授权码与访问令牌、令牌内省、登出、认证自管理 |
| `backend/` | FastAPI + SQLAlchemy 2.0 + PyMySQL | 8000 | 会话、消息、附件、分析任务、分析引擎、结果、配置、WebSocket 推送 |
| `frontend/` | Vue 3 + Vite 6 + Element Plus 2.9 | 5173 | 五个页面的交互层，全部请求走相对路径由 Vite 代理到后端 |
| MySQL | 8.0.26 | 3306 | `analysis_auth`（认证域 6 张表）+ `analysis_sys`（业务域 33 张表） |

**为什么把认证拆成独立服务**：业务后端不持有任何口令与令牌签发逻辑，访问令牌是不透明字符串（opaque token），后端无法本地校验，只能通过认证中心的 `/oauth/introspect` 判定有效性。这样令牌吊销、会话强制下线、口令重置都在认证中心一处生效，业务后端只读缓存结果（默认 60 秒 TTL）。

---

## 二、后端分层

`backend/app/` 严格按「接口层 → 服务层 → 模型层」组织，横切能力放在 `core/`，分析能力自成一包。

| 目录 | 文件 | 职责 |
| --- | --- | --- |
| `api/` | `auth.py` | 跳转认证中心、处理回调、登录态查询、登出 |
| | `chat.py` | 会话增删改查、历史消息游标分页、发送提问、下发一次性长连接令牌 |
| | `attachment.py` | 附件上传（落盘 + 落库 + 即时解析）、列表、详情、下载、删除 |
| | `tasks.py` | 任务详情（含工具调用链）、任务列表（支持按会话和状态过滤）、取消 |
| | `results.py` | 六大模块结构化结果、md/json/xlsx 导出下载 |
| | `admin.py` | 运行总览、配置查看与修改、热重载、功能开关、数据源、场景与工具清单、运行日志 |
| `services/` | `conversation.py` | 会话生命周期；删除时级联清理消息、附件、任务、结果与三个文件目录 |
| | `message.py` | 消息读写、游标分页、助手消息占位与正文回填 |
| | `chat.py` | 一轮提问的编排：落用户消息 → 建任务 → 建助手占位 → 投递线程池 |
| | `attachment.py` | 附件类型与大小校验、落盘、文本/表格解析与预览摘要 |
| | `task.py` | 任务状态机、进度换算、工具调用记录、任务日志 |
| | `result.py` | 六模块结果的落库与序列化、三种格式导出（md / json / xlsx） |
| | `context.py` | 多轮上下文装配：历史消息注入、超长对话摘要压缩、上一轮场景与结论复用 |
| `analysis/` | `engine.py` | 一次分析任务的主流程（8 个阶段，见下文） |
| | `tools/` | 6 个可被分析步骤调用的工具（见 §五） |
| | `scenarios/` | 6 个专有业务场景 + 1 个通用兜底场景，以及关键词计分路由 |
| | `llm.py` | 结论文案生成，规则引擎兜底，无外部模型依赖也能跑通全链路 |
| `ws/` | `manager.py` | 会话级连接管理、跨线程推送、迟到补发缓存 |
| | `routes.py` | 握手校验（一次性令牌）、连接登记、关闭码约定 |
| | `emitter.py` | 把 8 种报文类型收敛成 8 个函数，供引擎调用 |
| `core/` | `config.py` | `.env` 静态配置（数据库、端口、认证中心地址、存储根目录） |
| | `runtime_config.py` | 数据库配置的内存缓存与热更新（见 §七） |
| | `security.py` | 认证中心客户端 + 令牌内省缓存 |
| | `deps.py` | 依赖注入：取当前用户、取令牌信息、管理员角色校验 |
| | `db.py` | 引擎与会话工厂、`session_scope()` 上下文管理器 |
| | `paths.py` | 存储目录规范、文件名清洗、路径穿越防护、目录级联删除 |
| `models/` | `__init__.py` | 11 张核心表的 ORM 定义 |
| `schemas/` | `__init__.py` | 请求体 Pydantic 模型（响应统一用手写 dict 序列化） |

接口层不写业务逻辑，服务层不感知 HTTP，分析包不直接操作 WebSocket（一律经 `ws/emitter.py`）。

---

## 三、一次分析的完整时序

用户点「发送」到看见结果，跨进程、跨线程、跨 HTTP 与 WebSocket 两条通道：

```
前端                 后端 api/chat          services/chat       线程池         analysis/engine        ws/emitter
 │                      │                      │                 │                 │                    │
 │─ POST /api/chat/send ►│                      │                 │                 │                    │
 │                      │── 校验会话归属 ──────►│                 │                 │                    │
 │                      │                      │─ 落用户消息      │                 │                    │
 │                      │                      │─ 建任务(queued)  │                 │                    │
 │                      │                      │─ 建助手占位消息  │                 │                    │
 │                      │                      │─ submit ───────►│                 │                    │
 │◄── 200 {task_id} ────│                      │                 │─ run_task ─────►│                    │
 │                      │                      │                 │                 │                    │
 │ (此前已连上 WebSocket)│                      │                 │  1 prepare 装配多轮上下文            │
 │                      │                      │                 │  2 route   场景路由                  │
 │                      │                      │                 │  3 start   running ────────────────► message_start
 │                      │                      │                 │  4 run     逐步执行步骤链 ──────────► tool_start
 │◄══════════════ 服务端主动推送 ═══════════════════════════════════════════════════════════════════════╡
 │                      │                      │                 │                 │────────────────────► tool_finish
 │                      │                      │                 │                 │────────────────────► task_status
 │                      │                      │                 │  5 interpret 产出六大模块            │
 │                      │                      │                 │  6 generate  生成报告 ─────────────► message_delta（流式）
 │                      │                      │                 │  7 persist   落库结果 + 回填助手消息  │
 │                      │                      │                 │  8 finish ─────────────────────────► result_ready
 │                      │                      │                 │                 │────────────────────► done
```

八个阶段分别是 `prepare / route / start / run / interpret / generate / persist / finish`，任意阶段收到取消信号都会跳到 `TaskCancelled` 分支，把任务落成 `cancelled` 并推 `error` 与 `done`。

**任务状态机**：

```
queued ──► running ──┬──► success
                     ├──► failed      （工具异常 / 引擎异常 / 服务重启遗留）
                     └──► cancelled   （用户点取消）
```

约束：同一会话同一时刻只允许一个 `queued/running` 任务，重复提交返回 409 并带上正在运行的任务 ID。

---

## 四、实时推送链路

这是本项目最容易出问题的一环，有三处专门设计。

### 4.1 跨线程推送

分析在 `ThreadPoolExecutor` 中执行（避免长任务阻塞事件循环），但 WebSocket 发送必须在事件循环里做。`ConnectionManager` 在应用启动的 `lifespan` 中捕获主事件循环：

```python
manager.bind_loop(asyncio.get_running_loop())   # main.py lifespan 第 2 步
```

任务线程通过 `asyncio.run_coroutine_threadsafe()` 把报文投递回主循环：

```
analysis 线程 ──► emitter.emit() ──► manager.push() ──► run_coroutine_threadsafe ──► 主事件循环 ──► ws.send_json
```

`push()` 内部只做加锁登记与投递，不做任何阻塞 I/O，因此可以被引擎在任意步骤反复调用。

### 4.2 迟到补发

一次分析通常只跑数百毫秒——客户端完全可能「任务已经跑完，WebSocket 才连上」（尤其在开发机上），刷新页面重连时更是必然错过前半程。

因此 `manager` 为每个会话保留**最近一轮的报文环形缓存**（单会话上限 400 条，最多缓存 200 个会话，超限按插入顺序淘汰）：

1. `push()` 无论当前是否有在线连接，都先把报文写入缓存；
2. 新连接通过握手后，先回 `connected`，紧接着 `await manager.replay(conn)` 把本轮报文原样补发一遍，每条附加 `"replayed": true`；
3. 收到新的 `message_start` 时清空该会话缓存——它代表新一轮开始，上一轮的报文不再有意义。

前端拿到 `replayed` 版 `message_start` 时先清空实时状态再重建（保留已插入的消息 ID），所以重连不会重复累加，也不会丢进度。

### 4.3 一次性握手令牌

WebSocket 握手不走 Cookie（浏览器无法为 WS 请求定制头），因此采用「先换票、再握手」：

1. 前端 `POST /api/chat/ws-token`，服务端在 `websocket_tokens` 表写入一条记录（随机令牌、绑定用户与会话、有效期默认 300 秒）；
2. 前端用 `ws://host/api/chat/ws/chat?websocket_token=xxx` 建连；
3. 服务端校验：令牌存在、`consumed_at IS NULL`、未过期、`user_id` 与令牌持有者一致、`conversation_id` 归属该用户；
4. 校验通过即写入 `consumed_at`，令牌作废，**重放同一令牌会被拒绝**（关闭码 4001）。

关闭码约定：`1000` 正常关闭、`4001` 令牌无效或已消费、`4003` 无权限、`1011` 服务端异常。前端遇到 4003 停止重连，其余情况按指数退避（上限 15 秒）重连，重连前先换新令牌。

### 4.4 八种报文

| 报文 | 关键字段 | 触发时机 |
| --- | --- | --- |
| `message_start` | `task_id` `message_id` `user_message_id` `input_text` `scenario` `step_total` | 场景路由完成，任务转 running |
| `message_delta` | `delta_text` `seq` | 结论文本流式增量（每 48 字一块） |
| `tool_start` | `tool_name` `tool_args` `tool_call_seq` | 每个分析步骤开始 |
| `tool_finish` | `tool_name` `tool_call_seq` `status` `tool_result_summary` `duration_ms` `rows` | 步骤结束 |
| `task_status` | `task_status` `current_step` `progress` `step_index` `step_total` | 每次进度变化 |
| `result_ready` | `result_id` `download_url` | 六大模块落库完成 |
| `error` | `error_message` `error_stage` | 任意阶段异常或被取消 |
| `done` | `task_status` `finished_at` `duration_ms` | 本轮彻底结束（终态） |

所有报文都带 `type`、`ts`、`conversation_id`（以及绝大多数情况下的 `task_id`），补发版本额外带 `replayed: true`。

---

## 五、分析引擎：场景路由 + 工具调用

### 5.1 场景路由

请求进来先做意图路由（`analysis/scenarios/registry.py`）：对问题文本按关键词计分，强特征词权重 3、普通词权重 1，取最高分且大于 0 的场景；全为 0 则落到通用兜底场景；同分按注册顺序（越专有越靠前）。

注册顺序即优先级：

| 顺序 | key | 场景 | 说明 |
| --- | --- | --- | --- |
| 1 | `catalog` | 商品与类目诊断 | 点击率、转化率、商品质量 |
| 2 | `market` | 渠道投放效率归因 | ROAS、投放预算、渠道效率 |
| 3 | `inventory` | 库存与履约健康度 | 库存周转、缺货、发货时效 |
| 4 | `feedback` | 用户口碑与差评诊断 | 差评集中点、评分变化 |
| 5 | `refund` | 退款与售后归因 | 退款率、退款原因分布 |
| 6 | `growth` | 增长与活动复盘 | GMV 环比、促销活动效果 |
| 7 | `generic` | 通用经营体检 | 兜底，不命中任何专有场景时使用 |

路由同时会抽取限定条件（品类、百分比阈值、日期区间、检索关键词）注入场景，例如「美妆个护类目点击率从 4.2% 掉到 2.1%」会被解析出 `category_hint=美妆`、`threshold_pct=4.2`。

**多轮复用**：会话内第二轮提问时，引擎会先读本会话上一轮任务写入的路由日志（`task_logs` 中 `lifecycle` 类型、以 `场景路由|` 开头的记录），沿用同一个场景，保证追问仍在同一分析框架内展开，而不是另起一个新场景。

### 5.2 分析工具

场景的每个步骤声明调用哪个工具，引擎按序执行并逐步推送进度。6 个工具都注册在 `analysis/tools/`：

| 工具 | 作用 | 主要参数 |
| --- | --- | --- |
| `db_query` | 对业务数据仓库执行**只读** SQL（只允许 SELECT/WITH，且只能查 `biz_*` 表），返回结构化结果行 | `sql` |
| `text_search` | 在知识库、用户评论、上传文本中检索关键词 | `keyword` |
| `file_read` | 读取用户上传的附件或工作区文件（csv/excel/json/文本） | `file_path` |
| `file_write` | 把中间产物（明细表、汇总、草稿）写入会话工作区 | `file_name` `content` `format` |
| `shell_exec` | 在会话工作区执行白名单内的本地计算脚本 | `script` |
| `result_generate` | 按标准六模块格式生成报告，写入会话 exports 目录 | 六个模块的内容 |

步骤之间可传递产出：参数写成 `"@step_key"` 时，引擎会替换成前序步骤的真实返回值（`engine._resolve_args`），因此「先查明细、再把明细交给聚合步骤」不需要在场景里硬编码数据。

工具的可用性受运行时配置约束：`analysis.max_tool_calls`（单任务工具调用上限，默认 12）、`analysis.tool_timeout_sec`（单次超时，默认 60 秒）、`feature.enable_shell_tool`（shell 工具开关）。

### 5.3 六大模块标准化输出

不管走哪个场景，产出结构完全一致，这是「标准化输出」的落点：

| 模块 | 字段 | 说明 |
| --- | --- | --- |
| 1 问题定义 | `problem_definition` | 把用户口语化的问题改写成可分析的问题陈述 |
| 2 关键指标 | `key_metrics[]` | `metric_name` / `metric_value` / `metric_unit` / `metric_period` |
| 3 证据列表 | `evidence[]` | `source` / `source_type`（database\|knowledge\|file\|review） / `content` / `confidence` / `collected_at` |
| 4 归因结论 | `attribution` | 结论正文 |
| 5 待补充数据 | `missing_data` | 本轮无法回答、需要补哪些数据 |
| 6 下一步建议 | `next_actions` | 可执行动作 |

证据列表的每条都必须能回溯到数据源——这是「结论可验证」的实现方式：`db_query` 的返回行、知识库命中的原文、附件解析出的片段，都带上来源与置信度一起进入模块 3。

---

## 六、数据模型

两个库共 39 张表。认证域 6 张表（`auth_clients` / `auth_users` / `auth_codes` / `auth_tokens` / `auth_sessions` / `auth_login_logs`）由认证中心独占，业务后端不读。业务域 33 张表分两类：

### 6.1 核心表（11 张，`database/02_core_schema.sql`）

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `users` | 业务侧用户影子记录，与认证中心账号按 `username` 对应 | `username` 唯一 |
| `conversations` | 会话 | 归属 `user_id`，删除时级联清理 |
| `messages` | 消息，问答成对 | `seq_no` 会话内自增，游标分页依据 |
| `attachments` | 附件元信息，文件实体落在 `data/uploads/` | 关联消息与会话 |
| `analysis_tasks` | 分析任务，状态机见 §三 | `task_status` 五态 |
| `analysis_results` | 六大模块结构化结果 | 一条任务一条结果 |
| `context_summaries` | 超长对话的摘要压缩结果 | 供多轮上下文装配 |
| `websocket_tokens` | 一次性握手令牌 | `consumed_at` 标记消费 |
| `system_configs` | 运行时可热更新配置（54 项，8 个分组） | `config_key` 唯一 |
| `task_logs` | 任务日志，`log_type` 区分 lifecycle / tool / db / file / error | 工具调用链即 `log_type='tool'` 的 JSON 记录 |
| `data_sources` | 业务数据源登记（供管理控制台启停） | — |

### 6.2 业务数据表（22 张，`database/03_business_schema.sql`）

演示数据仓库，表名前缀统一为 `biz_`，`db_query` 工具只能读这一组表。按主题分：

| 主题 | 表 |
| --- | --- |
| 商品与类目 | `biz_category` `biz_product` |
| 流量与转化 | `biz_search_exposure` `biz_product_click` `biz_product_conversion` `biz_visit_event` `biz_cart_event` `biz_order_event` |
| 交易 | `biz_order` `biz_sales` `biz_sales_summary` |
| 客户 | `biz_customer` |
| 库存履约 | `biz_inventory` `biz_inbound` `biz_outbound` |
| 口碑 | `biz_review` `biz_rating` |
| 售后 | `biz_refund` `biz_refund_reason` `biz_refund_apply` |
| 渠道投放 | `biz_channel` `biz_ad_delivery` |

演示数据集约 6.6 万行，由 `backend/scripts/gen_demo_data.py` 用固定随机种子生成（可重复复现），时间窗口为 2026-09-01 ~ 2026-09-30，其中 09-01~09-15 为基线期、09-16~09-30 为异常期。窗口与两个区间的起止日期都可由运行时配置调整。

**几个踩过的坑（照抄即可避免）**：

- MySQL 8 不支持 `NULLS LAST` 语法，需要「空值排最后」时用 `ORDER BY col IS NULL, col`；
- `biz_category.category_id` 是 `C01`…`C05` 字符串编码，不是自增整数，`db_query` 里不要按 int 比较；
- FastAPI 中字面量路径必须注册在路径参数之前（例如 `/api/results/download` 要早于 `/api/results/{task_id}`），否则 `download` 会被尝试解析成 int 而返回 422；
- `analysis_tasks.started_at` / `finished_at` 必须是 `DATETIME(3)`（毫秒精度）。MySQL 的 `DATETIME` 默认 0 位小数秒，而一次分析通常只跑几百毫秒，秒级精度会把开始与结束记成同一秒，令 `duration_ms` 恒为 0（跨秒时又整跳成 1000）。模型侧用 `DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")` 表达，见 [backend/app/models/\_\_init\_\_.py](../backend/app/models/__init__.py) 的 `DATETIME_MS`。

---

## 七、配置热重载

配置分两层，职责不重叠：

| 层 | 来源 | 生效方式 | 内容 |
| --- | --- | --- | --- |
| 静态配置 | `.env` → `core/config.py` | 修改后需重启 | 数据库连接、监听端口、认证中心地址与客户端凭据、存储根目录、CORS 白名单 |
| 运行时配置 | `system_configs` 表 → `core/runtime_config.py` | 改完即时生效，无需重启 | 分析参数、功能开关、存储策略、上传限制、字典、LLM 参数、安全策略 |

运行时配置在进程启动时从 `system_configs` 全量加载进内存字典，此后所有业务代码统一通过 `runtime_config.get("xxx.yyy")` 读取，因此**读路径零数据库开销**。管理员在控制台修改后调用热重载，模块重新全量加载并按不可变字典整体替换（copy-on-write），并发读不会看到中间状态。热重载返回变更明细（`changed_keys`），管理控制台直接展示 diff。

54 项配置分 8 个分组：`analysis`(11) / `auth`(8) / `dict`(7) / `feature`(6) / `llm`(7) / `security`(3) / `storage`(4) / `system`(8)。

---

## 八、认证与鉴权链路

```
浏览器              前端 :5173            后端 :8000            认证中心 :9000
  │                    │                     │                       │
  │─ 点「登录」────────►│                     │                       │
  │                    │─ GET /auth/login ──►│                       │
  │                    │                     │ 生成 state，写 HttpOnly Cookie
  │◄─────────────────── 302 认证中心授权页 ────┤                       │
  │────────────────────────────────────────── 提交账号口令 ─────────►│
  │◄──────────────────────────────── 302 回 redirect_uri?code&state ─┤
  │                    │                     │                       │
  │─ 浏览器直达后端回调 ►│                     │                       │
  │                    │                     │─ 校验 state Cookie    │
  │                    │                     │─ POST /oauth/token ──►│
  │                    │                     │◄── access_token ──────┤
  │                    │                     │ 写 HttpOnly Cookie    │
  │◄─────────────────── 302 前端首页 ─────────┤ jy_access_token       │
```

要点：

- **令牌对前端不可见**。`jy_access_token` 是 `HttpOnly` Cookie，前端拿不到也不该拿到，登录态只能通过 `GET /api/auth/me` 查询。
- **登录是整页跳转**，不是 XHR。授权中心登录页由认证中心自己渲染，前端只负责跳过去。
- **state 防 CSRF**：发起授权时后端写 `jy_oauth_state` Cookie，回调时用 `secrets.compare_digest` 比对，不一致直接拒绝。回调地址由后端配置（`AUTH_REDIRECT_URI`）决定，不由请求中的 Host 推导。
- **业务后端不校验令牌本身**，而是调认证中心 `/oauth/introspect`；内省结果按令牌做 60 秒 TTL 缓存，避免每个请求都打认证中心。认证中心短暂不可用时，缓存中未过期的结果仍然可用。登出时主动清除该令牌的缓存，保证即时失效。
- **鉴权失败语义**：未携带或无效令牌 → 401；令牌有效但角色不足（普通分析用户访问 `/api/admin/*`）→ 403；访问他人会话或任务 → 404（不暴露资源是否存在）。
- **Cookie 按 host 共享、不区分端口**，所以前端 5173 与后端 8000 只要都用 `localhost`（或都用 `127.0.0.1`）就能带上同一个 Cookie。混用两个主机名会导致「登录成功却仍显示未登录」。

---

## 九、文件存储目录规范

三个用途各自独立根目录，路径一律为 `{根}/{user_id}/{conversation_id}/`：

```
backend/data/
├── uploads/{user_id}/{conversation_id}/     用户上传的原始附件
├── exports/{user_id}/{conversation_id}/     分析结果导出文件（md / json / xlsx）
└── workspace/{user_id}/{conversation_id}/   分析过程中的中间产物（明细表、汇总、草稿）
```

写入策略：文件名先经 `sanitize_filename()` 清洗（剥离任何目录成分、替换非法字符、去掉结尾空格与点、限长 180 字符），再经 `safe_join()` 拼接并校验结果不逃逸出根目录，路径穿越会直接抛错。

删除会话时三个目录整体递归删除，同时清理消息、附件、任务、结果记录。验收脚本实测一次级联删除会清掉 3 个目录、10 个文件。

---

## 十、前端结构

前端围绕「提问 → 实时进度 → 六大模块结果 → 导出」主链路组织，7 个业务模块对应 9 个组件：

| 模块 | 主要文件 | 职责 |
| --- | --- | --- |
| 会话管理 | `ConversationList.vue` + `store/conversation.js` | 新建、搜索、选择、改名、删除（提示级联清理范围） |
| 消息流 | `MessageStream.vue` + `store/chat.js` | 历史消息游标分页、上滑加载更早、助手消息流式追加 |
| 实时进度 | `TaskProgressPanel.vue` | 场景、当前步骤、进度条、工具调用链、连接状态与重连提示 |
| 附件 | `AttachmentPanel.vue` + `AskComposer.vue` | 上传前置校验、解析状态、预览、下载、删除 |
| 结果展示 | `ResultModules.vue` | 六大模块结构化渲染，证据按来源着色、按置信度分档 |
| 导出 | `ExportBar.vue` | md / json / xlsx 三种格式，沿用服务端返回的文件名 |
| 管理配置 | `views/AdminView.vue` + `store/admin.js` | 总览、配置修改与热重载 diff、功能开关、数据源、场景与工具、日志 |

实时状态集中在 `store/chat.js` 的 `handleEvent()`，8 种报文各有对应处理分支；`ws/client.js` 负责取令牌、心跳（25 秒）、指数退避重连与状态机。

页面路由与权限：

| 路由 | 页面 | 权限 |
| --- | --- | --- |
| `/login` | 登录页 | 公开 |
| `/` | 分析工作台 | 需登录 |
| `/history` | 历史会话 | 需登录 |
| `/result/:taskId` | 分析结果详情 | 需登录 |
| `/admin` | 管理控制台 | 需 admin 角色 |

路由守卫在首次导航时确认登录态，未登录跳 `/login`，非管理员访问 `/admin` 会被拦回工作台。

---

## 十一、关键设计取舍

| 决定 | 原因 |
| --- | --- |
| 响应统一为扁平 JSON，不套 `code/message/data` | 状态语义直接由 HTTP 状态码承载，错误统一 `{"detail": "..."}`，前端少一层解包 |
| 消息列表用游标分页（`seq_no` DESC + `before_seq`）而非 offset | 多轮对话会持续追加消息，offset 分页在追加时会导致翻页错位与重复 |
| 分析在后台线程池而非请求内同步执行 | 一次分析数百毫秒到数十秒，同步执行会占满 worker 并让前端无法拿到实时进度 |
| WS 令牌一次性且与会话绑定 | 避免令牌被复制到别的会话重放；断线重连换新令牌的代价很小 |
| 为每个会话缓存一轮报文 | 「连接晚于任务启动」在真实网络下是常态，纯推送模型必然丢进度 |
| 工具只能查 `biz_*` 表且只读 | 把 LLM/规则生成的 SQL 关进沙箱，杜绝误删业务数据 |
| 场景结论由规则引擎产出，LLM 只做文案润色 | 没有外部模型也能跑通全链路，演示与验收不依赖网络与配额 |
| 运行时配置与静态配置分离 | 端口、数据库、认证凭据改一次就该重启；分析参数、开关需要在线调 |
