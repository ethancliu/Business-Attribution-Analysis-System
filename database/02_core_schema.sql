-- =============================================================================
-- 经营多轮归因分析系统 —— 业务库核心表结构
-- 数据库: analysis_sys
-- 说明: 11 张核心表
--        前 10 张（users ... task_logs）字段名/字段含义严格对齐《需求规范 九、数据库数据表设计》，
--        第 11 张 data_sources 是本系统补充的业务数据源登记表，供管理控制台的数据源页启用/停用。
-- 版本: 1.0.0
-- =============================================================================

CREATE DATABASE IF NOT EXISTS `analysis_sys`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_general_ci;
USE `analysis_sys`;

SET FOREIGN_KEY_CHECKS = 0;

-- -----------------------------------------------------------------------------
-- 1. users 用户表
--    业务库侧的用户镜像，external_user_id 关联认证中心 auth_users.id
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
    `id`               BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `external_user_id` VARCHAR(64)  NOT NULL COMMENT '外部（认证中心）用户ID',
    `username`         VARCHAR(64)  NOT NULL COMMENT '登录账号',
    `display_name`     VARCHAR(128) NOT NULL COMMENT '显示名称',
    `role`             VARCHAR(32)  NOT NULL DEFAULT 'analyst' COMMENT '角色: analyst 分析用户, admin 系统管理员',
    `status`           VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT '状态: active 正常, disabled 停用',
    `created_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_external_user_id` (`external_user_id`),
    UNIQUE KEY `uk_username` (`username`),
    KEY `idx_role` (`role`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '用户表';

-- -----------------------------------------------------------------------------
-- 2. conversations 会话表
--    status: active 正常活跃 / archived 已归档 / deleted 已删除
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `conversations`;
CREATE TABLE `conversations` (
    `id`              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `user_id`         BIGINT       NOT NULL COMMENT '所属用户ID',
    `title`           VARCHAR(255) NOT NULL DEFAULT '新的分析会话' COMMENT '会话标题',
    `status`          VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT '状态: active 正常活跃, archived 已归档, deleted 已删除',
    `last_message_at` DATETIME     DEFAULT NULL COMMENT '最后一条消息时间',
    `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_user_status_time` (`user_id`, `status`, `last_message_at`),
    CONSTRAINT `fk_conv_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '会话表';

-- -----------------------------------------------------------------------------
-- 3. messages 消息表
--    role: user / assistant / system / tool
--    message_type: text 普通文本 / tool_call 工具调用 / tool_result 工具结果 /
--                  result 结构化结果 / error 错误
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `messages`;
CREATE TABLE `messages` (
    `id`              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `conversation_id` BIGINT       NOT NULL COMMENT '所属会话ID',
    `role`            VARCHAR(16)  NOT NULL COMMENT '角色: user 用户, assistant 助手, system 系统, tool 工具',
    `message_type`    VARCHAR(32)  NOT NULL DEFAULT 'text' COMMENT '消息类型: text/tool_call/tool_result/result/error',
    `content`         MEDIUMTEXT   NOT NULL COMMENT '消息内容',
    `tool_name`       VARCHAR(64)  DEFAULT NULL COMMENT '工具名称（工具类消息专用）',
    `tool_status`     VARCHAR(16)  DEFAULT NULL COMMENT '工具状态: running/success/failed',
    `seq_no`          INT          NOT NULL DEFAULT 1 COMMENT '会话内序号，保证时序',
    `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    KEY `idx_conv_seq` (`conversation_id`, `seq_no`),
    KEY `idx_conv_created` (`conversation_id`, `created_at`),
    CONSTRAINT `fk_msg_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '消息表';

-- -----------------------------------------------------------------------------
-- 4. attachments 附件表
--    parse_status: pending 待解析 / parsing 解析中 / parsed 已解析 / failed 解析失败
--    文件落盘路径规范: uploads/{user_id}/{conversation_id}/
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `attachments`;
CREATE TABLE `attachments` (
    `id`              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `conversation_id` BIGINT       NOT NULL COMMENT '所属会话ID',
    `message_id`      BIGINT       DEFAULT NULL COMMENT '关联消息ID（可为空，表示仅上传未发送）',
    `file_name`       VARCHAR(255) NOT NULL COMMENT '原始文件名',
    `file_path`       VARCHAR(512) NOT NULL COMMENT '存储相对路径 uploads/{user_id}/{conversation_id}/xxx',
    `file_type`       VARCHAR(64)  NOT NULL DEFAULT 'unknown' COMMENT '文件类型（扩展名）',
    `file_size`       BIGINT       NOT NULL DEFAULT 0 COMMENT '文件大小（字节）',
    `parse_status`    VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '解析状态: pending/parsing/parsed/failed',
    `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
    PRIMARY KEY (`id`),
    KEY `idx_conv_created` (`conversation_id`, `created_at`),
    KEY `idx_parse_status` (`parse_status`),
    CONSTRAINT `fk_att_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '附件表';

-- -----------------------------------------------------------------------------
-- 5. analysis_tasks 分析任务表
--    task_status: queued 排队中 / running 运行中 / success 执行成功 /
--                 failed 执行失败 / cancelled 已取消
--    规则: 一条用户提问消息 -> 一个独立分析任务
--          同一会话同一时间仅允许一个 running 任务
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `analysis_tasks`;
CREATE TABLE `analysis_tasks` (
    `id`              BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `conversation_id` BIGINT      NOT NULL COMMENT '所属会话ID',
    `user_id`         BIGINT      NOT NULL COMMENT '发起用户ID',
    `input_text`      TEXT        NOT NULL COMMENT '本轮用户提问原文',
    `task_status`     VARCHAR(16) NOT NULL DEFAULT 'queued' COMMENT '状态: queued/running/success/failed/cancelled',
    `current_step`    VARCHAR(128) DEFAULT NULL COMMENT '当前执行步骤描述',
    -- 毫秒精度（fsp=3）：一次分析通常只跑几百毫秒，秒级精度会让耗时恒为 0
    `started_at`      DATETIME(3) DEFAULT NULL COMMENT '开始执行时间',
    `finished_at`     DATETIME(3) DEFAULT NULL COMMENT '结束时间',
    `error_message`   TEXT        DEFAULT NULL COMMENT '错误信息',
    `created_at`      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    KEY `idx_conv_status` (`conversation_id`, `task_status`),
    KEY `idx_user_created` (`user_id`, `created_at`),
    CONSTRAINT `fk_task_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '分析任务表';

-- -----------------------------------------------------------------------------
-- 6. analysis_results 分析结果表
--    六大固定模块：问题定义 / 关键指标 / 证据列表 / 归因结论 / 待补充数据 / 下一步建议
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `analysis_results`;
CREATE TABLE `analysis_results` (
    `id`                  BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `task_id`             BIGINT      NOT NULL COMMENT '所属任务ID',
    `conversation_id`     BIGINT      NOT NULL COMMENT '所属会话ID',
    `problem_definition`  TEXT        NOT NULL COMMENT '模块1 问题定义',
    `key_metrics_json`    JSON        DEFAULT NULL COMMENT '模块2 关键指标数组 [{metric_name,metric_value,metric_unit,metric_period}]',
    `evidence_list_json`  JSON        DEFAULT NULL COMMENT '模块3 证据列表 [{source_type,source_name,evidence_text,related_metric,confidence}]',
    `conclusion_text`     MEDIUMTEXT  NOT NULL COMMENT '模块4 归因结论',
    `missing_data_text`   TEXT        DEFAULT NULL COMMENT '模块5 待补充数据',
    `next_action_text`    TEXT        DEFAULT NULL COMMENT '模块6 下一步建议（至少2条）',
    `result_markdown`     MEDIUMTEXT  DEFAULT NULL COMMENT '完整结构化结果 Markdown 全文',
    `result_file_path`    VARCHAR(512) DEFAULT NULL COMMENT '导出文件相对路径 exports/{user_id}/{conversation_id}/xxx.md',
    `created_at`          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_id` (`task_id`),
    KEY `idx_conv_created` (`conversation_id`, `created_at`),
    CONSTRAINT `fk_result_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE,
    -- 一个任务最多产出一份结果；任务被删除时结果同步删除
    CONSTRAINT `fk_result_task` FOREIGN KEY (`task_id`) REFERENCES `analysis_tasks` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '分析结果表';

-- -----------------------------------------------------------------------------
-- 7. context_summaries 上下文摘要表
--    多轮追问时压缩历史对话，避免上下文无限膨胀
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `context_summaries`;
CREATE TABLE `context_summaries` (
    `id`              BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `conversation_id` BIGINT      NOT NULL COMMENT '所属会话ID',
    `start_seq_no`    INT         NOT NULL COMMENT '摘要覆盖的起始消息序号',
    `end_seq_no`      INT         NOT NULL COMMENT '摘要覆盖的结束消息序号',
    `summary_text`    TEXT        NOT NULL COMMENT '摘要内容',
    `created_at`      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
    PRIMARY KEY (`id`),
    KEY `idx_conv_seq` (`conversation_id`, `end_seq_no`),
    CONSTRAINT `fk_summary_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '上下文摘要表';

-- -----------------------------------------------------------------------------
-- 8. websocket_tokens 长连接令牌表
--    一次性令牌：WebSocket 握手携带，校验后立即置 consumed_at
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `websocket_tokens`;
CREATE TABLE `websocket_tokens` (
    `id`              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `user_id`         BIGINT       NOT NULL COMMENT '所属用户ID',
    `conversation_id` BIGINT       NOT NULL COMMENT '绑定会话ID',
    `token`           VARCHAR(128) NOT NULL COMMENT '长连接令牌',
    `expires_at`      DATETIME     NOT NULL COMMENT '过期时间',
    `consumed_at`     DATETIME     DEFAULT NULL COMMENT '消费时间（非空表示已使用）',
    `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '签发时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_token` (`token`),
    KEY `idx_user_conv` (`user_id`, `conversation_id`),
    CONSTRAINT `fk_wstoken_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '长连接令牌表';

-- -----------------------------------------------------------------------------
-- 9. system_configs 系统配置表
--    config_group: system 系统 / analysis 分析 / auth 认证 / storage 存储 / llm 大模型 / feature 功能开关
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `system_configs`;
CREATE TABLE `system_configs` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `config_key`   VARCHAR(128) NOT NULL COMMENT '配置键',
    `config_value` TEXT         DEFAULT NULL COMMENT '配置值（统一字符串存储）',
    `config_group` VARCHAR(64)  NOT NULL DEFAULT 'system' COMMENT '配置分组',
    `description`  VARCHAR(512) DEFAULT NULL COMMENT '配置说明',
    `updated_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_config_key` (`config_key`),
    KEY `idx_group` (`config_group`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '系统配置表';

-- -----------------------------------------------------------------------------
-- 10. task_logs 任务日志表
--     log_level: DEBUG / INFO / WARN / ERROR
--     log_type : lifecycle 生命周期 / tool 工具执行 / llm 模型调用 /
--                db 数据库 / file 文件 / error 异常
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `task_logs`;
CREATE TABLE `task_logs` (
    `id`          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `task_id`     BIGINT      NOT NULL COMMENT '所属任务ID',
    `log_level`   VARCHAR(16) NOT NULL DEFAULT 'INFO' COMMENT '日志级别: DEBUG/INFO/WARN/ERROR',
    `log_type`    VARCHAR(32) NOT NULL DEFAULT 'lifecycle' COMMENT '日志类型',
    `log_content` TEXT        NOT NULL COMMENT '日志内容',
    `created_at`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录时间',
    PRIMARY KEY (`id`),
    KEY `idx_task_time` (`task_id`, `created_at`),
    KEY `idx_level_time` (`log_level`, `created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '任务日志表';

-- -----------------------------------------------------------------------------
-- 11. data_sources 业务数据源表（扩展表，支撑「系统管理员-管理业务数据源连接」）
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `data_sources`;
CREATE TABLE `data_sources` (
    `id`          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `name`        VARCHAR(128) NOT NULL COMMENT '数据源名称',
    `ds_type`     VARCHAR(32)  NOT NULL DEFAULT 'mysql' COMMENT '类型: mysql/sqlite/file/api',
    `host`        VARCHAR(128) DEFAULT NULL COMMENT '主机',
    `port`        INT          DEFAULT NULL COMMENT '端口',
    `db_name`     VARCHAR(128) DEFAULT NULL COMMENT '库名',
    `db_user`     VARCHAR(128) DEFAULT NULL COMMENT '账号',
    `db_password` VARCHAR(255) DEFAULT NULL COMMENT '口令（演示明文，生产应加密）',
    `extra_json`  TEXT         DEFAULT NULL COMMENT '扩展参数 JSON',
    `status`      VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态: enabled 启用, disabled 停用',
    `description` VARCHAR(512) DEFAULT NULL COMMENT '说明',
    `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_name` (`name`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '业务数据源表';

SET FOREIGN_KEY_CHECKS = 1;
