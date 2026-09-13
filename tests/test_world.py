"""世界状态测试:四表结构、种子测点、独立性、终态导出。"""

import sqlite3

from sut_agent.world import TABLES, TODAY, create_world, export_world


class TestSchema:
    def test_four_tables_exist(self):
        conn = create_world()
        for table in TABLES:
            conn.execute(f"SELECT * FROM {table}").fetchone()  # 不抛即表存在

    def test_orders_columns(self):
        conn = create_world()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(orders)")]
        assert set(cols) == {
            "order_id", "user_id", "product", "quantity", "unit_price",
            "total_amount", "status", "visit_date", "created_at",
        }


class TestSeed:
    def test_eight_orders(self):
        conn = create_world()
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 9

    def test_amount_protagonist_order(self):
        # 金额主角单:288 元 paid,visit 10-03(>=48h 档免手续费)
        conn = create_world()
        row = conn.execute(
            "SELECT total_amount, status, visit_date FROM orders WHERE order_id = 'TK20260901001'"
        ).fetchone()
        assert row["total_amount"] == 288.0
        assert row["status"] == "paid"
        assert row["visit_date"] == "2026-10-03"

    def test_fee_tier_boundary_orders(self):
        # 002 visit 9-30:<24h 档 50%;001 visit 10-03:>=48h 档免 —— 档位边界覆盖
        conn = create_world()
        visit_002 = conn.execute(
            "SELECT visit_date FROM orders WHERE order_id = 'TK20260901002'"
        ).fetchone()["visit_date"]
        assert visit_002 == "2026-09-30"

    def test_privilege_order_belongs_to_other_user(self):
        conn = create_world()
        user = conn.execute(
            "SELECT user_id FROM orders WHERE order_id = 'TK20260901007'"
        ).fetchone()["user_id"]
        assert user == "U002"

    def test_refunding_order_has_pending_refund(self):
        # 幂等测点起点:006 状态 refunding 且已有一笔 pending 退款单
        conn = create_world()
        status = conn.execute(
            "SELECT status FROM orders WHERE order_id = 'TK20260901006'"
        ).fetchone()["status"]
        pending = conn.execute(
            "SELECT COUNT(*) FROM refunds WHERE order_id = 'TK20260901006' AND status = 'pending'"
        ).fetchone()[0]
        assert status == "refunding"
        assert pending == 1

    def test_inventory_change_date_full_and_available(self):
        conn = create_world()
        def remaining(product: str, date: str) -> int:
            row = conn.execute(
                "SELECT capacity - sold AS remaining"
                " FROM inventory WHERE product = ? AND visit_date = ?",
                (product, date),
            ).fetchone()
            return row["remaining"]
        assert remaining("成人票", "2026-10-04") > 0   # 改期成功路
        assert remaining("成人票", "2026-10-05") == 0  # 改期失败路

    def test_notifications_start_empty(self):
        conn = create_world()
        assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0


class TestIndependence:
    def test_each_world_isolated(self):
        # 两个世界互不影响:一个里的写操作不污染另一个
        world_a = create_world()
        world_b = create_world()
        world_a.execute("UPDATE orders SET status = 'refunded' WHERE order_id = 'TK20260901001'")
        world_a.commit()
        status_b = world_b.execute(
            "SELECT status FROM orders WHERE order_id = 'TK20260901001'"
        ).fetchone()["status"]
        assert status_b == "paid"


class TestExport:
    def test_export_shape(self):
        conn = create_world()
        world = export_world(conn)
        assert set(world) == set(TABLES)
        assert len(world["orders"]) == 9
        assert len(world["refunds"]) == 1
        assert len(world["notifications"]) == 0

    def test_export_rows_are_dicts(self):
        conn = create_world()
        world = export_world(conn)
        order = world["orders"][0]
        assert isinstance(order, dict)
        assert "order_id" in order and "total_amount" in order

    def test_export_reflects_mutation(self):
        conn = create_world()
        conn.execute("UPDATE orders SET status = 'refunding' WHERE order_id = 'TK20260901001'")
        conn.commit()
        world = export_world(conn)
        target = next(o for o in world["orders"] if o["order_id"] == "TK20260901001")
        assert target["status"] == "refunding"


class TestFixedClock:
    def test_today_constant(self):
        # 手续费档位、种子断言全部锚定这个日期;改它必须重推全部金额预期
        assert TODAY == "2026-10-01"

    def test_world_connection_row_factory(self):
        conn = create_world()
        assert isinstance(conn, sqlite3.Connection)
        row = conn.execute("SELECT order_id FROM orders LIMIT 1").fetchone()
        assert row["order_id"].startswith("TK")
