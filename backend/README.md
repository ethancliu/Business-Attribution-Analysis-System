# 经营多轮归因分析系统 · 后端服务

FastAPI + SQLAlchemy 2.0 + MySQL 8 实现的归因分析后端。负责认证对接、会话与消息管理、
附件解析、场景化分析引擎、WebSocket 实时推送、结果标准化输出与导出、配置热重载。

## 技术栈

| 组件 | 选型 |
| --- | --- |
| Web 框架 | FastAPI（同步路由 + 原生 WebSocket） |
| ORM | SQLAlchemy 2.0（`Mapped` / `mapped_column` 声明式） |
| 数据库 | MySQL 8.0.26，驱动 PyMySQL |
| 配置 | pydantic-settings（进程级 `.env`）+ 数据库 `system_configs`（可热重载） |
| 认证 | 对接独立认证中心，OAuth2 授权码模式，opaque token + 内省 |
| 实时 | WebSocket，8 种报文类型；分析在后台线程池执行，跨线程回投主事件循环 |
| 导出 | openpyxl（Excel）、纯文本（Markdown）、json |

## 目录结构

```
backend/
├── app/
│   ├── main.py              # 应用入口：lifespan、CORS、路由挂载、异常处理
│   ├── core/                # 基础设施：配置、数据库、路径、安全、运行时配置、依赖注入
│   ├── models/              # SQLAlchemy 模型（11 张核心表）
│   ├── schemas/             # Pydantic 请求/响应模型
│   ├── api/                 # 路由层：auth / chat / attachment / tasks / results / admin
│   ├── services/            # 业务服务层：会话、消息、附件、任务、结果、上下文
│   ├── analysis/            # 分析引擎：路由、步骤链、6 大场景 + 通用兜底、工具集
│   └── ws/                  # 长连接：连接管理器、报文构造、接入点
├── knowledge/               # 知识库（方法论、指标口径、经验条目）
├── scripts/                 # 初始化、造数、自检、验收脚本
├── data/                    # 运行时文件存储（uploads / exports / workspace）
├── .env.example             # 基础设施配置模板
└── pyproject.toml           # uv 管理的依赖清单
```

## 快速开始

### 1. 准备依赖

```bash
cd backend
uv sync                     # 或 pip install -e .
```

### 2. 配置

```bash
cp .env.example .env
# 按实际环境修改数据库、认证中心地址
```

关键的进程级配置（改完需重启）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` | 业务库地址 |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `root` / `root` / `analysis_sys` | 业务库账号 |
| `AUTH_BASE_URL` | `http://localhost:9000` | 认证中心地址 |
| `AUTH_CLIENT_ID` / `AUTH_CLIENT_SECRET` | `jingying-web` / `jingying-web-secret-2026` | OAuth2 客户端凭据 |
| `AUTH_REDIRECT_URI` | `http://localhost:8000/auth/callback` | 回调地址，需与认证中心登记一致 |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | 登录成功后前端跳转地址 |
| `DATA_DIR` | `data` | 文件存储根目录 |

### 3. 初始化数据库

```bash
# 建库建表 + 字典 + 演示数据（需要 mysql 客户端在 PATH 中）
python scripts/init_db.py
python scripts/gen_demo_data.py      # 生成 9 月基准期/异常期演示数据
```

### 4. 启动

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
```

- 接口文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/healthz>（含数据库与认证中心连通性）

启动日志会打印配置来源（`.env` 或数据库）与配置项总数。

## 自检脚本

| 脚本 | 用途 |
| --- | --- |
| `scripts/init_db.py` | 建库建表 + 字典数据（执行 `database/` 下的 SQL） |
| `scripts/gen_demo_data.py` | 生成 9 月基线期/异常期演示数据（固定随机种子，可重复复现） |
| `scripts/selfcheck.py` | 不依赖 HTTP 的引擎自检：配置、场景路由、工具注册、7 个场景端到端跑通、报告六段结构 |
| `scripts/e2e_check.py` | 端到端验收：真实 HTTP + WebSocket，覆盖认证、鉴权、会话、附件、实时分析、六大模块、导出、多轮、配置热重载、级联删除 |
| `scripts/tools/stats.py` | 打印业务库统计（各表行数、场景数据分布） |
| `scripts/tools/dump_scenarios.py` | 打印全部已注册场景的元数据（名称、说明、关键词），供文档与验收核对 |
| `scripts/tools/demo_scenarios.py` | 走真实 HTTP 跑 6 个演示场景 + 2 组多轮追问，把原始结果落到 `data/_demo_dump/*.json`（`docs/DEMO.md` 的取数来源） |
| `scripts/tools/demo_extract.py` | 把上一步的 JSON 提取成可读文本 `data/_demo_dump/_extract.txt`，便于逐模块校对 |

```bash
python -X utf8 scripts/selfcheck.py                     # 全量
python -X utf8 scripts/selfcheck.py --scenario catalog  # 单个场景
python -X utf8 scripts/e2e_check.py --user analyst --password Analyst@123

# 重新生成演示文档的取数素材（需认证中心 + 后端已启动）
python -X utf8 scripts/tools/demo_scenarios.py   # 6 个场景 + 多轮追问 -> data/_demo_dump/
python -X utf8 scripts/tools/demo_extract.py     # 提取为 _extract.txt
```

> `data/_demo_dump/` 只是复现演示文档时的临时取数目录，不属于 [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) 约定的
> `uploads/` / `exports/` / `workspace/` 三类存储，可随时删除。

`e2e_check.py` 需要认证中心（9000）与后端（8000）都已启动。退出码非 0 表示有验收项失败。
它默认直连后端 8000，也可用环境变量 `E2E_BACKEND` 指向前端开发服务器（5173）来额外验证代理链路；
`E2E_AUTH` 用于覆盖认证中心地址。注意：脚本会从 `/auth/login` 的 302 响应里解析后端自己配置的回调地址，
不会自行拼接——回调地址由后端 `AUTH_REDIRECT_URI` 决定，猜错会导致认证中心返回 400「回调地址不一致」。

## 运行时配置（热重载）

可热更新的配置存在业务库 `system_configs` 表，按分组管理：

| 分组 | 代表配置 |
| --- | --- |
| `analysis` | `analysis.max_rounds`、`analysis.step_interval_ms`、`analysis.tool_timeout_sec`、`analysis.context_keep_rounds`、`analysis.summary_trigger_messages`、基准期/异常期四个日期 |
| `system` | `system.name`、`system.env`、`system.max_upload_mb`、`system.allow_extensions`、`system.max_concurrent_tasks`、`websocket.token_ttl_sec` |
| `feature` | `feature.enable_export`、`feature.enable_shell_tool` 等功能开关 |
| `security` | `security.sql_row_limit` 等安全阈值 |
| `storage` | 文件存储相关阈值 |

修改方式二选一：

- 管理控制台修改后自动热重载；
- `POST /api/admin/configs/update` 改值，或 `POST /api/admin/reload` 全量/按分组重载。

代码读取配置一律通过 `app.core.runtime_config`，因此改完立即生效、无需重启。
**新增配置项时必须同时补进 `database/04_dict.sql` 与代码里的读取键名，否则会静默退到默认值。**

## 关键实现说明

### 分析任务在后台线程执行

`app/services/chat.py` 用 `ThreadPoolExecutor` 承载分析，避免阻塞事件循环。
线程内通过 `app.ws.manager.manager.push()` 推送报文，内部用
`asyncio.run_coroutine_threadsafe()` 把协程投回主循环（主循环在 lifespan 中由
`manager.bind_loop()` 捕获）。

### 长连接补发

一次分析只需几百毫秒，客户端完全可能「任务已启动、连接才建立」，或分析中途刷新页面。
因此 `ConnectionManager` 为每个会话缓存最近一轮的全部报文，新连接接入时先补发一遍
（报文带 `replayed: true`），前端据此立即还原完整进度。缓存随新一轮 `message_start` 清空。

### 一次性握手令牌

WebSocket 建连前先调 `POST /api/chat/ws-token` 取令牌，握手时校验并写 `consumed_at`，
重放同一令牌会被 4001 关闭。前端重连必须重新申请令牌。

### 场景路由

`app/analysis/scenarios/registry.py` 用关键词计分（强关键词权重 3、普通关键词权重 1）
把提问路由到六大预置场景之一，得分过低则落到通用兜底场景。多轮追问时优先沿用上一轮的场景。

## 常见问题

**`/api/chat/ls` 报 SQL 语法错误（`NULLS LAST`）**
MySQL 不支持 `NULLS LAST`；DESC 排序时 NULL 天然排最后，不要用 SQLAlchemy 的 `.nullslast()`。

**分析结果里品类数据全为 0**
`biz_category.category_id` 是 `C01`…`C05` 字符串编码，不是数字。场景 SQL 里必须加引号，
或走 `app/analysis/scenarios/common.py` 的 `resolve_category_id()` 解析。

**配置改了不生效**
先用 `GET /api/admin/configs` 确认该键在库里存在且名称与代码读取的一致；键名不一致时
代码会静默使用默认值。参考上文「运行时配置」一节的提醒。
