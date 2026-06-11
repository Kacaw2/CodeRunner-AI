"""Tests for Model Router (Phase B) and Agent Definitions (Phase C)."""
from unittest.mock import patch, MagicMock

import pytest


# ── Model Router ────────────────────────────────────────────────


class TestModelTier:
    def test_tier_values(self):
        from ai.llm.tiers import ModelTier

        assert ModelTier.FAST.value == "fast"
        assert ModelTier.BALANCED.value == "balanced"
        assert ModelTier.STRONG.value == "strong"

    def test_tier_is_string_enum(self):
        from ai.llm.tiers import ModelTier

        assert isinstance(ModelTier.FAST, str)
        assert ModelTier.FAST == "fast"


class TestDeepSeekProvider:
    def test_supports_all_tiers(self):
        from ai.llm.tiers import ModelTier
        from ai.llm.providers.deepseek import DeepSeekProvider

        provider = DeepSeekProvider()
        for tier in ModelTier:
            assert provider.supports_tier(tier)

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    def test_get_llm_returns_chat_openai(self):
        from ai.llm.tiers import ModelTier
        from ai.llm.providers.deepseek import DeepSeekProvider

        provider = DeepSeekProvider()
        provider._api_key = "test-key"
        llm = provider.get_llm(ModelTier.FAST)
        assert llm is not None

    def test_get_llm_raises_without_api_key(self):
        from ai.llm.tiers import ModelTier
        from ai.llm.providers.deepseek import DeepSeekProvider
        from core.exceptions import ConfigError

        provider = DeepSeekProvider()
        provider._api_key = ""
        with pytest.raises(ConfigError):
            provider.get_llm(ModelTier.BALANCED)

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    def test_different_tiers_have_different_configs(self):
        from ai.llm.tiers import ModelTier
        from ai.llm.providers.deepseek import DeepSeekProvider

        provider = DeepSeekProvider()
        provider._api_key = "test-key"

        fast = provider.get_llm(ModelTier.FAST)
        strong = provider.get_llm(ModelTier.STRONG)

        assert fast.max_tokens != strong.max_tokens
        assert fast.temperature != strong.temperature


class TestModelRouter:
    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    def test_get_llm_default_balanced(self):
        from ai.llm.router import ModelRouter
        from ai.llm.tiers import ModelTier

        router = ModelRouter()
        llm = router.get_llm()
        assert llm is not None

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    def test_get_llm_specific_tier(self):
        from ai.llm.router import ModelRouter
        from ai.llm.tiers import ModelTier

        router = ModelRouter()
        llm = router.get_llm(ModelTier.STRONG)
        assert llm.max_tokens == 4096

    def test_provider_name(self):
        from ai.llm.router import ModelRouter

        router = ModelRouter()
        assert router.provider_name == "deepseek"

    def test_unsupported_tier_falls_back(self):
        from ai.llm.router import ModelRouter
        from ai.llm.tiers import ModelTier
        from ai.llm.providers.base import BaseProvider

        class FakeProvider(BaseProvider):
            name = "fake"

            def supports_tier(self, tier):
                return tier == ModelTier.BALANCED

            def get_llm(self, tier):
                return MagicMock(tier_used=tier)

        router = ModelRouter(provider=FakeProvider())
        result = router.get_llm(ModelTier.STRONG)
        assert result.tier_used == ModelTier.BALANCED


class TestAIConfigIntegration:
    @patch("ai.llm.get_model_router")
    def test_get_llm_delegates_to_router(self, mock_get_router):
        from ai.agents.config import AIConfig
        from ai.llm.tiers import ModelTier

        mock_instance = MagicMock()
        mock_get_router.return_value = mock_instance
        mock_instance.get_llm.return_value = MagicMock()

        AIConfig.get_llm(tier=ModelTier.FAST)
        mock_instance.get_llm.assert_called_once_with(ModelTier.FAST)

    @patch("ai.llm.get_model_router")
    def test_get_llm_default_tier_is_balanced(self, mock_get_router):
        from ai.agents.config import AIConfig
        from ai.llm.tiers import ModelTier

        mock_instance = MagicMock()
        mock_get_router.return_value = mock_instance
        mock_instance.get_llm.return_value = MagicMock()

        AIConfig.get_llm()
        mock_instance.get_llm.assert_called_once_with(ModelTier.BALANCED)


# ── Agent Definitions ───────────────────────────────────────────


class TestAgentDefinitions:
    def test_all_four_agents_defined(self):
        from core.definitions import AGENT_DEFINITIONS

        assert set(AGENT_DEFINITIONS.keys()) == {"tutor", "reviewer", "generator", "analytics"}

    def test_definition_fields_present(self):
        from core.definitions import AGENT_DEFINITIONS

        for name, defn in AGENT_DEFINITIONS.items():
            assert defn.name == name
            assert defn.description
            assert defn.default_model_tier is not None
            assert len(defn.allowed_roles) > 0
            assert len(defn.allowed_tools) > 0
            assert defn.risk_level in ("low", "medium", "high")

    def test_generator_is_teacher_admin_only(self):
        from core.definitions import AGENT_DEFINITIONS

        gen = AGENT_DEFINITIONS["generator"]
        assert "student" not in gen.allowed_roles
        assert "teacher" in gen.allowed_roles
        assert "admin" in gen.allowed_roles

    def test_tutor_allows_students(self):
        from core.definitions import AGENT_DEFINITIONS

        tutor = AGENT_DEFINITIONS["tutor"]
        assert "student" in tutor.allowed_roles

    def test_generator_is_high_risk(self):
        from core.definitions import AGENT_DEFINITIONS

        assert AGENT_DEFINITIONS["generator"].risk_level == "high"

    def test_tutor_is_low_risk(self):
        from core.definitions import AGENT_DEFINITIONS

        assert AGENT_DEFINITIONS["tutor"].risk_level == "low"


class TestCanRouteTo:
    def test_student_can_route_to_tutor(self):
        from core.definitions import can_route_to

        assert can_route_to("tutor", "student") is True

    def test_student_cannot_route_to_generator(self):
        from core.definitions import can_route_to

        assert can_route_to("generator", "student") is False

    def test_teacher_can_route_to_generator(self):
        from core.definitions import can_route_to

        assert can_route_to("generator", "teacher") is True

    def test_unknown_agent_returns_false(self):
        from core.definitions import can_route_to

        assert can_route_to("nonexistent", "student") is False


class TestAllowedToolsFor:
    def test_tutor_tools(self):
        from core.definitions import allowed_tools_for

        tools = allowed_tools_for("tutor")
        assert "coderunner.code.execute" in tools
        assert "coderunner.problem.get_detail" in tools
        assert "coderunner.knowledge.search" in tools

    def test_generator_tools(self):
        from core.definitions import allowed_tools_for

        tools = allowed_tools_for("generator")
        assert "coderunner.code.execute_internal" in tools
        assert "coderunner.knowledge.search_similar_problems" in tools
        assert "coderunner.submission.list_for_student" not in tools

    def test_unknown_agent_returns_empty(self):
        from core.definitions import allowed_tools_for

        assert allowed_tools_for("nonexistent") == ()


class TestModelTierOnAgents:
    def test_tutor_uses_balanced(self):
        from ai.agents.tutor.agent import TutorAgent
        from ai.llm.tiers import ModelTier

        assert TutorAgent.default_model_tier == ModelTier.BALANCED

    def test_reviewer_uses_balanced(self):
        from ai.agents.reviewer.agent import ReviewerAgent
        from ai.llm.tiers import ModelTier

        assert ReviewerAgent.default_model_tier == ModelTier.BALANCED

    def test_generator_uses_strong(self):
        from ai.agents.generator.agent import GeneratorAgent
        from ai.llm.tiers import ModelTier

        assert GeneratorAgent.default_model_tier == ModelTier.STRONG

    def test_analytics_uses_strong(self):
        from ai.agents.analytics.agent import AnalyticsAgent
        from ai.llm.tiers import ModelTier

        assert AnalyticsAgent.default_model_tier == ModelTier.STRONG


class TestDefinitionsConsistentWithAgents:
    """Verify that definitions match the actual agent class attributes."""

    def test_tiers_match(self):
        from core.definitions import AGENT_DEFINITIONS
        from ai.agents.tutor.agent import TutorAgent
        from ai.agents.reviewer.agent import ReviewerAgent
        from ai.agents.generator.agent import GeneratorAgent
        from ai.agents.analytics.agent import AnalyticsAgent

        agent_classes = {
            "tutor": TutorAgent,
            "reviewer": ReviewerAgent,
            "generator": GeneratorAgent,
            "analytics": AnalyticsAgent,
        }

        for name, defn in AGENT_DEFINITIONS.items():
            cls = agent_classes[name]
            assert defn.default_model_tier == cls.default_model_tier, (
                f"{name}: definition tier {defn.default_model_tier} != class tier {cls.default_model_tier}"
            )

    def test_names_match(self):
        from core.definitions import AGENT_DEFINITIONS
        from ai.agents.tutor.agent import TutorAgent
        from ai.agents.reviewer.agent import ReviewerAgent
        from ai.agents.generator.agent import GeneratorAgent
        from ai.agents.analytics.agent import AnalyticsAgent

        agent_classes = {
            "tutor": TutorAgent,
            "reviewer": ReviewerAgent,
            "generator": GeneratorAgent,
            "analytics": AnalyticsAgent,
        }

        for name, defn in AGENT_DEFINITIONS.items():
            cls = agent_classes[name]
            assert defn.name == cls.name

    def test_memory_policies_match(self):
        from core.definitions import AGENT_DEFINITIONS
        from ai.agents.tutor.agent import TutorAgent
        from ai.agents.reviewer.agent import ReviewerAgent
        from ai.agents.generator.agent import GeneratorAgent
        from ai.agents.analytics.agent import AnalyticsAgent

        agent_classes = {
            "tutor": TutorAgent,
            "reviewer": ReviewerAgent,
            "generator": GeneratorAgent,
            "analytics": AnalyticsAgent,
        }

        for name, defn in AGENT_DEFINITIONS.items():
            assert agent_classes[name].memory_policy == defn.memory_policy
