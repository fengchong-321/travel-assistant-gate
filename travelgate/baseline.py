"""基线读写与对比:eval-gated CI 的锚点。

基线 = 上一版被认可的指标快照。门禁的判定不是「这次多少分」,而是「比基线退了
多少」—— 绝对分数受 LLM 随机性影响,相对退化才是信号。tolerance(噪声带)由
多轮重跑量方差校准:必须大于方差带,否则门禁会拦截正常波动。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class BaselineMetrics(BaseModel):
    """进基线文件的指标子集:故意保持小而稳 —— 指标越多,噪声面越大。"""

    started_at: str
    sut_model: str
    pass_rate: float  # case 级(四维全部通过)通过率
    dimension_scores: dict[str, float] = Field(default_factory=dict)  # {"tools": 0.86, ...}
    per_category_pass_rate: dict[str, float] = Field(default_factory=dict)


def save_baseline(metrics: BaselineMetrics, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metrics.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_baseline(path: Path) -> BaselineMetrics:
    return BaselineMetrics.model_validate_json(path.read_text(encoding="utf-8"))


def diff_against_baseline(
    current: BaselineMetrics, baseline: BaselineMetrics, tolerance: float = 0.0
) -> list[str]:
    """返回退化项描述(空列表 = 无退化);gate 命令据此决定 exit code。

    对比三层:总体 pass_rate → 四维维度分(定位「哪一层坏了」)→ 分类别通过率。
    每条描述必须可定位:哪个指标、从多少到多少、降了几个点。
    """
    regressions: list[str] = []

    drop = baseline.pass_rate - current.pass_rate
    if drop > tolerance:
        regressions.append(
            f"总体 pass_rate {baseline.pass_rate:.4f} → {current.pass_rate:.4f}"
            f"(降 {drop * 100:.1f} 个点)"
        )

    for dim, base_score in baseline.dimension_scores.items():
        now = current.dimension_scores.get(dim)
        if now is None:
            regressions.append(f"维度 {dim} 在本次结果中消失(基线 {base_score:.4f})")
        elif base_score - now > tolerance:
            regressions.append(
                f"维度 {dim}:{base_score:.4f} → {now:.4f}(降 {(base_score - now) * 100:.1f} 个点)"
            )

    for cat, base_rate in baseline.per_category_pass_rate.items():
        now = current.per_category_pass_rate.get(cat)
        if now is None:
            regressions.append(f"类别 {cat} 在本次结果中消失(基线 {base_rate:.4f})")
        elif base_rate - now > tolerance:
            regressions.append(
                f"类别 {cat}:{base_rate:.4f} → {now:.4f}(降 {(base_rate - now) * 100:.1f} 个点)"
            )

    return regressions
