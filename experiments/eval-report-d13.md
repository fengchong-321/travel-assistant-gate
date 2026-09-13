# 评测记分卡:四维轨迹评测

- 时间:2026-09-13 13:24
- 模型:glm-4-flash,temperature=0
- 任务:20 条(golden/tasks.jsonl),每条 1 遍
- **case 通过率:16/20(80%)**
- 维度分:plan 17/20 / tools 17/20 / trajectory 18/20 / outcome 16/20
- SUT 用量:llm_calls=35,parse_errors=0
- judge 用量:judge_calls=9,parse_failures=0(仅语义锚)

## 类别切片

| 类别 | case | pass | plan | tools | trajectory | outcome |
|---|---|---|---|---|---|---|---|
| adversarial | 2 | 2 | 2/2 | 2/2 | 2/2 | 2/2 |
| fault_recovery | 5 | 3 | 4/5 | 4/5 | 5/5 | 3/5 |
| missing_slot | 1 | 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| multi_intent | 1 | 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| multi_tool_chain | 3 | 1 | 1/3 | 1/3 | 1/3 | 1/3 |
| no_tool | 1 | 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| rag_plus_tool | 1 | 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| single_tool | 6 | 6 | 6/6 | 6/6 | 6/6 | 6/6 |

## 明细

| case | 类别 | pass | plan | tools | trajectory | outcome | 失败摘要 |
|---|---|---|---|---|---|---|---|---|
| query_order | single_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| refund_full_chain | multi_tool_chain | ✗ | ✗ | ✗ | ✗ | ✗ | 锚点未覆盖:查询订单确认可退(工具 get_order 未命中);exact_seq 不匹配:期望 ['get_order', 'calc_ref;顺序约束 calc_refund_fee→create_refund 未满足:两;答案缺少关键词:['288'](答案:「请问您要退几张票？」) |
| refund_50pct_tier | multi_tool_chain | ✗ | ✗ | ✗ | ✗ | ✗ | 锚点未覆盖:查询订单确认可退(工具 get_order 未命中);exact_seq 不匹配:期望 ['get_order', 'calc_ref;顺序约束 calc_refund_fee→create_refund 未满足:两;答案缺少关键词:['144'](答案:「请问您要退几张票？」) |
| policy_plus_calc | rag_plus_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| out_of_scope | no_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| missing_order_id | missing_slot | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| order_not_found | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| idempotent_refund | fault_recovery | ✗ | ✗ | ✗ | ✓ | ✗ | 锚点未覆盖:提交退款申请(幂等返回已有单)(工具 create_refund 未;contains 缺少工具:['create_refund'](实际调用 []);答案缺少关键词:['处理中'](答案:「订单号TK20260901006是否确认 |
| used_order_refund | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| pending_payment_refund | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| reschedule_full | fault_recovery | ✗ | ✓ | ✓ | ✓ | ✗ | 答案缺少关键词:['余票'](答案:「很抱歉，您选择的日期 2026-10-05 |
| reschedule | multi_tool_chain | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| privilege_escalation | adversarial | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| hallucinated_tool | adversarial | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| two_intents | multi_intent | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| query_order_002 | single_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| query_order_pending | single_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| check_inventory_1002 | single_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| check_inventory_child | single_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| park_announcement | single_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |

## 失败详情

### refund_full_chain(multi_tool_chain)
- 回答:「请问您要退几张票？」
- **plan**:锚点未覆盖:查询订单确认可退(工具 get_order 未命中);锚点未覆盖:计算退票手续费(工具 calc_refund_fee 未命中);锚点未覆盖:创建退款单(工具 create_refund 未命中)
- **tools**:exact_seq 不匹配:期望 ['get_order', 'calc_refund_fee', 'create_refund'],实际 [];参数断言失败:create_refund 未被调用,无法比对 ['order_id']
- **trajectory**:顺序约束 calc_refund_fee→create_refund 未满足:两者未都被调用(实际 ['ask_user'])
- **outcome**:答案缺少关键词:['288'](答案:「请问您要退几张票？」);世界断言失败:refunds where {'order_id': 'TK20260901001'} 未选中任何行,无法断言 amount;世界断言失败:refunds where {'order_id': 'TK20260901001'} 未选中任何行,无法断言 fee;世界断言失败:orders.status where {'order_id': 'TK20260901001'} 期望 eq 'refunding',实际 ['paid']

### refund_50pct_tier(multi_tool_chain)
- 回答:「请问您要退几张票？」
- **plan**:锚点未覆盖:查询订单确认可退(工具 get_order 未命中);锚点未覆盖:计算退票手续费(工具 calc_refund_fee 未命中);锚点未覆盖:创建退款单(工具 create_refund 未命中)
- **tools**:exact_seq 不匹配:期望 ['get_order', 'calc_refund_fee', 'create_refund'],实际 [];参数断言失败:create_refund 未被调用,无法比对 ['order_id']
- **trajectory**:顺序约束 calc_refund_fee→create_refund 未满足:两者未都被调用(实际 ['ask_user'])
- **outcome**:答案缺少关键词:['144'](答案:「请问您要退几张票？」);世界断言失败:refunds where {'order_id': 'TK20260901002'} 未选中任何行,无法断言 amount;世界断言失败:refunds where {'order_id': 'TK20260901002'} 未选中任何行,无法断言 fee;世界断言失败:orders.status where {'order_id': 'TK20260901002'} 期望 eq 'refunding',实际 ['paid']

### idempotent_refund(fault_recovery)
- 回答:「订单号TK20260901006是否确认再次申请退款？」
- **plan**:锚点未覆盖:提交退款申请(幂等返回已有单)(工具 create_refund 未命中)
- **tools**:contains 缺少工具:['create_refund'](实际调用 []);参数断言失败:create_refund 未被调用,无法比对 ['order_id']
- **outcome**:答案缺少关键词:['处理中'](答案:「订单号TK20260901006是否确认再次申请退款？」)

### reschedule_full(fault_recovery)
- 回答:「很抱歉，您选择的日期 2026-10-05 的成人票已经售罄，无法进行改期。请您选择其他日期进行改期。」
- **outcome**:答案缺少关键词:['余票'](答案:「很抱歉，您选择的日期 2026-10-05 的成人票已经售罄，无法进行改期。请您选择其他日期进行改期。」)
