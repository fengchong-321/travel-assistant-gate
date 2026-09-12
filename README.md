# TravelAssistantGate

门票客服 Agent 的轨迹评测工具:**评测一次执行,而非一个回答。**

被测 Agent 会自主规划 —— 选工具、调工具、查知识库、编排多步任务。它的输出是
一段动作序列加上数据库的真实变更,所以只看"最终答案对不对"远远不够:答案对
不代表过程对,更不代表世界真的被正确地改了。本工具对一次执行做四维断言:

| 维度 | 断言什么 |
|------|---------|
| **Plan 规划** | 任务拆解是否覆盖关键步骤(工具锚点优先,LLM judge 仅语义兜底) |
| **Tool 工具** | 工具选择三档匹配(exact_seq / set / contains)+ 关键参数逐个 diff + forbidden 一票否决 |
| **Trajectory 过程** | 步数上限、循环检测、缺槽位必须追问、顺序约束、失败后诚实说明 |
| **Outcome 结果** | 答案关键词断言 + **世界状态断言**(SQLite 里退款单金额、状态流转、幂等) |

世界状态断言是核心差异:Agent 说「已退款 288 元」不算数,`refunds` 表里单建了、
金额对、订单状态流转了、幂等没破,才算 —— 验证世界,不验证文字。

## 命名

- 项目全称:**TravelAssistantGate**(旅游助手 Agent 的质量门禁)
- 仓库:`travel-assistant-gate`;包与 CLI 简称:`travelgate`

## 架构

```
travelgate/     评测工具:轨迹 schema / 四维评分器(纯函数)/ 匹配器 / 基线 / 报告 / CLI
sut_agent/      被测 Agent:门票客服(Planner + ReAct 循环 + 8 业务工具 + sqlite 世界)
golden/         任务集(JSONL golden set,git 版本管理)
tests/          平台自测(全离线,Fake 注入)
```

关键设计:**每次执行从种子重建独立 sqlite 世界 + 固定时钟**(2026-10-01)——
退票手续费档位完全确定、并发执行互不污染、行级断言可预期。这是轨迹评测
flakiness 控制的地基。

## 开发

```bash
uv sync                                  # 安装依赖
uv run pytest                            # 全离线单测
uv run ruff check .                      # lint
uv run mypy travelgate sut_agent         # 类型检查
```

## 路线

- [x] 仓库脚手架 + 归一化匹配契约 + 基线 diff + 世界状态模型(四表/种子/固定时钟)
- [x] 被测 Agent:工具层 + ReAct 循环 + RAG + FastAPI 服务;工具调用协议经
      [FC 稳定性实验](experiments/fc-stability-report.md)定为 function calling(10 任务 × 3 遍完成率 100%)
- [ ] 轨迹 schema + 四维评分器 + 任务集
- [ ] eval-gated CI:PR 触发评测子集,对比基线,退化即红
