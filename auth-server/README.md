# 经营多轮归因分析系统 · 认证中心

独立的 OAuth2 授权码模式认证服务。业务后端不持有任何口令与令牌签发逻辑，只通过本服务的 `/oauth/introspect` 判定令牌有效性。

## 技术栈

| 组件 | 选型 |
| --- | --- |
| 框架 | FastAPI |
| 数据库 | MySQL 8（库 `analysis_auth`）+ SQLAlchemy 2.0 + PyMySQL |
| 配置 | pydantic-settings（环境变量 / `.env`） |
| 登录页 | Jinja2 服务端渲染（`app/static/login.html`） |
| 依赖管理 | uv |

## 快速开始

```bash
cd auth-server
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 9000 --log-level info
```

- 健康检查：<http://127.0.0.1:9000/oauth/healthz>
- 接口文档：<http://127.0.0.1:9000/docs>

数据库先建好：执行 `database/01_auth_schema.sql`（含建库、建表与预置客户端/账号），
或直接跑 `backend/scripts/init_db.py`。

## 配置

全部配置项都有默认值，**不创建 `.env` 也能直接启动**。需要覆盖时复制 `.env.example` 为 `.env`。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `9000` | 监听地址与端口 |
| `DEBUG` | `true` | 调试模式 |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` | 认证库地址 |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `root` / `root` / `analysis_auth` | 认证库账号 |
| `AUTH_CODE_TTL_SEC` | `300` | 授权码有效期 5 分钟 |
| `ACCESS_TOKEN_TTL_SEC` | `7200` | 访问令牌 2 小时 |
| `REFRESH_TOKEN_TTL_SEC` | `604800` | 刷新令牌 7 天 |
| `SESSION_TTL_SEC` | `43200` | 登录会话 12 小时 |
| `ADMIN_API_KEY` | `jingying-auth-admin-2026` | 自管理接口的 `X-Admin-Key` |
| `CORS_ORIGINS` | `*` | 允许来源，逗号分隔 |

> `HOST` 默认是 `0.0.0.0`，本机联调建议显式传 `--host 127.0.0.1`，避免把服务暴露到局域网。

## 预置数据

`database/01_auth_schema.sql` + `04_dict.sql` 会写入一个客户端与三个账号。

**OAuth2 客户端**

| 项 | 值 |
| --- | --- |
| `client_id` | `jingying-web` |
| `client_secret` | `jingying-web-secret-2026` |
| 授权范围 | `openid profile analysis` |
| 已注册回调 | `http://localhost:8000/auth/callback`、`http://127.0.0.1:8000/auth/callback`、`http://localhost:5173/auth/callback`、`http://localhost:5173/login/callback` |

回调地址必须与业务后端 `.env` 里的 `AUTH_REDIRECT_URI` **完全一致**，否则换令牌时返回 `400 回调地址不一致`。

**演示账号**

| 用户名 | 口令 | 角色 | 姓名 |
| --- | --- | --- | --- |
| `admin` | `Admin@123` | admin | 系统管理员 |
| `analyst` | `Analyst@123` | analyst | 张分析（运营） |
| `zhangyun` | `Zhang@123` | analyst | 赵云舒（商品运营） |

口令摘要为 `SHA256(salt + password)`，在 SQL 里由 MySQL 的 `SHA2()` 直接算出，因此脚本可独立复现。
生产环境应替换为 bcrypt / argon2。

## 授权码流程

```
GET  /oauth/authorize   ?response_type=code&client_id=&redirect_uri=&scope=&state=
     未登录 -> 渲染登录页；已登录 -> 302 回 redirect_uri?code=&state=
POST /oauth/login       提交账号口令，建立登录会话（Cookie auth_sid）并回跳带回授权码
POST /oauth/token       用授权码或刷新令牌换访问令牌（不透明 token）
POST /oauth/introspect  令牌内省，业务后端据此判定有效性（本服务不可用则业务后端只能依赖缓存）
POST /oauth/revoke      吊销单个访问令牌
POST /oauth/logout      登出，吊销会话及其下全部令牌
GET  /oauth/userinfo    取当前令牌对应用户
GET  /oauth/sessions    查询登录会话列表
GET  /oauth/healthz     健康检查
```

令牌一律为随机不透明字符串，业务后端无法本地校验，因此吊销、强制下线、口令重置都在本服务一处生效。

## 自管理接口

需要请求头 `X-Admin-Key: <ADMIN_API_KEY>`。

| 接口 | 作用 |
| --- | --- |
| `GET /admin/overview` | 认证中心总览统计 |
| `GET /admin/clients` / `POST /admin/clients/{client_id}/toggle` | 客户端列表与启停 |
| `GET /admin/users` / `POST /admin/users/{username}/toggle` | 用户列表与启停 |
| `POST /admin/users/{username}/reset-password` | 重置口令 |
| `GET /admin/logs` | 认证操作日志 |
| `POST /admin/sessions/{session_id}/kick` | 强制下线指定会话 |
| `POST /admin/cleanup` | 清理过期授权码与令牌 |

业务后端的 `GET /api/admin/auth-center` 就是代理调用 `GET /admin/overview` 得到的。

## 目录结构

```
auth-server/
├── app/
│   ├── main.py              # 服务入口：路由装配、异常处理、登录页
│   ├── api/
│   │   ├── oauth.py         # 授权、令牌、内省、吊销、登出、用户信息、会话
│   │   └── admin.py         # 自管理接口（X-Admin-Key 保护）
│   ├── core/
│   │   ├── config.py        # 配置项与默认值
│   │   ├── db.py            # 引擎与会话工厂
│   │   └── security.py      # 口令校验与令牌生成
│   ├── models/__init__.py   # 6 张表：clients / users / codes / tokens / sessions / login_logs
│   ├── schemas/__init__.py
│   └── static/login.html    # 登录页模板
└── pyproject.toml
```

## 常见问题

**业务后端登录后报 `换取令牌失败（400）：回调地址不一致`**
业务后端提交的 `redirect_uri` 与本服务记在授权码上的不一致。检查后端 `.env` 的 `AUTH_REDIRECT_URI`
是否在 `auth_clients.redirect_uris` 里，注意协议、主机名、端口、末尾斜杠都要一致。

**浏览器登录成功后回到前端仍显示未登录**
业务后端的回调没走通。直接看后端日志有没有 `换取令牌失败`；若日志显示 302 但没写 Cookie，
多半是回调请求被前端开发服务器的代理拦下了，而后端配置的回调地址是 8000——浏览器会按后端返回的
302 直达 8000，这是正常的，因为 Cookie 按 host 共享、不区分端口。

**改了口令后旧令牌还能用**
访问令牌有 2 小时有效期。需要立即失效就调 `POST /admin/sessions/{session_id}/kick`
踢掉该会话，或 `POST /admin/cleanup` 清理过期凭据。
