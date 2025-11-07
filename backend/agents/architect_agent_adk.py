"""
ADK-based Architect Agent - Dual-agent system for GCP architecture optimization.

Two specialized agents:
1. InventoryAnalystAgent (read-only): Analyzes inventory and proposes options
2. ArchitectProposalAgent (write-enabled): Implements architect decisions

Workflow:
1. Analyst loads inventory and priorities
2. Analyst analyzes dependencies and identifies improvement opportunities
3. Analyst proposes 3-5 optimization options
4. Architect reviews and selects preferred option
5. Proposal agent implements changes
6. Audit trail records all decisions
"""

import json
import sys
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from uuid import uuid4

# Ensure parent agents directory is in path
agents_path = os.path.dirname(__file__)
sys.path.insert(0, agents_path)

from models_adk import (
    Priority,
    ProposalType,
    ProposalStatus,
    ArchitectProposal,
    ConsolidationProposal,
    OptimizationProposal,
    DecommissionProposal,
    ImpactAnalysis,
    ArchitectReview,
    ArchitectWorkflowRequest,
    ArchitectWorkflowResponse,
)

# Import tool modules (would use google.adk in production)
# Add tools directory to path
tools_path = os.path.join(os.path.dirname(__file__), 'tools')
sys.path.insert(0, tools_path)

from inventory_tools_standalone import (
    load_gcp_inventory,
    get_unreviewed_objects,
    get_priority_summary,
    analyze_object_dependencies,
)

from lineage_tools_adk import (
    analyze_lineage_upstream,
    analyze_lineage_downstream,
    build_lineage_graph,
    extract_critical_paths,
)

from proposal_tools import (
    generate_consolidation_proposal,
    generate_optimization_proposal,
    generate_decommission_proposal,
    analyze_proposal_impact,
    prioritize_proposals,
)

from update_tools import (
    update_object_priority,
    create_lineage_edge,
    mark_for_decommission,
    store_architecture_diagram,
    get_latest_architecture_diagram,
    list_architecture_diagrams,
)


class InventoryAnalystAgent:
    """
    Read-only agent that analyzes GCP inventory.

    Responsibilities:
    - Load and review current inventory
    - Analyze dependencies
    - Identify improvement opportunities
    - Generate optimization proposals
    """

    def __init__(self, project_id: str, dataset_id: str = "minietl"):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.name = "InventoryAnalystAgent"

    def analyze_inventory(self) -> Dict[str, Any]:
        """Load and analyze current GCP inventory."""
        print(f"\n[{self.name}] Analyzing GCP inventory...")

        # Load inventory
        inventory = load_gcp_inventory(self.project_id, self.dataset_id)
        if inventory["status"] != "success":
            return {"status": "error", "error": "Failed to load inventory"}

        # Get priority summary
        priority_summary = get_priority_summary(self.project_id, self.dataset_id)

        # Get unreviewed objects
        unreviewed = get_unreviewed_objects(self.project_id, self.dataset_id)

        print(f"✓ Loaded {inventory['total_objects']} objects")
        print(f"✓ {unreviewed['unreviewed_count']} objects need architect review")

        return {
            "status": "success",
            "inventory": inventory,
            "priority_summary": priority_summary,
            "unreviewed": unreviewed,
        }

    def analyze_critical_objects(self) -> Dict[str, Any]:
        """Identify critical objects and dependencies."""
        print(f"\n[{self.name}] Analyzing critical dependencies...")

        # Extract critical paths
        critical_paths = extract_critical_paths(self.project_id, self.dataset_id)

        print(f"✓ Found {critical_paths['total_critical_paths']} critical dependency chains")

        return {
            "status": "success",
            "critical_paths": critical_paths,
        }

    def generate_options(self, focus_priority: Optional[Priority] = None) -> List[Dict[str, Any]]:
        """Generate improvement options for architect review."""
        print(f"\n[{self.name}] Generating improvement options...")

        options = []

        # Get unreviewed objects
        unreviewed = get_unreviewed_objects(self.project_id, self.dataset_id)

        if unreviewed["status"] != "success":
            return []

        objects = unreviewed.get("objects", [])[:5]  # Top 5 for now

        for obj in objects:
            obj_id = obj["object_id"]

            # Option 1: Consolidation (if similar to other objects)
            if obj["downstream_dependencies"] == 0:
                consolidation = generate_consolidation_proposal(
                    self.project_id,
                    [obj_id],
                    f"consolidated-{obj['name']}",
                    f"Consolidate {obj['name']} with other unused objects",
                    self.dataset_id,
                )
                if consolidation["status"] == "success":
                    options.append(consolidation)

            # Option 2: Optimization
            opt_types = ["resource_sizing", "caching", "scheduling"]
            for opt_type in opt_types:
                optimization = generate_optimization_proposal(
                    self.project_id,
                    obj_id,
                    opt_type,
                    self.dataset_id,
                )
                if optimization["status"] == "success":
                    options.append(optimization)

            # Option 3: Decommission (if truly unused)
            if (
                obj["upstream_dependencies"] == 0
                and obj["downstream_dependencies"] == 0
            ):
                decommission = generate_decommission_proposal(
                    self.project_id,
                    obj_id,
                    "Object is unused and can be safely removed",
                    self.dataset_id,
                )
                if decommission["status"] == "success":
                    options.append(decommission)

        print(f"✓ Generated {len(options)} improvement options")
        return options

    def recommend(self, proposals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Recommend top options to architect."""
        print(f"\n[{self.name}] Prioritizing {len(proposals)} proposals...")

        if not proposals:
            return {"status": "error", "error": "No proposals to recommend"}

        ranked = prioritize_proposals(self.project_id, proposals, self.dataset_id)

        print(f"✓ Top recommendation: {ranked.get('top_recommendation', {}).get('title', 'N/A')}")

        return ranked


class ArchitectProposalAgent:
    """
    Write-enabled agent that implements architect decisions.

    Responsibilities:
    - Present options to architect
    - Collect architect feedback
    - Implement approved proposals
    - Maintain audit trail
    """

    def __init__(self, project_id: str, dataset_id: str = "minietl"):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.name = "ArchitectProposalAgent"
        self.decisions: List[ArchitectReview] = []

    def present_option(self, proposal: Dict[str, Any]) -> str:
        """Format proposal for architect review."""
        title = proposal.get("title", "Unknown Proposal")
        prop_type = proposal.get("proposal_type", "UNKNOWN")
        savings = proposal.get("expected_cost_savings", 0)
        effort = proposal.get("estimated_effort_hours", 0)

        summary = f"""
{title}
Type: {prop_type}
Expected Savings: ${savings}/month
Estimated Effort: {effort} hours
Risk Level: {proposal.get('risk_level', 'UNKNOWN')}
"""
        return summary

    def collect_review(
        self,
        object_id: str,
        priority: Priority,
        notes: str = "",
        architect_name: str = "system",
    ) -> ArchitectReview:
        """Record architect decision."""
        review = ArchitectReview(
            object_id=object_id,
            priority=priority,
            notes=notes,
            reviewed_by=architect_name,
        )
        self.decisions.append(review)
        return review

    def implement_priority_assignment(
        self,
        object_id: str,
        priority: str,
        architect_notes: str = "",
        architect_name: str = "system",
    ) -> Dict[str, Any]:
        """Implement priority assignment in BigQuery."""
        print(f"\n[{self.name}] Implementing priority assignment...")

        result = update_object_priority(
            self.project_id,
            object_id,
            priority,
            architect_notes,
            architect_name,
            self.dataset_id,
        )

        if result["status"] == "success":
            print(f"✓ Updated {object_id} to priority {priority}")
        else:
            print(f"✗ Failed to update {object_id}: {result['error']}")

        return result

    def implement_consolidation(
        self,
        source_objects: List[str],
        target_name: str,
    ) -> Dict[str, Any]:
        """Implement consolidation by creating new lineage edges."""
        print(f"\n[{self.name}] Implementing consolidation...")

        # Create edges from consolidation target to all dependents
        results = []
        for source_id in source_objects:
            # Mark source for decommission
            result = mark_for_decommission(
                self.project_id,
                source_id,
                f"Consolidated into {target_name}",
                dataset_id=self.dataset_id,
            )
            results.append(result)
            if result["status"] == "success":
                print(f"✓ Marked {source_id} for decommission")

        return {
            "status": "success" if all(r["status"] == "success" for r in results) else "partial",
            "consolidated_objects": source_objects,
            "results": results,
        }

    def implement_decommission(
        self,
        object_id: str,
        reason: str,
        replacement_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Implement decommission marking."""
        print(f"\n[{self.name}] Implementing decommission...")

        result = mark_for_decommission(
            self.project_id,
            object_id,
            reason,
            replacement_id=replacement_id,
            dataset_id=self.dataset_id,
        )

        if result["status"] == "success":
            print(f"✓ Marked {object_id} for decommission")
        else:
            print(f"✗ Failed: {result['error']}")

        return result


class ArchitectWorkflow:
    """
    Orchestrates the complete architect review and implementation workflow.

    Coordinates both agents through the decision-making process.
    """

    def __init__(self, project_id: str, dataset_id: str = "minietl"):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.analyst = InventoryAnalystAgent(project_id, dataset_id)
        self.proposal_agent = ArchitectProposalAgent(project_id, dataset_id)
        self.proposals: List[Dict[str, Any]] = []

    def start_workflow(self, request: ArchitectWorkflowRequest) -> ArchitectWorkflowResponse:
        """Start the architect workflow."""
        print(f"\n{'='*80}")
        print(f"ARCHITECT WORKFLOW - {request.workflow_id}")
        print(f"{'='*80}")

        response = ArchitectWorkflowResponse(
            workflow_id=request.workflow_id,
            status="IN_PROGRESS",
        )

        try:
            # Step 1: Analyze inventory
            print(f"\n[STEP 1] Analyzing GCP Inventory...")
            inventory_analysis = self.analyst.analyze_inventory()
            if inventory_analysis["status"] != "success":
                response.status = "FAILED"
                return response

            response.inventory_summary = inventory_analysis["inventory"]

            # Step 2: Analyze critical objects
            print(f"\n[STEP 2] Analyzing Critical Dependencies...")
            critical_analysis = self.analyst.analyze_critical_objects()

            # Step 3: Generate improvement options
            print(f"\n[STEP 3] Generating Improvement Options...")
            self.proposals = self.analyst.generate_options(request.focus_priority)

            if not self.proposals:
                print("No proposals generated")
            else:
                # Step 4: Prioritize options
                print(f"\n[STEP 4] Prioritizing Options...")
                ranked = self.analyst.recommend(self.proposals)
                response.proposals = self._format_proposals(self.proposals[:5])

            # Step 5: Simulate architect review
            print(f"\n[STEP 5] Simulating Architect Review...")
            if response.proposals:
                top_proposal = response.proposals[0]
                print(f"✓ Architect would review: {top_proposal.title}")
                response.reviews_collected = len(response.proposals)

            response.status = "COMPLETED"
            response.completed_at = datetime.utcnow()

        except Exception as e:
            print(f"✗ Error: {e}")
            response.status = "FAILED"

        return response

    def _format_proposals(self, proposals: List[Dict[str, Any]]) -> List[ArchitectProposal]:
        """Convert proposal dicts to ArchitectProposal objects."""
        formatted = []

        for prop in proposals[:5]:
            try:
                proposal = ArchitectProposal(
                    proposal_id=prop.get("proposal_id", f"PROP_{uuid4().hex[:8]}"),
                    object_id=prop.get("object_id", ""),
                    proposal_type=ProposalType(prop.get("proposal_type", "OPTIMIZATION")),
                    status=ProposalStatus.PRESENTED,
                    title=prop.get("title", ""),
                    description=prop.get("description", prop.get("rationale", "")),
                    rationale=prop.get("rationale", ""),
                    priority=Priority(prop.get("priority", "MEDIUM")),
                )
                formatted.append(proposal)
            except Exception as e:
                print(f"Warning: Could not format proposal: {e}")

        return formatted

    def apply_architect_decision(
        self,
        object_id: str,
        priority: Priority,
        architect_name: str = "system",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Apply architect's priority decision."""
        print(f"\n[APPLY DECISION] {object_id} -> {priority.value}")

        result = self.proposal_agent.implement_priority_assignment(
            object_id,
            priority.value,
            notes,
            architect_name,
        )

        return result

    def mark_object_for_decommission(
        self,
        object_id: str,
        reason: str,
        replacement_id: Optional[str] = None,
        architect_name: str = "system",
    ) -> Dict[str, Any]:
        """Mark an object for decommission using proposal agent tooling."""
        print(f"\n[DECOMMISSION] {object_id} -> Reason: {reason}")

        result = self.proposal_agent.implement_decommission(
            object_id=object_id,
            reason=reason or "Marked for decommission via workflow",
            replacement_id=replacement_id,
        )

        if result.get("status") == "success":
            self.proposal_agent.collect_review(
                object_id=object_id,
                priority=Priority.DECOMMISSION,
                notes=reason,
                architect_name=architect_name,
            )

        return result

    def generate_mermaid_diagram(
        self,
        object_id: str,
        *,
        include_scope: str = "both",
        store: bool = False,
        diagram_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a Mermaid diagram for the object's lineage and optionally persist it."""
        print(f"\n[DIAGRAM] Generating mermaid diagram for {object_id}")

        graph_result = build_lineage_graph(
            self.project_id,
            object_id,
            dataset_id=self.dataset_id,
            include_scope=include_scope,
        )

        if graph_result.get("status") != "success":
            return graph_result

        nodes = graph_result.get("nodes", [])
        edges = graph_result.get("edges", [])

        lines = ["flowchart TD"]
        for node in nodes:
            node_id = node["object_id"]
            safe_name = node.get("name", node_id).replace('"', '\\"')
            safe_type = node.get("object_type", "UNKNOWN").replace('"', '\\"')
            label = f"{safe_name}\\n{safe_type}"
            lines.append(f'{node_id}["{label}"]')

        target_node = next((n for n in nodes if n.get("is_target")), None)
        if target_node:
            lines.append(f'style {target_node["object_id"]} fill:#ffefd5,stroke:#ff8c00,stroke-width:2px')

        for edge in edges:
            source = edge["source"]
            target = edge["target"]
            edge_type = edge.get("type", "").replace('"', '\\"')
            if edge_type:
                lines.append(f'{source} -->|{edge_type}| {target}')
            else:
                lines.append(f"{source} --> {target}")

        diagram_text = "\n".join(lines)

        response: Dict[str, Any] = {
            "status": "success",
            "object_id": object_id,
            "diagram_format": "mermaid",
            "diagram_text": diagram_text,
            "node_count": graph_result.get("node_count", len(nodes)),
            "edge_count": graph_result.get("edge_count", len(edges)),
        }

        if store:
            store_result = store_architecture_diagram(
                project_id=self.project_id,
                object_id=object_id,
                diagram_text=diagram_text,
                diagram_format="mermaid",
                diagram_name=diagram_name,
                activate=True,
                dataset_id=self.dataset_id,
            )
            response["store_result"] = store_result
            if store_result.get("status") != "success":
                response["status"] = "partial"
        return response

    def store_custom_diagram(
        self,
        object_id: str,
        diagram_text: str,
        diagram_format: str = "mermaid",
        diagram_name: Optional[str] = None,
        activate: bool = True,
    ) -> Dict[str, Any]:
        """Persist a custom Mermaid diagram to BigQuery."""
        if not diagram_text or not diagram_text.strip():
            return {"status": "error", "error": "diagram_text required"}

        return store_architecture_diagram(
            project_id=self.project_id,
            object_id=object_id,
            diagram_text=diagram_text,
            diagram_format=diagram_format,
            diagram_name=diagram_name,
            activate=activate,
            dataset_id=self.dataset_id,
        )

    def get_latest_diagram(self, object_id: str) -> Dict[str, Any]:
        """Fetch the most recent active diagram for an object."""
        return get_latest_architecture_diagram(
            project_id=self.project_id,
            object_id=object_id,
            dataset_id=self.dataset_id,
        )

    def list_diagram_history(
        self,
        object_id: str,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """List diagram history for an object ordered newest first."""
        return list_architecture_diagrams(
            project_id=self.project_id,
            object_id=object_id,
            dataset_id=self.dataset_id,
            limit=limit,
        )


# Module-level functions for Flask API integration
def create_architect_workflow(project_id: str, dataset_id: str = "minietl") -> ArchitectWorkflow:
    """Factory function to create workflow."""
    return ArchitectWorkflow(project_id, dataset_id)


def start_architect_review(
    project_id: str,
    workflow_id: str,
    architect_name: Optional[str] = None,
    dataset_id: str = "minietl",
    focus_priority: Optional[Priority] = None,
    include_lineage: bool = True,
    generate_proposals: bool = True,
) -> ArchitectWorkflowResponse:
    """Start architect review workflow."""
    request = ArchitectWorkflowRequest(
        workflow_id=workflow_id,
        architect_name=architect_name or "system",
        focus_priority=focus_priority,
        include_lineage=include_lineage,
        generate_proposals=generate_proposals,
    )

    workflow = ArchitectWorkflow(project_id, dataset_id)
    return workflow.start_workflow(request)
