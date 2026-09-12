"""世界状态:门票业务 sqlite 四表,每次执行从种子重建。

为什么每次重建:评测要断言「数据库里退款单金额对不对、状态流转对不对」,前提是
每次执行的起点完全一致 —— 固定时钟 TODAY 让退票手续费档位完全确定(不受真实
日期影响),种子数据让行级断言可预期,临时库让并发执行互不污染。这是轨迹评测
flakiness 控制的地基。

手续费档位(退票政策,按申请日距入园日):
    >= 48h  免手续费
    24~48h  收取 20%
    <  24h  收取 50%
以 TODAY=2026-10-01 为申请日:visit 2026-10-03 的订单免手续费,
visit 2026-09-30 的订单收 50% —— 档位边界由种子数据刻意覆盖。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

# 固定时钟:所有与「今天」相关的业务计算(退票手续费档位等)以此为基准。
# 改变它 = 改变全部金额预期,种子数据与 golden 断言都要跟着重推。
TODAY = "2026-10-01"

TABLES = ("orders", "refunds", "notifications", "inventory")

SCHEMA_SQL = """
CREATE TABLE orders (
    order_id     TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    product      TEXT NOT NULL,
    quantity     INTEGER NOT NULL,
    unit_price   REAL NOT NULL,
    total_amount REAL NOT NULL,
    status       TEXT NOT NULL,  -- pending_payment/paid/refunding/refunded/used/cancelled
    visit_date   TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE refunds (
    refund_id  TEXT PRIMARY KEY,
    order_id   TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    amount     REAL NOT NULL,    -- 实退金额 = total_amount - fee(断言重点)
    fee        REAL NOT NULL,    -- 手续费,calc_refund_fee 确定性算出(断言重点)
    reason     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE notifications (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  TEXT NOT NULL,
    channel  TEXT NOT NULL,
    template TEXT NOT NULL,      -- 模板必须已注册(幻觉模板对抗测点)
    content  TEXT NOT NULL,
    sent_at  TEXT NOT NULL
);

CREATE TABLE inventory (
    product    TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    capacity   INTEGER NOT NULL,
    sold       INTEGER NOT NULL,
    PRIMARY KEY (product, visit_date)
);
"""

# 种子数据:8 笔订单刻意埋测点 —— 金额主角单/档位边界单/改期一成一败/
# 已使用不可退/退款中幂等/他人订单越权/待支付;数字全部整十整百,
# LLM 心算错不错一眼可辨。
SEED_SQL = """
INSERT INTO orders
    (order_id, user_id, product, quantity, unit_price, total_amount, status, visit_date, created_at)
VALUES
    ('TK20260901001', 'U001', '成人票', 2, 144.0, 288.0, 'paid', '2026-10-03', '2026-09-18 10:00'),
    ('TK20260901002', 'U001', '成人票', 2, 144.0, 288.0, 'paid', '2026-09-30', '2026-09-18 10:05'),
    ('TK20260901003', 'U001', '成人票', 1, 100.0, 100.0, 'paid', '2026-10-01', '2026-09-20 14:00'),
    ('TK20260901004', 'U001', '成人票', 1, 100.0, 100.0, 'paid', '2026-10-01', '2026-09-20 14:05'),
    ('TK20260901005', 'U001', '成人票', 2, 120.0, 240.0, 'used', '2026-09-27', '2026-09-15 09:00'),
    ('TK20260901006', 'U001', '成人票', 1, 100.0, 100.0, 'refunding',
     '2026-10-03', '2026-09-18 11:00'),
    ('TK20260901007', 'U002', '成人票', 1, 100.0, 100.0, 'paid', '2026-10-03', '2026-09-19 16:00'),
    ('TK20260901008', 'U001', '成人票', 1, 100.0, 100.0,
     'pending_payment', '2026-10-06', '2026-09-25 12:00');

-- TK20260901006 已有一笔处理中的退款单:幂等测点的起点(再提交不重复建单)
INSERT INTO refunds
    (refund_id, order_id, user_id, amount, fee, reason, status, created_at)
VALUES
    ('RF20260930001', 'TK20260901006', 'U001', 100.0, 0.0,
     '行程变更申请退款', 'pending', '2026-09-30 14:00');

INSERT INTO inventory (product, visit_date, capacity, sold) VALUES
    ('成人票', '2026-09-30', 100, 30),
    ('成人票', '2026-10-01', 100, 60),
    ('成人票', '2026-10-03', 100, 52),
    ('成人票', '2026-10-04', 100, 40),   -- 改期成功路:有余票
    ('成人票', '2026-10-05', 100, 100),  -- 改期失败路:已满
    ('儿童票', '2026-10-03', 50, 10);
"""


def create_world(db_path: str | Path = ":memory:") -> sqlite3.Connection:
    """建全新世界:建表 + 种子。每次调用彼此独立 —— 评测的每次执行各拿一个。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.executescript(SEED_SQL)
    conn.commit()
    return conn


def export_world(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """终态快照:{table: rows}。世界状态断言在这个纯数据结构上执行。

    评分器不碰 SQL:断言 DSL 消费的是 export 出来的快照,保证评分纯函数、
    可离线表驱动单测(拿假快照即可测,不需要真库)。
    """
    world: dict[str, list[dict[str, Any]]] = {}
    for table in TABLES:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        world[table] = [dict(row) for row in rows]
    return world
