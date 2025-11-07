# Architect Agent: ADK vs. Legacy Design Comparison

## Executive Summary

**Legacy `architect_agent.py`**: Monolithic, synchronous, single-class design
- ✅ Works with existing BigQuery setup
- ✅ Simple, single responsibility class
- ❌ Not truly "agentic" - architect does all work
- ❌ No external tool integration
- ❌ Limited to in-memory proposal store

**New ADK-based `architect_agent_adk.py`**: Dual-agent, asynchronous, tool-based design
- ✅ True agentic behavior (agents have specialized roles)
- ✅ Google ADK integration (@agent_tool decorator)
- ✅ Composable, reusable tools
- ✅ Production-ready architecture
- ✅ Scalable to handle complex workflows
- ⚠️ Requires BigQuery schema extensions

---

## Architecture Comparison

### Legacy Design

```
┌─────────────────────────────────────────┐
│      ArchitectAgent (Monolithic)        │
├─────────────────────────────────────────┤
│ • load_inventory()                      │
│ • get_critical_high_summary()           │
│ • propose_priority_changes()            │
│ • architect_approves()                  │
│ • architect_modifies()                  │
│ • _update_scd2_with_review()            │
│ • _collect_metrics()                    │
│ • _fetch_unreviewed_objects()           │
└─────────────────────────────────────────┘
         ↓ BigQuery ↓
┌─────────────────────────────────────────┐
│      BigQuery (etlobjectscd2, etc.)     │
└─────────────────────────────────────────┘
```

**Flow**:
1. Single `ArchitectAgent` class handles all operations
2. Architect (human) calls methods directly
3. Results stored in in-memory `_proposal_store`
4. Decisions persisted to BigQuery in SCD2 format

**Key Characteristics**:
- Single point of control
- Synchronous execution
- Direct BigQuery manipulation
- No tool abstraction

### ADK-Based Design

```
┌──────────────────────────────────────────────────────────────┐
│              ArchitectWorkflow (Orchestrator)                │
├──────────────────────────────────────────────────────────────┤
│  • start_workflow()                                          │
│  • apply_architect_decision()                                │
│  • _format_proposals()                                       │
└──────────────────────────────────────────────────────────────┘
    ↓                                             ↓
┌─────────────────────────────┐  ┌────────────────────────────────┐
│ InventoryAnalystAgent       │  │ ArchitectProposalAgent         │
│ (Read-Only)                 │  │ (Write-Enabled)                │
├─────────────────────────────┤  ├────────────────────────────────┤
│ • analyze_inventory()       │  │ • present_option()             │
│ • analyze_critical_objects()│  │ • collect_review()             │
│ • generate_options()        │  │ • implement_*()                │
│ • recommend()               │  │   - priority_assignment()      │
└─────────────────────────────┘  │   - consolidation()            │
              ↓                    │   - decommission()             │
        ┌─────────────────┐        └────────────────────────────────┘
        │  Inventory      │                    ↓
        │  Tools (6)      │            ┌──────────────────┐
        ├─────────────────┤            │  Update Tools (3)│
        │ load_gcp_       │            ├──────────────────┤
        │ inventory()     │            │ update_object_   │
        │ get_unreviewed_ │            │ priority()       │
        │ objects()       │            │ create_lineage_  │
        │ get_priority_   │            │ edge()           │
        │ summary()       │            │ mark_for_        │
        │ find_objects_   │            │ decommission()   │
        │ by_pattern()    │            └──────────────────┘
        │ analyze_object_ │                    ↓
        │ dependencies()  │        ┌──────────────────────┐
        │ find_critical_  │        │  BigQuery (SCD2)     │
        │ dependency_     │        │  etlobjectscd2       │
        │ chains()        │        │  etledges            │
        └─────────────────┘        │  architect_proposals │
                ↓                   │  architect_audit_log │
        ┌─────────────────┐         └──────────────────────┘
        │  Lineage        │
        │  Tools (4)      │
        ├─────────────────┤
        │ analyze_lineage_│
        │ upstream()      │
        │ analyze_lineage_│
        │ downstream()    │
        │ build_lineage_  │
        │ graph()         │
        │ extract_        │
        │ critical_paths()│
        └─────────────────┘
              ↓
        ┌─────────────────┐
        │  Proposal       │
        │  Tools (5)      │
        ├─────────────────┤
        │ generate_       │
        │ consolidation_  │
        │ proposal()      │
        │ generate_       │
        │ optimization_   │
        │ proposal()      │
        │ generate_       │
        │ decommission_   │
        │ proposal()      │
        │ analyze_        │
        │ proposal_       │
        │ impact()        │
        │ prioritize_     │
        │ proposals()     │
        └─────────────────┘
              ↓
        ┌─────────────────┐
        │  BigQuery       │
        │  (minietl)      │
        │  etlobjectscd2  │
        │  etledges       │
        └─────────────────┘
```

**Flow**:
1. `ArchitectWorkflow` orchestrates two specialized agents
2. `InventoryAnalystAgent` analyzes and generates proposals (read-only)
3. `ArchitectProposalAgent` implements decisions (write-enabled)
4. Tools are @agent_tool decorated functions - composable and reusable
5. Results persisted to BigQuery with full audit trail

**Key Characteristics**:
- Two specialized agents with clear roles
- Composable tool architecture
- Separation of analysis (read) from implementation (write)
- Audit logging for all decisions
- Google ADK integration ready

---

## Side-by-Side Feature Comparison

| Feature | Legacy | ADK-Based |
|---------|--------|-----------|
| **Architecture** | Monolithic | Dual-agent |
| **Number of Tools** | ~8 methods | 18 composable tools |
| **Separation of Concerns** | Single class | Two agents |
| **Read/Write Separation** | Mixed | Clear separation |
| **Tool Integration** | Direct calls | @agent_tool decorator |
| **Google ADK Ready** | No | ✅ Yes |
| **Audit Trail** | Via SCD2 only | Full audit table |
| **Proposal Storage** | In-memory dict | BigQuery table |
| **Dependency Analysis** | Limited | 4 recursive CTE tools |
| **Cost Analysis** | Via metrics | Proposal impact tools |
| **Error Handling** | Basic try/catch | Comprehensive |
| **Logging** | Logger instance | Print + audit logs |
| **Testing** | Manual | Structured E2E tests |
| **Scalability** | Single object | Batch operations |
| **Extension** | Add methods | Add new @agent_tool |

---

## 18 Specialized Tools (vs. 8 Methods)

### Inventory Tools (6)
1. `load_gcp_inventory()` - Full object registry
2. `get_unreviewed_objects()` - Prioritization queue
3. `get_priority_summary()` - Current distribution
4. `find_objects_by_pattern()` - Search capability
5. `analyze_object_dependencies()` - Dependency analysis
6. `find_critical_dependency_chains()` - Impact identification

### Lineage Tools (4)
7. `analyze_lineage_upstream()` - Recursive upstream
8. `analyze_lineage_downstream()` - Recursive downstream
9. `build_lineage_graph()` - Complete graph
10. `extract_critical_paths()` - Path analysis

### Proposal Tools (5)
11. `generate_consolidation_proposal()` - Consolidation options
12. `generate_optimization_proposal()` - Optimization options
13. `generate_decommission_proposal()` - Decommission options
14. `analyze_proposal_impact()` - Impact calculation
15. `prioritize_proposals()` - ROI ranking

### Update Tools (3)
16. `update_object_priority()` - Priority assignment
17. `create_lineage_edge()` - Relationship creation
18. `mark_for_decommission()` - Decommission marking

---

## Key Differences in Operation

### 1. **Proposal Generation**

**Legacy**:
```python
proposals = architect_agent.propose_priority_changes()
# Returns list of proposals for unreviewed objects
# In-memory storage only
```

**ADK-Based**:
```python
# Step 1: Analyst loads and analyzes
inventory = analyst.analyze_inventory()
critical_objs = analyst.analyze_critical_objects()

# Step 2: Analyst generates 3-5 options per object
proposals = analyst.generate_options(focus_priority=Priority.CRITICAL)

# Step 3: Analyst prioritizes by ROI
ranked = analyst.recommend(proposals)

# Step 4: Proposal agent implements selected option
result = proposal_agent.implement_priority_assignment(
    object_id=obj_id,
    priority=Priority.CRITICAL,
    architect_notes="Implemented via workflow"
)
```

### 2. **Dependency Analysis**

**Legacy**:
- Direct BigQuery query for object metrics
- No recursive traversal
- Limited lineage understanding

**ADK-Based**:
```python
# Recursive upstream analysis with CTE
upstream = analyze_lineage_upstream(
    project_id, object_id,
    max_depth=10
)  # Returns complete upstream tree

# Recursive downstream analysis
downstream = analyze_lineage_downstream(
    project_id, object_id,
    max_depth=10
)  # Returns complete downstream tree

# Complete graph visualization
graph = build_lineage_graph(
    project_id, object_id,
    include_scope="both"
)  # Returns nodes and edges for visualization
```

### 3. **Proposal Impact Analysis**

**Legacy**:
- Cost and execution metrics from factbilling/factlog
- No consolidation/optimization analysis
- Basic precedence handling

**ADK-Based**:
```python
# Specific proposal types with impact analysis
consolidation = generate_consolidation_proposal(
    project_id,
    source_objects=[obj1, obj2, obj3],
    target_name="consolidated-service",
    rationale="Reduce operational complexity"
)
# Returns: cost savings, effort, risk level, strategy

optimization = generate_optimization_proposal(
    project_id,
    object_id,
    optimization_type="resource_sizing",
)
# Returns: specific recommendations with savings estimates

decommission = generate_decommission_proposal(
    project_id,
    object_id,
    reason="Replaced by real-time system"
)
# Returns: migration plan, dependent count, savings
```

### 4. **Role Separation**

**Legacy**:
- Single agent handles everything
- Architect interacts directly with methods
- No clear boundaries

**ADK-Based**:
- `InventoryAnalystAgent`: Analyzes, recommends (READ-ONLY)
- `ArchitectProposalAgent`: Implements decisions (WRITE-ENABLED)
- Orchestrator: Manages workflow and communication
- Clear separation of concerns

### 5. **Audit Trail**

**Legacy**:
- SCD2 versioning only
- Limited context on decisions

**ADK-Based**:
```python
architect_audit_log table:
├── audit_id (AUDIT_ABC123)
├── object_id
├── action (PRIORITY_ASSIGNED, PROPOSAL_APPROVED, etc.)
├── action_timestamp
├── actor (architect name)
├── details (JSON)
├── change_from (previous state)
└── change_to (new state)

# Complete decision history:
- What changed
- Who made the decision
- When it happened
- Why (architect notes)
- Impact (from → to)
```

---

## BigQuery Schema Enhancements (ADK-Based)

### New Tables Required

```sql
-- Architect proposals
CREATE TABLE etlobjectscd2 (
    ... existing fields ...
    -- NEW COLUMNS:
    priority STRING (CRITICAL, HIGH, MEDIUM, LOW, DECOMMISSION)
    is_decommission BOOLEAN
    decommission_reason STRING
    architect_notes STRING
    architect_review_timestamp TIMESTAMP
    architect_reviewed_by STRING
);

-- Architecture proposals history
CREATE TABLE architect_proposals (
    proposal_id STRING,
    object_id STRING,
    proposal_type STRING,
    status STRING (DRAFT, PRESENTED, APPROVED, REJECTED, IMPLEMENTED),
    title STRING,
    description STRING,
    rationale STRING,
    priority STRING,
    consolidation JSON,
    optimization JSON,
    decommission JSON,
    impact_analysis JSON,
    generated_at TIMESTAMP,
    generated_by_agent STRING,
    architect_notes STRING,
    architect_decision_at TIMESTAMP
);

-- Complete audit trail
CREATE TABLE architect_audit_log (
    audit_id STRING,
    object_id STRING,
    action STRING,
    action_timestamp TIMESTAMP,
    actor STRING,
    details JSON,
    change_from JSON,
    change_to JSON
);
```

### Data Models (ADK-Based)

Pydantic models for validation:
- `Priority` enum (CRITICAL, HIGH, MEDIUM, LOW, DECOMMISSION)
- `ProposalType` enum (CONSOLIDATION, OPTIMIZATION, DECOMMISSION, ENHANCEMENT)
- `ProposalStatus` enum (DRAFT, PRESENTED, APPROVED, REJECTED, IMPLEMENTED)
- `ArchitectProposal` - Complete proposal with impact analysis
- `ImpactAnalysis` - Metrics, risks, recommendations
- `ArchitectReview` - Architect decision record
- `AuditLogEntry` - Single audit event
- `ArchitectWorkflowRequest/Response` - Workflow lifecycle

---

## When to Use Each

### Use Legacy `architect_agent.py` When:

✅ You need simple priority assignment only
✅ No complex dependency analysis required
✅ Architect makes synchronous decisions
✅ Small number of objects (<100)
✅ In-memory proposal store is acceptable

### Use ADK-Based `architect_agent_adk.py` When:

✅ **Preparing for production deployment** - Full audit trail
✅ **Need tool composability** - Tools reusable across agents
✅ **Google ADK integration** - Using Gemini API for smarter decisions
✅ **Complex workflows** - Multiple decision points
✅ **Scalable analysis** - Handling hundreds of objects
✅ **Dependency understanding** - Need recursive lineage
✅ **Consolidation/optimization** - Multi-step proposals
✅ **Compliance** - Complete audit of all decisions

---

## Migration Path (Legacy → ADK)

If existing system uses legacy `architect_agent.py`:

```
Week 1-2: Data Model Creation
├── Create architect_proposals table
├── Create architect_audit_log table
└── Add columns to etlobjectscd2

Week 2-3: Tool Development (ADK)
├── Implement inventory tools
├── Implement lineage tools
├── Implement proposal tools
└── Implement update tools

Week 3-4: Agent Implementation
├── Implement InventoryAnalystAgent
├── Implement ArchitectProposalAgent
├── Implement ArchitectWorkflow
└── Create E2E tests

Week 4-5: API & UI Integration
├── Create Flask routes
├── Integrate with Streamlit dashboard
├── Add API documentation
└── Migrate existing workflows

Week 5: Deployment
├── UAT testing
├── Data migration (if needed)
├── Cutover to new system
└── Monitor for issues
```

---

## Summary Table

| Aspect | Legacy | ADK-Based | Winner |
|--------|--------|-----------|--------|
| **Maturity** | Production | New/Future | Legacy |
| **Simplicity** | Simple | Complex | Legacy |
| **Scalability** | Limited | Excellent | ADK |
| **Auditability** | Basic | Comprehensive | ADK |
| **Tool Reusability** | No | Yes | ADK |
| **Google ADK Ready** | No | Yes | ADK |
| **Complex Analysis** | No | Yes | ADK |
| **Production-Ready** | Yes | No (yet) | Legacy |
| **Future Proof** | No | Yes | ADK |

---

## Recommendation

**Current State**: Use legacy `architect_agent.py` - stable, working, simple
**Development**: Use ADK-based - preparing for production scale
**Long-term**: ADK-based becomes standard - scalable, auditable, composable

The two can coexist during a migration period, with legacy handling simple prioritization while ADK handles complex analysis and proposals.
