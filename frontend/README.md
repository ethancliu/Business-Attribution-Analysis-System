# 经营多轮归因分析系统 · 前端

Vue 3 + Vite + Element Plus 实现的分析工作台。五个页面，围绕「提问 → 实时进度 → 六大模块结果 → 导出」的主链路组织。

## 技术栈

| 组件 | 选型 |
| --- | --- |
| 框架 | Vue 3 `<script setup>` 组合式 API |
| 构建 | Vite 6 |
| 路由 | Vue Router 4（history 模式） |
| 状态 | Pinia（setup store 写法） |
| UI | Element Plus 2.9（全量引入 + 中文语言包 + 图标全局注册） |
| 实时 | 原生 WebSocket（自研客户端，封装取令牌、心跳、断线重连） |
| 样式 | scoped CSS + CSS 变量主题（`src/styles/variables.css`） |

## 快速开始

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173
```

开发服务器把 `/api`、`/auth`、`/healthz`（含 WebSocket 升级）代理到后端 8000，
因此前端一律使用相对路径，不存在跨域问题，Cookie 也落在同一个 host 上。

后端地址可通过环境变量覆盖：

```bash
VITE_BACKEND=http://127.0.0.1:8000 npm run dev
```

生产构建：

```bash
npm run build        # 产物在 dist/
npm run preview      # 本地预览
```

## 页面结构

| 路由 | 页面 | 内容 |
| --- | --- | --- |
| `/login` | 登录页 | 点击跳转认证中心完成 OAuth2 授权；展示演示账号、分析窗口、8 类长连接报文说明 |
| `/` | 分析工作台 | 三栏：会话列表 / 消息流 + 提问框 / 实时进度 + 附件；结果抽屉 |
| `/history` | 历史会话 | 会话表格、搜索、改名、批量删除、展开行查看该会话的分析任务 |
| `/result/:taskId` | 分析结果详情 | 六大模块标准化输出 + 任务元信息 + 工具调用链 + 导出 |
| `/admin` | 管理控制台 | 运行总览、配置热重载、功能开关、业务数据源、场景与工具、运行日志（仅 admin） |

路由守卫在首次进入时调用 `GET /api/auth/me` 确认登录态；未登录跳 `/login`，
非管理员访问 `/admin` 会被拦回工作台。

## 目录结构

```
src/
├── main.js               # 应用装配：Pinia、Router、Element Plus、图标
├── App.vue               # 外壳：登录页不加顶栏，其余页面统一 header + 内容区
├── api/                  # 接口封装（fetch），按后端模块拆分
│   ├── http.js           # 统一客户端：查询串、错误归一化、文件下载
│   ├── auth.js  chat.js  attachment.js  task.js  result.js  admin.js
├── store/                # Pinia：user / conversation / chat / result / admin
├── ws/client.js          # 长连接客户端：取令牌、心跳、断线重连、状态机
├── components/           # 7 个业务模块组件 + 通用组件
│   ├── ConversationList.vue    # 会话管理模块
│   ├── MessageStream.vue       # 消息流模块（含流式光标）
│   ├── TaskProgressPanel.vue   # 实时进度模块（步骤 + 工具调用链）
│   ├── AttachmentPanel.vue     # 附件模块
│   ├── ResultModules.vue       # 结果六大模块渲染
│   ├── ExportBar.vue           # 导出模块
│   ├── AskComposer.vue         # 提问输入区
│   ├── AppHeader.vue  EmptyState.vue
├── views/                # 5 个页面
├── router/index.js
└── utils/                # constants.js（枚举字典）、format.js（格式化）
```

## 七个前端模块与职责

1. **会话管理**（`ConversationList.vue` + `store/conversation.js`）：新建、搜索、选择、改名、删除；删除会提示级联清理范围。
2. **消息流**（`MessageStream.vue` + `store/chat.js`）：历史消息游标分页、上滑加载更早；助手消息支持流式追加。
3. **实时进度**（`TaskProgressPanel.vue`）：场景识别、当前步骤、进度条、工具调用链（名称 / 入参 / 状态 / 耗时 / 行数）、长连接状态与自动重连提示。
4. **附件**（`AttachmentPanel.vue` + `AskComposer.vue`）：上传（类型与大小前置校验）、解析状态、预览、下载、删除。
5. **结果展示**（`ResultModules.vue`）：六大模块结构化渲染；证据按来源类型着色、按置信度分档。
6. **导出**（`ExportBar.vue`）：Markdown / JSON / Excel 三种格式，沿用服务端 `Content-Disposition` 的文件名。
7. **管理配置**（`views/AdminView.vue` + `store/admin.js`）：配置查看与修改（自动热重载）、全量重载与变更 diff、功能开关、数据源、场景与工具清单、运行日志。

## 长连接约定

握手令牌是**一次性**的：每次（重）连都要先 `POST /api/chat/ws-token` 换新令牌，
`src/ws/client.js` 已把这件事封装进 `tokenProvider`。

服务端在 `accept` 之后先推 `connected`，紧接着把该会话最近一轮的报文**补发**一遍
（报文带 `replayed: true`）。前端收到「重放版 `message_start`」时会先把实时状态清空再重建，
因此页面刷新、短暂断网重连都不会出现重复累加，也不会丢进度。

`store/chat.js` 的 `handleEvent()` 集中处理需求规定的 8 种报文：

| 报文 | 前端动作 |
| --- | --- |
| `message_start` | 初始化实时状态：场景、步骤总数、流式开关 |
| `message_delta` | 追加到流式文本，同时写入对应助手消息气泡 |
| `tool_start` | 往工具调用链插入一条「执行中」记录 |
| `tool_finish` | 回填该次调用的状态、结果摘要、耗时、行数 |
| `task_status` | 更新状态、当前步骤、进度百分比 |
| `result_ready` | 记录 `result_id` 与下载地址，进度置 100% |
| `error` | 展示错误信息，结束流式 |
| `done` | 收口，并以服务端落库内容为准刷新助手消息正文 |

## 认证与 Cookie

登录是整页跳转：前端 `window.location.href = '/auth/login'` → 后端 302 到认证中心授权页 →
授权码回调后端换取令牌并种下 `HttpOnly` Cookie `jy_access_token` → 后端 302 回前端首页。

令牌对前端不可见（HttpOnly），前端只通过 `GET /api/auth/me` 判断登录态。
所有请求携带 `credentials: 'include'`。

## 常见问题

**浏览器控制台报 WebSocket 404**
确认 `npm run dev` 启动的是本项目的 Vite（5173），并且代理配置里的 `ws: true` 生效。

**登录后回到前端仍显示未登录**
Cookie 是按 host 存的（不区分端口），但要求后端与前端在同一 host。用 `localhost` 访问前端、
后端配置却写成 `127.0.0.1`（或反之）会导致 Cookie 不匹配。统一用一个主机名即可。

**上传附件提示类型不支持**
允许的扩展名来自后端 `/api/config/public` 的 `allowed_upload_ext`，可在管理控制台改
`system.allow_extensions` 后热重载。
