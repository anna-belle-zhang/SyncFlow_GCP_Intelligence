"""Tests to verify the backend cleanup was successful and no dependencies are broken."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


class TestBackendCleanupVerification:
    """Verify that unused files were successfully removed and no imports are broken."""

    @pytest.fixture
    def backend_dir(self) -> Path:
        """Get path to backend directory."""
        return Path(__file__).parent.parent

    def test_architect_agent_removed(self, backend_dir: Path) -> None:
        """Test that legacy architect_agent.py was removed."""
        legacy_file = backend_dir / "architect_agent.py"
        assert not legacy_file.exists(), f"Legacy {legacy_file} should have been removed"

    def test_architect_agent_smart_removed(self, backend_dir: Path) -> None:
        """Test that architect_agent_smart.py was removed."""
        smart_file = backend_dir / "architect_agent_smart.py"
        assert not smart_file.exists(), f"{smart_file} should have been removed"

    def test_architect_object_parser_removed(self, backend_dir: Path) -> None:
        """Test that architect_object_parser.py was removed."""
        parser_file = backend_dir / "architect_object_parser.py"
        assert not parser_file.exists(), f"{parser_file} should have been removed"

    def test_main_py_removed(self, backend_dir: Path) -> None:
        """Test that legacy main.py was removed."""
        main_file = backend_dir / "main.py"
        assert not main_file.exists(), f"{main_file} should have been removed"

    def test_orchestrator_stub_removed(self, backend_dir: Path) -> None:
        """Test that orchestration stub was removed."""
        orchestrator_file = backend_dir / "app" / "orchestration" / "orchestrator.py"
        # If app/orchestration exists but orchestrator.py doesn't, that's OK
        if orchestrator_file.parent.exists():
            assert (
                not orchestrator_file.exists()
            ), f"{orchestrator_file} should have been removed"

    def test_duplicate_inventory_tools_removed(self, backend_dir: Path) -> None:
        """Test that duplicate inventory_tools.py was removed from agents/tools."""
        duplicate_file = backend_dir / "agents" / "tools" / "inventory_tools.py"
        assert (
            not duplicate_file.exists()
        ), f"Duplicate {duplicate_file} should have been removed"

    def test_active_inventory_tools_exists(self, backend_dir: Path) -> None:
        """Test that active inventory_tools_standalone.py still exists."""
        active_file = backend_dir / "agents" / "tools" / "inventory_tools_standalone.py"
        assert (
            active_file.exists()
        ), f"Active {active_file} should exist (not removed)"

    def test_core_agent_files_exist(self, backend_dir: Path) -> None:
        """Test that core agent files still exist."""
        core_files = [
            backend_dir / "agents" / "architect_agent_adk.py",
            backend_dir / "agents" / "models_adk.py",
            backend_dir / "agents" / "architect_agent_gemini_enhanced.py",
        ]

        for file in core_files:
            assert file.exists(), f"Core agent file {file} should exist"

    def test_core_tool_files_exist(self, backend_dir: Path) -> None:
        """Test that core tool files still exist."""
        tool_files = [
            backend_dir / "agents" / "tools" / "inventory_tools_standalone.py",
            backend_dir / "agents" / "tools" / "lineage_tools_adk.py",
            backend_dir / "agents" / "tools" / "proposal_tools.py",
            backend_dir / "agents" / "tools" / "update_tools.py",
        ]

        for file in tool_files:
            assert file.exists(), f"Core tool file {file} should exist"

    def test_syncflow_server_can_import(self, backend_dir: Path) -> None:
        """Test that syncflow_server.py can be imported without errors."""
        try:
            from backend.syncflow_server import SyncFlowApp

            assert SyncFlowApp is not None
        except ImportError as e:
            pytest.fail(f"Failed to import SyncFlowApp: {e}")

    def test_bigquery_loader_can_import(self, backend_dir: Path) -> None:
        """Test that bigquery_loader.py can be imported."""
        try:
            from backend.bigquery_loader import BigQueryManager

            assert BigQueryManager is not None
        except ImportError as e:
            pytest.fail(f"Failed to import BigQueryManager: {e}")

    def test_models_refactored_correctly(self, backend_dir: Path) -> None:
        """Test that models.py is a minimal schema-only version."""
        models_file = backend_dir / "models.py"
        assert models_file.exists(), "models.py should exist"

        # Read and verify it's schema-focused
        with open(models_file) as f:
            content = f.read()

        # Should have schema definitions
        assert "SCHEMA" in content or "schema" in content.lower()

        # Should be relatively small (refactored from 260 lines to ~70)
        lines = content.count("\n")
        assert lines < 150, f"models.py should be <150 lines after refactoring, got {lines}"

    def test_gemini_agent_imports(self) -> None:
        """Test that Gemini agent can be imported."""
        try:
            from backend.agents.architect_agent_gemini_enhanced import (
                ArchitectAgentGeminiEnhanced,
            )

            assert ArchitectAgentGeminiEnhanced is not None
        except ImportError as e:
            pytest.fail(f"Failed to import ArchitectAgentGeminiEnhanced: {e}")

    def test_adk_agent_imports(self) -> None:
        """Test that ADK agent can be imported."""
        try:
            from backend.agents.architect_agent_adk import ArchitectWorkflow

            assert ArchitectWorkflow is not None
        except ImportError as e:
            pytest.fail(f"Failed to import ADK agent components: {e}")

    def test_test_files_reorganized(self, backend_dir: Path) -> None:
        """Test that test files were moved to proper locations."""
        test_files = [
            backend_dir / "tests" / "agents" / "test_architect_workflow.py",
            backend_dir / "tests" / "agents" / "tools" / "test_inventory_functions.py",
            backend_dir / "tests" / "agents" / "tools" / "test_inventory_tools.py",
            backend_dir / "tests" / "agents" / "tools" / "test_scd2_validation.py",
        ]

        for file in test_files:
            assert file.exists(), f"Test file {file} should exist in new location"

    def test_docs_reorganized(self, backend_dir: Path) -> None:
        """Test that documentation files were centralized."""
        doc_files = [
            backend_dir / "docs" / "agents" / "DESIGN_COMPARISON.md",
            backend_dir / "docs" / "agents" / "IMPLEMENTATION_SUMMARY.md",
            backend_dir / "docs" / "agents" / "TEST_RESULTS.md",
        ]

        for file in doc_files:
            assert file.exists(), f"Doc file {file} should exist in centralized location"

    def test_readme_kept_in_agents(self, backend_dir: Path) -> None:
        """Test that README.md is kept in agents/ for quick reference."""
        readme = backend_dir / "agents" / "README.md"
        assert readme.exists(), "README.md should be kept in agents/ for quick reference"

    def test_requirements_txt_has_google_genai(self, backend_dir: Path) -> None:
        """Test that google-genai dependency was added to requirements.txt."""
        requirements_file = backend_dir / "requirements.txt"
        assert requirements_file.exists(), "requirements.txt should exist"

        with open(requirements_file) as f:
            content = f.read()

        assert "google-genai" in content, "google-genai dependency should be in requirements.txt"

    def test_no_import_errors_in_syncflow_server(self) -> None:
        """Test that syncflow_server.py has no import errors after cleanup."""
        try:
            import backend.syncflow_server
            import importlib

            importlib.reload(backend.syncflow_server)
        except ImportError as e:
            pytest.fail(f"Import error in syncflow_server: {e}")

    def test_removed_imports_not_used(self) -> None:
        """Test that removed imports are not used elsewhere."""
        # These imports were removed from syncflow_server.py
        removed_imports = [
            "from datetime import timedelta",
            "from functools import lru_cache",
            "from flask import send_from_directory",
            "from google.oauth2 import service_account",
        ]

        try:
            with open(
                Path(__file__).parent.parent / "syncflow_server.py"
            ) as f:
                content = f.read()

            # Check that removed imports are not there
            for import_statement in removed_imports:
                assert (
                    import_statement not in content
                ), f"Removed import {import_statement} should not be in syncflow_server.py"
        except FileNotFoundError:
            pytest.skip("syncflow_server.py not found")

    def test_legacy_architect_agent_routes_removed(self) -> None:
        """Test that legacy architect agent routes were removed."""
        try:
            with open(
                Path(__file__).parent.parent / "syncflow_server.py"
            ) as f:
                content = f.read()

            # These routes should be removed
            removed_routes = [
                "/api/objects/<id>/architect-review",
                "/api/architect/priority-summary",
                "/api/architect/decommission-candidates",
                "/api/architect/critical-objects",
            ]

            for route in removed_routes:
                # The route path should not be in the server file
                # (unless it's mentioned in a comment/doc)
                lines = [
                    line
                    for line in content.split("\n")
                    if route in line and not line.strip().startswith("#")
                ]
                assert (
                    not lines
                ), f"Legacy route {route} should be removed from syncflow_server.py"
        except FileNotFoundError:
            pytest.skip("syncflow_server.py not found")

    def test_gemini_agent_initialization_in_syncflow(self) -> None:
        """Test that Gemini agent is initialized in SyncFlowApp."""
        try:
            with open(
                Path(__file__).parent.parent / "syncflow_server.py"
            ) as f:
                content = f.read()

            # Should have Gemini agent import and initialization
            assert (
                "ArchitectAgentGeminiEnhanced" in content
            ), "Gemini agent should be imported in syncflow_server.py"
            assert (
                "self.gemini_agent" in content
            ), "Gemini agent should be initialized in SyncFlowApp"
        except FileNotFoundError:
            pytest.skip("syncflow_server.py not found")

    def test_new_gemini_api_endpoint_exists(self) -> None:
        """Test that new Gemini API endpoint is registered."""
        try:
            with open(
                Path(__file__).parent.parent / "syncflow_server.py"
            ) as f:
                content = f.read()

            assert (
                "/api/v2/agents/architect-gemini" in content
            ), "Gemini API endpoint should be registered"
        except FileNotFoundError:
            pytest.skip("syncflow_server.py not found")


class TestImportIntegrity:
    """Test that all critical imports still work after cleanup."""

    def test_agent_toolkit_imports(self) -> None:
        """Test all agent-related imports work."""
        try:
            from backend.agents.architect_agent_adk import (
                InventoryAnalystAgent,
                ArchitectProposalAgent,
                ArchitectWorkflow,
            )
            from backend.agents.architect_agent_gemini_enhanced import ArchitectAgentGeminiEnhanced
            from backend.agents.models_adk import (
                ArchitectProposal,
                ProposalType,
                Priority,
            )
        except ImportError as e:
            pytest.fail(f"Agent toolkit import failed: {e}")

    def test_tool_imports(self) -> None:
        """Test all tool imports work."""
        try:
            from backend.agents.tools.inventory_tools_standalone import (
                load_gcp_inventory,
            )
            from backend.agents.tools.lineage_tools_adk import (
                analyze_lineage_upstream,
                analyze_lineage_downstream,
            )
            from backend.agents.tools.proposal_tools import (
                generate_optimization_proposal,
            )
            from backend.agents.tools.update_tools import update_object_priority
        except ImportError as e:
            pytest.fail(f"Tool imports failed: {e}")

    def test_server_imports(self) -> None:
        """Test server imports work."""
        try:
            from backend.syncflow_server import SyncFlowApp
            from backend.bigquery_loader import BigQueryManager
        except ImportError as e:
            pytest.fail(f"Server imports failed: {e}")

    def test_models_imports(self) -> None:
        """Test models imports work."""
        try:
            from backend.models import (
                ETLOBJECTSCD2_SCHEMA,
                ETLEDGES_SCHEMA,
                FACTLOG_SCHEMA,
                FACTBILLING_SCHEMA,
            )
        except ImportError as e:
            pytest.fail(f"Models imports failed: {e}")
