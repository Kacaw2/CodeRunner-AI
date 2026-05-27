"""Tests for the knowledge base (vector store) subsystem."""
import os
import shutil
import tempfile

import pytest


@pytest.fixture()
def kb(tmp_path):
    """Create a KnowledgeBase with an isolated temp directory."""
    from agent_host.knowledge_base import KnowledgeBase
    return KnowledgeBase(persist_dir=str(tmp_path / "kb"))


@pytest.fixture()
def seeded_kb(kb):
    """A KB pre-loaded with sample data."""
    kb.add_knowledge_point("loops", "A for loop iterates over a sequence.", "concept")
    kb.add_knowledge_point("recursion", "A function that calls itself to solve subproblems.", "concept")
    kb.add_error_pattern("IndexError", "list index out of range", "Accessing an index beyond the list length.")
    kb.add_error_pattern("TypeError", "unsupported operand type", "Mixing incompatible types in an expression.")
    return kb


class TestCollectionSetup:
    def test_cosine_distance_metric(self, kb):
        meta = kb.questions.metadata
        assert meta is not None
        assert meta.get("hnsw:space") == "cosine"

        meta_kp = kb.knowledge.metadata
        assert meta_kp.get("hnsw:space") == "cosine"

        meta_ep = kb.error_patterns.metadata
        assert meta_ep.get("hnsw:space") == "cosine"


class TestIndexAndSearch:
    def test_index_problem_and_search(self, kb):
        problem = type("Problem", (), {
            "id": 1,
            "title": "Two Sum",
            "description": "Given an array of integers, return indices of the two numbers that add up to a target.",
            "difficulty": "easy",
            "variants": [
                type("Q", (), {"programming_language": "python"})(),
                type("Q", (), {"programming_language": "c"})(),
            ],
        })()

        kb.index_problem(problem)
        assert kb.questions.count() == 1

        results = kb.search_similar_problems("find two numbers that sum to target", n=3)
        assert len(results) >= 1
        assert results[0]["title"] == "Two Sum"

    def test_similarity_score_range(self, kb):
        problem = type("Problem", (), {
            "id": 1,
            "title": "Fibonacci Sequence",
            "description": "Compute the nth Fibonacci number using dynamic programming.",
            "difficulty": "medium",
            "variants": [],
        })()
        kb.index_problem(problem)

        results = kb.search_similar_problems("fibonacci dynamic programming")
        assert len(results) >= 1
        for r in results:
            assert 0 <= r["similarity"] <= 1, f"similarity {r['similarity']} not in [0,1]"

    def test_dedup_threshold(self, kb):
        p1 = type("Problem", (), {
            "id": 1,
            "title": "Reverse a String",
            "description": "Write a function that reverses a given string.",
            "difficulty": "easy",
            "variants": [],
        })()
        p2 = type("Problem", (), {
            "id": 2,
            "title": "Reverse String",
            "description": "Given a string, return its reverse.",
            "difficulty": "easy",
            "variants": [],
        })()
        kb.index_problem(p1)
        kb.index_problem(p2)

        results = kb.search_similar_problems("reverse a string", n=5)
        high_sim = [r for r in results if r["similarity"] > 0.8]
        assert len(high_sim) >= 1, "Nearly identical problems should have similarity > 0.8"

    def test_problem_level_indexing_no_duplicates(self, kb):
        problem = type("Problem", (), {
            "id": 10,
            "title": "Binary Search",
            "description": "Implement binary search on a sorted array.",
            "difficulty": "medium",
            "variants": [
                type("Q", (), {"programming_language": "python"})(),
                type("Q", (), {"programming_language": "java"})(),
                type("Q", (), {"programming_language": "c"})(),
            ],
        })()
        kb.index_problem(problem)
        assert kb.questions.count() == 1


class TestKnowledgeSearch:
    def test_search_returns_structured_data(self, seeded_kb):
        results = seeded_kb.search_knowledge("for loop iteration", n=2)
        assert len(results) >= 1
        first = results[0]
        assert "content" in first
        assert "topic" in first
        assert "score" in first
        assert "distance" in first
        assert 0 <= first["score"] <= 1

    def test_search_empty_returns_empty(self, kb):
        results = kb.search_knowledge("anything")
        assert results == []


class TestErrorPatternSearch:
    def test_search_returns_structured_data(self, seeded_kb):
        results = seeded_kb.search_error_patterns("index out of range", n=2)
        assert len(results) >= 1
        first = results[0]
        assert "content" in first
        assert "error_type" in first
        assert "score" in first
        assert 0 <= first["score"] <= 1

    def test_search_empty_returns_empty(self, kb):
        results = kb.search_error_patterns("anything")
        assert results == []


class TestScopeIsolation:
    def test_global_scope_visible_to_all(self, kb):
        kb.add_knowledge_point("arrays", "Arrays store elements contiguously.", scope="global")
        results = kb.search_knowledge("arrays", scope_filter={"owner_id": 999})
        assert len(results) >= 1

    def test_teacher_scope_visible_to_owner(self, kb):
        kb.add_knowledge_point("private_topic", "Secret teaching material.", scope="teacher", owner_id=42)
        results = kb.search_knowledge("secret teaching", scope_filter={"owner_id": 42})
        assert len(results) >= 1

    def test_teacher_scope_hidden_from_others(self, kb):
        kb.add_knowledge_point("private_topic", "Secret teaching material.", scope="teacher", owner_id=42)
        kb.add_knowledge_point("public_topic", "Public knowledge.", scope="global")
        results = kb.search_knowledge("secret teaching", scope_filter={"owner_id": 999})
        visible_topics = [r["topic"] for r in results]
        assert "private_topic" not in visible_topics


class TestLowRelevanceFiltering:
    def test_tutor_filters_low_relevance(self, seeded_kb):
        results = seeded_kb.search_knowledge("completely unrelated quantum physics", n=2)
        from agent_host.agents.tutor import TutorAgent
        filtered = [r for r in results if r.get("score", 0) >= TutorAgent.MIN_KNOWLEDGE_SCORE]
        assert len(filtered) <= len(results)


class TestIndexAllProblems:
    def test_incremental_publish_indexes_problem_not_variant(self, app, db_session, teacher_user):
        from unittest.mock import MagicMock, patch
        from app.api.v1.ai import _publish_question_data_as_problem

        kb = MagicMock()
        question_data = {
            "title": "Array Sum",
            "description": "Sum all integers in an array.",
            "difficulty": "easy",
            "programming_language": "python",
            "solution": "print(sum(map(int, input().split())))",
            "test_cases": [
                {"input": "1 2 3", "expected_output": "6", "is_hidden": False},
            ],
        }

        with patch("agent_host.knowledge_base.get_knowledge_base", return_value=kb):
            problem, variant = _publish_question_data_as_problem(question_data, teacher_user.id)

        assert problem.id is not None
        assert variant.problem_id == problem.id
        kb.index_problem.assert_called_once_with(problem)
        assert not kb.index_question.called

    def test_legacy_index_question_method_is_removed(self):
        from agent_host.knowledge_base import KnowledgeBase

        assert not hasattr(KnowledgeBase, "index_question")

    def test_index_all_problems_function(self, app, db_session, tmp_path):
        from app.models.problem import Problem
        from agent_host import knowledge_base as kb_module

        p = Problem(slug="test-problem", title="Test Problem", description="A test.", difficulty="easy")
        db_session.add(p)
        db_session.flush()

        original_instance = kb_module._kb_instance
        try:
            kb_module._kb_instance = kb_module.KnowledgeBase(persist_dir=str(tmp_path / "kb2"))
            count = kb_module.index_all_problems()
            assert count >= 1
        finally:
            kb_module._kb_instance = original_instance
