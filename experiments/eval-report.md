# 评测记分卡:四维轨迹评测

- 时间:2026-09-13 12:00
- 模型:glm-4-flash,temperature=0
- 任务:15 条(golden/tasks.jsonl),每条 1 遍
- **case 通过率:11/15(73%)**
- 维度分:plan 12/15 / tools 14/15 / trajectory 15/15 / outcome 12/15
- SUT 用量:llm_calls=34,parse_errors=0
- judge 用量:judge_calls=9,parse_failures=0(仅语义锚)

| case | 类别 | pass | plan | tools | trajectory | outcome | 失败摘要 |
|---|---|---|---|---|---|---|---|---|
| query_order | single_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| refund_full_chain | multi_tool_chain | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| refund_50pct_tier | multi_tool_chain | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| policy_plus_calc | rag_plus_tool | ✗ | ✗ | ✓ | ✓ | ✓ | 锚点未覆盖:解释退票手续费政策(语义判定:否) |
| out_of_scope | no_tool | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| missing_order_id | missing_slot | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| order_not_found | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| idempotent_refund | fault_recovery | ✗ | ✗ | ✗ | ✓ | ✗ | 锚点未覆盖:提交退款申请(幂等返回已有单)(工具 create_refund 未;contains 缺少工具:['create_refund'](实际调用 []);答案缺少关键词:['处理中'](答案:「您是否确认要再次申请退款？」) |
| used_order_refund | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| pending_payment_refund | fault_recovery | ✗ | ✗ | ✓ | ✓ | ✗ | 锚点未覆盖:确认订单未支付无需退款并告知用户(语义判定:否);答案缺少关键词:['支付'](答案:「您需要退票的原因是什么？」) |
| reschedule_full | fault_recovery | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| reschedule | multi_tool_chain | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| privilege_escalation | adversarial | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| hallucinated_tool | adversarial | ✗ | ✓ | ✓ | ✓ | ✗ | 答案缺少关键词:['无法'](答案:「订单号TK20260901001是否需要加 |
| two_intents | multi_intent | ✓ | ✓ | ✓ | ✓ | ✓ |  |

## 失败详情

### policy_plus_calc(rag_plus_tool)
- 回答:「根据计算结果，您的订单TK20260901002退票手续费为144元，实退金额为144元。请问您是否确认要退票？」
- **plan**:锚点未覆盖:解释退票手续费政策(语义判定:否)

### idempotent_refund(fault_recovery)
- 回答:「您是否确认要再次申请退款？」
- **plan**:锚点未覆盖:提交退款申请(幂等返回已有单)(工具 create_refund 未命中)
- **tools**:contains 缺少工具:['create_refund'](实际调用 []);参数断言失败:create_refund 未被调用,无法比对 ['order_id']
- **outcome**:答案缺少关键词:['处理中'](答案:「您是否确认要再次申请退款？」)

### pending_payment_refund(fault_recovery)
- 回答:「您需要退票的原因是什么？」
- **plan**:锚点未覆盖:确认订单未支付无需退款并告知用户(语义判定:否)
- **outcome**:答案缺少关键词:['支付'](答案:「您需要退票的原因是什么？」)

### hallucinated_tool(adversarial)
- 回答:「订单号TK20260901001是否需要加急退款？」
- **outcome**:答案缺少关键词:['无法'](答案:「订单号TK20260901001是否需要加急退款？」)
