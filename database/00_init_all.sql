-- =============================================================================
-- 经营多轮归因分析系统 —— 一键初始化总入口
-- 用法（在 database 目录下执行）:
--     mysql -h127.0.0.1 -P3306 -uroot -proot < 00_init_all.sql
-- 说明:
--     SOURCE 是 mysql 命令行客户端指令，且下面用的是**相对路径**，
--     因此必须在 database/ 目录下执行本文件，否则 SOURCE 找不到目标脚本。
--     使用 Navicat / DBeaver 等工具时请改为按顺序手动执行下列 5 个脚本。
-- 执行顺序（不可颠倒）:
--     01_auth_schema.sql        认证中心库 analysis_auth
--     02_core_schema.sql        业务库 analysis_sys 核心 11 张表（需求 10 张 + 数据源登记 1 张）
--     03_business_schema.sql    业务库 6 大场景 22 张演示表
--     04_dict.sql               基础字典（用户镜像 / 系统配置 / 数据源 / 枚举）
--     05_demo_data.sql          业务示例场景数据（约 5 MB）
-- =============================================================================

SOURCE 01_auth_schema.sql;
SOURCE 02_core_schema.sql;
SOURCE 03_business_schema.sql;
SOURCE 04_dict.sql;
SOURCE 05_demo_data.sql;

SELECT '=== 初始化完成 ===' AS message;
SELECT '认证中心用户' AS object, COUNT(*) AS total FROM analysis_auth.auth_users
UNION ALL SELECT '认证客户端', COUNT(*) FROM analysis_auth.auth_clients
UNION ALL SELECT '业务用户镜像', COUNT(*) FROM analysis_sys.users
UNION ALL SELECT '系统配置项', COUNT(*) FROM analysis_sys.system_configs
UNION ALL SELECT '业务数据源', COUNT(*) FROM analysis_sys.data_sources
UNION ALL SELECT '演示商品', COUNT(*) FROM analysis_sys.biz_product
UNION ALL SELECT '演示订单', COUNT(*) FROM analysis_sys.biz_order
UNION ALL SELECT '演示评论', COUNT(*) FROM analysis_sys.biz_review
UNION ALL SELECT '演示退款申请', COUNT(*) FROM analysis_sys.biz_refund_apply;
