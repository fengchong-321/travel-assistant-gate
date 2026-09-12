"""知识检索(RAG):markdown 知识库 → 按标题切块 → 向量 → 余弦检索。

Embedder 是协议:真实实现走 embeddings API,测试注入确定性假实现,
检索逻辑本身全离线可测。引擎与工具层解耦 —— tools.search_knowledge
通过注入消费这里的检索函数,装配发生在 app 层。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class Chunk:
    source: str  # 所属文档文件名
    title: str  # 二级标题(无标题则文档主标题)
    text: str


def load_chunks(kb_dir: Path) -> list[Chunk]:
    """每篇 markdown 按 ## 二级标题切块;无二级标题则整篇一块。"""
    chunks: list[Chunk] = []
    for md in sorted(kb_dir.glob("*.md")):
        content = md.read_text(encoding="utf-8")
        m = re.match(r"^#\s+(.+)$", content, flags=re.M)
        doc_title = m.group(1).strip() if m else md.stem
        sections = re.split(r"(?m)^##\s+", content)
        for section in sections[1:]:  # 首段是主标题前的内容,跳过
            lines = section.splitlines()
            title = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            if body:
                text = f"{doc_title} {title}\n{body}"
                chunks.append(Chunk(source=md.name, title=title, text=text))
        if len(sections) == 1 and content.strip():
            chunks.append(Chunk(source=md.name, title=doc_title, text=content.strip()))
    return chunks


class ApiEmbedder:
    """真实实现:OpenAI 兼容 embeddings API。"""

    def __init__(self, settings: Any) -> None:
        from openai import OpenAI  # 在线依赖,延迟导入

        self._client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
        self._model = settings.embedding_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in resp.data]


class KnowledgeBase:
    def __init__(self, chunks: list[Chunk], embedder: Embedder):
        self.chunks = chunks
        self._embedder = embedder
        vectors = embedder.embed([c.text for c in chunks]) if chunks else []
        self._matrix = np.array(vectors, dtype=float) if vectors else np.zeros((0, 1))

    def search(self, query: str, top_k: int = 3) -> list[dict[str, str | float]]:
        if not self.chunks:
            return []
        qv = np.array(self._embedder.embed([query])[0], dtype=float)
        norms = np.linalg.norm(self._matrix, axis=1) * np.linalg.norm(qv)
        sims = (self._matrix @ qv) / np.where(norms == 0, 1e-12, norms)
        order = np.argsort(-sims)[: top_k]
        return [
            {
                "source": self.chunks[i].source,
                "title": self.chunks[i].title,
                "text": self.chunks[i].text,
                "score": round(float(sims[i]), 4),
            }
            for i in order
        ]


def build_knowledge_base(kb_dir: Path, embedder: Embedder) -> KnowledgeBase:
    return KnowledgeBase(load_chunks(kb_dir), embedder)
