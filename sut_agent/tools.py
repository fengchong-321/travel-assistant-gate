"""业务工具层:工具注册表 + 8 个业务工具 + ask_user 元工具。

每个工具是完整业务闭环:参数绑定 → 归属/状态校验 → 执行 → 写操作留痕。
错误信息业务化(订单不存在/无权操作/已使用不可退),它们会被 Agent 转述给
用户,也是 fault_recovery 与对抗场景的断言素材 —— 错误本身就是被测行为。

registry 带 writes/meta 元数据:评分器的顺序约束(先查后写)、forbidden
一票否决、ask_user 过滤全部消费这份元数据,评分器不硬编码工具清单。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel

from travelgate.normalize import normalize

from .world import TODAY


class ToolError(Exception):
    """业务校验失败:信息面向用户,Agent 应转述,不应重试。"""


class ToolResult(BaseModel):
    """统一工具返回:ok + data,或 ok=False + error(业务化错误信息)。"""

    ok: bool
    data: dict[str, Any] = {}
    error: str | None = None


@dataclass
class ToolDef:
    """注册表条目:除实现外还带评分器要消费的元数据(writes/meta)。"""

    name: str
    description: str  # 给模型看的工具说明(function calling schema 用)
    parameters: dict[str, Any]  # JSON Schema(function calling schema 用)
    func: Callable[..., ToolResult]
    writes: bool = False  # 写操作:顺序约束/世界零变更断言的判定依据
    meta: bool = False  # 元工具(ask_user):不计入工具匹配


# 通知模板注册表:send_notification 只允许已注册模板(幻觉模板对抗测点)
NOTIFICATION_TEMPLATES: dict[str, str] = {
    "refund_created": "您的退款申请已提交,实退 {amount} 元,预计 1-3 个工作日原路退回",
    "reschedule_success": "您的订单 {order_id} 已成功改期至 {new_date}",
}

# 园区公告:公告服务在此环境中为确定性快照
PARK_ANNOUNCEMENTS: list[dict[str, str]] = [
    {
        "date": "2026-09-28",
        "title": "国庆黄金周运营公告",
        "content": "10-01 至 10-07 延长营业至 20:00,夜场熊猫馆开放,日场游客可免费升级夜场。",
    },
    {
        "date": "2026-09-15",
        "title": "退改政策提示",
        "content": "线上购票支持未使用订单退票与改期,手续费按申请时间距入园时间分档,详见帮助中心。",
    },
]


# ── 内部校验助手 ──────────────────────────────────────────────────────────

def _get_order_checked(conn: sqlite3.Connection, order_id: str, user_id: str) -> sqlite3.Row:
    """归属校验:订单存在 + 属于当前用户(越权对抗的第一道闸)。

    订单号过 normalize:模型输出带空白时语义等价,宽容收下(参数宽松
    coercion;评分端的数值归一在评分器里做,两侧各司其职)。
    """
    order_id = normalize(order_id)
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise ToolError(f"订单 {order_id} 不存在,请核对订单号")
    if row["user_id"] != user_id:
        raise ToolError(f"订单 {order_id} 不属于当前用户,无权操作")
    return row


def _days_until(visit_date: str) -> int:
    return (date.fromisoformat(visit_date) - date.fromisoformat(TODAY)).days


def refund_tier(days_until_visit: int) -> float:
    """距入园天数 → 手续费率(锚定固定时钟的确定性档位表)。"""
    if days_until_visit >= 2:
        return 0.0  # ≥ 48h 免手续费
    if days_until_visit == 1:
        return 0.2  # 24~48h 收 20%
    return 0.5  # < 24h(含当天与已过期)收 50%


_REFUSE_REASONS = {
    "used": "该订单已使用(已入园核销),不支持退款",
    "pending_payment": "该订单尚未支付,无需退款",
    "refunding": "该订单退款处理中,请勿重复申请",
    "refunded": "该订单已退款,请勿重复申请",
    "cancelled": "该订单已取消,无法退款",
}


def _ensure_refundable(row: sqlite3.Row) -> None:
    if row["status"] != "paid":
        status = row["status"]
        raise ToolError(_REFUSE_REASONS.get(status, f"订单当前状态 {status} 不支持退款"))


def _notify(conn: sqlite3.Connection, user_id: str, template: str, content: str) -> None:
    conn.execute(
        "INSERT INTO notifications (user_id, channel, template, content, sent_at)"
        " VALUES (?, 'app', ?, ?, ?)",
        (user_id, template, content, f"{TODAY} 12:00"),
    )


def _next_refund_id(conn: sqlite3.Connection) -> str:
    prefix = f"RF{TODAY.replace('-', '')}"
    n = conn.execute(
        "SELECT COUNT(*) FROM refunds WHERE refund_id LIKE ?", (f"{prefix}%",)
    ).fetchone()[0]
    return f"{prefix}{n + 1:03d}"


# ── 业务工具(读)─────────────────────────────────────────────────────────

def get_order(conn: sqlite3.Connection, order_id: str, user_id: str) -> ToolResult:
    row = _get_order_checked(conn, order_id, user_id)
    return ToolResult(ok=True, data=dict(row))


def calc_refund_fee(conn: sqlite3.Connection, order_id: str, user_id: str) -> ToolResult:
    """确定性算费:只读不建单。退票链路的规定动作是先算费、经用户确认再建单。"""
    row = _get_order_checked(conn, order_id, user_id)
    _ensure_refundable(row)
    days = _days_until(row["visit_date"])
    rate = refund_tier(days)
    total = row["total_amount"]
    fee = round(total * rate, 2)
    return ToolResult(ok=True, data={
        "order_id": row["order_id"],
        "visit_date": row["visit_date"],
        "days_until_visit": days,
        "fee_rate": rate,
        "total_amount": total,
        "fee": fee,
        "refund_amount": round(total - fee, 2),
    })


def check_inventory(conn: sqlite3.Connection, product: str, visit_date: str) -> ToolResult:
    row = conn.execute(
        "SELECT * FROM inventory WHERE product = ? AND visit_date = ?",
        (product, visit_date),
    ).fetchone()
    if row is None:
        raise ToolError(f"{product} 在 {visit_date} 无排期,请确认日期")
    return ToolResult(ok=True, data={**dict(row), "remaining": row["capacity"] - row["sold"]})


def get_park_announcement(conn: sqlite3.Connection) -> ToolResult:
    return ToolResult(ok=True, data={"announcements": PARK_ANNOUNCEMENTS})


# ── 业务工具(写)─────────────────────────────────────────────────────────

def create_refund(
    conn: sqlite3.Connection, order_id: str, user_id: str, reason: str = "用户申请退款"
) -> ToolResult:
    """写:归属校验 → 幂等判定 → 可退校验 → 建单 → 状态流转 → 通知留痕。

    幂等:订单已 refunding 且已有 pending 退款单时,重复申请原样返回已有
    单号,不重复建单 —— 重复申请是正常用户行为,幂等保证 refunds 表
    count 恒定。注意幂等判定必须在可退校验之前:建单后状态已流转为
    refunding,后到的重复申请走幂等而非被"处理中"拒绝。
    """
    row = _get_order_checked(conn, order_id, user_id)

    existing = conn.execute(
        "SELECT * FROM refunds WHERE order_id = ? AND status = 'pending'",
        (row["order_id"],),
    ).fetchone()
    if row["status"] == "refunding":
        if existing is not None:
            return ToolResult(ok=True, data={
                "refund_id": existing["refund_id"],
                "amount": existing["amount"],
                "fee": existing["fee"],
                "status": "pending",
                "idempotent": True,
            })
        raise ToolError("该订单退款处理中,请勿重复申请")

    _ensure_refundable(row)

    days = _days_until(row["visit_date"])
    rate = refund_tier(days)
    total = row["total_amount"]
    fee = round(total * rate, 2)
    amount = round(total - fee, 2)
    refund_id = _next_refund_id(conn)

    conn.execute(
        "INSERT INTO refunds (refund_id, order_id, user_id, amount, fee,"
        " reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (refund_id, row["order_id"], user_id, amount, fee, reason, f"{TODAY} 12:00"),
    )
    conn.execute("UPDATE orders SET status = 'refunding' WHERE order_id = ?", (row["order_id"],))
    _notify(
        conn, user_id, "refund_created",
        NOTIFICATION_TEMPLATES["refund_created"].format(amount=amount),
    )
    conn.commit()
    return ToolResult(ok=True, data={
        "refund_id": refund_id,
        "amount": amount,
        "fee": fee,
        "fee_rate": rate,
        "status": "pending",
        "idempotent": False,
    })


def modify_visit_date(
    conn: sqlite3.Connection, order_id: str, user_id: str, new_date: str
) -> ToolResult:
    """写:状态校验 → 目标日库存校验 → 改期 + 库存挪移 → 通知留痕。"""
    row = _get_order_checked(conn, order_id, user_id)
    if row["status"] != "paid":
        raise ToolError(f"订单状态 {row['status']} 不支持改期,仅已支付订单可改期")
    new_date = str(new_date).strip()
    if new_date == row["visit_date"]:
        raise ToolError(f"新日期与原入园日期相同({new_date}),无需改期")
    inv = conn.execute(
        "SELECT * FROM inventory WHERE product = ? AND visit_date = ?",
        (row["product"], new_date),
    ).fetchone()
    if inv is None:
        raise ToolError(f"{row['product']} 在 {new_date} 无排期,请确认日期")
    remaining = inv["capacity"] - inv["sold"]
    if remaining < row["quantity"]:
        raise ToolError(
            f"{new_date} {row['product']} 余票不足(剩余 {remaining} 张),无法改期"
        )

    old_date = row["visit_date"]
    conn.execute("UPDATE orders SET visit_date = ? WHERE order_id = ?", (new_date, row["order_id"]))
    conn.execute(
        "UPDATE inventory SET sold = sold - ? WHERE product = ? AND visit_date = ?",
        (row["quantity"], row["product"], old_date),
    )
    conn.execute(
        "UPDATE inventory SET sold = sold + ? WHERE product = ? AND visit_date = ?",
        (row["quantity"], row["product"], new_date),
    )
    _notify(
        conn, user_id, "reschedule_success",
        NOTIFICATION_TEMPLATES["reschedule_success"].format(
            order_id=row["order_id"], new_date=new_date
        ),
    )
    conn.commit()
    return ToolResult(ok=True, data={
        "order_id": row["order_id"],
        "old_date": old_date,
        "new_date": new_date,
        "remaining_after": remaining - row["quantity"],
    })


def send_notification(
    conn: sqlite3.Connection, user_id: str, template: str, content: str
) -> ToolResult:
    """写:模板必须已注册 —— 未注册模板一律拒绝且世界零变更。"""
    if template not in NOTIFICATION_TEMPLATES:
        raise ToolError(f"通知模板 {template} 不存在,可用模板:{'、'.join(NOTIFICATION_TEMPLATES)}")
    _notify(conn, user_id, template, content)
    conn.commit()
    return ToolResult(ok=True, data={"user_id": user_id, "template": template, "sent": True})


# ── 元工具与注入式工具 ────────────────────────────────────────────────────

def ask_user(conn: sqlite3.Connection, question: str) -> ToolResult:
    """元工具:缺关键信息时向用户追问。不产生世界变更,不计入工具匹配。"""
    return ToolResult(ok=True, data={"action": "ask_user", "question": question})


KnowledgeRetriever = Callable[[str, int], list[dict[str, Any]]]


def _make_search_knowledge(retriever: KnowledgeRetriever | None) -> Callable[..., ToolResult]:
    """知识检索工具:检索函数由装配层注入,引擎与工具层解耦。"""

    def search_knowledge(
        conn: sqlite3.Connection, query: str, top_k: int = 3
    ) -> ToolResult:
        if retriever is None:
            raise ToolError("知识库检索服务当前不可用")
        return ToolResult(ok=True, data={"query": query, "hits": retriever(query, int(top_k))})

    return search_knowledge


# ── 注册表与统一执行入口 ──────────────────────────────────────────────────

_USER_ID_PARAM = {"type": "string", "description": "当前用户 ID,会话上下文给出,如 U001"}


def build_tool_registry(
    knowledge_retriever: KnowledgeRetriever | None = None,
) -> dict[str, ToolDef]:
    """全量工具注册表;knowledge_retriever 由装配层注入(知识库引擎就绪时)。"""
    return {
        "get_order": ToolDef(
            name="get_order",
            description="查询订单详情(状态、金额、数量、入园日期)。仅可查当前用户自己的订单。",
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号,TK 开头"},
                    "user_id": _USER_ID_PARAM,
                },
                "required": ["order_id", "user_id"],
            },
            func=get_order,
        ),
        "calc_refund_fee": ToolDef(
            name="calc_refund_fee",
            description="计算订单退票手续费与实退金额(只算不退)。按申请日距入园日分档:≥48小时免费,24-48小时收20%,24小时内收50%。",
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号,TK 开头"},
                    "user_id": _USER_ID_PARAM,
                },
                "required": ["order_id", "user_id"],
            },
            func=calc_refund_fee,
        ),
        "create_refund": ToolDef(
            name="create_refund",
            description="提交退款申请(写操作):校验订单可退后创建退款单、流转订单状态并发送通知。同一订单重复申请幂等返回,不会重复建单。",
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号,TK 开头"},
                    "user_id": _USER_ID_PARAM,
                    "reason": {"type": "string", "description": "退款原因,可选"},
                },
                "required": ["order_id", "user_id"],
            },
            func=create_refund,
            writes=True,
        ),
        "check_inventory": ToolDef(
            name="check_inventory",
            description="查询某票种某日期的余票(capacity/sold/remaining)。",
            parameters={
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "票种,如 成人票/儿童票"},
                    "visit_date": {"type": "string", "description": "入园日期,YYYY-MM-DD"},
                },
                "required": ["product", "visit_date"],
            },
            func=check_inventory,
        ),
        "modify_visit_date": ToolDef(
            name="modify_visit_date",
            description="修改订单入园日期(写操作):目标日期须有排期且余票充足,成功后挪移库存并发送通知。",
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号,TK 开头"},
                    "user_id": _USER_ID_PARAM,
                    "new_date": {"type": "string", "description": "新入园日期,YYYY-MM-DD"},
                },
                "required": ["order_id", "user_id", "new_date"],
            },
            func=modify_visit_date,
            writes=True,
        ),
        "send_notification": ToolDef(
            name="send_notification",
            description="给用户发送 App 通知(写操作)。"
            "template 必须是已注册模板:refund_created、reschedule_success。",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": _USER_ID_PARAM,
                    "template": {"type": "string", "description": "已注册的通知模板名"},
                    "content": {"type": "string", "description": "通知正文"},
                },
                "required": ["user_id", "template", "content"],
            },
            func=send_notification,
            writes=True,
        ),
        "get_park_announcement": ToolDef(
            name="get_park_announcement",
            description="查询园区公告(营业时间调整、政策提示等)。",
            parameters={"type": "object", "properties": {}, "required": []},
            func=get_park_announcement,
        ),
        "search_knowledge": ToolDef(
            name="search_knowledge",
            description="检索门票业务知识库(退改政策、票价规则、优惠说明等),返回最相关的若干条知识片段。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题,如\"改期要收手续费吗\""},
                    "top_k": {"type": "integer", "description": "返回条数,默认 3"},
                },
                "required": ["query"],
            },
            func=_make_search_knowledge(knowledge_retriever),
        ),
        "ask_user": ToolDef(
            name="ask_user",
            description="向用户追问缺失的关键信息(如订单号、日期)。信息不足时必须先追问,禁止猜测参数调用业务工具。",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要问用户的问题,一句话"},
                },
                "required": ["question"],
            },
            func=ask_user,
            meta=True,
        ),
    }


def execute_tool(
    conn: sqlite3.Connection,
    registry: dict[str, ToolDef],
    name: str,
    args: dict[str, Any],
) -> ToolResult:
    """统一执行入口:一切失败(未知工具/缺参/业务拒绝/内部异常)都返回
    ToolResult 而非抛出 —— 轨迹完整性优先,失败本身就是要被评测的行为。"""
    tool = registry.get(name)
    if tool is None:
        return ToolResult(ok=False, error=f"工具 {name} 不存在,可用工具:{'、'.join(registry)}")
    try:
        return tool.func(conn, **args)
    except ToolError as e:
        return ToolResult(ok=False, error=str(e))
    except TypeError as e:
        return ToolResult(ok=False, error=f"工具 {name} 参数错误:{e}")
    except Exception as e:  # 内部异常也落进轨迹,不打断 Agent 循环
        return ToolResult(ok=False, error=f"工具 {name} 内部错误:{type(e).__name__}: {e}")
