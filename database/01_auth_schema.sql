-- =============================================================================
-- 经营多轮归因分析系统 —— 认证中心数据库初始化脚本
-- 数据库: analysis_auth
-- 说明: 认证中心（auth-server）独立部署，使用独立 schema，与业务库 analysis_sys 物理隔离
-- 版本: 1.0.0
-- =============================================================================

DROP DATABASE IF EXISTS `analysis_auth`;
CREATE DATABASE `analysis_auth`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_general_ci;
USE `analysis_auth`;

-- -----------------------------------------------------------------------------
-- 1. 接入客户端表 auth_clients
--    登记允许接入认证中心的第三方系统（本系统后端即注册在此）
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `auth_clients`;
CREATE TABLE `auth_clients` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `client_id`     VARCHAR(64)  NOT NULL COMMENT '客户端标识',
    `client_secret` VARCHAR(128) NOT NULL COMMENT '客户端密钥（演示明文，生产应加密存储）',
    `client_name`   VARCHAR(128) NOT NULL COMMENT '客户端名称',
    `redirect_uris` VARCHAR(1024) NOT NULL COMMENT '允许的回调地址，多个以英文逗号分隔',
    `scope`         VARCHAR(255) NOT NULL DEFAULT 'openid profile' COMMENT '默认授权范围',
    `status`        VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT '状态: active/enabled 启用, disabled 停用',
    `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_client_id` (`client_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '认证中心接入客户端表';

-- -----------------------------------------------------------------------------
-- 2. 认证用户表 auth_users
--    认证中心侧的用户主数据；业务库 users 表通过 external_user_id 与之关联
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `auth_users`;
CREATE TABLE `auth_users` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `username`      VARCHAR(64)  NOT NULL COMMENT '登录账号',
    `password_hash` VARCHAR(128) NOT NULL COMMENT '口令摘要 = SHA256(salt + password)，生产应替换为 bcrypt/argon2',
    `salt`          VARCHAR(64)  NOT NULL COMMENT '口令盐值',
    `display_name`  VARCHAR(128) NOT NULL COMMENT '显示名称',
    `email`         VARCHAR(128) DEFAULT NULL COMMENT '邮箱',
    `phone`         VARCHAR(32)  DEFAULT NULL COMMENT '手机号',
    `role`          VARCHAR(32)  NOT NULL DEFAULT 'analyst' COMMENT '角色: analyst 分析用户, admin 系统管理员',
    `status`        VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT '状态: active 正常, disabled 停用, locked 锁定',
    `last_login_at` DATETIME     DEFAULT NULL COMMENT '最近登录时间',
    `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_username` (`username`),
    KEY `idx_role_status` (`role`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '认证用户表';

-- -----------------------------------------------------------------------------
-- 3. 授权码表 auth_codes
--    授权码模式（authorization_code）中的临时授权码，一次性消费
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `auth_codes`;
CREATE TABLE `auth_codes` (
    `id`           BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `code`         VARCHAR(128) NOT NULL COMMENT '授权码',
    `client_id`    VARCHAR(64)  NOT NULL COMMENT '客户端标识',
    `user_id`      BIGINT       NOT NULL COMMENT '授权用户ID',
    `redirect_uri` VARCHAR(512) NOT NULL COMMENT '回调地址',
    `scope`        VARCHAR(255) NOT NULL DEFAULT 'openid profile' COMMENT '授权范围',
    `expires_at`   DATETIME     NOT NULL COMMENT '过期时间',
    `consumed_at`  DATETIME     DEFAULT NULL COMMENT '消费时间（非空表示已使用）',
    `created_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_code` (`code`),
    KEY `idx_client_user` (`client_id`, `user_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '授权码表';

-- -----------------------------------------------------------------------------
-- 4. 访问令牌表 auth_tokens
--    opaque token 方案：令牌本身不携带信息，由 /oauth/introspect 内省校验
--    便于演示令牌吊销与用户会话全生命周期管理
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `auth_tokens`;
CREATE TABLE `auth_tokens` (
    `id`            BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    `access_token`  VARCHAR(128) NOT NULL COMMENT '访问令牌',
    `refresh_token` VARCHAR(128) DEFAULT NULL COMMENT '刷新令牌',
    `client_id`     VARCHAR(64)  NOT NULL COMMENT '客户端标识',
    `user_id`       BIGINT       NOT NULL COMMENT '所属用户ID',
    `session_id`    VARCHAR(64)  NOT NULL COMMENT '所属登录会话ID',
    `scope`         VARCHAR(255) NOT NULL DEFAULT 'openid profile' COMMENT '授权范围',
    `expires_at`    DATETIME     NOT NULL COMMENT '访问令牌过期时间',
    `refresh_expires_at` DATETIME DEFAULT NULL COMMENT '刷新令牌过期时间',
    `revoked_at`    DATETIME     DEFAULT NULL COMMENT '吊销时间',
    `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_access_token` (`access_token`),
    KEY `idx_refresh_token` (`refresh_token`),
    KEY `idx_user_session` (`user_id`, `session_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '访问令牌表';

-- -----------------------------------------------------------------------------
-- 5. 登录会话表 auth_sessions
--    用户会话全生命周期：登录 -> 活跃 -> 登出/过期 -> 失效
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `auth_sessions`;
CREATE TABLE `auth_sessions` (
    `id`          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `session_id`  VARCHAR(64) NOT NULL COMMENT '会话标识',
    `user_id`     BIGINT      NOT NULL COMMENT '用户ID',
    `client_id`   VARCHAR(64) NOT NULL COMMENT '客户端标识',
    `ip`          VARCHAR(64) DEFAULT NULL COMMENT '登录IP',
    `user_agent`  VARCHAR(512) DEFAULT NULL COMMENT '客户端UA',
    `status`      VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT '状态: active 活跃, logout 已登出, expired 已过期, kicked 被踢下线',
    `expires_at`  DATETIME    NOT NULL COMMENT '会话过期时间',
    `logout_at`   DATETIME    DEFAULT NULL COMMENT '登出时间',
    `created_at`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_session_id` (`session_id`),
    KEY `idx_user_status` (`user_id`, `status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '登录会话表';

-- -----------------------------------------------------------------------------
-- 6. 认证操作日志表 auth_login_logs
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `auth_login_logs`;
CREATE TABLE `auth_login_logs` (
    `id`         BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `username`   VARCHAR(64) DEFAULT NULL COMMENT '账号',
    `action`     VARCHAR(32) NOT NULL COMMENT '动作: login/logout/authorize/token/refresh/revoke',
    `ip`         VARCHAR(64) DEFAULT NULL COMMENT '来源IP',
    `user_agent` VARCHAR(512) DEFAULT NULL COMMENT '客户端UA',
    `success`    TINYINT(1)  NOT NULL DEFAULT 1 COMMENT '是否成功 1是0否',
    `message`    VARCHAR(512) DEFAULT NULL COMMENT '结果描述',
    `created_at` DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '发生时间',
    PRIMARY KEY (`id`),
    KEY `idx_username_time` (`username`, `created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '认证操作日志表';

-- =============================================================================
-- 认证中心基础字典数据
-- =============================================================================

-- 接入客户端：本系统后端（backend）
INSERT INTO `auth_clients` (`client_id`, `client_secret`, `client_name`, `redirect_uris`, `scope`, `status`)
VALUES ('jingying-web', 'jingying-web-secret-2026', '经营多轮归因分析系统',
        'http://localhost:8000/auth/callback,http://127.0.0.1:8000/auth/callback,http://localhost:5173/auth/callback,http://localhost:5173/login/callback',
        'openid profile analysis', 'active');

-- 认证用户
-- 口令算法: password_hash = SHA256(salt + password)，直接由 MySQL 计算，保证脚本可独立复现
--   admin    / Admin@123     -> 系统管理员
--   analyst  / Analyst@123   -> 分析用户（普通业务用户）
--   zhangyun / Zhang@123     -> 分析用户（商品运营，用于商品目录优化场景演示）
INSERT INTO `auth_users` (`username`, `password_hash`, `salt`, `display_name`, `email`, `role`, `status`)
VALUES
('admin',    SHA2(CONCAT('s4lt-admin-2026',    'Admin@123'),   256), 's4lt-admin-2026',    '系统管理员',     'admin@jingying.local',    'admin',   'active'),
('analyst',  SHA2(CONCAT('s4lt-analyst-2026',  'Analyst@123'), 256), 's4lt-analyst-2026',  '张分析（运营）', 'analyst@jingying.local',  'analyst', 'active'),
('zhangyun', SHA2(CONCAT('s4lt-zhangyun-2026', 'Zhang@123'),   256), 's4lt-zhangyun-2026', '赵云舒（商品运营）', 'zhangyun@jingying.local', 'analyst', 'active');
