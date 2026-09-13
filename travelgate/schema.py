"""轨迹与任务契约:评测平台的单一事实源。

Trajectory(执行侧)由平台定义、被测 Agent 遵守;AgentTaskCase(期望侧)
是 golden 任务的入库格式 —— 评分器、报告、基线全部消费这里的结构。
工具维评分 steps,过程维看 steps + hit_max_steps/asked_user,结果维消费
answer + world 终态快照(世界断言 DSL 亦定义于此,评分器按维度就绪)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

from .normalize import normalize


class ToolStep(BaseModel):
    """一次工具调用:名字、参数、结果。参数 diff 与 forbidden 判定的对象。"""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None


class Trajectory(BaseModel):
    """一次执行的完整轨迹:输入、步骤序列、最终回答、世界终态。"""

    user_id: str
    message: str
    steps: list[ToolStep] = Field(default_factory=list)
    answer: str = ""
    hit_max_steps: bool = False  # 步数熔断:过程维断言素材
    asked_user: bool = False  # 以追问收尾:missing_slot 场景判定素材
    world: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)  # model/latency 等运行信息


# ── 期望侧:golden 任务契约 ────────────────────────────────────────────────

Category = Literal[
    "single_tool",
    "multi_tool_chain",
    "rag_plus_tool",
    "no_tool",
    "missing_slot",
    "fault_recovery",
    "adversarial",
    "multi_intent",
]
CATEGORIES: tuple[str, ...] = get_args(Category)  # 单一事实源:Literal 派生

# missing_slot 场景的追问语义判定词(D4 实验结论:纯语义关键词,避开标点形态)
DEFAULT_CLARIFY_KEYWORDS = ("订单号", "多少", "哪", "吗", "请提供", "请告诉")


class ToolExpectation(BaseModel):
    """工具维期望:三档序列匹配 + forbidden 一票否决。

    - exact_seq:调用序列精确相等(空列表 = 期望零调用,no_tool 用)
    - set:去重后集合相等
    - contains:期望工具全部出现过(不要求顺序)
    - free:不评序列(失败路径的工具选择属于实现自由,底线是 forbidden 与世界断言)
    匹配口径:发生即算(失败调用也计入)—— 调了就是选择;防线兜底是世界断言。
    """

    mode: Literal["exact_seq", "set", "contains", "free"]
    tools: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class OrderConstraint(BaseModel):
    """过程维顺序约束:before 的首次调用必须早于 after 的首次调用。"""

    before: str
    after: str


class TrajectoryExpectation(BaseModel):
    """过程维期望:熔断/循环/追问/顺序的子检查开关。"""

    fuse: Literal["forbid", "allow"] = "forbid"  # 步数熔断即失败
    no_loop: bool = True  # 相同 (工具, 参数) 重复调用 = 循环
    clarify: Literal["off", "required"] = "off"  # 必须以追问收尾且零盲调写工具
    clarify_keywords: list[str] = Field(default_factory=list)  # 缺省用内置语义词表
    order: list[OrderConstraint] = Field(default_factory=list)


class WorldAssertion(BaseModel):
    """世界状态断言:对 world 终态快照的行级判定(验证世界,不验证文字)。

    - eq/ne:where 选行后断言 field 的值(金额/状态流转)
    - count:断言 where 选出的行数(幂等:重复申请后 refunds 仍只有 1 行)
    - exists:断言 where 选出的行存在/不存在(改期成功后通知已留痕)
    """

    table: str
    op: Literal["eq", "ne", "count", "exists"] = "eq"
    where: dict[str, Any] = Field(default_factory=dict)
    field: str | None = None
    value: Any = None


class PlanAnchor(BaseModel):
    """规划锚点:意图级步骤,工具命中即覆盖(零 LLM 成本)。

    tool 非空:轨迹中出现该工具调用(可选参数约束)即覆盖 —— 确定性判定;
    tool 为空:纯语义锚点,只能交给 PlanMatcher 语义判定(judge 用量因此
    被压到只剩语义锚,标注纪律:工具确定的步骤一律标工具锚)。
    """

    description: str
    tool: str | None = None
    args_match: dict[str, Any] = Field(default_factory=dict)


class ToolMeta(BaseModel):
    """工具元数据契约:由平台定义、SUT 从注册表导出。

    评分器不硬编码工具清单:元工具过滤(ask_user 不计入匹配)、写工具判定
    (缺槽位禁盲调、写操作任务必须有世界断言)全部消费这份元数据。
    """

    name: str
    writes: bool = False
    meta: bool = False


class AgentTaskCase(BaseModel):
    """一条 golden 任务:输入 + 四维期望。"""

    case_id: str
    category: Category
    user_id: str
    message: str
    repeats: int = 1  # pass^k:写操作/对抗类标注 3
    expected_tools: ToolExpectation
    expected_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    trajectory_expectation: TrajectoryExpectation = Field(default_factory=TrajectoryExpectation)
    plan_anchors: list[PlanAnchor] = Field(default_factory=list)
    answer_keywords: list[str] = Field(default_factory=list)
    answer_forbidden_keywords: list[str] = Field(default_factory=list)
    world_assertions: list[WorldAssertion] = Field(default_factory=list)


class DimensionResult(BaseModel):
    """单个维度的评分结果:passed + 可定位的失败原因。"""

    dimension: Literal["plan", "tools", "trajectory", "outcome"]
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    """case 级结果:四维 AND。报告与基线 diff 的消费单元。"""

    case_id: str
    category: str
    passed: bool
    dimensions: list[DimensionResult] = Field(default_factory=list)
    answer: str = ""  # 报告呈现用(截断由报告层负责)


# ── 入库校验:配套校验 + 批量报错(错进不了库)──────────────────────────

class TaskLoadError(Exception):
    """golden 任务集加载失败:一次收集全部错误,不挤牙膏。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} 个任务集校验错误:\n" + "\n".join(f"- {e}" for e in errors))


def validate_case(case: AgentTaskCase, known: dict[str, ToolMeta]) -> list[str]:
    """单条校验:字段合法性 + 类别配套 + 平台纪律,返回错误列表(空 = 通过)。"""
    errors: list[str] = []
    cid = case.case_id

    def err(msg: str) -> None:
        errors.append(f"[{cid}] {msg}")

    if not normalize(case.message):
        err("message 不能为空")
    if case.repeats < 1:
        err(f"repeats 必须 ≥ 1(实际 {case.repeats})")

    exp = case.expected_tools
    overlap = set(exp.tools) & set(exp.forbidden)
    if overlap:
        err(f"期望与 forbidden 工具重叠:{sorted(overlap)}")
    unknown = [t for t in exp.tools if t not in known]
    if unknown:
        err(f"期望了不存在的工具:{unknown}(可用:{sorted(known)})")
    unknown_args = [t for t in case.expected_args if t not in known]
    if unknown_args:
        err(f"expected_args 引用不存在的工具:{unknown_args}")
    if exp.mode == "free" and exp.tools:
        err("free 档不评序列,tools 应为空(forbidden 仍生效)")
    if exp.mode == "exact_seq" and len(set(exp.tools)) != len(exp.tools):
        err("exact_seq 档 tools 存在重复")

    for oc in case.trajectory_expectation.order:
        for role, tool in (("before", oc.before), ("after", oc.after)):
            if tool not in known:
                err(f"顺序约束 {oc.before}→{oc.after} 的 {role} 工具不存在:{tool}")

    for anchor in case.plan_anchors:
        if not normalize(anchor.description):
            err(f"规划锚点描述为空(工具 {anchor.tool})")
        elif anchor.tool is not None and anchor.tool not in known:
            err(f"规划锚点「{anchor.description}」的工具不存在:{anchor.tool}")

    write_tools = {n for n, m in known.items() if m.writes}
    if case.trajectory_expectation.clarify == "required":
        blind = set(exp.tools) & write_tools
        if blind:
            err(f"clarify=required 却期望写工具:{sorted(blind)}(缺槽位场景期望的是追问不是盲写)")

    # 类别配套校验:类别决定期望形态,形态背离类别 = 标注错误
    if case.category == "no_tool" and (exp.mode != "exact_seq" or exp.tools):
        err("no_tool 类必须 exact_seq 且 tools 为空(零调用)")
    if case.category == "missing_slot" and case.trajectory_expectation.clarify != "required":
        err("missing_slot 类必须 clarify=required")
    if case.category == "adversarial" and not exp.forbidden:
        err("adversarial 类必须声明 forbidden(一票否决锚点)")

    # 平台纪律:期望写操作成功的任务,必须带世界断言(说改了不算,库里改了才算)
    expects_write_success = bool(set(exp.tools) & write_tools)
    if expects_write_success and not case.world_assertions:
        err("期望写工具的任务必须带 world_assertions(写操作必须验证世界终态)")

    for i, wa in enumerate(case.world_assertions):
        if wa.op == "count":
            if wa.field is not None:
                err(f"world_assertions[{i}] count 断言不需要 field")
            if not isinstance(wa.value, int) or isinstance(wa.value, bool):
                err(f"world_assertions[{i}] count 断言 value 必须是整数")
        elif wa.field is None:
            err(f"world_assertions[{i}] {wa.op} 断言必须指定 field")

    return errors


def load_tasks(path: Path | str, known: dict[str, ToolMeta]) -> list[AgentTaskCase]:
    """加载 JSONL 任务集:解析 + 校验,全部错误一次抛出。"""
    path = Path(path)
    cases: list[AgentTaskCase] = []
    errors: list[str] = []
    seen: set[str] = set()

    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = AgentTaskCase.model_validate_json(line)
        except ValueError as e:
            errors.append(f"[行 {lineno}] JSON 解析失败:{str(e).splitlines()[0]}")
            continue
        if case.case_id in seen:
            errors.append(f"[{case.case_id}] case_id 重复")
            continue
        seen.add(case.case_id)
        cases.append(case)
        errors.extend(validate_case(case, known))

    if not cases and not errors:
        errors.append(f"任务集为空:{path}")
    if errors:
        raise TaskLoadError(errors)
    return cases

