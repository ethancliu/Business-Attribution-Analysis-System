#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
经营多轮归因分析系统 —— 业务示例数据生成器

用途:
    以确定性随机种子生成 6 个业务场景的模拟数据，并输出为可独立执行的
    SQL 脚本 `database/05_demo_data.sql`。

    之所以用生成器而不是手写 SQL：
      1. 数据量约 1.2 万行，手写不可维护；
      2. 固定随机种子(random.Random(20260901))保证每次生成的数值完全一致，
         演示文档中引用的指标口径可复现；
      3. 场景中的「异常」是通过可在数据中真实算出来的方式埋入的，
         分析引擎的 db_query 工具跑的是真实聚合 SQL，而非硬编码结论。

用法:
    uv run python backend/scripts/gen_demo_data.py
    # 或
    python backend/scripts/gen_demo_data.py

输出:
    database/05_demo_data.sql
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------

SEED = 20260901
RNG = random.Random(SEED)

# 统计窗口：2026-09-01 ~ 2026-09-30，拆成基准期与异常期两段
PERIOD_START = date(2026, 9, 1)
PERIOD_END = date(2026, 9, 30)
SPLIT_DATE = date(2026, 9, 16)  # 异常期起点

ALL_DATES = [PERIOD_START + timedelta(days=i) for i in range((PERIOD_END - PERIOD_START).days + 1)]
BASE_DATES = [d for d in ALL_DATES if d < SPLIT_DATE]
ANOMALY_DATES = [d for d in ALL_DATES if d >= SPLIT_DATE]

ROOT = Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "database" / "05_demo_data.sql"

BATCH = 200  # 单条 INSERT 语句最多包含的行数


# ---------------------------------------------------------------------------
# SQL 输出辅助
# ---------------------------------------------------------------------------

class SqlWriter:
    """按表批量写出多行 INSERT 语句。"""

    def __init__(self) -> None:
        self.buf: list[str] = []
        self.pending: dict[str, list[str]] = {}
        self.order: list[str] = []

    def add(self, table: str, columns: list[str], values: list) -> None:
        if table not in self.pending:
            self.pending[table] = []
            self.order.append(table)
        self.pending[table].append(self._row(values))
        if len(self.pending[table]) >= BATCH:
            self._flush(table)

    def _row(self, values: list) -> str:
        parts = []
        for v in values:
            if v is None:
                parts.append("NULL")
            elif isinstance(v, bool):
                parts.append("1" if v else "0")
            elif isinstance(v, (int, float, Decimal)):
                parts.append(str(v))
            elif isinstance(v, date):
                parts.append(f"'{v.isoformat()}'")
            else:
                parts.append("'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'")
        return "(" + ", ".join(parts) + ")"

    def _flush(self, table: str) -> None:
        rows = self.pending.get(table)
        if not rows:
            return
        cols = self.columns[table]
        self.buf.append(
            f"INSERT INTO `{table}` ({', '.join('`' + c + '`' for c in cols)}) VALUES\n"
            + ",\n".join(rows)
            + ";\n"
        )
        self.pending[table] = []

    columns: dict[str, list[str]] = {}

    def declare(self, table: str, columns: list[str]) -> None:
        self.columns[table] = columns

    def finish(self) -> str:
        for table in self.order:
            self._flush(table)
        return "\n".join(self.buf)


W = SqlWriter()

# 每张表的列顺序（与 03_business_schema.sql 保持一致）
W.declare("biz_category", ["category_id", "category_name", "parent_id", "level", "is_leaf", "status"])
W.declare("biz_product", ["product_id", "product_name", "category_id", "brand", "price", "cost",
                          "stock_qty", "on_shelf_date", "shelf_status", "title_length", "image_count",
                          "attr_fill_rate"])
W.declare("biz_search_exposure", ["stat_date", "category_id", "product_id", "search_keyword",
                                  "exposure_cnt", "search_cnt", "zero_result_cnt"])
W.declare("biz_product_click", ["stat_date", "product_id", "category_id", "exposure_cnt", "click_cnt", "uv"])
W.declare("biz_product_conversion", ["stat_date", "product_id", "category_id", "click_cnt", "cart_cnt",
                                     "order_cnt", "pay_amount"])
W.declare("biz_customer", ["customer_id", "customer_name", "register_date", "channel_id", "city",
                           "member_level", "lifecycle"])
W.declare("biz_visit_event", ["stat_date", "customer_id", "visit_cnt", "pv", "duration_sec", "device"])
W.declare("biz_cart_event", ["stat_date", "customer_id", "add_cart_cnt", "cart_amount", "abandon_cnt"])
W.declare("biz_order_event", ["stat_date", "customer_id", "order_cnt", "order_amount", "refund_cnt"])
W.declare("biz_inventory", ["stat_date", "warehouse_id", "product_id", "on_hand_qty", "available_qty",
                            "locked_qty", "in_transit_qty", "safety_stock_qty"])
W.declare("biz_inbound", ["stat_date", "warehouse_id", "product_id", "inbound_qty", "inbound_amount", "plan_qty"])
W.declare("biz_outbound", ["stat_date", "warehouse_id", "product_id", "outbound_qty", "outbound_type"])
W.declare("biz_sales", ["stat_date", "product_id", "category_id", "sale_qty", "sale_amount", "avg_daily_sale"])
W.declare("biz_review", ["stat_date", "review_id", "product_id", "customer_id", "review_content",
                         "sentiment", "issue_tag", "has_image"])
W.declare("biz_rating", ["stat_date", "product_id", "rating_1_cnt", "rating_2_cnt", "rating_3_cnt",
                         "rating_4_cnt", "rating_5_cnt", "avg_rating"])
W.declare("biz_refund", ["stat_date", "product_id", "category_id", "order_cnt", "refund_cnt", "refund_amount"])
W.declare("biz_channel", ["channel_id", "channel_name", "channel_type", "status"])
W.declare("biz_ad_delivery", ["stat_date", "channel_id", "impression", "click", "spend", "new_customer"])
W.declare("biz_order", ["stat_date", "order_id", "channel_id", "customer_id", "product_id", "order_amount",
                        "discount_amount", "pay_amount", "order_status"])
W.declare("biz_sales_summary", ["stat_date", "channel_id", "order_cnt", "gmv", "pay_amount", "active_user",
                                "refund_amount"])
W.declare("biz_refund_reason", ["reason_code", "reason_name", "reason_type", "is_responsible"])
W.declare("biz_refund_apply", ["stat_date", "refund_id", "order_id", "customer_id", "product_id",
                               "reason_code", "refund_amount", "apply_channel", "refund_status", "handle_hours"])


# ---------------------------------------------------------------------------
# A. 商品目录优化场景
# ---------------------------------------------------------------------------

CATEGORIES = [
    ("C01", "美妆个护"),
    ("C02", "数码配件"),
    ("C03", "家居日用"),
    ("C04", "服饰鞋包"),
    ("C05", "食品生鲜"),
]

# 美妆个护类目下的商品（目录质量问题商品）
C01_PRODUCTS = [
    ("氨基酸洁面乳", "润妍", 89.00, 32.00),
    ("玻尿酸精华液", "润妍", 199.00, 78.00),
    ("烟酰胺面霜", "肌研社", 159.00, 61.00),
    ("视黄醇眼霜", "肌研社", 229.00, 88.00),
    ("水杨酸洁面啫喱", "清颜", 69.00, 24.00),
    ("神经酰胺乳液", "清颜", 129.00, 52.00),
    ("果酸身体乳", "润妍", 99.00, 38.00),
    ("防晒喷雾SPF50", "阳光纪", 119.00, 45.00),
    ("卸妆油", "清颜", 79.00, 29.00),
    ("睡眠面膜", "肌研社", 149.00, 58.00),
    ("唇部精华", "阳光纪", 59.00, 21.00),
    ("头皮精华液", "润妍", 139.00, 55.00),
]

# 其它类目的商品（目录质量正常）
OTHER_PRODUCTS = {
    "C02": [("Type-C 快充数据线 1.5 米 支持 100W 快充 尼龙编织", "速联", 39.00, 12.00),
            ("氮化镓充电器 65W 双口 PD 快充 便携旅行装", "速联", 129.00, 55.00),
            ("蓝牙 5.3 无线耳机 主动降噪 长续航 入耳式", "声动", 299.00, 138.00),
            ("磁吸手机支架 车载出风口 360 度旋转 稳固防滑", "速联", 49.00, 16.00),
            ("移动电源 20000mAh 双向快充 数显电量 轻薄便携", "电小满", 159.00, 72.00),
            ("机械键盘 87 键 客制化 热插拔 RGB 背光 有线", "键造", 359.00, 168.00),
            ("无线鼠标 静音办公 2.4G 双模 人体工学设计", "键造", 89.00, 33.00),
            ("笔记本散热支架 铝合金 六档调节 可折叠便携", "速联", 79.00, 28.00),
            ("摄像头 1080P 高清 带麦克风 免驱 网课直播专用", "视界", 149.00, 68.00),
            ("USB 分线器 七合一 高速传输 带供电口 铝合金", "速联", 69.00, 22.00),
            ("智能手环 血氧监测 心率预警 14 天续航 防水", "电小满", 219.00, 101.00),
            ("桌面理线器 硅胶防滑 多孔收纳 办公桌面整理", "键造", 29.00, 8.00)],
    "C03": [("天然乳胶枕 泰国进口 护颈助眠 透气可拆洗", "眠安", 259.00, 112.00),
            ("全棉四件套 60 支长绒棉 亲肤裸睡 四季通用", "眠安", 399.00, 178.00),
            ("折叠收纳箱 加厚牛津布 大容量 衣物被子整理", "纳百川", 69.00, 24.00),
            ("厨房置物架 不锈钢 三层落地 免打孔 承重强", "纳百川", 159.00, 66.00),
            ("浴室防滑垫 硅胶吸盘 速干抑菌 加厚加大", "纳百川", 49.00, 15.00),
            ("香薰蜡烛 大豆蜡 天然植物精油 助眠无烟", "眠安", 89.00, 31.00),
            ("真空压缩袋 手卷免抽气 加厚耐用 旅行收纳", "纳百川", 39.00, 11.00),
            ("陶瓷餐具套装 釉下彩 家用饭碗盘勺 可微波", "器の家", 199.00, 82.00),
            ("懒人沙发 榻榻米 可拆洗 客厅卧室躺椅", "眠安", 459.00, 212.00),
            ("拖把套装 免手洗 旋转甩干 干湿两用 带桶", "纳百川", 129.00, 52.00),
            ("不锈钢保温杯 316 内胆 大容量 长效保温", "器の家", 99.00, 36.00),
            ("桌面收纳盒 亚克力 抽屉式 化妆品文具整理", "纳百川", 59.00, 18.00)],
    "C04": [("纯棉基础款圆领 T 恤 男女同款 四季百搭", "棉致", 79.00, 28.00),
            ("阔腿牛仔裤 高腰显瘦 直筒垂感 春秋薄款", "棉致", 199.00, 86.00),
            ("轻薄羽绒服 90 白鸭绒 立领短款 便携收纳", "暖度", 599.00, 278.00),
            ("针织开衫 宽松慵懒风 中长款 秋冬外搭", "暖度", 259.00, 108.00),
            ("运动休闲裤 速干透气 束脚 跑步健身长裤", "悦动", 149.00, 58.00),
            ("帆布鞋 厚底增高 百搭小白鞋 情侣款", "悦动", 189.00, 76.00),
            ("真丝方巾 桑蚕丝 大方巾 春秋防风防晒", "棉致", 169.00, 68.00),
            ("双肩背包 防泼水 15.6 寸电脑仓 通勤旅行", "行者", 229.00, 98.00),
            ("短款风衣 卡其色 收腰显瘦 春秋薄外套", "暖度", 459.00, 202.00),
            ("无痕内衣 聚拢舒适 无钢圈 薄款透气", "棉致", 129.00, 49.00),
            ("羊毛围巾 100% 羊毛 加厚保暖 纯色百搭", "暖度", 199.00, 82.00),
            ("棒球帽 遮阳防晒 可调节 男女通用", "悦动", 69.00, 22.00)],
    "C05": [("新疆阿克苏冰糖心苹果 5 斤装 现摘现发", "鲜果集", 49.90, 26.00),
            ("海南贵妃芒 3 斤装 树上熟 香甜多汁", "鲜果集", 39.90, 21.00),
            ("阳澄湖大闸蟹 8 只装 公母对半 鲜活发货", "蟹逅", 299.00, 178.00),
            ("五常大米 10 斤装 稻花香 2 号 当季新米", "谷香村", 89.90, 52.00),
            ("内蒙古草原羔羊肉卷 2 斤装 冷冻火锅食材", "牧原鲜", 129.00, 78.00),
            ("云南小粒咖啡豆 中深烘焙 现磨手冲 500g", "豆言", 99.00, 45.00),
            ("进口车厘子 2 斤装 JJ 级 顺丰冷链", "鲜果集", 159.00, 102.00),
            ("低脂鸡胸肉 10 袋装 即食代餐 高蛋白", "轻食记", 69.90, 38.00),
            ("有机纯牛奶 250ml×24 盒 整箱装", "牧原鲜", 79.90, 51.00),
            ("冻干柠檬片 泡水喝 无添加 罐装 200g", "豆言", 39.90, 16.00),
            ("东北粘玉米 10 穗装 真空包装 软糯香甜", "谷香村", 45.90, 24.00),
            ("每日坚果 30 小包 混合果仁 孕妇零食", "轻食记", 129.00, 68.00)],
}

# 搜索词库：美妆个护的高频词在目录中缺失商品，导致空搜索暴涨
SEARCH_KEYWORDS = {
    "C01": ["氨基酸洁面", "玻尿酸精华", "烟酰胺面霜", "视黄醇眼霜", "水杨酸洁面", "神经酰胺"],
    "C02": ["氮化镓充电器", "蓝牙耳机", "移动电源", "机械键盘", "数据线"],
    "C03": ["乳胶枕", "四件套", "收纳箱", "保温杯", "香薰"],
    "C04": ["阔腿牛仔裤", "羽绒服", "帆布鞋", "针织开衫", "双肩包"],
    "C05": ["阿克苏苹果", "大闸蟹", "五常大米", "咖啡豆", "车厘子"],
}

# 目录中真实存在商品、但检索命中率低的词（C01 埋点）
C01_MISSING_KEYWORDS = {"氨基酸洁面", "玻尿酸精华", "神经酰胺"}

BRANDS_FALLBACK = "自营"


def build_catalog() -> tuple[list, list[str]]:
    """生成类目与商品，返回 (商品明细列表, 全部商品ID)。"""
    for cid, cname in CATEGORIES:
        W.add("biz_category", ["category_id", "category_name", "parent_id", "level", "is_leaf", "status"],
              [cid, cname, None, 1, 1, "active"])

    products = []
    pid_seq = 0
    for cid, _cname in CATEGORIES:
        rows = C01_PRODUCTS if cid == "C01" else OTHER_PRODUCTS[cid]
        for name, brand, price, cost in rows:
            pid_seq += 1
            pid = f"P{pid_seq:04d}"
            if cid == "C01":
                # 目录质量差：标题短、主图少、属性填充率低
                title_len = RNG.randint(6, 13)
                image_cnt = RNG.choice([1, 1, 1, 2])
                attr_rate = round(RNG.uniform(22, 45), 2)
                stock = RNG.randint(30, 400)
            else:
                title_len = len(name)
                image_cnt = RNG.randint(4, 6)
                attr_rate = round(RNG.uniform(76, 96), 2)
                stock = RNG.randint(200, 2000)
            on_shelf = PERIOD_START - timedelta(days=RNG.randint(30, 400))
            products.append({"pid": pid, "cid": cid, "name": name, "brand": brand,
                             "price": price, "cost": cost})
            W.add("biz_product",
                  ["product_id", "product_name", "category_id", "brand", "price", "cost", "stock_qty",
                   "on_shelf_date", "shelf_status", "title_length", "image_count", "attr_fill_rate"],
                  [pid, name, cid, brand, price, cost, stock, on_shelf, "on", title_len, image_cnt, attr_rate])
    return products, [p["pid"] for p in products]


def build_catalog_funnel(products: list) -> None:
    """搜索曝光 / 点击 / 转化 三张漏斗表。

    埋入的异常：
      C01 美妆个护 曝光量基本持平，但异常期点击率从 ~4.2% 掉到 ~2.1%；
      C01 的 3 个核心搜索词空搜索次数在异常期放大 3 倍。
    """
    ctr_base_c01 = 0.042
    ctr_anomaly_c01 = 0.021
    ctr_other = 0.055
    cvr_base = 0.030          # 点击->下单
    cvr_anomaly_c01 = 0.018   # C01 异常期转化同步恶化

    cat_products: dict[str, list] = {}
    for p in products:
        cat_products.setdefault(p["cid"], []).append(p)

    for d in ALL_DATES:
        anomaly = d >= SPLIT_DATE
        for cid, _cname in CATEGORIES:
            plist = cat_products[cid]
            # --- 搜索曝光 ---
            for kw in SEARCH_KEYWORDS[cid]:
                search_cnt = RNG.randint(2800, 4200)
                if cid == "C01":
                    exposure = search_cnt * RNG.randint(9, 12)
                    if kw in C01_MISSING_KEYWORDS:
                        zero = RNG.randint(900, 1400) if anomaly else RNG.randint(240, 380)
                    else:
                        zero = RNG.randint(120, 260) if anomaly else RNG.randint(90, 180)
                else:
                    exposure = search_cnt * RNG.randint(11, 15)
                    zero = RNG.randint(40, 160)
                W.add("biz_search_exposure",
                      ["stat_date", "category_id", "product_id", "search_keyword",
                       "exposure_cnt", "search_cnt", "zero_result_cnt"],
                      [d, cid, None, kw, exposure, search_cnt, zero])

            # --- 点击 + 转化 ---
            for p in plist:
                if cid == "C01":
                    ctr = ctr_anomaly_c01 if anomaly else ctr_base_c01
                    cvr = cvr_anomaly_c01 if anomaly else cvr_base
                else:
                    ctr = ctr_other
                    cvr = cvr_base
                exposure = RNG.randint(2200, 3600)
                # 目录质量分：标题短 + 主图少 -> 曝光打折
                quality = 1.0
                clicks = max(1, int(exposure * ctr * RNG.uniform(0.88, 1.12)))
                uv = max(1, int(clicks * RNG.uniform(0.72, 0.86)))
                W.add("biz_product_click",
                      ["stat_date", "product_id", "category_id", "exposure_cnt", "click_cnt", "uv"],
                      [d, p["pid"], cid, exposure, clicks, uv])

                cart = max(0, int(clicks * cvr * RNG.uniform(1.6, 2.1)))
                orders = max(0, int(clicks * cvr * RNG.uniform(0.9, 1.15)))
                pay = round(orders * float(p["price"]) * RNG.uniform(0.94, 1.06), 2)
                W.add("biz_product_conversion",
                      ["stat_date", "product_id", "category_id", "click_cnt", "cart_cnt", "order_cnt", "pay_amount"],
                      [d, p["pid"], cid, clicks, cart, orders, pay])


# ---------------------------------------------------------------------------
# B. 客户行为分析场景
# ---------------------------------------------------------------------------

CITIES = ["上海", "北京", "深圳", "杭州", "成都", "广州", "南京", "武汉", "西安", "苏州"]
DEVICES = ["app", "app", "app", "pc", "mini"]
MEMBER_LEVELS = ["normal", "normal", "silver", "gold", "platinum"]
LIFECYCLES = ["new", "active", "active", "active", "silent", "churn"]

CHANNELS = [
    ("CH01", "搜索-品牌词", "search"),
    ("CH02", "搜索-品类词", "search"),
    ("CH03", "社媒-信息流", "social"),
    ("CH04", "内容-种草", "content"),
    ("CH05", "联盟-CPS", "alliance"),
    ("CH06", "直访", "direct"),
]


def build_customers() -> list[str]:
    ids = []
    for i in range(1, 201):
        cid = f"U{i:05d}"
        ids.append(cid)
        reg = PERIOD_START - timedelta(days=RNG.randint(1, 720))
        W.add("biz_customer", ["customer_id", "customer_name", "register_date", "channel_id", "city",
                               "member_level", "lifecycle"],
              [cid, f"客户{i:03d}", reg, RNG.choice([c[0] for c in CHANNELS]),
               RNG.choice(CITIES), RNG.choice(MEMBER_LEVELS), RNG.choice(LIFECYCLES)])
    return ids


def build_customer_behavior(customers: list[str]) -> None:
    """访问/加购/下单事件。异常期整体活跃用户轻微下滑，加购弃购率上升。"""
    sampled = customers[:80]
    for d in ALL_DATES:
        anomaly = d >= SPLIT_DATE
        for cid in sampled:
            visit = RNG.randint(1, 4)
            pv = visit * RNG.randint(3, 9)
            duration = pv * RNG.randint(25, 90)
            W.add("biz_visit_event", ["stat_date", "customer_id", "visit_cnt", "pv", "duration_sec", "device"],
                  [d, cid, visit, pv, duration, RNG.choice(DEVICES)])

            add_cart = RNG.randint(0, 3)
            cart_amount = round(add_cart * RNG.uniform(60, 420), 2)
            abandon = sum(1 for _ in range(add_cart) if RNG.random() < (0.68 if anomaly else 0.55))
            W.add("biz_cart_event", ["stat_date", "customer_id", "add_cart_cnt", "cart_amount", "abandon_cnt"],
                  [d, cid, add_cart, cart_amount, abandon])

            if anomaly:
                order_cnt = 1 if RNG.random() < 0.22 else 0
            else:
                order_cnt = 1 if RNG.random() < 0.30 else 0
            order_amount = round(order_cnt * RNG.uniform(80, 520), 2)
            refund = 1 if order_cnt and RNG.random() < 0.06 else 0
            W.add("biz_order_event", ["stat_date", "customer_id", "order_cnt", "order_amount", "refund_cnt"],
                  [d, cid, order_cnt, order_amount, refund])


# ---------------------------------------------------------------------------
# C. 库存异常分析场景
# ---------------------------------------------------------------------------

WAREHOUSES = ["WH01", "WH02", "WH03"]


def build_inventory(products: list) -> None:
    """库存异常：C01 类目异常期出现「可用库存低于安全库存」且「在途未补」，同时滞销 SKU 积压。"""
    subset = products[:60]
    for d in ALL_DATES:
        anomaly = d >= SPLIT_DATE
        for idx, p in enumerate(subset):
            wh = WAREHOUSES[idx % len(WAREHOUSES)]
            cid = p["cid"]
            if cid == "C01" and anomaly:
                safety = RNG.randint(120, 220)
                available = RNG.randint(0, 35)          # 严重缺货
                locked = RNG.randint(40, 90)
                on_hand = available + locked
                in_transit = RNG.randint(0, 20)         # 补货在途几乎为 0
            elif cid in ("C03", "C04") and anomaly:
                safety = RNG.randint(150, 260)
                available = RNG.randint(900, 1600)      # 严重积压
                locked = RNG.randint(20, 60)
                on_hand = available + locked
                in_transit = RNG.randint(200, 500)
            else:
                safety = RNG.randint(150, 260)
                available = RNG.randint(260, 700)
                locked = RNG.randint(20, 80)
                on_hand = available + locked
                in_transit = RNG.randint(60, 220)

            W.add("biz_inventory",
                  ["stat_date", "warehouse_id", "product_id", "on_hand_qty", "available_qty",
                   "locked_qty", "in_transit_qty", "safety_stock_qty"],
                  [d, wh, p["pid"], on_hand, available, locked, in_transit, safety])

            plan = RNG.randint(200, 600)
            inbound = max(0, int(plan * (RNG.uniform(0.15, 0.35) if (cid == "C01" and anomaly) else RNG.uniform(0.8, 1.05))))
            W.add("biz_inbound", ["stat_date", "warehouse_id", "product_id", "inbound_qty", "inbound_amount", "plan_qty"],
                  [d, wh, p["pid"], inbound, round(inbound * float(p["cost"]), 2), plan])

            sale_out = RNG.randint(40, 180)
            out_type = "sale" if RNG.random() < 0.9 else ("transfer" if RNG.random() < 0.6 else "scrap")
            W.add("biz_outbound", ["stat_date", "warehouse_id", "product_id", "outbound_qty", "outbound_type"],
                  [d, wh, p["pid"], sale_out, out_type])

            qty = RNG.randint(30, 160)
            W.add("biz_sales", ["stat_date", "product_id", "category_id", "sale_qty", "sale_amount", "avg_daily_sale"],
                  [d, p["pid"], cid, qty, round(qty * float(p["price"]), 2), round(qty / 30.0, 2)])


# ---------------------------------------------------------------------------
# D. 评论反馈分析场景
# ---------------------------------------------------------------------------

REVIEW_TEMPLATES = {
    ("negative", "质量问题"): [
        "收到货发现瓶身有划痕，膏体也有分层，明显是临期或者存储不当",
        "用了三天脸颊泛红起皮，成分表里酒精排第二，敏感肌慎入",
        "质地和专柜买的完全不一样，怀疑是假货，联系客服也没给说法",
        "泵头按压一次出不来量，按十几次才有，设计太不合理了",
    ],
    ("negative", "物流问题"): [
        "物流太慢了，下单到收货整整八天，包装还破了",
        "快递暴力运输，外盒压扁，里面的玻璃瓶碎了",
        "承诺次日达结果三天才到，活动期间也不给补偿",
        "发错仓库了，从广东发到东北，白白多等四天",
    ],
    ("negative", "描述不符"): [
        "详情页写 100ml，实际收到只有 80ml，规格标错了吧",
        "图片看着是雾面质地，实际是巨油的那种，跟描述差太多",
        "标题写保质期到 2028 年，收到的只有 2026 年 10 月",
        "说是无香精，打开一股浓烈的香精味，跟宣传不符",
    ],
    ("negative", "客服问题"): [
        "咨询成分问题，客服一直发话术模板，根本答非所问",
        "申请退款被驳回两次，每次都要重新描述一遍问题",
        "客服承诺补发小样，到现在半个月了也没收到",
        "售后电话永远占线，在线客服排队四十分钟没人接",
    ],
    ("neutral", "价格问题"): [
        "买完第二天就降价 20 块，价保申请又不给通过",
        "凑单买的，单买不划算，感觉被套路了",
        "效果一般般吧，这个价位有更好的选择",
        "用了一周没什么感觉，无功无过",
    ],
    ("positive", None): [
        "质地清爽好吸收，用了两周闭口确实少了，会回购",
        "包装很有质感，物流也快，第二天就到了，好评",
        "成分表干净，敏感肌用着不刺激，性价比很高",
        "第二次买了，家里人都说好用，推荐",
        "客服态度很好，有小样赠送，体验不错",
    ],
}
ISSUE_TAGS = ["质量问题", "物流问题", "描述不符", "客服问题", "价格问题"]
# 负面评论可选的问题标签（「价格问题」仅在 neutral 语境下使用，故不在此列）
NEGATIVE_ISSUE_TAGS = ["质量问题", "物流问题", "描述不符", "客服问题"]


def build_reviews(products: list) -> None:
    """评论/评分：异常期 C01 负面评论占比从 ~12% 抬升到 ~34%，集中在质量与描述不符。"""
    idx = 0
    for d in ALL_DATES:
        anomaly = d >= SPLIT_DATE
        for p in products:
            # 每个商品每天 0~2 条评论
            n = RNG.choice([0, 0, 1, 1, 2])
            for _ in range(n):
                idx += 1
                cid = p["cid"]
                neg_p = 0.34 if (cid == "C01" and anomaly) else (0.16 if cid == "C01" else 0.10)
                r = RNG.random()
                if r < neg_p:
                    sentiment = "negative"
                    tag = (RNG.choices(NEGATIVE_ISSUE_TAGS, weights=[45, 20, 25, 10])[0]
                           if cid == "C01" else RNG.choice(NEGATIVE_ISSUE_TAGS))
                    content = RNG.choice(REVIEW_TEMPLATES[(sentiment, tag)])
                elif r < neg_p + 0.12:
                    sentiment, tag = "neutral", "价格问题"
                    content = RNG.choice(REVIEW_TEMPLATES[(sentiment, tag)])
                else:
                    sentiment, tag = "positive", None
                    content = RNG.choice(REVIEW_TEMPLATES[(sentiment, None)])
                W.add("biz_review", ["stat_date", "review_id", "product_id", "customer_id", "review_content",
                                     "sentiment", "issue_tag", "has_image"],
                      [d, f"RV{idx:07d}", p["pid"], f"U{RNG.randint(1, 200):05d}", content,
                       sentiment, tag, 1 if RNG.random() < 0.35 else 0])

        # 评分分布
        for p in products:
            cid = p["cid"]
            if cid == "C01" and anomaly:
                dist = [RNG.randint(18, 30), RNG.randint(12, 22), RNG.randint(15, 25), RNG.randint(12, 20), RNG.randint(20, 34)]
            else:
                dist = [RNG.randint(2, 8), RNG.randint(3, 9), RNG.randint(8, 16), RNG.randint(30, 45), RNG.randint(90, 140)]
            total = sum(dist)
            avg = round(sum((i + 1) * c for i, c in enumerate(dist)) / total, 2)
            W.add("biz_rating", ["stat_date", "product_id", "rating_1_cnt", "rating_2_cnt", "rating_3_cnt",
                                 "rating_4_cnt", "rating_5_cnt", "avg_rating"],
                  [d, p["pid"], *dist, avg])

        # 退款表
        for p in products:
            cid = p["cid"]
            orders = RNG.randint(20, 90)
            if cid == "C01" and anomaly:
                refunds = int(orders * RNG.uniform(0.16, 0.24))
            else:
                refunds = int(orders * RNG.uniform(0.03, 0.08))
            W.add("biz_refund", ["stat_date", "product_id", "category_id", "order_cnt", "refund_cnt", "refund_amount"],
                  [d, p["pid"], cid, orders, refunds, round(refunds * float(p["price"]), 2)])


# ---------------------------------------------------------------------------
# E. 市场表现分析场景 + F. 退款模式分析场景
# ---------------------------------------------------------------------------

REFUND_REASONS = [
    ("R01", "商品质量问题", "quality", 1),
    ("R02", "商品与描述不符", "expectation", 1),
    ("R03", "收到商品破损", "quality", 1),
    ("R04", "临期或过期", "quality", 1),
    ("R05", "物流长时间未送达", "logistics", 0),
    ("R06", "快递丢失", "logistics", 0),
    ("R07", "拍错/多拍/不想要", "other", 0),
    ("R08", "效果未达预期", "expectation", 1),
    ("R09", "价格保护/降价", "expectation", 1),
    ("R10", "客服处理不当", "service", 1),
    ("R11", "发错货", "service", 1),
    ("R12", "尺码不合适", "other", 0),
]


def build_market_and_refund(products: list, customers: list[str]) -> None:
    """市场表现 + 退款模式。

    埋入的异常：
      CH03 社媒-信息流 花费不变但转化断崖，ROAS 从 ~3.5 掉到 ~1.8；
      CH01 搜索-品牌词 CPA 上升约 40%；
      整体 GMV 异常期环比下滑约 12%；
      退款率抬升，原因集中在质量类。
    """
    for cid, cname, ctype in CHANNELS:
        W.add("biz_channel", ["channel_id", "channel_name", "channel_type", "status"], [cid, cname, ctype, "enabled"])

    for rc, rn, rt, resp in REFUND_REASONS:
        W.add("biz_refund_reason", ["reason_code", "reason_name", "reason_type", "is_responsible"],
              [rc, rn, rt, resp])

    order_seq = 0
    refund_seq = 0

    for d in ALL_DATES:
        anomaly = d >= SPLIT_DATE
        for cid, cname, ctype in CHANNELS:
            # ---------------- 投放 ----------------
            if ctype == "search":
                impression = RNG.randint(180_000, 260_000)
                ctr = RNG.uniform(0.028, 0.040)
                spend = round(RNG.uniform(9_000, 14_000), 2)
            elif cid == "CH03":  # 社媒-信息流
                impression = RNG.randint(900_000, 1_400_000)
                ctr = RNG.uniform(0.006, 0.011) if anomaly else RNG.uniform(0.013, 0.019)
                spend = round(RNG.uniform(28_000, 33_000), 2)  # 花费几乎不变
            elif ctype == "content":
                impression = RNG.randint(260_000, 420_000)
                ctr = RNG.uniform(0.020, 0.032)
                spend = round(RNG.uniform(15_000, 22_000), 2)
            elif ctype == "alliance":
                impression = RNG.randint(80_000, 160_000)
                ctr = RNG.uniform(0.030, 0.050)
                spend = round(RNG.uniform(3_000, 6_000), 2)
            else:  # direct
                impression = RNG.randint(60_000, 120_000)
                ctr = RNG.uniform(0.040, 0.060)
                spend = round(RNG.uniform(300, 1_200), 2)

            click = max(1, int(impression * ctr))
            if anomaly:
                new_customer = int(click * RNG.uniform(0.010, 0.020)) if cid == "CH03" else int(click * RNG.uniform(0.028, 0.045))
            else:
                new_customer = int(click * RNG.uniform(0.045, 0.065)) if cid == "CH03" else int(click * RNG.uniform(0.030, 0.048))
            W.add("biz_ad_delivery", ["stat_date", "channel_id", "impression", "click", "spend", "new_customer"],
                  [d, cid, impression, click, spend, new_customer])

            # ---------------- 订单 ----------------
            if cid == "CH03":
                cvr = RNG.uniform(0.0085, 0.0115) if anomaly else RNG.uniform(0.016, 0.021)
            elif cid == "CH01":
                cvr = RNG.uniform(0.030, 0.040) if anomaly else RNG.uniform(0.042, 0.052)
            else:
                cvr = RNG.uniform(0.022, 0.036)

            order_cnt = max(1, int(click * cvr))
            gmv = Decimal("0.00")
            pay_total = Decimal("0.00")
            refund_total = Decimal("0.00")
            day_orders = []
            for _ in range(order_cnt):
                order_seq += 1
                amount = Decimal(str(round(RNG.uniform(80, 900), 2)))
                discount = Decimal(str(round(float(amount) * RNG.uniform(0, 0.18), 2)))
                pay = amount - discount
                # 异常期退款概率抬升
                refund_p = 0.085 if anomaly else 0.045
                is_refund = RNG.random() < refund_p
                status = "refunded" if is_refund else RNG.choice(["paid", "shipped", "done", "done"])
                cust = RNG.choice(customers)
                prod = RNG.choice(products)
                oid = f"SO{d.strftime('%Y%m%d')}{order_seq:06d}"
                W.add("biz_order", ["stat_date", "order_id", "channel_id", "customer_id", "product_id",
                                    "order_amount", "discount_amount", "pay_amount", "order_status"],
                      [d, oid, cid, cust, prod["pid"], float(amount), float(discount), float(pay), status])
                day_orders.append((oid, cust, prod, float(pay)))
                gmv += amount
                pay_total += pay
                if is_refund:
                    refund_total += pay

            W.add("biz_sales_summary", ["stat_date", "channel_id", "order_cnt", "gmv", "pay_amount",
                                        "active_user", "refund_amount"],
                  [d, cid, order_cnt, float(gmv), float(pay_total), new_customer + RNG.randint(50, 400),
                   float(refund_total)])

            # ---------------- 退款申请 ----------------
            if not day_orders:
                continue
            n_refund = max(0, int(len(day_orders) * (RNG.uniform(0.05, 0.10) if anomaly else RNG.uniform(0.03, 0.06))))
            for oid, cust, prod, pay in RNG.sample(day_orders, min(n_refund, len(day_orders))):
                refund_seq += 1
                if anomaly:
                    reason = RNG.choices(
                        [r[0] for r in REFUND_REASONS],
                        weights=[26, 19, 13, 8, 7, 4, 6, 8, 4, 3, 2, 0],
                    )[0]
                else:
                    reason = RNG.choices(
                        [r[0] for r in REFUND_REASONS],
                        weights=[12, 11, 8, 4, 11, 6, 18, 9, 8, 4, 4, 5],
                    )[0]
                handle = round(RNG.uniform(2, 96), 2)
                W.add("biz_refund_apply",
                      ["stat_date", "refund_id", "order_id", "customer_id", "product_id", "reason_code",
                       "refund_amount", "apply_channel", "refund_status", "handle_hours"],
                      [d, f"RF{d.strftime('%Y%m%d')}{refund_seq:05d}", oid, cust, prod["pid"], reason,
                       pay, RNG.choice(["app", "app", "pc", "mini"]),
                       RNG.choices(["approved", "done", "applied", "rejected"], weights=[30, 50, 12, 8])[0],
                       handle])


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

HEADER = """-- =============================================================================
-- 经营多轮归因分析系统 —— 业务示例场景数据
-- 数据库: analysis_sys
-- 生成器: backend/scripts/gen_demo_data.py  (随机种子 20260901，可完整复现)
-- 统计窗口: 2026-09-01 ~ 2026-09-30
--           基准期 2026-09-01 ~ 2026-09-15
--           异常期 2026-09-16 ~ 2026-09-30
-- 覆盖场景: A 商品目录优化 / B 客户行为分析 / C 库存异常分析 /
--           D 评论反馈分析 / E 市场表现分析 / F 退款模式分析
-- 注意: 请先执行 02_core_schema.sql 与 03_business_schema.sql
-- =============================================================================

USE `analysis_sys`;

SET FOREIGN_KEY_CHECKS = 0;

-- 幂等：清空业务场景表后重新写入
TRUNCATE TABLE `biz_category`;
TRUNCATE TABLE `biz_product`;
TRUNCATE TABLE `biz_search_exposure`;
TRUNCATE TABLE `biz_product_click`;
TRUNCATE TABLE `biz_product_conversion`;
TRUNCATE TABLE `biz_customer`;
TRUNCATE TABLE `biz_visit_event`;
TRUNCATE TABLE `biz_cart_event`;
TRUNCATE TABLE `biz_order_event`;
TRUNCATE TABLE `biz_inventory`;
TRUNCATE TABLE `biz_inbound`;
TRUNCATE TABLE `biz_outbound`;
TRUNCATE TABLE `biz_sales`;
TRUNCATE TABLE `biz_review`;
TRUNCATE TABLE `biz_rating`;
TRUNCATE TABLE `biz_refund`;
TRUNCATE TABLE `biz_channel`;
TRUNCATE TABLE `biz_ad_delivery`;
TRUNCATE TABLE `biz_order`;
TRUNCATE TABLE `biz_sales_summary`;
TRUNCATE TABLE `biz_refund_reason`;
TRUNCATE TABLE `biz_refund_apply`;

"""

FOOTER = """
SET FOREIGN_KEY_CHECKS = 1;

-- =============================================================================
-- 数据生成完成
-- 快速自检 SQL（可选执行）:
--   -- 商品目录优化：比对两期点击率
--   SELECT (SELECT SUM(click_cnt)/SUM(exposure_cnt) FROM biz_product_click
--            WHERE category_id='C01' AND stat_date<'2026-09-16') AS ctr_base,
--          (SELECT SUM(click_cnt)/SUM(exposure_cnt) FROM biz_product_click
--            WHERE category_id='C01' AND stat_date>='2026-09-16') AS ctr_anomaly;
--   -- 市场表现：比对两期 GMV
--   SELECT (SELECT SUM(gmv) FROM biz_sales_summary WHERE stat_date<'2026-09-16')  AS gmv_base,
--          (SELECT SUM(gmv) FROM biz_sales_summary WHERE stat_date>='2026-09-16') AS gmv_anomaly;
-- =============================================================================
"""


def main() -> None:
    products, _pids = build_catalog()
    build_catalog_funnel(products)
    customers = build_customers()
    build_customer_behavior(customers)
    build_inventory(products)
    build_reviews(products)
    build_market_and_refund(products, customers)

    body = W.finish()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(HEADER + body + FOOTER, encoding="utf-8")

    rows = body.count("),\n(") + body.count(") VALUES") + body.count(";\n") * 0
    size_mb = OUT_FILE.stat().st_size / 1024 / 1024
    print(f"[OK] 已生成 {OUT_FILE}")
    print(f"     文件大小 {size_mb:.2f} MB")
    print(f"     表数量   {len(W.order)}")


if __name__ == "__main__":
    main()
