# ADK Architect Agent: Dual-Agent Communication Pattern

## Complete Workflow Diagram

```mermaid
graph TB
    subgraph Input["Input"]
        REQ["ArchitectWorkflowRequest<br/>workflow_id, focus_priority"]
    end

    subgraph Analyst["InventoryAnalystAgent<br/>(Read-Only Analysis)"]
        A1["Step 1: analyze_inventory<br/>Load objects & priorities"]
        A2["Step 2: analyze_critical_objects<br/>Extract dependency chains"]
        A3["Step 3: generate_options<br/>Create proposals"]
        A4["Step 4: recommend<br/>Rank by ROI & impact"]
    end

    subgraph AnalystTools["Analyst Tools"]
        T1["inventory_tools<br/>load_gcp_inventory<br/>get_unreviewed_objects<br/>analyze_dependencies"]
        T2["lineage_tools<br/>analyze_upstream<br/>analyze_downstream<br/>extract_critical_paths"]
        T3["proposal_tools<br/>generate_consolidation<br/>generate_optimization<br/>analyze_impact"]
    end

    subgraph DataModels["Data Models (Communication)"]
        M1["ArchitectProposal<br/>id, type, title<br/>description, status<br/>cost_savings, effort"]
        M2["ArchitectWorkflowResponse<br/>proposals[], status<br/>inventory_summary<br/>completed_at"]
    end

    subgraph Proposal["Architect Decision Point<br/>(Human Review)"]
        P1["Review Proposals<br/>Compare options<br/>Select preferred<br/>Provide feedback"]
    end

    subgraph Proposer["ArchitectProposalAgent<br/>(Write-Enabled Implementation)"]
        P2["Step 5: collect_review<br/>Record architect decision<br/>Priority, notes, architect_name"]
        P3["Step 6: implement_decision<br/>Apply changes to BigQuery"]
        P4["Step 7: create_audit_entry<br/>Log action with reasoning"]
    end

    subgraph ProposerTools["Proposer Tools"]
        T4["update_tools<br/>update_object_priority<br/>mark_for_decommission<br/>create_lineage_edge<br/>store_diagram"]
    end

    subgraph Database["BigQuery minietl"]
        DB1["etlobjectscd2<br/>Objects & Priorities"]
        DB2["architect_audit_log<br/>Decisions & Changes"]
        DB3["architect_diagrams<br/>Saved Diagrams"]
    end

    subgraph Output["Output"]
        OUT["ArchitectWorkflowResponse<br/>status=COMPLETED<br/>proposals_count<br/>audit_trail"]
    end

    REQ --> A1
    A1 --> A2
    A2 --> A3
    A3 --> A4

    A1 --> T1
    A2 --> T2
    A3 --> T3
    T1 --> M1
    T2 --> M1
    T3 --> M1

    A4 --> M2
    M2 --> P1

    P1 -->|Approve| P2
    P1 -->|Reject| P2

    P2 --> M1
    M1 --> P3

    P3 --> T4
    T4 --> DB1
    T4 --> DB2
    T4 --> DB3

    P4 --> DB2

    P3 --> OUT

    style Analyst fill:#FF6D00,stroke:#E65100,color:#fff
    style Proposer fill:#00BCD4,stroke:#006064,color:#fff
    style AnalystTools fill:#FFB74D,stroke:#F57F17,color:#000
    style ProposerTools fill:#4DD0E1,stroke:#00838F,color:#000
    style DataModels fill:#9C27B0,stroke:#6A1B9A,color:#fff
    style Proposal fill:#FFC107,stroke:#F57F17,color:#000
    style Database fill:#1E88E5,stroke:#0D47A1,color:#fff
```

## Agent Interaction Sequence Diagram

```mermaid
sequenceDiagram
    participant User as Architect User
    participant Workflow as ArchitectWorkflow
    participant Analyst as InventoryAnalystAgent
    participant Proposer as ArchitectProposalAgent
    participant BQ as BigQuery minietl

    User->>Workflow: start_workflow(request)

    Workflow->>Analyst: analyze_inventory()
    Analyst->>BQ: Query etlobjectscd2
    BQ-->>Analyst: Return objects
    Analyst-->>Workflow: inventory_analysis

    Workflow->>Analyst: analyze_critical_objects()
    Analyst->>BQ: Query lineage (etledges)
    BQ-->>Analyst: Return dependencies
    Analyst-->>Workflow: critical_paths

    Workflow->>Analyst: generate_options()
    Analyst->>Analyst: For each unreviewed object:<br/>Generate 3-5 proposals
    Analyst-->>Workflow: List[ArchitectProposal]

    Workflow->>Analyst: recommend()
    Analyst->>Analyst: Rank proposals by ROI
    Analyst-->>Workflow: ArchitectWorkflowResponse

    Workflow-->>User: Display ranked proposals

    User->>User: Review & select proposal

    User->>Workflow: apply_architect_decision()
    Workflow->>Proposer: implement_priority_assignment()
    Proposer->>Proposer: Record ArchitectReview
    Proposer->>BQ: UPDATE etlobjectscd2
    Proposer->>BQ: INSERT architect_audit_log
    BQ-->>Proposer: Success
    Proposer-->>Workflow: result
    Workflow-->>User: Decision applied ✓
```

## Data Flow Diagram

```mermaid
graph LR
    subgraph Input["Inventory Data"]
        I1["etlobjectscd2<br/>24 Active Objects"]
        I2["etledges<br/>Dependency Graph"]
    end

    subgraph Analysis["Analysis Phase<br/>(Analyst Agent)"]
        AN["1. Load inventory<br/>2. Extract dependencies<br/>3. Generate proposals<br/>4. Calculate impact<br/>5. Rank options"]
    end

    subgraph Proposals["Proposals<br/>(Data Model)"]
        P1["Consolidation<br/>Proposal"]
        P2["Optimization<br/>Proposal"]
        P3["Decommission<br/>Proposal"]
        P4["Enhancement<br/>Proposal"]
    end

    subgraph Review["Architect Review<br/>(Decision Point)"]
        R1["Human Review<br/>Select Preferred<br/>Approve/Reject<br/>Add Notes"]
    end

    subgraph Execution["Execution Phase<br/>(Proposer Agent)"]
        EX["6. Record decision<br/>7. Update priority<br/>8. Create edges<br/>9. Mark decommission<br/>10. Log audit trail"]
    end

    subgraph Output["Updated State"]
        O1["etlobjectscd2<br/>Updated priorities"]
        O2["architect_audit_log<br/>Decision history"]
        O3["architect_diagrams<br/>Generated diagrams"]
    end

    I1 --> AN
    I2 --> AN
    AN --> P1
    AN --> P2
    AN --> P3
    AN --> P4

    P1 --> R1
    P2 --> R1
    P3 --> R1
    P4 --> R1

    R1 -->|Approved| EX
    R1 -->|Rejected| AN

    EX --> O1
    EX --> O2
    EX --> O3

    style Analysis fill:#FF6D00,stroke:#E65100,color:#fff
    style Execution fill:#00BCD4,stroke:#006064,color:#fff
    style Review fill:#FFC107,stroke:#F57F17,color:#000
    style Input fill:#1E88E5,stroke:#0D47A1,color:#fff
    style Output fill:#4CAF50,stroke:#2E7D32,color:#fff
```

## Agent Responsibility Matrix

```mermaid
graph TB
    subgraph Analyst["InventoryAnalystAgent<br/>(Read-Only)"]
        A["✓ Inventory Analysis<br/>✓ Dependency Detection<br/>✓ Proposal Generation<br/>✓ Impact Analysis<br/>✓ Ranking & Prioritization<br/>✗ Database Writes<br/>✗ Decision Recording<br/>✗ Implementation"]
    end

    subgraph Proposer["ArchitectProposalAgent<br/>(Write-Enabled)"]
        P["✗ Analysis<br/>✗ Proposal Generation<br/>✓ Decision Presentation<br/>✓ Review Collection<br/>✓ Priority Assignment<br/>✓ Decommissioning<br/>✓ Audit Logging<br/>✓ Implementation"]
    end

    subgraph Tools["Shared Tool Libraries"]
        T1["inventory_tools_standalone.py"]
        T2["lineage_tools_adk.py"]
        T3["proposal_tools.py"]
        T4["update_tools.py"]
    end

    Analyst --> T1
    Analyst --> T2
    Analyst --> T3
    Proposer --> T4

    style Analyst fill:#FF6D00,stroke:#E65100,color:#fff
    style Proposer fill:#00BCD4,stroke:#006064,color:#fff
    style Tools fill:#9C27B0,stroke:#6A1B9A,color:#fff
```

## State Transition Diagram

```mermaid
stateDiagram-v2
    [*] --> INIT

    INIT: ArchitectWorkflowRequest
    INIT --> INVENTORY_LOADING: start_workflow()

    INVENTORY_LOADING: Load GCP objects<br/>InventoryAnalystAgent
    INVENTORY_LOADING --> DEPENDENCY_ANALYSIS: ✓ Objects loaded
    INVENTORY_LOADING --> FAILED: ✗ Load error

    DEPENDENCY_ANALYSIS: Extract critical paths<br/>InventoryAnalystAgent
    DEPENDENCY_ANALYSIS --> PROPOSAL_GEN: ✓ Dependencies extracted

    PROPOSAL_GEN: Generate 3-5 options<br/>InventoryAnalystAgent
    PROPOSAL_GEN --> PROPOSAL_RANKING: ✓ Options created

    PROPOSAL_RANKING: Prioritize proposals<br/>InventoryAnalystAgent
    PROPOSAL_RANKING --> ARCH_REVIEW: ✓ Ranked options

    ARCH_REVIEW: Return to architect<br/>ArchitectWorkflowResponse
    ARCH_REVIEW --> DECISION_PENDING: Waiting for human decision

    DECISION_PENDING: Human reviews proposals<br/>Selects preferred option
    DECISION_PENDING --> IMPLEMENTING: ✓ Decision approved
    DECISION_PENDING --> PROPOSAL_GEN: ✗ Rejected, regenerate

    IMPLEMENTING: ArchitectProposalAgent<br/>Update BigQuery
    IMPLEMENTING --> AUDIT_LOGGING: ✓ Changes applied

    AUDIT_LOGGING: Record decision<br/>architect_audit_log entry
    AUDIT_LOGGING --> COMPLETED: ✓ Audit trail recorded

    COMPLETED: ArchitectWorkflowResponse<br/>status=COMPLETED
    COMPLETED --> [*]

    FAILED --> [*]
```

## Complete Tool Interaction Map

```mermaid
graph TB
    subgraph Workflow["ArchitectWorkflow<br/>Orchestrator"]
        W["Coordinates both agents<br/>through complete workflow"]
    end

    subgraph Analyst["InventoryAnalystAgent"]
        A["analyze_inventory()<br/>analyze_critical_objects()<br/>generate_options()<br/>recommend()"]
    end

    subgraph AnalystTools["Analysis Tools"]
        T1["inventory_tools_standalone.py<br/>load_gcp_inventory()<br/>get_unreviewed_objects()<br/>get_priority_summary()<br/>analyze_object_dependencies()"]
        T2["lineage_tools_adk.py<br/>analyze_lineage_upstream()<br/>analyze_lineage_downstream()<br/>build_lineage_graph()<br/>extract_critical_paths()"]
        T3["proposal_tools.py<br/>generate_consolidation_proposal()<br/>generate_optimization_proposal()<br/>generate_decommission_proposal()<br/>analyze_proposal_impact()<br/>prioritize_proposals()"]
    end

    subgraph Proposer["ArchitectProposalAgent"]
        P["present_option()<br/>collect_review()<br/>implement_priority_assignment()<br/>implement_consolidation()<br/>implement_decommission()"]
    end

    subgraph ProposerTools["Implementation Tools"]
        T4["update_tools.py<br/>update_object_priority()<br/>create_lineage_edge()<br/>mark_for_decommission()<br/>store_architecture_diagram()<br/>get_latest_architecture_diagram()<br/>list_architecture_diagrams()"]
    end

    subgraph Database["BigQuery minietl"]
        DB1["etlobjectscd2<br/>(Read & Write)"]
        DB2["etledges<br/>(Read & Write)"]
        DB3["architect_audit_log<br/>(Write Only)"]
        DB4["architect_proposals<br/>(Write Only)"]
        DB5["architect_diagrams<br/>(Read & Write)"]
    end

    W --> A
    W --> P

    A --> T1
    A --> T2
    A --> T3

    P --> T4

    T1 --> DB1
    T1 --> DB2
    T2 --> DB2
    T3 --> DB4

    T4 --> DB1
    T4 --> DB2
    T4 --> DB3
    T4 --> DB5

    style Workflow fill:#6A1B9A,stroke:#4A148C,color:#fff
    style Analyst fill:#FF6D00,stroke:#E65100,color:#fff
    style Proposer fill:#00BCD4,stroke:#006064,color:#fff
    style AnalystTools fill:#FFB74D,stroke:#F57F17,color:#000
    style ProposerTools fill:#4DD0E1,stroke:#00838F,color:#000
    style Database fill:#1E88E5,stroke:#0D47A1,color:#fff
```

