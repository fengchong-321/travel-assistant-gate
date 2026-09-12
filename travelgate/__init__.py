"""TravelAssistantGate(包名 travelgate):门票客服 Agent 的轨迹多维评测工具。

评测一次执行,而非一个回答:被测 Agent 的输出是动作序列 + 数据库的真实变更,
本工具从规划、工具、过程、世界状态四个维度断言一次执行的正确性。
"""

__version__ = "0.1.0"
