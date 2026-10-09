-- =============================================================================
-- 经营多轮归因分析系统 —— 基础字典脚本
-- 数据库: analysis_sys
-- 内容: 业务库用户镜像、系统配置字典、业务数据源字典、业务枚举字典
-- 版本: 1.0.0
-- =============================================================================

USE `analysis_sys`;

-- -----------------------------------------------------------------------------
-- 1. 用户镜像（与认证中心 auth_users 对应）
--    external_user_id = 认证中心 auth_users.id
-- -----------------------------------------------------------------------------
INSERT INTO `users` (`id`, `external_user_id`, `username`, `display_name`, `role`, `status`) VALUES
(1, '1', 'admin',    '系统管理员',      'admin',   'active'),
(2, '2', 'analyst',  '张分析（运营）',   'analyst', 'active'),
(3, '3', 'zhangyun', '赵云舒（商品运营）', 'analyst', 'active')
ON DUPLICATE KEY UPDATE
    `external_user_id` = VALUES(`external_user_id`),
    `display_name`     = VALUES(`display_name`),
    `role`             = VALUES(`role`),
    `status`           = VALUES(`status`);

-- -----------------------------------------------------------------------------
-- 2. 系统配置字典
--    config_group: system 系统 / analysis 分析 / auth 认证 / storage 存储 /
--                  llm 大模型 / feature 功能开关 / security 安全
--    说明: 本表为配置热更新的数据源，管理员修改后调用 POST /api/admin/reload 即时生效
-- -----------------------------------------------------------------------------
INSERT INTO `system_configs` (`config_key`, `config_value`, `config_group`, `description`) VALUES
-- 系统基础
('system.name',              '经营多轮归因分析系统', 'system',    '系统名称，展示于前端页头'),
('system.version',           '1.0.0',               'system',    '系统版本号'),
('system.env',               'dev',                 'system',    '运行环境 dev/test/prod'),
('system.page_size',         '20',                  'system',    '历史消息默认分页条数'),
('system.max_upload_mb',     '50',                  'system',    '单个附件上传大小上限（MB）'),
('system.allow_extensions',  'txt,md,csv,json,xlsx,xls,pdf,log', 'system', '允许上传的附件扩展名，逗号分隔'),
('system.max_concurrent_tasks', '4',                'system',    '同时执行的分析任务数上限（后台线程池大小）'),
('websocket.token_ttl_sec',  '300',                 'system',    'WebSocket 一次性握手令牌有效期（秒）'),
-- 分析引擎
('analysis.max_rounds',      '20',                  'analysis',  '单会话最大分析轮次'),
-- 分析窗口：基准期用于对照，异常期用于发现异动，全部场景 SQL 均按此切分
('analysis.base_period_start',    '2026-09-01', 'analysis', '基准期开始日期'),
('analysis.base_period_end',      '2026-09-15', 'analysis', '基准期结束日期'),
('analysis.anomaly_period_start', '2026-09-16', 'analysis', '异常期开始日期'),
('analysis.anomaly_period_end',   '2026-09-30', 'analysis', '异常期结束日期'),
('analysis.tool_timeout_sec','60',                  'analysis',  '单个工具执行超时时间（秒）'),
('analysis.max_tool_calls',  '12',                  'analysis',  '单轮分析最大工具调用次数'),
('analysis.context_keep_rounds', '4',               'analysis',  '上下文保留的最近轮数，超出部分压缩为摘要'),
('analysis.summary_trigger_messages', '40',         'analysis',  '消息数超过该阈值时触发上下文摘要压缩'),
('analysis.step_interval_ms', '300',                'analysis',  '分析步骤间推送间隔（毫秒），用于演示流式过程'),
('analysis.default_scenario', 'auto',               'analysis',  '默认业务场景 auto=按问题自动识别'),
-- 认证接入
('auth.authorize_url',       'http://localhost:9000/oauth/authorize', 'auth', '认证中心授权地址'),
('auth.token_url',           'http://localhost:9000/oauth/token',     'auth', '认证中心令牌地址'),
('auth.userinfo_url',        'http://localhost:9000/oauth/userinfo',  'auth', '认证中心用户信息地址'),
('auth.introspect_url',      'http://localhost:9000/oauth/introspect','auth', '认证中心令牌内省地址'),
('auth.client_id',           'jingying-web',            'auth', '接入客户端ID'),
('auth.client_secret',       'jingying-web-secret-2026','auth', '接入客户端密钥'),
('auth.redirect_uri',        'http://localhost:8000/auth/callback', 'auth', '本系统回调地址'),
('auth.introspect_cache_sec','60',                      'auth', '令牌内省结果缓存秒数'),
-- 存储
('storage.upload_dir',       'uploads',    'storage', '附件存储根目录，规范 uploads/{user_id}/{conversation_id}/'),
('storage.export_dir',       'exports',    'storage', '导出结果存储根目录，规范 exports/{user_id}/{conversation_id}/'),
('storage.workspace_dir',    'workspace',  'storage', '分析临时目录，规范 workspace/{user_id}/{conversation_id}/'),
('storage.retention_days',   '30',         'storage', '导出文件保留天数'),
-- 大模型（分析引擎增强，留空则使用内置规则引擎）
('llm.enabled',              'false',      'llm', '是否启用大模型增强，true 时由 LLM 润色结论文本'),
('llm.provider',             'openai_compatible', 'llm', 'provider: openai_compatible / anthropic / dashscope'),
('llm.base_url',             '',           'llm', '大模型服务地址'),
('llm.api_key',              '',           'llm', '大模型 API Key'),
('llm.model',                '',           'llm', '模型名称'),
('llm.temperature',          '0.2',        'llm', '采样温度'),
('llm.timeout_sec',          '60',         'llm', '调用超时时间（秒）'),
-- 功能开关
('feature.enable_shell_tool',    'true',   'feature', '是否启用命令执行工具（白名单受控）'),
('feature.enable_file_write',    'true',   'feature', '是否启用文件写入工具'),
('feature.enable_export',        'true',   'feature', '是否启用分析结果导出'),
('feature.enable_ws_stream',     'true',   'feature', '是否启用长连接实时推送'),
('feature.enable_multi_turn',    'true',   'feature', '是否启用多轮追问'),
('feature.maintenance_mode',     'false',  'feature', '维护模式，开启后除管理员外禁止发起分析'),
-- 安全
('security.allowed_shell_commands', 'echo,dir,type,findstr,python,where', 'security', '命令执行工具白名单命令'),
('security.sql_readonly',           'true',  'security', '数据库查询工具是否强制只读（禁止 insert/update/delete/drop）'),
('security.sql_row_limit',          '2000',  'security', '数据库查询工具单次最大返回行数')
ON DUPLICATE KEY UPDATE
    `config_group` = VALUES(`config_group`),
    `description`  = VALUES(`description`);

-- -----------------------------------------------------------------------------
-- 3. 业务数据源字典
-- -----------------------------------------------------------------------------
INSERT INTO `data_sources` (`name`, `ds_type`, `host`, `port`, `db_name`, `db_user`, `db_password`, `status`, `description`) VALUES
('主业务库', 'mysql', '127.0.0.1', 3306, 'analysis_sys', 'root', 'root', 'enabled', '经营分析主业务库，承载全部演示场景数据'),
('认证中心库', 'mysql', '127.0.0.1', 3306, 'analysis_auth', 'root', 'root', 'enabled', '认证中心用户与令牌库（管理员只读查看）'),
('本地知识库', 'file', NULL, NULL, NULL, NULL, NULL, 'enabled', '知识库目录 backend/knowledge，供文本检索工具使用')
ON DUPLICATE KEY UPDATE
    `ds_type`     = VALUES(`ds_type`),
    `description` = VALUES(`description`);

-- -----------------------------------------------------------------------------
-- 4. 业务枚举字典（存于 system_configs，config_group='dict'）
-- -----------------------------------------------------------------------------
INSERT INTO `system_configs` (`config_key`, `config_value`, `config_group`, `description`) VALUES
('dict.conversation_status', 'active=正常活跃,archived=已归档,deleted=已删除', 'dict', '会话状态枚举'),
('dict.task_status',         'queued=排队中,running=运行中,success=执行成功,failed=执行失败,cancelled=已取消', 'dict', '分析任务状态枚举'),
('dict.message_role',        'user=用户,assistant=助手,system=系统,tool=工具', 'dict', '消息角色枚举'),
('dict.message_type',        'text=普通文本,tool_call=工具调用,tool_result=工具结果,result=结构化结果,error=错误', 'dict', '消息类型枚举'),
('dict.parse_status',        'pending=待解析,parsing=解析中,parsed=已解析,failed=解析失败', 'dict', '附件解析状态枚举'),
('dict.user_role',           'analyst=分析用户,admin=系统管理员', 'dict', '用户角色枚举'),
('dict.ws_message_type',     'message_start=分析开始,message_delta=文本增量,tool_start=工具开始,tool_finish=工具完成,task_status=状态变更,result_ready=结果就绪,error=错误,done=本轮结束', 'dict', '长连接消息类型枚举')
ON DUPLICATE KEY UPDATE
    `config_value` = VALUES(`config_value`),
    `description`  = VALUES(`description`);
