"""知识检索测试:FakeEmbedder 确定性向量,检索逻辑全离线。"""

from pathlib import Path

from sut_agent.knowledge import KnowledgeBase, build_knowledge_base, load_chunks
from sut_agent.settings import get_settings

KB_DIR = Path(get_settings().kb_dir)


class FakeEmbedder:
    """确定性嵌入:文本命中词表的计数向量 —— 同义文本相似,检索可预期。"""

    VOCAB = ["退票", "手续费", "改期", "票价", "入园", "免票", "小时", "金额"]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(t.count(w)) for w in self.VOCAB] for t in texts]


class TestLoadChunks:
    def test_seed_docs_loaded_with_sections(self):
        chunks = load_chunks(KB_DIR)
        titles = {c.title for c in chunks}
        assert "手续费三档" in titles
        assert "改期规则" in titles
        sources = {c.source for c in chunks}
        assert "退票政策.md" in sources and "入园须知.md" in sources

    def test_chunk_carries_source_and_text(self):
        chunks = load_chunks(KB_DIR)
        target = next(c for c in chunks if c.title == "手续费三档")
        assert target.source == "退票政策.md"
        assert "48 小时" in target.text

    def test_empty_dir_yields_no_chunks(self, tmp_path: Path):
        assert load_chunks(tmp_path) == []


class TestSearch:
    def test_refund_query_hits_refund_policy_first(self):
        kb = build_knowledge_base(KB_DIR, FakeEmbedder())
        hits = kb.search("退票手续费怎么收", top_k=2)
        assert hits
        assert hits[0]["source"] == "退票政策.md"
        assert hits[0]["score"] > 0

    def test_top_k_respected(self):
        kb = build_knowledge_base(KB_DIR, FakeEmbedder())
        assert len(kb.search("票价", top_k=2)) <= 2

    def test_empty_kb_returns_empty(self):
        kb = KnowledgeBase([], FakeEmbedder())
        assert kb.search("任意", top_k=3) == []

    def test_hit_shape(self):
        kb = build_knowledge_base(KB_DIR, FakeEmbedder())
        hit = kb.search("改期要收费吗", top_k=1)[0]
        assert set(hit) == {"source", "title", "text", "score"}
