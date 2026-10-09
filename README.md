# 经营多轮归因分析系统

面向电商经营团队的多轮归因分析工作台。用户用自然语言提问（「美妆个护类目点击率腰斩，问题出在哪？」），系统自动路由到对应业务场景，调用数据库查询、知识检索、文件读写等工具逐步取证，边执行边通过长连接把进度推给前端，最终产出一份结构固定的六模块归因报告，并可导出 Markdown / JSON / Excel。

核心主张有两条：**结论必须能回溯到证据**，以及**追问必须复用上文**——第二轮提问不是新起一个孤立问题，而是接着上一轮的问题定义、指标口径与结论继续深挖。

---

## 交付物

| 交付物 | 位置 |
| --- | --- |
| 可运行的三端源码 | [backend/](backend/)（业务后端）、[auth-server/](auth-server/)（认证中心）、[frontend/](frontend/)（前端） |
| 数据库建表与演示数据脚本 | [database/](database/) 下 7 个 SQL 文件 |
| 架构设计说明 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 接口规范 | [docs/API.md](docs/API.md) |
| 部署文档 | [docs/DEPLOY.md](docs/DEPLOY.md) |
| 业务演示 | [docs/DEMO.md](docs/DEMO.md) |

---

## 架构一览

```
浏览器 :5173 (Vue 3 + Vite + Element Plus)
   │
   ├── HTTP /api /auth ─────┐
   └── WebSocket ───────────┤
                            ▼
              业务后端 :8000 (FastAPI + SQLAlchemy)
                     │                    │
                     │ OAuth2 / 令牌内省   │ 文件落盘
                     ▼                    ▼
          认证中心 :9000           data/uploads | exports | workspace
                                            │
                            MySQL 8 :3306 ──┘
                            ├── analysis_auth  认证域 6 张表
                            └── analysis_sys   业务域 33 张表（核心 11 + 演示数据 22）
```

三个服务可以独立启动、独立部署。业务后端不持有任何口令与令牌签发逻辑，访问令牌是不透明字符串，只能由认证中心内省判定有效性。

详细分层、时序与设计取舍见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 快速开始

前提：MySQL 8 在 `127.0.0.1:3306`（账号 `root/root`），Python 3.12 + uv，Node 18+。

```bash
# 1) 建库建表 + 字典 + 演示数据（在 database/ 目录下执行，SOURCE 用的是相对路径）
cd database
cmd /c "mysql --host=127.0.0.1 --port=3306 --user=root --password=root --default-character-set=utf8mb4 < 00_init_all.sql"

# 2) 认证中心
cd ../auth-server
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 9000 --log-level info

# 3) 业务后端（另开一个终端）
cd ../backend
uv sync
uv run python scripts/gen_demo_data.py        # 生成 9 月基线期 / 异常期演示数据
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info

# 4) 前端（再开一个终端）
cd ../frontend
npm install
npm run dev                                    # http://127.0.0.1:5173
```

浏览器打开 <http://localhost:5173>，用 `analyst / Analyst@123` 登录即可提问。

完整步骤、配置项与排错见 [docs/DEPLOY.md](docs/DEPLOY.md)。

---

## 演示账号

| 用户名 | 口令 | 角色 | 说明 |
| --- | --- | --- | --- |
| `admin` | `Admin@123` | admin | 系统管理员，可进管理控制台 |
| `analyst` | `Analyst@123` | analyst | 普通分析用户（张分析 · 运营） |
| `zhangyun` | `Zhang@123` | analyst | 商品运营，用于商品目录优化场景 |

---

## 功能范围

**五个页面**

| 路由 | 页面 | 内容 |
| --- | --- | --- |
| `/login` | 登录页 | 跳转认证中心完成 OAuth2 授权；展示演示账号与分析窗口 |
| `/` | 分析工作台 | 三栏：会话列表 / 消息流 + 提问框 / 实时进度 + 附件；结果抽屉 |
| `/history` | 历史会话 | 搜索、改名、批量删除、展开查看该会话的分析任务 |
| `/result/:taskId` | 分析结果详情 | 六大模块 + 任务元信息 + 工具调用链 + 导出 |
| `/admin` | 管理控制台 | 运行总览、配置热重载、功能开关、业务数据源、场景与工具、运行日志（仅 admin） |

**六个业务场景**（另有通用兜底场景，共 7 个注册场景）

| 场景 | 触发示例 |
| --- | --- |
| 商品目录质量归因 | 美妆个护类目点击率腰斩，从 4.2% 掉到 2.1%，问题出在哪？ |
| 渠道投放效率归因 | 信息流渠道 ROAS 从 5.9 掉到 1.6，投放预算没变，问题出在哪？ |
| 用户反馈与口碑归因 | 用户主要在抱怨什么？差评有没有集中爆发的点？ |
| 库存与履约归因 | 好几个畅销款最近老是缺货，库存周转也变慢了，是哪里出了问题？ |
| 退款与售后归因 | 退款率最近涨得很厉害，到底是商品质量问题还是物流问题？ |
| 大盘经营下滑归因 | 9 月下半月整体 GMV 环比下滑，是哪些因素导致的？ |
| 通用经营体检（兜底） | 未命中任何专有场景时的兜底，例如「这次促销活动的效果为什么不如预期？」 |

六个场景的完整演示输出见 [docs/DEMO.md](docs/DEMO.md)。

**六模块标准化输出**：问题定义 → 关键指标 → 证据列表 → 归因结论 → 待补充数据 → 下一步建议。证据列表的每一条都带来源（数据源类型）、置信度与采集时间，可回溯到具体的数据表、知识库条目或附件片段。

**八个长连接报文**：`message_start` / `message_delta` / `tool_start` / `tool_finish` / `task_status` / `result_ready` / `error` / `done`。

---

## 验收

### 端到端验收脚本

```bash
cd backend
.venv\Scripts\python.exe -X utf8 scripts\e2e_check.py --user analyst --password Analyst@123
```

前置：认证中心（9000）与后端（8000）已启动。脚本走真实 HTTP 与 WebSocket，退出码非 0 表示有验收项失败。

想连前端开发服务器的代理链路一起验，加环境变量：

```powershell
$env:E2E_BACKEND = "http://localhost:5173"
.venv\Scripts\python.exe -X utf8 scripts\e2e_check.py
Remove-Item Env:\E2E_BACKEND
```

### 验收覆盖

| # | 验收项 | 脚本验证内容 |
| --- | --- | --- |
| 1 | 认证对接 | `/auth/login` 302 到认证中心并下发 state Cookie；授权码回跳；回调校验 state 并种下 HttpOnly Cookie；登录态可查 |
| 2 | 鉴权与越权防护 | 无令牌访问业务接口 / 管理接口 / 他人会话均 401；普通用户访问管理接口 403 |
| 3 | 会话管理 | 新建、改名、列表、按标题搜索、历史消息游标分页 |
| 4 | 附件上传与解析 | 上传落盘、即时解析、详情预览、下载内容一致、列表 |
| 5 | 实时分析链路 | 一次性令牌；提问创建任务；长连接收到全部应收报文类型；场景识别正确；工具调用链完整；`done` 收口；令牌重放被拒；断线重连补发整轮报文 |
| 6 | 六模块结果与导出 | 六大模块齐全且字段完整；证据可回溯、来源多样；md / json / xlsx 三种导出与别名下载路径可用 |
| 7 | 多轮追问 | 第二轮复用上一轮场景；消息按 user/assistant 交替；游标分页可用 |
| 8 | 配置热重载 | 全量重载无变更；修改配置即时生效并可还原；管理接口全部可用；功能开关可切换 |
| 9 | 会话删除与级联清理 | 删除会话后三个存储目录被清理、记录消失、再访问返回 404 |

### 引擎自检（不依赖 HTTP）

```bash
cd backend
.venv\Scripts\python.exe -X utf8 scripts\selfcheck.py
```

覆盖配置加载、场景路由、工具注册、7 个场景端到端跑通、报告六段结构。

---

## 目录结构

```
jingyingguiyinfenxixitong_108/
├── auth-server/          # 认证中心（FastAPI，9000）
├── backend/              # 业务后端（FastAPI，8000）
├── database/             # 建表与演示数据 SQL
├── docs/                 # 架构、接口、部署、演示文档
├── frontend/             # 前端（Vue 3 + Vite，5173）
└── README.md
```

各子项目另有自己的 README：[backend/README.md](backend/README.md)、[frontend/README.md](frontend/README.md)、[auth-server/README.md](auth-server/README.md)。

> 仓库根目录的 `.venv/` 与 `pyproject.toml` 是 IDE 自动生成的项目骨架（依赖为空），与三个服务无关；
> 后端与认证中心各自在子目录下用 uv 管理自己的虚拟环境。

---

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、SQLAlchemy 2.0、PyMySQL、Pydantic v2、Uvicorn、openpyxl |
| 认证中心 | FastAPI、SQLAlchemy 2.0、Jinja2（登录页）、OAuth2 授权码模式 |
| 前端 | Vue 3 `<script setup>`、Vite 6、Vue Router 4、Pinia 2、Element Plus 2.9、原生 WebSocket |
| 数据库 | MySQL 8.0.26 |
| 依赖管理 | uv（Python）、npm（前端） |

演示数据由 `backend/scripts/gen_demo_data.py` 用固定随机种子生成，可重复复现；分析结论由规则引擎产出，LLM 只负责文案润色，**没有外部模型依赖也能跑通全链路**，演示与验收不依赖网络。
