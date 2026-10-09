-- =============================================================================
-- 经营多轮归因分析系统 —— 业务示例场景库表结构
-- 数据库: analysis_sys
-- 说明: 覆盖《需求规范 十四、业务示例场景要求》列出的 6 个可选场景库
--       统一前缀 biz_ ，共 22 张演示表，供分析引擎的 db_query 工具真实查询
-- 场景索引:
--   A 商品目录优化 : biz_product / biz_category / biz_search_exposure / biz_product_click / biz_product_conversion
--   B 客户行为分析 : biz_customer / biz_visit_event / biz_cart_event / biz_order_event
--   C 库存异常分析 : biz_inventory / biz_inbound / biz_outbound / biz_sales
--   D 评论反馈分析 : biz_review / biz_rating / biz_refund            （复用 biz_product）
--   E 市场表现分析 : biz_channel / biz_ad_delivery / biz_order / biz_sales_summary
--   F 退款模式分析 : biz_refund_apply / biz_refund_reason            （复用 biz_order / biz_customer）
-- 版本: 1.0.0
-- =============================================================================

USE `analysis_sys`;
SET FOREIGN_KEY_CHECKS = 0;

-- =============================================================================
-- A. 商品目录优化场景
-- =============================================================================

DROP TABLE IF EXISTS `biz_category`;
CREATE TABLE `biz_category` (
    `category_id`    VARCHAR(32)  NOT NULL COMMENT '类目ID',
    `category_name`  VARCHAR(128) NOT NULL COMMENT '类目名称',
    `parent_id`      VARCHAR(32)  DEFAULT NULL COMMENT '父类目ID',
    `level`          INT          NOT NULL DEFAULT 1 COMMENT '类目层级',
    `is_leaf`        TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '是否叶子类目',
    `status`         VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT '状态',
    PRIMARY KEY (`category_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '类目表（商品目录优化场景）';

DROP TABLE IF EXISTS `biz_product`;
CREATE TABLE `biz_product` (
    `product_id`     VARCHAR(32)   NOT NULL COMMENT '商品ID',
    `product_name`   VARCHAR(255)  NOT NULL COMMENT '商品名称',
    `category_id`    VARCHAR(32)   NOT NULL COMMENT '所属类目ID',
    `brand`          VARCHAR(64)   DEFAULT NULL COMMENT '品牌',
    `price`          DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '售价（元）',
    `cost`           DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '成本（元）',
    `stock_qty`      INT           NOT NULL DEFAULT 0 COMMENT '可售库存',
    `on_shelf_date`  DATE          DEFAULT NULL COMMENT '上架日期',
    `shelf_status`   VARCHAR(16)   NOT NULL DEFAULT 'on' COMMENT '货架状态: on 在售, off 下架',
    `title_length`   INT           NOT NULL DEFAULT 0 COMMENT '标题字符数（目录质量指标）',
    `image_count`    INT           NOT NULL DEFAULT 0 COMMENT '主图数量（目录质量指标）',
    `attr_fill_rate` DECIMAL(5,2)  NOT NULL DEFAULT 0 COMMENT '属性填充率 %（目录质量指标）',
    PRIMARY KEY (`product_id`),
    KEY `idx_category` (`category_id`),
    KEY `idx_shelf` (`shelf_status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '商品表（商品目录优化场景）';

DROP TABLE IF EXISTS `biz_search_exposure`;
CREATE TABLE `biz_search_exposure` (
    `id`             BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`      DATE        NOT NULL COMMENT '统计日期',
    `category_id`    VARCHAR(32) NOT NULL COMMENT '类目ID',
    `product_id`     VARCHAR(32) DEFAULT NULL COMMENT '商品ID（可为空表示类目级搜索词无对应商品）',
    `search_keyword` VARCHAR(128) NOT NULL COMMENT '搜索词',
    `exposure_cnt`   INT         NOT NULL DEFAULT 0 COMMENT '曝光次数',
    `search_cnt`     INT         NOT NULL DEFAULT 0 COMMENT '搜索次数',
    `zero_result_cnt` INT        NOT NULL DEFAULT 0 COMMENT '无结果（空搜索）次数',
    PRIMARY KEY (`id`),
    KEY `idx_date_cat` (`stat_date`, `category_id`),
    KEY `idx_keyword` (`search_keyword`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '搜索曝光表（商品目录优化场景）';

DROP TABLE IF EXISTS `biz_product_click`;
CREATE TABLE `biz_product_click` (
    `id`           BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`    DATE        NOT NULL COMMENT '统计日期',
    `product_id`   VARCHAR(32) NOT NULL COMMENT '商品ID',
    `category_id`  VARCHAR(32) NOT NULL COMMENT '类目ID',
    `exposure_cnt` INT         NOT NULL DEFAULT 0 COMMENT '列表页曝光次数',
    `click_cnt`    INT         NOT NULL DEFAULT 0 COMMENT '点击次数',
    `uv`           INT         NOT NULL DEFAULT 0 COMMENT '点击用户数',
    PRIMARY KEY (`id`),
    KEY `idx_date_prod` (`stat_date`, `product_id`),
    KEY `idx_date_cat` (`stat_date`, `category_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '点击表（商品目录优化场景）';

DROP TABLE IF EXISTS `biz_product_conversion`;
CREATE TABLE `biz_product_conversion` (
    `id`             BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`      DATE        NOT NULL COMMENT '统计日期',
    `product_id`     VARCHAR(32) NOT NULL COMMENT '商品ID',
    `category_id`    VARCHAR(32) NOT NULL COMMENT '类目ID',
    `click_cnt`      INT         NOT NULL DEFAULT 0 COMMENT '点击次数',
    `cart_cnt`       INT         NOT NULL DEFAULT 0 COMMENT '加购次数',
    `order_cnt`      INT         NOT NULL DEFAULT 0 COMMENT '下单笔数',
    `pay_amount`     DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '成交金额（元）',
    PRIMARY KEY (`id`),
    KEY `idx_date_prod` (`stat_date`, `product_id`),
    KEY `idx_date_cat` (`stat_date`, `category_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '转化表（商品目录优化场景）';

-- =============================================================================
-- B. 客户行为分析场景
-- =============================================================================

DROP TABLE IF EXISTS `biz_customer`;
CREATE TABLE `biz_customer` (
    `customer_id`   VARCHAR(32)  NOT NULL COMMENT '客户ID',
    `customer_name` VARCHAR(128) NOT NULL COMMENT '客户名称',
    `register_date` DATE         NOT NULL COMMENT '注册日期',
    `channel_id`    VARCHAR(32)  DEFAULT NULL COMMENT '获客渠道ID',
    `city`          VARCHAR(64)  DEFAULT NULL COMMENT '城市',
    `member_level`  VARCHAR(16)  NOT NULL DEFAULT 'normal' COMMENT '会员等级: normal/silver/gold/platinum',
    `lifecycle`     VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT '生命周期: new/active/silent/churn',
    PRIMARY KEY (`customer_id`),
    KEY `idx_channel` (`channel_id`),
    KEY `idx_lifecycle` (`lifecycle`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '用户表（客户行为分析场景）';

DROP TABLE IF EXISTS `biz_visit_event`;
CREATE TABLE `biz_visit_event` (
    `id`          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`   DATE        NOT NULL COMMENT '统计日期',
    `customer_id` VARCHAR(32) NOT NULL COMMENT '客户ID',
    `visit_cnt`   INT         NOT NULL DEFAULT 0 COMMENT '访问次数',
    `pv`          INT         NOT NULL DEFAULT 0 COMMENT '页面浏览量',
    `duration_sec` INT        NOT NULL DEFAULT 0 COMMENT '停留时长（秒）',
    `device`      VARCHAR(16) NOT NULL DEFAULT 'app' COMMENT '设备: app/pc/mini',
    PRIMARY KEY (`id`),
    KEY `idx_date_cust` (`stat_date`, `customer_id`),
    KEY `idx_date_device` (`stat_date`, `device`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '访问事件表（客户行为分析场景）';

DROP TABLE IF EXISTS `biz_cart_event`;
CREATE TABLE `biz_cart_event` (
    `id`          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`   DATE        NOT NULL COMMENT '统计日期',
    `customer_id` VARCHAR(32) NOT NULL COMMENT '客户ID',
    `add_cart_cnt` INT        NOT NULL DEFAULT 0 COMMENT '加购次数',
    `cart_amount` DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '加购金额（元）',
    `abandon_cnt` INT         NOT NULL DEFAULT 0 COMMENT '弃购次数',
    PRIMARY KEY (`id`),
    KEY `idx_date_cust` (`stat_date`, `customer_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '加购事件表（客户行为分析场景）';

DROP TABLE IF EXISTS `biz_order_event`;
CREATE TABLE `biz_order_event` (
    `id`          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`   DATE        NOT NULL COMMENT '统计日期',
    `customer_id` VARCHAR(32) NOT NULL COMMENT '客户ID',
    `order_cnt`   INT         NOT NULL DEFAULT 0 COMMENT '下单笔数',
    `order_amount` DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '下单金额（元）',
    `refund_cnt`  INT         NOT NULL DEFAULT 0 COMMENT '退款笔数',
    PRIMARY KEY (`id`),
    KEY `idx_date_cust` (`stat_date`, `customer_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '下单事件表（客户行为分析场景）';

-- =============================================================================
-- C. 库存异常分析场景
-- =============================================================================

DROP TABLE IF EXISTS `biz_inventory`;
CREATE TABLE `biz_inventory` (
    `id`               BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`        DATE        NOT NULL COMMENT '统计日期',
    `warehouse_id`     VARCHAR(32) NOT NULL COMMENT '仓库ID',
    `product_id`       VARCHAR(32) NOT NULL COMMENT '商品ID',
    `on_hand_qty`      INT         NOT NULL DEFAULT 0 COMMENT '账面库存',
    `available_qty`    INT         NOT NULL DEFAULT 0 COMMENT '可用库存',
    `locked_qty`       INT         NOT NULL DEFAULT 0 COMMENT '锁定库存',
    `in_transit_qty`   INT         NOT NULL DEFAULT 0 COMMENT '在途库存',
    `safety_stock_qty` INT         NOT NULL DEFAULT 0 COMMENT '安全库存',
    PRIMARY KEY (`id`),
    KEY `idx_date_prod` (`stat_date`, `product_id`),
    KEY `idx_date_wh` (`stat_date`, `warehouse_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '库存表（库存异常分析场景）';

DROP TABLE IF EXISTS `biz_inbound`;
CREATE TABLE `biz_inbound` (
    `id`           BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`    DATE        NOT NULL COMMENT '统计日期',
    `warehouse_id` VARCHAR(32) NOT NULL COMMENT '仓库ID',
    `product_id`   VARCHAR(32) NOT NULL COMMENT '商品ID',
    `inbound_qty`  INT         NOT NULL DEFAULT 0 COMMENT '入库数量',
    `inbound_amount` DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '入库金额（元）',
    `plan_qty`     INT         NOT NULL DEFAULT 0 COMMENT '计划入库数量',
    PRIMARY KEY (`id`),
    KEY `idx_date_prod` (`stat_date`, `product_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '入库表（库存异常分析场景）';

DROP TABLE IF EXISTS `biz_outbound`;
CREATE TABLE `biz_outbound` (
    `id`            BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`     DATE        NOT NULL COMMENT '统计日期',
    `warehouse_id`  VARCHAR(32) NOT NULL COMMENT '仓库ID',
    `product_id`    VARCHAR(32) NOT NULL COMMENT '商品ID',
    `outbound_qty`  INT         NOT NULL DEFAULT 0 COMMENT '出库数量',
    `outbound_type` VARCHAR(16) NOT NULL DEFAULT 'sale' COMMENT '出库类型: sale 销售出库, transfer 调拨, scrap 报废',
    PRIMARY KEY (`id`),
    KEY `idx_date_prod` (`stat_date`, `product_id`),
    KEY `idx_type` (`outbound_type`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '出库表（库存异常分析场景）';

DROP TABLE IF EXISTS `biz_sales`;
CREATE TABLE `biz_sales` (
    `id`           BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`    DATE        NOT NULL COMMENT '统计日期',
    `product_id`   VARCHAR(32) NOT NULL COMMENT '商品ID',
    `category_id`  VARCHAR(32) NOT NULL COMMENT '类目ID',
    `sale_qty`     INT         NOT NULL DEFAULT 0 COMMENT '销量',
    `sale_amount`  DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '销售额（元）',
    `avg_daily_sale` DECIMAL(10,2) NOT NULL DEFAULT 0 COMMENT '日均销量',
    PRIMARY KEY (`id`),
    KEY `idx_date_prod` (`stat_date`, `product_id`),
    KEY `idx_date_cat` (`stat_date`, `category_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '销量表（库存异常分析场景）';

-- =============================================================================
-- D. 评论反馈分析场景
-- =============================================================================

DROP TABLE IF EXISTS `biz_review`;
CREATE TABLE `biz_review` (
    `id`             BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`      DATE        NOT NULL COMMENT '评论日期',
    `review_id`      VARCHAR(40) NOT NULL COMMENT '评论ID',
    `product_id`     VARCHAR(32) NOT NULL COMMENT '商品ID',
    `customer_id`    VARCHAR(32) DEFAULT NULL COMMENT '客户ID',
    `review_content` VARCHAR(1024) NOT NULL COMMENT '评论内容',
    `sentiment`      VARCHAR(16) NOT NULL DEFAULT 'neutral' COMMENT '情感: positive/neutral/negative',
    `issue_tag`      VARCHAR(64) DEFAULT NULL COMMENT '问题标签: 质量/物流/描述不符/客服/包装/价格',
    `has_image`      TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '是否带图',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_review_id` (`review_id`),
    KEY `idx_date_prod` (`stat_date`, `product_id`),
    KEY `idx_sentiment` (`sentiment`),
    KEY `idx_issue` (`issue_tag`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '评论表（评论反馈分析场景）';

DROP TABLE IF EXISTS `biz_rating`;
CREATE TABLE `biz_rating` (
    `id`          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`   DATE        NOT NULL COMMENT '统计日期',
    `product_id`  VARCHAR(32) NOT NULL COMMENT '商品ID',
    `rating_1_cnt` INT        NOT NULL DEFAULT 0 COMMENT '1星数',
    `rating_2_cnt` INT        NOT NULL DEFAULT 0 COMMENT '2星数',
    `rating_3_cnt` INT        NOT NULL DEFAULT 0 COMMENT '3星数',
    `rating_4_cnt` INT        NOT NULL DEFAULT 0 COMMENT '4星数',
    `rating_5_cnt` INT        NOT NULL DEFAULT 0 COMMENT '5星数',
    `avg_rating`  DECIMAL(4,2) NOT NULL DEFAULT 0 COMMENT '平均评分',
    PRIMARY KEY (`id`),
    KEY `idx_date_prod` (`stat_date`, `product_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '评分表（评论反馈分析场景）';

DROP TABLE IF EXISTS `biz_refund`;
CREATE TABLE `biz_refund` (
    `id`            BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`     DATE        NOT NULL COMMENT '统计日期',
    `product_id`    VARCHAR(32) NOT NULL COMMENT '商品ID',
    `category_id`   VARCHAR(32) NOT NULL COMMENT '类目ID',
    `order_cnt`     INT         NOT NULL DEFAULT 0 COMMENT '订单笔数',
    `refund_cnt`    INT         NOT NULL DEFAULT 0 COMMENT '退款笔数',
    `refund_amount` DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '退款金额（元）',
    PRIMARY KEY (`id`),
    KEY `idx_date_prod` (`stat_date`, `product_id`),
    KEY `idx_date_cat` (`stat_date`, `category_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '退款表（评论反馈分析场景）';

-- =============================================================================
-- E. 市场表现分析场景
-- =============================================================================

DROP TABLE IF EXISTS `biz_channel`;
CREATE TABLE `biz_channel` (
    `channel_id`   VARCHAR(32)  NOT NULL COMMENT '渠道ID',
    `channel_name` VARCHAR(128) NOT NULL COMMENT '渠道名称',
    `channel_type` VARCHAR(32)  NOT NULL COMMENT '渠道类型: search 搜索, social 社媒, content 内容, alliance 联盟, direct 直访',
    `status`       VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态',
    PRIMARY KEY (`channel_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '渠道表（市场表现分析场景）';

DROP TABLE IF EXISTS `biz_ad_delivery`;
CREATE TABLE `biz_ad_delivery` (
    `id`           BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`    DATE        NOT NULL COMMENT '统计日期',
    `channel_id`   VARCHAR(32) NOT NULL COMMENT '渠道ID',
    `impression`   BIGINT      NOT NULL DEFAULT 0 COMMENT '曝光量',
    `click`        BIGINT      NOT NULL DEFAULT 0 COMMENT '点击量',
    `spend`        DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '投放花费（元）',
    `new_customer` INT         NOT NULL DEFAULT 0 COMMENT '拉新数',
    PRIMARY KEY (`id`),
    KEY `idx_date_channel` (`stat_date`, `channel_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '投放表（市场表现分析场景）';

DROP TABLE IF EXISTS `biz_order`;
CREATE TABLE `biz_order` (
    `id`           BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`    DATE        NOT NULL COMMENT '统计日期',
    `order_id`     VARCHAR(40) NOT NULL COMMENT '订单号',
    `channel_id`   VARCHAR(32) NOT NULL COMMENT '来源渠道ID',
    `customer_id`  VARCHAR(32) DEFAULT NULL COMMENT '客户ID',
    `product_id`   VARCHAR(32) DEFAULT NULL COMMENT '商品ID',
    `order_amount` DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '订单金额（元）',
    `discount_amount` DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '优惠金额（元）',
    `pay_amount`   DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '实付金额（元）',
    `order_status` VARCHAR(16) NOT NULL DEFAULT 'paid' COMMENT '订单状态: paid 已付款, shipped 已发货, done 已完成, refunded 已退款',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_order_id` (`order_id`),
    KEY `idx_date_channel` (`stat_date`, `channel_id`),
    KEY `idx_status` (`order_status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '订单表（市场表现分析场景）';

DROP TABLE IF EXISTS `biz_sales_summary`;
CREATE TABLE `biz_sales_summary` (
    `id`             BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`      DATE        NOT NULL COMMENT '统计日期',
    `channel_id`     VARCHAR(32) NOT NULL COMMENT '渠道ID',
    `order_cnt`      INT         NOT NULL DEFAULT 0 COMMENT '订单数',
    `gmv`            DECIMAL(16,2) NOT NULL DEFAULT 0 COMMENT '成交总额 GMV（元）',
    `pay_amount`     DECIMAL(16,2) NOT NULL DEFAULT 0 COMMENT '实付金额（元）',
    `active_user`    INT         NOT NULL DEFAULT 0 COMMENT '活跃用户数',
    `refund_amount`  DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '退款金额（元）',
    PRIMARY KEY (`id`),
    KEY `idx_date_channel` (`stat_date`, `channel_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '销售汇总表（市场表现分析场景）';

-- =============================================================================
-- F. 退款模式分析场景
-- =============================================================================

DROP TABLE IF EXISTS `biz_refund_reason`;
CREATE TABLE `biz_refund_reason` (
    `reason_code` VARCHAR(32)  NOT NULL COMMENT '退款原因编码',
    `reason_name` VARCHAR(128) NOT NULL COMMENT '退款原因名称',
    `reason_type` VARCHAR(32)  NOT NULL COMMENT '原因大类: quality 质量问题, logistics 物流问题, expectation 预期不符, service 服务问题, other 其它',
    `is_responsible` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否商家责任',
    PRIMARY KEY (`reason_code`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '退款原因表（退款模式分析场景）';

DROP TABLE IF EXISTS `biz_refund_apply`;
CREATE TABLE `biz_refund_apply` (
    `id`             BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键',
    `stat_date`      DATE        NOT NULL COMMENT '申请日期',
    `refund_id`      VARCHAR(40) NOT NULL COMMENT '退款单号',
    `order_id`       VARCHAR(40) NOT NULL COMMENT '关联订单号',
    `customer_id`    VARCHAR(32) DEFAULT NULL COMMENT '客户ID',
    `product_id`     VARCHAR(32) DEFAULT NULL COMMENT '商品ID',
    `reason_code`    VARCHAR(32) NOT NULL COMMENT '退款原因编码',
    `refund_amount`  DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '退款金额（元）',
    `apply_channel`  VARCHAR(32) NOT NULL DEFAULT 'app' COMMENT '申请渠道',
    `refund_status`  VARCHAR(16) NOT NULL DEFAULT 'approved' COMMENT '状态: applied 已申请, approved 已通过, rejected 已驳回, done 已完成',
    `handle_hours`   DECIMAL(8,2) NOT NULL DEFAULT 0 COMMENT '处理时长（小时）',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_refund_id` (`refund_id`),
    KEY `idx_date_reason` (`stat_date`, `reason_code`),
    KEY `idx_order` (`order_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '退款申请表（退款模式分析场景）';

SET FOREIGN_KEY_CHECKS = 1;
