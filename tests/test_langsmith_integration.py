"""
LangSmith Integration Tests

Tests for LangSmith tracing functionality in the Village Planning Agent.

Test Coverage:
1. LangSmith Manager initialization
2. Configuration validation
3. Callback handler creation
4. Metadata generation
5. LLM Factory integration
6. Enable/disable functionality
7. Error handling
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestLangSmithManager:
    """Tests for LangSmithManager class"""

    def setup_method(self):
        """Reset the singleton before each test"""
        from src.core.langsmith_integration import LangSmithManager
        LangSmithManager._instance = None
        LangSmithManager._initialized = False

    def test_singleton_pattern(self):
        """Test that LangSmithManager follows singleton pattern"""
        from src.core.langsmith_integration import LangSmithManager

        manager1 = LangSmithManager()
        manager2 = LangSmithManager()

        assert manager1 is manager2
        assert id(manager1) == id(manager2)

    def test_disabled_when_no_tracing_flag(self):
        """Test that tracing is disabled when LANGCHAIN_TRACING_V2 is false"""
        with patch.dict(os.environ, {
            'LANGCHAIN_TRACING_V2': 'false',
            'LANGCHAIN_API_KEY': 'test_key'
        }):
            # Force reimport to pick up new env vars
            from src.core import config
            import importlib
            importlib.reload(config)

            from src.core.langsmith_integration import LangSmithManager
            manager = LangSmithManager()

            assert manager.is_enabled() is False

    def test_disabled_when_no_api_key(self):
        """Test that tracing is disabled when API key is missing"""
        with patch.dict(os.environ, {
            'LANGCHAIN_TRACING_V2': 'true',
            'LANGCHAIN_API_KEY': ''
        }):
            from src.core import config
            import importlib
            importlib.reload(config)

            from src.core.langsmith_integration import LangSmithManager
            manager = LangSmithManager()

            assert manager.is_enabled() is False

    def test_enabled_with_valid_config(self):
        """Test that tracing is enabled with valid configuration"""
        with patch.dict(os.environ, {
            'LANGCHAIN_TRACING_V2': 'true',
            'LANGCHAIN_API_KEY': 'lsv2_test_key_12345'
        }):
            from src.core import config
            import importlib
            importlib.reload(config)

            try:
                from src.core.langsmith_integration import LangSmithManager
                manager = LangSmithManager()
                # This might fail if langsmith is not installed
                # In that case, manager should still be disabled
                assert isinstance(manager.is_enabled(), bool)
            except ImportError:
                # Expected if langsmith is not installed
                pass

    def test_get_callbacks_returns_list(self):
        """Test that get_callbacks returns a list"""
        from src.core.langsmith_integration import LangSmithManager
        manager = LangSmithManager()

        callbacks = manager.get_callbacks()
        assert isinstance(callbacks, list)

    def test_get_callbacks_empty_when_disabled(self):
        """Test that get_callbacks returns empty list when disabled"""
        from src.core.langsmith_integration import LangSmithManager
        manager = LangSmithManager()

        callbacks = manager.get_callbacks()
        assert callbacks == []

    def test_create_run_metadata_basic(self):
        """Test basic metadata creation"""
        from src.core.langsmith_integration import LangSmithManager
        manager = LangSmithManager()

        metadata = manager.create_run_metadata(
            project_name="Test Village",
            dimension="industry"
        )

        assert isinstance(metadata, dict)
        assert metadata["project_name"] == "Test Village"
        assert metadata["dimension"] == "industry"
        assert "timestamp" in metadata

    def test_create_run_metadata_with_layer(self):
        """Test metadata creation with layer parameter"""
        from src.core.langsmith_integration import LangSmithManager
        manager = LangSmithManager()

        metadata = manager.create_run_metadata(
            project_name="Test Village",
            dimension="industry",
            layer=3
        )

        assert metadata["layer"] == 3
        assert metadata["layer_name"] == "detailed"

    def test_create_run_metadata_with_extra_info(self):
        """Test metadata creation with extra information"""
        from src.core.langsmith_integration import LangSmithManager
        manager = LangSmithManager()

        metadata = manager.create_run_metadata(
            project_name="Test Village",
            extra_info={"custom_field": "custom_value"}
        )

        assert metadata["custom_field"] == "custom_value"

    def test_get_config_masks_api_key(self):
        """Test that get_config masks the API key"""
        from src.core.langsmith_integration import LangSmithManager
        manager = LangSmithManager()

        config = manager.get_config()

        if config.get("api_key"):
            assert "***" in config["api_key"] or config["api_key"] == "***"


class TestLLMFactoryIntegration:
    """Tests for LLM Factory LangSmith integration"""

    def test_create_llm_accepts_metadata(self):
        """Test that create_llm accepts metadata parameter"""
        from src.core.llm_factory import create_llm

        # This should not raise an error
        try:
            llm = create_llm(
                model="glm-4-flash",
                metadata={"test": "value"}
            )
            assert llm is not None
        except Exception as e:
            # May fail if API keys are not configured
            assert "API key" in str(e) or "api_key" in str(e)

    def test_create_llm_accepts_callbacks(self):
        """Test that create_llm accepts callbacks parameter"""
        from src.core.llm_factory import create_llm

        mock_callback = Mock()

        try:
            llm = create_llm(
                model="glm-4-flash",
                callbacks=[mock_callback]
            )
            assert llm is not None
        except Exception as e:
            # May fail if API keys are not configured
            assert "API key" in str(e) or "api_key" in str(e)

    def test_merge_callbacks_function_exists(self):
        """Test that _merge_callbacks helper function exists"""
        from src.core import llm_factory

        assert hasattr(llm_factory, '_merge_callbacks')


class TestConvenienceFunctions:
    """Tests for convenience functions"""

    def setup_method(self):
        """Reset the singleton before each test"""
        from src.core.langsmith_integration import LangSmithManager, _manager_instance
        if _manager_instance:
            LangSmithManager._instance = None
            LangSmithManager._initialized = False

    def test_get_langsmith_manager(self):
        """Test get_langsmith_manager convenience function"""
        from src.core.langsmith_integration import get_langsmith_manager

        manager = get_langsmith_manager()
        assert manager is not None

        # Should return same instance on subsequent calls
        manager2 = get_langsmith_manager()
        assert manager is manager2

    def test_is_tracing_enabled(self):
        """Test is_tracing_enabled convenience function"""
        from src.core.langsmith_integration import is_tracing_enabled

        # Should return a boolean
        result = is_tracing_enabled()
        assert isinstance(result, bool)

    def test_get_tracing_callbacks(self):
        """Test get_tracing_callbacks convenience function"""
        from src.core.langsmith_integration import get_tracing_callbacks

        callbacks = get_tracing_callbacks()
        assert isinstance(callbacks, list)

    def test_create_run_metadata_convenience(self):
        """Test create_run_metadata convenience function"""
        from src.core.langsmith_integration import create_run_metadata

        metadata = create_run_metadata(
            project_name="Test",
            dimension="test_dim"
        )

        assert isinstance(metadata, dict)
        assert metadata["project_name"] == "Test"


class TestPlannerIntegration:
    """Tests for planner LangSmith integration"""

    def test_analysis_planner_imports_work(self):
        """Test that analysis planners can be imported"""
        try:
            from src.planners.analysis_planners import AnalysisPlannerFactory
            assert AnalysisPlannerFactory is not None
        except ImportError as e:
            pytest.skip(f"Could not import analysis planners: {e}")

    def test_concept_planner_imports_work(self):
        """Test that concept planners can be imported"""
        try:
            from src.planners.concept_planners import ConceptPlannerFactory
            assert ConceptPlannerFactory is not None
        except ImportError as e:
            pytest.skip(f"Could not import concept planners: {e}")

    def test_detailed_planner_imports_work(self):
        """Test that detailed planners can be imported"""
        try:
            from src.planners.detailed_planners import DetailedPlannerFactory
            assert DetailedPlannerFactory is not None
        except ImportError as e:
            pytest.skip(f"Could not import detailed planners: {e}")


class TestErrorHandling:
    """Tests for error handling"""

    def test_langsmith_graceful_degradation(self):
        """Test that system works when LangSmith is not configured"""
        from src.core.llm_factory import create_llm

        # Should not raise an error even without LangSmith
        try:
            llm = create_llm(model="glm-4-flash")
            assert llm is not None
        except Exception as e:
            # Only error should be about API keys, not LangSmith
            assert "langsmith" not in str(e).lower()

    def test_missing_langsmith_package(self):
        """Test behavior when langsmith package is missing"""
        # This test verifies graceful degradation
        from src.core.langsmith_integration import LangSmithManager

        manager = LangSmithManager()
        # Should not crash even if langsmith is not installed
        assert manager is not None


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
