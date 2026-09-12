"""baseline 读写与 diff 测试:门禁判定的单元基础。"""

from pathlib import Path

from travelgate.baseline import (
    BaselineMetrics,
    diff_against_baseline,
    load_baseline,
    save_baseline,
)


def make_metrics(**overrides: float | str | dict) -> BaselineMetrics:
    defaults: dict = {
        "started_at": "2026-10-01T10:00:00",
        "sut_model": "glm-4-flash",
        "pass_rate": 0.90,
        "dimension_scores": {"plan": 0.92, "tools": 0.88, "trajectory": 0.95, "outcome": 0.86},
        "per_category_pass_rate": {"single_tool": 1.0, "adversarial": 0.75},
    }
    defaults.update(overrides)
    return BaselineMetrics(**defaults)


class TestSaveLoad:
    def test_roundtrip(self, tmp_path: Path):
        path = tmp_path / "baselines" / "main.json"
        save_baseline(make_metrics(), path)
        assert load_baseline(path) == make_metrics()

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "a" / "b" / "main.json"
        assert save_baseline(make_metrics(), path).exists()


class TestDiff:
    def test_no_regression(self):
        assert diff_against_baseline(make_metrics(), make_metrics()) == []

    def test_overall_drop(self):
        current = make_metrics(pass_rate=0.85)
        regressions = diff_against_baseline(current, make_metrics())
        assert len(regressions) == 1
        assert "总体 pass_rate" in regressions[0]
        assert "5.0 个点" in regressions[0]

    def test_dimension_drop_locates_layer(self):
        dims = {"plan": 0.92, "tools": 0.58, "trajectory": 0.95, "outcome": 0.86}
        current = make_metrics(dimension_scores=dims)
        regressions = diff_against_baseline(current, make_metrics())
        assert len(regressions) == 1
        assert "维度 tools" in regressions[0]

    def test_category_drop(self):
        current = make_metrics(per_category_pass_rate={"single_tool": 1.0, "adversarial": 0.50})
        regressions = diff_against_baseline(current, make_metrics())
        assert len(regressions) == 1
        assert "类别 adversarial" in regressions[0]

    def test_disappeared_category(self):
        current = make_metrics(per_category_pass_rate={"single_tool": 1.0})
        regressions = diff_against_baseline(current, make_metrics())
        assert any("消失" in r for r in regressions)

    def test_disappeared_dimension(self):
        current = make_metrics(dimension_scores={"plan": 0.92})
        regressions = diff_against_baseline(current, make_metrics())
        assert len(regressions) == 3  # tools/trajectory/outcome 三个维度消失

    def test_tolerance_absorbs_noise(self):
        current = make_metrics(pass_rate=0.885)  # 降 1.5 个点
        assert diff_against_baseline(current, make_metrics(), tolerance=0.02) == []
        assert len(diff_against_baseline(current, make_metrics(), tolerance=0.0)) == 1
