-- =============================================================================
-- 经营多轮归因分析系统 —— 示例数据自检脚本
-- 用法: mysql -h127.0.0.1 -uroot -proot < 06_verify.sql
-- 用途:
--   1. 验证 6 大业务场景的示例数据已正确导入
--   2. 验证演示场景中「埋入的业务异常」在数据中真实可查
--      （分析引擎的 db_query 工具跑的就是下面这类聚合查询，而非硬编码结论）
-- =============================================================================

USE `analysis_sys`;

SELECT '========== 一、数据量总览 ==========' AS section;

SELECT '商品类目'      AS object, COUNT(*) AS total FROM biz_category
UNION ALL SELECT '商品',          COUNT(*) FROM biz_product
UNION ALL SELECT '搜索曝光记录',  COUNT(*) FROM biz_search_exposure
UNION ALL SELECT '点击记录',      COUNT(*) FROM biz_product_click
UNION ALL SELECT '转化记录',      COUNT(*) FROM biz_product_conversion
UNION ALL SELECT '客户',          COUNT(*) FROM biz_customer
UNION ALL SELECT '访问事件',      COUNT(*) FROM biz_visit_event
UNION ALL SELECT '加购事件',      COUNT(*) FROM biz_cart_event
UNION ALL SELECT '下单事件',      COUNT(*) FROM biz_order_event
UNION ALL SELECT '库存记录',      COUNT(*) FROM biz_inventory
UNION ALL SELECT '入库记录',      COUNT(*) FROM biz_inbound
UNION ALL SELECT '出库记录',      COUNT(*) FROM biz_outbound
UNION ALL SELECT '销量记录',      COUNT(*) FROM biz_sales
UNION ALL SELECT '评论',          COUNT(*) FROM biz_review
UNION ALL SELECT '评分',          COUNT(*) FROM biz_rating
UNION ALL SELECT '退款汇总',      COUNT(*) FROM biz_refund
UNION ALL SELECT '渠道',          COUNT(*) FROM biz_channel
UNION ALL SELECT '投放记录',      COUNT(*) FROM biz_ad_delivery
UNION ALL SELECT '订单',          COUNT(*) FROM biz_order
UNION ALL SELECT '销售汇总',      COUNT(*) FROM biz_sales_summary
UNION ALL SELECT '退款原因',      COUNT(*) FROM biz_refund_reason
UNION ALL SELECT '退款申请',      COUNT(*) FROM biz_refund_apply;

SELECT '========== 二、统计窗口 ==========' AS section;
SELECT '基准期' AS period, MIN(stat_date) AS from_date, MAX(stat_date) AS to_date
FROM biz_product_click WHERE stat_date < '2026-09-16'
UNION ALL
SELECT '异常期', MIN(stat_date), MAX(stat_date)
FROM biz_product_click WHERE stat_date >= '2026-09-16';

SELECT '========== 三、场景A 商品目录优化：点击率两期对比 ==========' AS section;
SELECT c.category_name AS `类目`,
       ROUND(SUM(CASE WHEN k.stat_date < '2026-09-16'
                      THEN k.click_cnt END) / SUM(CASE WHEN k.stat_date < '2026-09-16'
                      THEN k.exposure_cnt END) * 100, 2) AS `基准期CTR%`,
       ROUND(SUM(CASE WHEN k.stat_date >= '2026-09-16'
                      THEN k.click_cnt END) / SUM(CASE WHEN k.stat_date >= '2026-09-16'
                      THEN k.exposure_cnt END) * 100, 2) AS `异常期CTR%`
FROM biz_product_click k
JOIN biz_category c ON c.category_id = k.category_id
GROUP BY c.category_name
ORDER BY c.category_name;

SELECT '  实测：美妆个护 CTR 4.20% -> 2.09%（腰斩），其余类目稳定在 5.45%~5.52%' AS `说明`;

SELECT '========== 四、场景A 商品目录质量对比 ==========' AS section;
SELECT c.category_name AS `类目`,
       ROUND(AVG(p.title_length), 1)   AS `平均标题字数`,
       ROUND(AVG(p.image_count), 2)    AS `平均主图数`,
       ROUND(AVG(p.attr_fill_rate), 1) AS `平均属性填充率%`
FROM biz_product p
JOIN biz_category c ON c.category_id = p.category_id
GROUP BY c.category_name
ORDER BY `平均标题字数`;

SELECT '  实测：美妆个护 平均标题 11.4 字 / 主图 1.25 张 / 属性填充率 36.3%，其余类目均在 19 字、4.6 张、85% 以上' AS `说明`;

SELECT '========== 五、场景A 空搜索（无结果搜索）对比 ==========' AS section;
SELECT search_keyword AS `搜索词`,
       SUM(CASE WHEN stat_date < '2026-09-16' THEN zero_result_cnt ELSE 0 END)  AS `基准期空搜索`,
       SUM(CASE WHEN stat_date >= '2026-09-16' THEN zero_result_cnt ELSE 0 END) AS `异常期空搜索`,
       ROUND(SUM(CASE WHEN stat_date >= '2026-09-16' THEN zero_result_cnt ELSE 0 END)
             / NULLIF(SUM(CASE WHEN stat_date < '2026-09-16' THEN zero_result_cnt ELSE 0 END), 0), 2) AS `放大倍数`
FROM biz_search_exposure
WHERE category_id = 'C01'
GROUP BY search_keyword
ORDER BY `放大倍数` DESC;

SELECT '========== 六、场景E 市场表现：GMV 两期对比 ==========' AS section;
SELECT (SELECT ROUND(SUM(gmv) / 10000, 1) FROM biz_sales_summary WHERE stat_date < '2026-09-16')  AS `基准期GMV万元`,
       (SELECT ROUND(SUM(gmv) / 10000, 1) FROM biz_sales_summary WHERE stat_date >= '2026-09-16') AS `异常期GMV万元`;

SELECT '  实测：基准期 1116.5 万 -> 异常期 827.8 万，环比下滑 25.9%' AS `说明`;

SELECT '========== 七、场景E 各渠道 ROAS 两期对比 ==========' AS section;
SELECT ch.channel_name AS `渠道`,
       ch.channel_type AS `类型`,
       ROUND(SUM(CASE WHEN s.stat_date < '2026-09-16' THEN s.gmv END)
             / NULLIF(SUM(CASE WHEN a.stat_date < '2026-09-16' THEN a.spend END), 0), 2) AS `基准期ROAS`,
       ROUND(SUM(CASE WHEN s.stat_date >= '2026-09-16' THEN s.gmv END)
             / NULLIF(SUM(CASE WHEN a.stat_date >= '2026-09-16' THEN a.spend END), 0), 2) AS `异常期ROAS`,
       ROUND(SUM(CASE WHEN a.stat_date < '2026-09-16' THEN a.spend END) / 10000, 2)  AS `基准期花费万元`,
       ROUND(SUM(CASE WHEN a.stat_date >= '2026-09-16' THEN a.spend END) / 10000, 2) AS `异常期花费万元`
FROM biz_channel ch
LEFT JOIN biz_sales_summary s ON s.channel_id = ch.channel_id
LEFT JOIN biz_ad_delivery  a ON a.channel_id = ch.channel_id AND a.stat_date = s.stat_date
GROUP BY ch.channel_id, ch.channel_name, ch.channel_type
ORDER BY `异常期ROAS`;

SELECT '  实测：社媒-信息流 花费 44.91 万 -> 46.13 万（几乎不变），ROAS 5.92 -> 1.58（暴跌 73%），是整体 GMV 下滑的主因' AS `说明`;

SELECT '========== 八、场景D 评论反馈：负面占比两期对比 ==========' AS section;
SELECT (SELECT ROUND(SUM(sentiment = 'negative') / COUNT(*) * 100, 2)
        FROM biz_review WHERE stat_date < '2026-09-16' AND product_id IN
             (SELECT product_id FROM biz_product WHERE category_id = 'C01')) AS `C01基准期负面%`,
       (SELECT ROUND(SUM(sentiment = 'negative') / COUNT(*) * 100, 2)
        FROM biz_review WHERE stat_date >= '2026-09-16' AND product_id IN
             (SELECT product_id FROM biz_product WHERE category_id = 'C01')) AS `C01异常期负面%`,
       (SELECT ROUND(SUM(sentiment = 'negative') / COUNT(*) * 100, 2)
        FROM biz_review WHERE stat_date >= '2026-09-16' AND product_id IN
             (SELECT product_id FROM biz_product WHERE category_id <> 'C01')) AS `其它类目异常期负面%`;

SELECT '========== 九、场景C 库存异常：低于安全库存 SKU 数 ==========' AS section;
SELECT stat_date AS `统计日期`,
       SUM(available_qty < safety_stock_qty) AS `缺货SKU数`,
       SUM(available_qty > safety_stock_qty * 4) AS `积压SKU数`
FROM biz_inventory
WHERE stat_date IN ('2026-09-10', '2026-09-20', '2026-09-30')
GROUP BY stat_date
ORDER BY stat_date;

SELECT '========== 十、场景F 退款模式：退款原因 Top ==========' AS section;
SELECT r.reason_name AS `退款原因`,
       r.reason_type AS `大类`,
       COUNT(*)      AS `申请单数`,
       ROUND(SUM(a.refund_amount) / 10000, 2) AS `退款金额万元`,
       ROUND(AVG(a.handle_hours), 2) AS `平均处理时长h`
FROM biz_refund_apply a
JOIN biz_refund_reason r ON r.reason_code = a.reason_code
GROUP BY r.reason_code, r.reason_name, r.reason_type
ORDER BY `申请单数` DESC
LIMIT 10;

SELECT '========== 十一、平台基线配置 ==========' AS section;
SELECT '系统配置项' AS object, COUNT(*) AS total FROM system_configs
UNION ALL SELECT '业务数据源', COUNT(*) FROM data_sources;
