"""
End-to-end test for Architect Agent workflow.

Tests the complete flow:
1. Analyze inventory
2. Generate proposals
3. Architect review
4. Apply decisions
"""

import os
import sys
from datetime import datetime

# Set auth
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = (
    '/mnt/e/A/storage_lifecycle_management/.gcp/service-account.json'
)

# Add parent to path
sys.path.insert(0, os.path.dirname(__file__))

from architect_agent_adk import (
    ArchitectWorkflow,
    start_architect_review,
)
from models_adk import Priority, ArchitectWorkflowRequest


def test_architect_workflow():
    """Test complete architect workflow."""
    print("\n" + "="*80)
    print("ARCHITECT AGENT - END-TO-END WORKFLOW TEST")
    print("="*80)
    print(f"Started: {datetime.utcnow().isoformat()}")

    project_id = "prismatic-smoke-463810-c1"

    # Test 1: Create workflow
    print("\n--- TEST 1: Create Workflow ---")
    try:
        workflow = ArchitectWorkflow(project_id)
        print(f"✓ Created workflow with:")
        print(f"  - InventoryAnalystAgent")
        print(f"  - ArchitectProposalAgent")
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False

    # Test 2: Analyze inventory
    print("\n--- TEST 2: Analyze Inventory ---")
    try:
        inventory_analysis = workflow.analyst.analyze_inventory()
        if inventory_analysis["status"] == "success":
            inventory = inventory_analysis["inventory"]
            print(f"✓ Loaded {inventory['total_objects']} objects")
            print(f"  Types: {inventory['total_objects']}")
        else:
            print(f"✗ Failed: {inventory_analysis.get('error')}")
            return False
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False

    # Test 3: Analyze critical dependencies
    print("\n--- TEST 3: Analyze Critical Dependencies ---")
    try:
        critical_analysis = workflow.analyst.analyze_critical_objects()
        if critical_analysis["status"] == "success":
            critical_paths = critical_analysis["critical_paths"]
            print(f"✓ Critical paths analysis:")
            print(f"  Total paths: {critical_paths['total_critical_paths']}")
        else:
            print(f"✗ Failed: {critical_analysis.get('error')}")
    except Exception as e:
        print(f"✗ Failed: {e}")

    # Test 4: Generate proposals
    print("\n--- TEST 4: Generate Improvement Proposals ---")
    try:
        proposals = workflow.analyst.generate_options()
        print(f"✓ Generated {len(proposals)} proposals")
        if proposals:
            for i, prop in enumerate(proposals[:3]):
                print(f"  {i+1}. {prop.get('title', 'Unknown')}")
                print(f"     Type: {prop.get('proposal_type')}")
                print(f"     Savings: ${prop.get('expected_cost_savings', 0)}/month")
    except Exception as e:
        print(f"✗ Failed: {e}")

    # Test 5: Prioritize proposals
    print("\n--- TEST 5: Prioritize Proposals ---")
    try:
        if proposals:
            ranked = workflow.analyst.recommend(proposals)
            if ranked["status"] == "success":
                print(f"✓ Ranked {ranked['total_proposals']} proposals")
                print(f"  Total potential savings: ${ranked['total_potential_savings']:.2f}/month")
                if ranked['top_recommendation']:
                    top = ranked['top_recommendation']
                    print(f"  Top: {top.get('title')}")
                    print(f"    ROI Score: {top.get('roi_score')}")
                    print(f"    Recommendation: {top.get('recommendation')}")
            else:
                print(f"✗ Failed: {ranked.get('error')}")
    except Exception as e:
        print(f"✗ Failed: {e}")

    # Test 6: Start full workflow
    print("\n--- TEST 6: Start Full Architect Workflow ---")
    try:
        request = ArchitectWorkflowRequest(
            workflow_id="WORKFLOW_TEST_001",
            architect_name="Test Architect",
            focus_priority=None,
            include_lineage=True,
            generate_proposals=True,
        )
        response = workflow.start_workflow(request)
        print(f"✓ Workflow completed")
        print(f"  Status: {response.status}")
        print(f"  Proposals: {len(response.proposals)}")
        print(f"  Reviews: {response.reviews_collected}")
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test 7: Apply architect decision
    print("\n--- TEST 7: Apply Architect Decision ---")
    try:
        if response.proposals:
            proposal = response.proposals[0]
            print(f"✓ Applying decision for: {proposal.title}")

            result = workflow.apply_architect_decision(
                object_id=proposal.object_id,
                priority=Priority.CRITICAL,
                architect_name="Test Architect",
                notes=f"Implemented via workflow: {proposal.title}",
            )

            if result["status"] == "success":
                print(f"✓ Applied successfully")
                print(f"  Object: {result['object_id']}")
                print(f"  Priority: {result['priority']}")
            else:
                print(f"⚠ Application status: {result.get('status')}")
    except Exception as e:
        print(f"⚠ Decision application: {e}")

    # Test 8: Using module-level function
    print("\n--- TEST 8: Module-Level API Function ---")
    try:
        response2 = start_architect_review(
            project_id=project_id,
            workflow_id="WORKFLOW_API_TEST",
            architect_name="API Architect",
        )
        print(f"✓ API workflow executed")
        print(f"  Status: {response2.status}")
        print(f"  Objects analyzed: {response2.inventory_summary.get('total_objects', 0)}")
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*80)
    print("✓ ARCHITECT WORKFLOW TEST COMPLETED")
    print("="*80)
    print(f"Completed: {datetime.utcnow().isoformat()}")
    return True


if __name__ == "__main__":
    success = test_architect_workflow()
    sys.exit(0 if success else 1)
