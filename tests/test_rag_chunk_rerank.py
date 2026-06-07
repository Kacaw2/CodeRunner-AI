"""Tests for chunk-level indexing, parent collapse, and rerank paths (on/off/fallback)."""
import pytest


@pytest.fixture()
def kb(tmp_path):
    from ai.knowledge.store import KnowledgeBase
    return KnowledgeBase(persist_dir=str(tmp_path / "kb"))


def _problem(pid, title, desc, langs=None, created_by=0):
    variants = [type("Q", (), {"programming_language": lg})() for lg in (langs or [])]
    return type("Problem", (), {
        "id": pid,
        "title": title,
        "description": desc,
        "difficulty": "easy",
        "created_by": created_by,
        "variants": variants,
    })()


class TestChunkingAndCollapse:
    def test_long_problem_splits_into_multiple_chunks(self, kb):
        from core.config import get_settings
        size = get_settings().RAG_CHUNK_SIZE
        long_desc = ("Implement an efficient algorithm. " * 60)  # well over chunk_size
        assert len(long_desc) > size
        kb.index_problem(_problem(1, "Big Problem", long_desc))
        # Multiple chunk rows stored under one parent.
        assert kb.questions.count() > 1

    def test_search_collapses_chunks_to_one_result_per_problem(self, kb):
        long_desc = ("Implement an efficient sorting algorithm. " * 60)
        kb.index_problem(_problem(1, "Big Sort Problem", long_desc))

        results = kb.search_similar_problems("sorting algorithm", n=5)
        pids = [r["problem_id"] for r in results]
        assert pids.count(1) == 1, "chunks of the same problem must collapse to one result"


class TestRerankPaths:
    def _candidates(self):
        return [
            {"problem_id": 1, "similarity": 0.50, "content": "alpha", "_distance": 0.50},
            {"problem_id": 2, "similarity": 0.90, "content": "beta", "_distance": 0.10},
            {"problem_id": 3, "similarity": 0.70, "content": "gamma", "_distance": 0.30},
        ]

    def test_rerank_disabled_returns_candidates_unchanged(self, kb, monkeypatch):
        from core.config import get_settings
        monkeypatch.setattr(get_settings(), "RAG_RERANK_ENABLED", False)
        cands = self._candidates()
        out = kb._rerank("query", cands)
        assert out is cands  # untouched, same object/order

    def test_rerank_enabled_reorders_by_reranker_score(self, kb, monkeypatch):
        from core.config import get_settings
        monkeypatch.setattr(get_settings(), "RAG_RERANK_ENABLED", True)

        class FakeReranker:
            # Invert similarity order: give the lowest-sim candidate the top score.
            def predict(self, pairs):
                return [1.0, 0.0, 0.5]  # for candidates 1,2,3 respectively

        kb._reranker = FakeReranker()
        out = kb._rerank("query", self._candidates())
        assert [c["problem_id"] for c in out] == [1, 3, 2]
        assert out[0]["rerank_score"] == 1.0

    def test_rerank_exception_falls_back_to_vector_similarity(self, kb, monkeypatch):
        from core.config import get_settings
        monkeypatch.setattr(get_settings(), "RAG_RERANK_ENABLED", True)

        class BrokenReranker:
            def predict(self, pairs):
                raise RuntimeError("model unavailable")

        kb._reranker = BrokenReranker()
        out = kb._rerank("query", self._candidates())
        # Fallback sorts by descending vector similarity: 2 (0.90), 3 (0.70), 1 (0.50)
        assert [c["problem_id"] for c in out] == [2, 3, 1]
