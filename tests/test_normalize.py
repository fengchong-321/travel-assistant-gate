"""normalize 契约测试:空白/句末标点不影响语义相等。"""

from travelgate.normalize import normalize, normalize_answer


class TestNormalize:
    def test_strips_all_whitespace(self):
        assert normalize("3 月 31 日") == "3月31日"

    def test_strips_fullwidth_space(self):
        assert normalize("退款　成功") == "退款成功"

    def test_strips_newlines_and_tabs(self):
        assert normalize("已为您\n办理\t退款") == "已为您办理退款"

    def test_empty_string(self):
        assert normalize("") == ""

    def test_keeps_inner_punctuation(self):
        # 只去空白;中间标点保留(语义部分)
        assert normalize("订单TK20260901001,已支付。") == "订单TK20260901001,已支付。"


class TestNormalizeAnswer:
    def test_trailing_fullwidth_period(self):
        assert normalize_answer("已为您退款 288 元。") == "已为您退款288元"

    def test_trailing_question_mark(self):
        assert normalize_answer("退款成功?") == "退款成功"

    def test_trailing_multiple_puncts(self):
        assert normalize_answer("退款成功!!") == "退款成功"

    def test_halfwidth_variants(self):
        for punct in "。．.!！?？;；,，":
            assert normalize_answer(f"成功{punct}") == "成功", punct

    def test_only_trailing_stripped(self):
        # 句中标点不去:只剥句末
        assert normalize_answer("好的,已退款。") == "好的,已退款"
