"""Tests for RAG language filtering and owner isolation in search_similar_problems."""
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


class TestLanguageFilter:
    def test_language_filter_returns_only_matching_language(self, kb):
        kb.index_problem(_problem(1, "Py Sort", "Sort a list of integers.", langs=["python"]))
        kb.index_problem(_problem(2, "Java Sort", "Sort an array of integers.", langs=["java"]))

        py = kb.search_similar_problems("sort integers", n=5, language="python")
        assert {r["problem_id"] for r in py} == {1}

        java = kb.search_similar_problems("sort integers", n=5, language="java")
        assert {r["problem_id"] for r in java} == {2}

    def test_no_language_returns_all(self, kb):
        kb.index_problem(_problem(1, "Py Sort", "Sort a list of integers.", langs=["python"]))
        kb.index_problem(_problem(2, "Java Sort", "Sort an array of integers.", langs=["java"]))

        results = kb.search_similar_problems("sort integers", n=5)
        assert {r["problem_id"] for r in results} == {1, 2}


class TestOwnerIsolation:
    def test_owner_sees_own_and_public_but_not_others(self, kb):
        kb.index_problem(_problem(1, "Owner A Problem", "Compute a checksum value.", created_by=42))
        kb.index_problem(_problem(2, "Owner B Problem", "Compute a checksum digest.", created_by=99))
        kb.index_problem(_problem(3, "Public Problem", "Compute a checksum total.", created_by=0))

        visible = kb.search_similar_problems("checksum", n=5, owner_id=42)
        ids = {r["problem_id"] for r in visible}
        assert 1 in ids       # own
        assert 3 in ids       # public (created_by=0)
        assert 99 not in ids  # other owner's problem id never surfaces
        assert 2 not in ids   # owner B's problem hidden from owner A

    def test_no_owner_filter_sees_everything(self, kb):
        kb.index_problem(_problem(1, "Owner A Problem", "Compute a checksum value.", created_by=42))
        kb.index_problem(_problem(2, "Owner B Problem", "Compute a checksum digest.", created_by=99))

        visible = kb.search_similar_problems("checksum", n=5)
        assert {r["problem_id"] for r in visible} == {1, 2}
