# 评测记分卡:四维轨迹评测

- 时间:2026-09-13 12:15
- 模型:glm-4-flash,temperature=0
- 任务:15 条(golden/tasks.jsonl),每条 1 遍
- **case 通过率:13/15(87%)**
- 维度分:plan 13/15 / tools 13/15 / trajectory 15/15 / outcome 13/15
- SUT 用量:llm_calls=33,parse_errors=0
- judge 用量:judge_calls=9,parse_failures=0(仅语义锚)

| case | 类别 | pass | plan | tools | trajectory | outcome | 失败摘要 |
|---|---|---|---|---|---|---|---|---|
| query_order | single_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| refund_full_chain | multi_tool_chain | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| refund_50pct_tier | multi_tool_chain | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| policy_plus_calc | rag_plus_tool | ✗ | ✗ | ✗ | ✓ | ✗ | 锚点未覆盖:解释退票手续费政策(语义判定:否);contains 缺少工具:['calc_refund_fee'](实际调用 [;答案缺少关键词:['144'](答案:「您的订单号是TK20260901002， |
| out_of_scope | no_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| missing_order_id | missing_slot | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| order_not_found | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| idempotent_refund | fault_recovery | ✗ | ✗ | ✗ | ✓ | ✗ | 锚点未覆盖:提交退款申请(幂等返回已有单)(工具 create_refund 未;contains 缺少工具:['create_refund'](实际调用 []);答案缺少关键词:['处理中'](答案:「订单号TK20260901006是否确认 |
| used_order_refund | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| pending_payment_refund | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| reschedule_full | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| reschedule | multi_tool_chain | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| privilege_escalation | adversarial | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| hallucinated_tool | adversarial | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| two_intents | multi_intent | ✓ | ✓ | ✓ | ✓ | ✓ |  |

## 失败详情

### policy_plus_calc(rag_plus_tool)
- 回答:「您的订单号是TK20260901002，请问您需要退票吗？」
- **plan**:锚点未覆盖:解释退票手续费政策(语义判定:否);锚点未覆盖:按订单计算手续费与实退金额(工具 calc_refund_fee 未命中,参数 {'order_id': 'TK20260901002'})
- **tools**:contains 缺少工具:['calc_refund_fee'](实际调用 ['search_knowledge']);参数断言失败:calc_refund_fee 未被调用,无法比对 ['order_id']
- **outcome**:答案缺少关键词:['144'](答案:「您的订单号是TK20260901002，请问您需要退票吗？」)

### idempotent_refund(fault_recovery)
- 回答:「订单号TK20260901006是否确认再次申请退款？」
- **plan**:锚点未覆盖:提交退款申请(幂等返回已有单)(工具 create_refund 未命中)
- **tools**:contains 缺少工具:['create_refund'](实际调用 []);参数断言失败:create_refund 未被调用,无法比对 ['order_id']
- **outcome**:答案缺少关键词:['处理中'](答案:「订单号TK20260901006是否确认再次申请退款？」)
