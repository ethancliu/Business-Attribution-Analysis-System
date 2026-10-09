# 经营多轮归因分析系统 · 本机部署文档

面向第一次拿到本项目的开发者，目标是在一台 Windows 机器上从零把三个服务跑起来。

- 项目根目录（下文以 `%ROOT%` 指代）：
  `D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108`
- 所有命令在 **PowerShell** 中执行；涉及 mysql 客户端输入重定向的命令必须显式走 `cmd.exe /c`（PowerShell 不支持 `<` 输入重定向）。

---

## 一、部署拓扑

| 服务 | 目录 | 监听地址 | 职责 | 依赖 |
| --- | --- | --- | --- | --- |
| MySQL 8.0.26 | — | `127.0.0.1:3306` | 存认证库 `analysis_auth` 与业务库 `analysis_sys` | 无（最先起） |
| 认证中心 auth-server | `auth-server/` | `127.0.0.1:9000` | 独立 OAuth2 授权码服务：登录、发码、换令牌、内省、登出、会话管理 | MySQL（`analysis_auth`） |
| 业务后端 backend | `backend/` | `127.0.0.1:8000` | 全部 `/api/**` 与 `/auth/**`、WebSocket 实时推送、分析引擎、导出 | MySQL（`analysis_sys`）+ 认证中心 |
| 前端 frontend | `frontend/` | `127.0.0.1:5173` | Vue 3 + Vite 开发服务器；把 `/api`、`/auth`、`/healthz`（含 WebSocket）代理到后端 | 后端 |

**启动顺序（不可颠倒）**：

```
MySQL → 认证中心(9000) → 后端(8000) → 前端(5173)
```

理由：后端启动时 lifespan 会连业务库、加载配置、清残留任务，并在 `/healthz` 里汇报认证中心连通性；前端只是把请求代理给后端，后端没起时前端页面能打开但登录与提问都会失败。

浏览器访问入口只有一个：`http://127.0.0.1:5173`。

---

## 二、环境要求

| 组件 | 版本要求 | 依据 |
| --- | --- | --- |
| Python | `>=3.11` | `backend/pyproject.toml`、`auth-server/pyproject.toml` 的 `requires-python = ">=3.11"` |
| Python（仓库根） | `>=3.12` | 根 `pyproject.toml` 的 `requires-python = ">=3.12"`（该文件 `dependencies = []`，仅作工作区标记） |
| uv | 任意较新版本 | 两个服务均带 `uv.lock`，`pyproject.toml` 里有 `[tool.uv] package = false` |
| Node / npm | 无显式声明，实测可用 | `frontend/package.json` 未写 `engines` |
| MySQL | 8.0.26 | `backend/README.md` 技术栈表 |

本机实测值（部署时可对照）：

| 项 | 实测值 |
| --- | --- |
| 后端虚拟环境 Python | `3.12.13`（`backend/.venv/Scripts/python.exe`） |
| uv | `D:\JAVA\Python\UV\uv.exe` |
| Node | `v24.9.0` |
| npm | `11.6.0` |
| npm registry | `http://registry.npmmirror.com/`（来自用户级 `%USERPROFILE%\.npmrc`） |
| MySQL 客户端 | `D:\JAVA\Mysql\bin\mysql.exe` |
| MySQL 服务 | `127.0.0.1:3306`，账号 `root` / 口令 `root` |
| 出网代理（仅下载 GitHub 资源时需要） | Clash Verge `127.0.0.1:7897` |

**前端依赖版本**（来自 `frontend/package.json`）：

| 包 | 版本 |
| --- | --- |
| `vue` | `^3.5.13` |
| `vue-router` | `^4.5.0` |
| `pinia` | `^2.3.0` |
| `element-plus` | `^2.9.1` |
| `@element-plus/icons-vue` | `^2.3.1` |
| `vite`（dev） | `^6.0.7` |
| `@vitejs/plugin-vue`（dev） | `^5.2.1` |

**数据库连接信息**来自 `backend/.env` 与 `database/04_dict.sql`：主机 `127.0.0.1`、端口 `3306`、用户 `root`、口令 `root`、字符集 `utf8mb4`。

---

## 三、第一步：初始化数据库

### 3.1 `database/` 目录下每个 SQL 文件的作用

| 文件 | 目标库 | 作用 |
| --- | --- | --- |
| `01_auth_schema.sql` | `analysis_auth` | **先 `DROP DATABASE IF EXISTS analysis_auth` 再重建**。建 6 张表：`auth_clients`、`auth_users`、`auth_codes`、`auth_tokens`、`auth_sessions`、`auth_login_logs`；并写入 1 个接入客户端与 3 个演示账号 |
| `02_core_schema.sql` | `analysis_sys` | `CREATE DATABASE IF NOT EXISTS analysis_sys`。建业务核心表（`users`、`conversations`、`messages`、`attachments`、`analysis_tasks`、`analysis_results`、`context_summaries`、`websocket_tokens`、`system_configs`、`task_logs`、`data_sources`） |
| `03_business_schema.sql` | `analysis_sys` | 建 6 大场景共 22 张 `biz_` 前缀演示表（商品目录 / 客户行为 / 库存异常 / 评论反馈 / 市场表现 / 退款模式） |
| `04_dict.sql` | `analysis_sys` | 写入字典数据：业务库用户镜像（3 条）、`system_configs` 系统配置（含分析窗口日期）、`data_sources` 数据源（3 条）、枚举字典 |
| `05_demo_data.sql` | `analysis_sys` | 业务示例场景数据，约 5 MB；先 `TRUNCATE` 22 张 `biz_` 表再写入，可重复执行 |
| `06_verify.sql` | `analysis_sys` | 只读校验脚本，输出各表行数、基准期/异常期窗口、6 大场景的聚合对比值 |
| `00_init_all.sql` | 两者 | 总入口，用 mysql 客户端指令 `SOURCE` 按顺序拉起上面 5 个文件，最后打印一张统计表 |

注意：

- `01_auth_schema.sql` 会 **DROP 认证库**，`02_core_schema.sql` 之后 `05_demo_data.sql` 会 **TRUNCATE 业务演示表**。不要在有真实数据的实例上执行。
- `04_dict.sql`、`05_demo_data.sql`、`06_verify.sql` 内部有 `USE analysis_sys`，因此必须在 `02_core_schema.sql` **之后**执行。

### 3.2 执行命令（mysql 客户端方式）

PowerShell 中先切到 `database` 目录，再用 `cmd.exe /c "..." < 文件` 逐个执行：

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\database"

cmd.exe /c "D:\JAVA\Mysql\bin\mysql.exe --host=127.0.0.1 --port=3306 --user=root --password=root < 01_auth_schema.sql"
cmd.exe /c "D:\JAVA\Mysql\bin\mysql.exe --host=127.0.0.1 --port=3306 --user=root --password=root < 02_core_schema.sql"
cmd.exe /c "D:\JAVA\Mysql\bin\mysql.exe --host=127.0.0.1 --port=3306 --user=root --password=root < 03_business_schema.sql"
cmd.exe /c "D:\JAVA\Mysql\bin\mysql.exe --host=127.0.0.1 --port=3306 --user=root --password=root < 04_dict.sql"
cmd.exe /c "D:\JAVA\Mysql\bin\mysql.exe --host=127.0.0.1 --port=3306 --user=root --password=root < 05_demo_data.sql"
```

要点：

- 必须用 `--host=127.0.0.1` 这种长参数形式（本机 mysql 客户端对 `-h127.0.0.1` 短参数绑定异常）。
- 必须走 `cmd.exe /c`，让 cmd 做输入重定向，脚本中的中文与 UTF-8 才不会乱码。
- 每条命令会提示 `Using a password on the command line interface can be insecure.`，属正常告警。
- `05_demo_data.sql` 约 5 MB，导入需要几十秒。

**可选：一次性执行（等价于上面 5 条）**

`00_init_all.sql` 用的是 mysql 客户端的 `SOURCE` 指令，路径相对于客户端当前目录，因此仍需在 `database` 目录下执行：

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\database"
cmd.exe /c "D:\JAVA\Mysql\bin\mysql.exe --host=127.0.0.1 --port=3306 --user=root --password=root < 00_init_all.sql"
```

### 3.3 校验

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\database"
cmd.exe /c "D:\JAVA\Mysql\bin\mysql.exe --host=127.0.0.1 --port=3306 --user=root --password=root < 06_verify.sql"
```

看到 `一、数据量总览` 起各分段有数据、`二、统计窗口` 显示基准期与异常期两段，即导入成功。

### 3.4 备选方式：用 Python 脚本初始化

`backend/scripts/init_db.py` 用 pymysql 直连执行同一批 SQL，不依赖 mysql 客户端。它同样会先建库、再按 5 个文件顺序执行，最后打印各表行数。

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\backend"
uv run python scripts/init_db.py
```

参数（见脚本 `argparse`）：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `DB_HOST` 环境变量，缺省 `127.0.0.1` | MySQL 主机 |
| `--port` | `DB_PORT` 环境变量，缺省 `3306` | MySQL 端口 |
| `--user` | `DB_USER` 环境变量，缺省 `root` | 账号 |
| `--password` | `DB_PASSWORD` 环境变量，缺省 `root` | 口令 |
| `--skip-data` | 关 | 只建表与字典，跳过 `05_demo_data.sql` |
| `--only` | 空 | 只执行指定脚本，如 `--only 05_demo_data.sql` |

```powershell
uv run python scripts/init_db.py --host 127.0.0.1 --port 3306 --user root --password root
uv run python scripts/init_db.py --only 05_demo_data.sql
```

---

## 四、第二步：启动认证中心（9000）

认证中心独立部署，用独立 schema，与业务库物理隔离。

### 4.1 安装依赖

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\auth-server"
uv sync
```

依赖清单见 `auth-server/pyproject.toml`：`fastapi>=0.115.0`、`uvicorn[standard]>=0.32.0`、`sqlalchemy>=2.0.36`、`pymysql>=1.1.1`、`cryptography>=43.0.0`、`pydantic>=2.9.0`、`pydantic-settings>=2.6.0`、`python-multipart>=0.0.12`、`jinja2>=3.1.4`。

### 4.2 配置

`auth-server/` 下 **没有** `.env` 也没有 `.env.example`。`app/core/config.py` 的 `SettingsConfigDict(env_file=".env")` 读的是进程当前目录（即 `auth-server/`）下的 `.env`；文件不存在时全部走代码默认值，**开箱即用**。

如需覆盖，在 `auth-server/` 下新建 `.env`，可用的键与默认值如下：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `经营多轮归因分析系统-认证中心` | 服务名 |
| `APP_VERSION` | `1.0.0` | 版本 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `9000` | 监听端口 |
| `DEBUG` | `true` | 调试开关 |
| `DB_HOST` | `127.0.0.1` | 认证库主机 |
| `DB_PORT` | `3306` | 认证库端口 |
| `DB_USER` | `root` | 账号 |
| `DB_PASSWORD` | `root` | 口令 |
| `DB_NAME` | `analysis_auth` | 认证库名 |
| `DB_CHARSET` | `utf8mb4` | 字符集 |
| `AUTH_CODE_TTL_SEC` | `300` | 授权码有效期 5 分钟 |
| `ACCESS_TOKEN_TTL_SEC` | `7200` | 访问令牌 2 小时 |
| `REFRESH_TOKEN_TTL_SEC` | `604800` | 刷新令牌 7 天 |
| `SESSION_TTL_SEC` | `43200` | 登录会话 12 小时 |
| `ADMIN_API_KEY` | `jingying-auth-admin-2026` | 管理接口请求头 `X-Admin-Key` |
| `CORS_ORIGINS` | `*` | 允许来源 |

**预置接入客户端**（写入 `analysis_auth.auth_clients`，见 `01_auth_schema.sql`）：

| 项 | 值 |
| --- | --- |
| `client_id` | `jingying-web` |
| `client_secret` | `jingying-web-secret-2026` |
| `scope` | `openid profile analysis` |
| `redirect_uris` | `http://localhost:8000/auth/callback,http://127.0.0.1:8000/auth/callback,http://localhost:5173/auth/callback,http://localhost:5173/login/callback` |

**预置账号**（写入 `analysis_auth.auth_users`，口令算法 `SHA256(salt + password)`）：

| 账号 | 口令 | 角色 | 显示名 |
| --- | --- | --- | --- |
| `admin` | `Admin@123` | admin | 系统管理员 |
| `analyst` | `Analyst@123` | analyst | 张分析（运营） |
| `zhangyun` | `Zhang@123` | analyst | 赵云舒（商品运营） |

### 4.3 启动

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\auth-server"
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 9000 --log-level info
```

- `-X utf8` 保证控制台中文日志不乱码。
- `auth-server/app/main.py` 的 docstring 里写的是 `uv run uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload`，实际部署用上面这条（显式指定虚拟环境解释器、绑 `127.0.0.1`），二者等价。
- 启动日志会打印认证库连接结果：`认证库连接成功 (analysis_auth)：用户 N 个，客户端 M 个`。若用户为 0 会告警提示先执行 `database/01_auth_schema.sql`。

### 4.4 验证

| 检查项 | 地址 | 期望 |
| --- | --- | --- |
| 健康检查 | `http://localhost:9000/oauth/healthz` | JSON，`status` 为 `ok`，`database` 为 `analysis_auth` |
| 接口文档 | `http://localhost:9000/docs` | Swagger UI 正常打开 |
| 首页 | `http://localhost:9000/` | 深色导航页，含「发起一次授权登录」等链接 |
| 会话列表 | `http://localhost:9000/oauth/sessions` | 返回登录会话数组 |

```powershell
curl.exe http://localhost:9000/oauth/healthz
```

---

## 五、第三步：启动业务后端（8000）

### 5.1 安装依赖

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\backend"
uv sync
```

依赖清单见 `backend/pyproject.toml`：`fastapi>=0.115.0`、`uvicorn[standard]>=0.32.0`、`sqlalchemy>=2.0.36`、`pymysql>=1.1.1`、`cryptography>=43.0.0`、`pydantic>=2.9.0`、`pydantic-settings>=2.6.0`、`python-multipart>=0.0.12`、`httpx>=0.27.0`、`websockets>=13.0`、`aiofiles>=24.1.0`、`openpyxl>=3.1.5`。

### 5.2 配置 `.env`

仓库里已同时存在 `backend/.env.example` 与 `backend/.env`，二者内容完全一致。**新建环境时**：

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\backend"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

`backend/app/core/config.py` 用绝对路径 `BASE_DIR / ".env"` 读取（`BASE_DIR` 即 `backend/`），所以无论从哪个目录启动都读得到。

**全部配置项**（值取自 `backend/.env`，默认值同 `app/core/config.py`）：

| 变量名 | 说明 | 示例值 / 默认值 |
| --- | --- | --- |
| `APP_NAME` | 服务名 | `经营多轮归因分析系统` |
| `APP_VERSION` | 版本号 | `1.0.0` |
| `HOST` | 进程内 `uvicorn.run` 用的监听地址（命令行启动时以命令行参数为准） | `0.0.0.0` |
| `PORT` | 启动日志里展示的服务端口 | `8000` |
| `DEBUG` | 调试开关；为 `true` 时日志级别为 DEBUG | `true` |
| `PUBLIC_BASE_URL` | 后端对外可达地址，用于拼回调地址 | `http://localhost:8000` |
| `FRONTEND_BASE_URL` | 登录回调完成后跳转的前端地址 | `http://localhost:5173` |
| `DB_HOST` | 业务库主机 | `127.0.0.1` |
| `DB_PORT` | 业务库端口 | `3306` |
| `DB_USER` | 业务库账号 | `root` |
| `DB_PASSWORD` | 业务库口令 | `root` |
| `DB_NAME` | 业务库名 | `analysis_sys` |
| `DB_CHARSET` | 字符集 | `utf8mb4` |
| `AUTH_BASE_URL` | 认证中心地址 | `http://localhost:9000` |
| `AUTH_CLIENT_ID` | OAuth2 客户端 ID，须与认证中心登记一致 | `jingying-web` |
| `AUTH_CLIENT_SECRET` | OAuth2 客户端密钥 | `jingying-web-secret-2026` |
| `AUTH_REDIRECT_URI` | 回调地址，须与认证中心 `redirect_uris` 中登记值一致 | `http://localhost:8000/auth/callback` |
| `AUTH_SCOPE` | 授权范围 | `openid profile analysis` |
| `AUTH_INTROSPECT_CACHE_SEC` | 令牌内省结果缓存秒数 | `60` |
| `AUTH_HTTP_TIMEOUT_SEC` | 调用认证中心的 HTTP 超时秒数 | `10` |
| `AUTH_TOKEN_TTL_HINT` | 认证中心未返回 `expires_in` 时的兜底有效期（秒） | `7200` |
| `DATA_DIR` | 文件存储根目录，相对 `backend/`，也可写绝对路径 | `data` |
| `CORS_ORIGINS` | 允许的跨域来源，逗号分隔 | `http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000,http://localhost:4173,http://127.0.0.1:4173` |
| `COOKIE_NAME` | 访问令牌 Cookie 名 | `jy_access_token` |
| `REFRESH_COOKIE_NAME` | 刷新令牌 Cookie 名 | `jy_refresh_token` |
| `COOKIE_SECURE` | 生产走 HTTPS 时必须改为 `true` | `false` |
| `COOKIE_SAMESITE` | Cookie SameSite 策略 | `lax` |

说明：

- 这些是**进程级**配置，改完要重启后端。
- 另一类**业务配置**（可热更新）存在业务库 `system_configs` 表（由 `database/04_dict.sql` 写入），改完调 `POST /api/admin/reload` 即时生效，无需重启。典型项见 `04_dict.sql`：`analysis.max_rounds`、`system.max_upload_mb`、`system.allow_extensions`、`analysis.base_period_start`/`base_period_end`/`anomaly_period_start`/`anomaly_period_end` 等。
- `DATA_DIR` 下的三个子目录 `uploads/`、`exports/`、`workspace/` 由后端启动时自动创建（见下节）。

### 5.3 初始化库表与演示数据

若第三步已经用 mysql 客户端或 `init_db.py` 完成建库建表，可跳过本节。

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\backend"
uv run python scripts/init_db.py
```

`gen_demo_data.py` 是 `database/05_demo_data.sql` 的**生成器**（固定随机种子 `20260901`，输出可复现），它只写文件、不碰数据库；生成的 SQL 已在仓库里，正常部署**不需要**再跑一次。只有要重新造数时才执行：

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\backend"
uv run python scripts/gen_demo_data.py
# 生成后重新导入
cmd.exe /c "D:\JAVA\Mysql\bin\mysql.exe --host=127.0.0.1 --port=3306 --user=root --password=root < ..\database\05_demo_data.sql"
```

`gen_demo_data.py` 无 argparse 参数，统计窗口与输出路径写死在脚本里（`2026-09-01 ~ 2026-09-30`，异常期起点 `2026-09-16`，输出 `database/05_demo_data.sql`）。

### 5.4 启动

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\backend"
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
```

`backend/README.md` 里的简写是 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info`；上面这条更稳妥（指定虚拟环境解释器 + `-X utf8`）。

**后端启动时自动做的事**（`backend/app/main.py` 的 `lifespan`，按顺序）：

1. `ensure_dirs()` — 建好 `uploads/`、`exports/`、`workspace/` 目录；
2. `manager.bind_loop()` — 把 WebSocket 管理器绑到主事件循环（分析在后台线程跑，需要跨线程回投报文）；
3. `runtime_config.load()` — 从数据库 `system_configs` 表加载热更新配置，并打印 `配置加载完成：来源=...，共 N 项`；
4. 数据库连通性检查，成功打印 `业务数据库连通正常：127.0.0.1:3306/analysis_sys`，失败打印 `业务数据库连接失败，请检查 .env 中的数据库配置`；
5. `task_service.cleanup_stale(db, max_age_minutes=1)` — 清理上次进程遗留的 `running`/`queued` 任务。

关闭时：关闭全部 WebSocket 连接 → 等待分析线程池退出。

**注意**：lifespan 里**不会**自动建表、也不会自动导入数据。表和数据必须由第三步的 SQL 完成，否则业务表不存在会直接报 SQL 错误。

### 5.5 验证

| 检查项 | 地址 | 期望 |
| --- | --- | --- |
| 健康检查 | `http://localhost:8000/healthz` | `status` 为 `ok`、`database` 为 `ok`、`auth_center.reachable` 为 `true` |
| 服务根路径 | `http://localhost:8000/` | 返回 service / version / docs / websocket 字段 |
| 接口文档 | `http://localhost:8000/docs` | Swagger UI 正常打开 |
| 公开配置 | `http://localhost:8000/api/config/public` | 返回系统名、WebSocket 路径、上传上限、分析窗口日期 |

```powershell
curl.exe http://localhost:8000/healthz
```

---

## 六、第四步：启动前端（5173）

### 6.1 安装依赖

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\frontend"
npm install
```

本机 npm registry 由用户级 `%USERPROFILE%\.npmrc` 指定为 `http://registry.npmmirror.com/`，`npm install` 会自动走国内镜像，无需额外参数。如需显式切换到 HTTPS：

```powershell
npm config set registry https://registry.npmmirror.com
```

### 6.2 开发模式

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\frontend"
npm run dev
```

- 监听 `127.0.0.1:5173`，`strictPort: true`（5173 被占会直接报错而不是换端口）。
- 浏览器打开 `http://127.0.0.1:5173`。

### 6.3 代理说明

`frontend/vite.config.js` 把三个前缀全部代理到后端，因此前端代码里一律使用相对路径、不存在跨域问题，Cookie 也落在同一个 host：

| 前缀 | 目标 | 是否转发 WebSocket |
| --- | --- | --- |
| `/api` | `http://127.0.0.1:8000` | 是（`ws: true`） |
| `/auth` | `http://127.0.0.1:8000` | 否 |
| `/healthz` | `http://127.0.0.1:8000` | 否 |

### 6.4 覆盖后端地址

代理目标由 `VITE_BACKEND` 决定，缺省 `http://127.0.0.1:8000`：

```powershell
$env:VITE_BACKEND = "http://127.0.0.1:8000"
npm run dev
```

或写成一行（bash 风格，仅在该终端生效）：

```bash
VITE_BACKEND=http://127.0.0.1:8000 npm run dev
```

注意：`vite.config.js` 读的是 `process.env.VITE_BACKEND`，只在 **dev/preview 服务器启动时**生效，改了要重启 `npm run dev`。

### 6.5 生产构建与部署产物

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\frontend"
npm run build
npm run preview
```

- `npm run build` 产出到 `frontend/dist/`（`build.outDir = 'dist'`），本机已有构建产物：`dist/index.html`、`dist/favicon.svg`、`dist/assets/`。
- `npm run preview` 跑的是 `vite preview --port 5173`。
- 生产部署时把 `dist/` 交给静态服务器，并把 `/api`、`/auth`、`/healthz`（含 WebSocket 升级）反向代理到后端 8000。注意此时前端与后端的**主机名必须一致**，否则 HttpOnly Cookie 不匹配（见第九节）。

---

## 七、自检脚本

`backend/scripts/` 下共 4 个可直接运行的脚本 + 2 个工具脚本。下表路径为**实测路径**：

| 脚本 | 类型 | 用途 |
| --- | --- | --- |
| `scripts/init_db.py` | 部署 | 建库、建表、写字典、导演示数据（见第三、五节） |
| `scripts/gen_demo_data.py` | 造数 | 生成 `database/05_demo_data.sql`（固定种子，可复现） |
| `scripts/selfcheck.py` | 自检 | **不依赖 HTTP**：检查运行时配置、场景路由、7 个工具注册、7 个场景端到端跑通、报告六段结构 |
| `scripts/e2e_check.py` | 验收 | **真实 HTTP + WebSocket**：登录、鉴权、会话、附件、实时分析、六大模块、导出、多轮、配置热重载、级联删除 |
| `scripts/tools/stats.py` | 工具 | `shell_exec` 工具白名单脚本，对数字做 `sum` / `describe` / `change` 统计，输出 JSON |
| `scripts/tools/dump_scenarios.py` | 工具 | 打印全部已注册场景的元数据（key、名称、描述、强弱关键词） |

### 7.1 `selfcheck.py`

前置：MySQL 已初始化，`.env` 可用。不需要启动任何服务。

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\backend"
.\.venv\Scripts\python.exe -X utf8 scripts\selfcheck.py
.\.venv\Scripts\python.exe -X utf8 scripts\selfcheck.py --scenario catalog
```

| 参数 | 说明 |
| --- | --- |
| `--scenario` | 只跑指定场景；可选值即 `CASES` 的 key：`catalog`、`market`、`inventory`、`feedback`、`refund`、`growth`、`generic` |

不传 `--scenario` 时会额外汇总检查配置与场景路由。

### 7.2 `e2e_check.py`

前置：**认证中心（9000）与后端（8000）都已启动**，数据库已初始化。退出码非 0 表示有验收项失败。

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\backend"
.\.venv\Scripts\python.exe -X utf8 scripts\e2e_check.py
.\.venv\Scripts\python.exe -X utf8 scripts\e2e_check.py --user admin --password Admin@123
```

参数（见脚本 `argparse`）：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--user` | `analyst` | 登录账号 |
| `--password` | `Analyst@123` | 登录口令 |
| `--admin-user` | `admin` | 管理控制台验收用的管理员账号 |
| `--admin-password` | `Admin@123` | 管理员口令 |
| `--question` | `信息流渠道 ROAS 从 5.9 掉到 1.6，投放预算没变，问题出在哪？` | 用于触发分析的问题 |
| `--keep` | 关 | 保留演示会话不删除 |

**两个环境变量用于改指向**（脚本第 26~27 行）：

| 环境变量 | 默认值 | 覆盖什么 |
| --- | --- | --- |
| `E2E_BACKEND` | `http://localhost:8000` | 被测后端地址 |
| `E2E_AUTH` | `http://localhost:9000` | 被依赖的认证中心地址 |

什么时候需要覆盖：后端或认证中心不是跑在本机默认端口时（例如同机开了两套环境、或把服务放在 127.0.0.1 之外的地址）。

```powershell
$env:E2E_BACKEND = "http://127.0.0.1:8000"
$env:E2E_AUTH = "http://127.0.0.1:9000"
.\.venv\Scripts\python.exe -X utf8 scripts\e2e_check.py
```

脚本执行的验收顺序：登录 → 鉴权拦截 → 会话 → 附件 → 实时分析 → 结果 → 多轮追问 → （管理员身份）配置热重载 → 级联删除收尾。

### 7.3 工具脚本

```powershell
Set-Location "D:\AI_20260413\vibe conding\项目实战文档\jingyingguiyinfenxixitong_108\backend"
.\.venv\Scripts\python.exe -I scripts\tools\stats.py sum 12 34 56
.\.venv\Scripts\python.exe -I scripts\tools\stats.py describe "[1,2,3,4,5]"
.\.venv\Scripts\python.exe -I scripts\tools\stats.py change 11165000 8278000
.\.venv\Scripts\python.exe scripts\tools\dump_scenarios.py
```

`stats.py` 的三个子命令：`sum`（求和）、`describe`（计数/均值/中位数/极值/标准差）、`change`（基准值→当前值的变化率）。

---

## 八、验收清单

前置：MySQL、认证中心(9000)、后端(8000)、前端(5173) 全部在运行；浏览器访问 `http://127.0.0.1:5173`。

| # | 操作 | 成功标准 |
| --- | --- | --- |
| 1 | 打开 `http://127.0.0.1:5173` | 未登录时路由守卫调 `GET /api/auth/me` 失败，自动跳到 `/login` 登录页；页面展示演示账号、分析窗口、8 类长连接报文说明 |
| 2 | 点「登录」 | 整页跳转到认证中心授权页 `http://localhost:9000/oauth/authorize?...`；输入 `analyst` / `Analyst@123` 提交 |
| 3 | 授权成功回跳 | 认证中心 302 带 `code` 回 `http://localhost:8000/auth/callback`，后端换令牌并种下 HttpOnly Cookie `jy_access_token`，再 302 回前端首页；工作台顶栏显示「张分析（运营）」 |
| 4 | 新建会话并提问 | 左侧会话列表出现新会话；提问框下方出现用户消息气泡，同时生成一条 `queued` 分析任务 |
| 5 | 观察实时进度 | 右侧进度区依次出现：场景识别结果（如「商品目录优化」）→ 步骤 `x/y` 与进度条 → 工具调用链（`db_query` 等，含入参、状态、耗时、行数）；消息流里助手正文流式追加 |
| 6 | 等待结果 | 进度到 100%，收到 `result_ready`；结果抽屉 / `/result/:taskId` 页出现**六大模块**：问题定义、关键指标、证据列表（按来源类型着色、按置信度分档）、归因结论、待补充数据、下一步建议（至少 2 条） |
| 7 | 导出 | `ExportBar` 提供 Markdown / JSON / Excel 三种格式下载；下载文件名沿用服务端 `Content-Disposition`。对应后端 `GET /api/results/download?result_id=<id>&format=md|json|xlsx` |
| 8 | 多轮追问 | 在同一会话继续提问，助手沿用上一轮场景作答；进度区重新走一遍步骤与工具链 |
| 9 | 刷新页面 | 重连后先收到 `connected`，紧接着补发上一轮报文（带 `replayed: true`），进度与正文完整还原，不重复累加 |
| 10 | 历史会话 | `/history` 能看到会话表格、搜索、改名、批量删除；展开行可看该会话的分析任务 |
| 11 | 管理控制台（仅 admin） | 用 `admin` / `Admin@123` 登录后 `/admin` 可打开：运行总览、配置热重载（改值→保存→`POST /api/admin/reload` 生效且返回变更 diff）、功能开关、业务数据源、场景与工具、运行日志 |
| 12 | 一键验收 | 执行第七节 `e2e_check.py`，输出「全部验收项通过」且退出码为 0 |

---

## 九、常见问题

### 来自 `backend/README.md`

**`/api/chat/ls` 报 SQL 语法错误（`NULLS LAST`）**
- 现象：调用会话列表接口返回 SQL 语法错误。
- 原因：MySQL 不支持 `NULLS LAST`。
- 解决：DESC 排序时 NULL 天然排在最后，不要用 SQLAlchemy 的 `.nullslast()`。

**分析结果里品类数据全为 0**
- 现象：归因结论里各类目指标都是 0。
- 原因：`biz_category.category_id` 是 `C01`…`C05` 的字符串编码，不是数字。
- 解决：场景 SQL 里给类目 ID 加引号，或走 `app/analysis/scenarios/common.py` 的 `resolve_category_id()` 解析。

**配置改了不生效**
- 现象：改完 `system_configs` 里的值，行为没变化。
- 原因：键名与代码读取的键名不一致时，代码会静默回退到默认值。
- 解决：先用 `GET /api/admin/configs` 确认该键在库里存在且名称与代码一致；改完必须调 `POST /api/admin/reload` 才生效；新增配置项时同时补进 `database/04_dict.sql`。

### 来自 `frontend/README.md`

**浏览器控制台报 WebSocket 404**
- 现象：长连接建立失败，控制台出现 404。
- 原因：`npm run dev` 起的不是本项目的 Vite（5173），或代理的 `ws: true` 没生效。
- 解决：确认 `npm run dev` 在本项目 `frontend/` 目录下执行、端口是 5173，且 `vite.config.js` 里 `/api` 代理带 `ws: true`。

**登录后回到前端仍显示未登录**
- 现象：授权成功回跳了，但前端仍跳登录页。
- 原因：Cookie 按 host 存（不区分端口），要求后端与前端在**同一个 host**。用 `localhost:5173` 访问前端、而 `.env` 里后端地址写的是 `127.0.0.1`（或反之）会导致 Cookie 对不上。
- 解决：前端与后端统一用一个主机名。要么全程 `localhost`，要么全程 `127.0.0.1`。

**上传附件提示类型不支持**
- 现象：附件上传被前端拦下或后端返回 413 / 类型错误。
- 原因：允许的扩展名来自后端 `/api/config/public` 的 `allowed_upload_ext`（默认 `txt,md,csv,json,xlsx,xls,pdf,log`），大小上限来自 `system.max_upload_mb`（默认 50）。
- 解决：登录管理员，在管理控制台改 `system.allow_extensions` / `system.max_upload_mb`，然后热重载。

### 补充排查

**端口被占用**
- 现象：`node:events` / uvicorn 启动即退出，报 `error while attempting to bind on address ... only one usage of each socket address` 或 Vite 因 `strictPort` 直接失败。
- 原因：9000 / 8000 / 5173 中某个已被占用。
- 解决：

```powershell
netstat -ano | Select-String ":9000|:8000|:5173"
Stop-Process -Id <PID> -Force
```

前端因 `strictPort: true` 不会自动换端口，必须先释放 5173。

**Cookie 主机名不一致**
- 现象：第 2、3 步登录流程走完，`GET /api/auth/me` 仍返回 401。
- 原因：`.env` 的 `PUBLIC_BASE_URL` / `FRONTEND_BASE_URL` 用的主机名与浏览器地址栏的主机名不同（`localhost` vs `127.0.0.1`）；Cookie 是 host 隔离的，反之亦然。
- 解决：把 `.env` 的 `PUBLIC_BASE_URL=http://localhost:8000`、`FRONTEND_BASE_URL=http://localhost:5173`，认证中心 `redirect_uris` 里的回调地址，以及浏览器访问地址统一到同一个主机名，然后重启后端。

**WebSocket 404 / 握手被拒**
- 现象：进度区不动，控制台 WebSocket 报 404 或连接被以 `4001` / `4003` 关闭。
- 原因：路径应为 `/api/chat/ws/chat`，且握手必须带一次性令牌。
- 解决：
  - 404：确认走的是 Vite 代理（前端 5173）或直连后端 8000，路径为 `/api/chat/ws/chat?websocket_token=<token>&conversation_id=<id>`。
  - `4001`：令牌无效/已消费/过期 —— 先 `POST /api/chat/ws-token` 重新签发再连。
  - `4003`：`conversation_id` 与令牌绑定不一致，或会话不属于当前用户 —— 不要重连，改用本会话自己的令牌。

**认证中心没起**
- 现象：后端 `/healthz` 里 `auth_center.reachable` 为 `false`；登录时页面报错；日志出现 `无法连接认证中心令牌接口: ...` 或 `认证中心不可用: ...`，回调处理失败。
- 原因：9000 未启动，或 `.env` 的 `AUTH_BASE_URL` 指向不对。
- 解决：先起认证中心，`curl.exe http://localhost:9000/oauth/healthz` 确认返回 `status: ok`，再确认 `AUTH_BASE_URL=http://localhost:9000`。注意令牌内省结果有 60 秒缓存（`AUTH_INTROSPECT_CACHE_SEC`），认证中心短暂抖动时可能仍沿用缓存。

**MySQL 连不上**
- 现象：后端启动日志打印 `业务数据库连接失败，请检查 .env 中的数据库配置`；接口返回 `数据库操作失败：...`；认证中心打印 `认证库自检失败：...`。
- 原因：MySQL 服务未启动、口令不对、库还没建。
- 解决：

```powershell
# 先用客户端确认连通（无输入重定向，直接用调用运算符）
& "D:\JAVA\Mysql\bin\mysql.exe" --host=127.0.0.1 --port=3306 --user=root --password=root -e "SELECT VERSION(), @@character_set_server"
```

再核对 `.env` 的 `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME`；如果是库不存在，先执行第三节的初始化。

**Node / uv 装不上、依赖拉不下来**
- 现象：`npm install` 超时或 `uv sync` 卡在下载；下载 GitHub 上的资源报错（如 `winget` 报 `0x80072efd`）。
- 原因：本机直连 GitHub / 官方源不稳定。
- 解决：
  - npm 走国内镜像：`npm config get registry` 应为 `http://registry.npmmirror.com/`；不对就 `npm config set registry https://registry.npmmirror.com`。
  - 需要访问 GitHub 时启用 Clash Verge 代理 `127.0.0.1:7897`，例如：

```powershell
$env:HTTP_PROXY = "http://127.0.0.1:7897"
$env:HTTPS_PROXY = "http://127.0.0.1:7897"
uv sync
```

**`python -X utf8` 与中文乱码**
- 现象：脚本输出或服务日志中文变成乱码。
- 原因：Windows 控制台默认代码页非 UTF-8。
- 解决：所有 Python 命令都带上 `-X utf8`（本文档中的命令均已带）；SQL 导入必须走 `cmd.exe /c "... < 文件"` 而不是 PowerShell 重定向。
