# SyncFlow Architecture Diagrams

## Diagram 1: Overall System Architecture

```mermaid
graph TB
    subgraph CloudRun["Cloud Run Services"]
        FE["Frontend Service<br/>Streamlit Dashboard<br/>Python"]
        BE["Backend API<br/>Flask REST<br/>Python"]
        MINI["minietl<br/>ETL Orchestrator<br/>Cloud Run Function"]
    end

    subgraph ADK["Google ADK Multi-Agent System"]
        ORCH["Agent Orchestrator<br/>Parallel Execution"]
        AG1["Architect Agent<br/>DocAgent<br/>Config and Lineage"]
        AG2["Ops Agent<br/>LogAgent<br/>Performance and Reliability"]
        AG3["FinOps Agent<br/>CloudFnOAgent<br/>Cost Optimization"]
    end

    subgraph BQ["BigQuery minietl Dataset"]
        T1["etlobjectscd2<br/>SCD2 History<br/>Version Tracking"]
        T2["etledges<br/>Lineage Graph<br/>Dependencies"]
        T3["factlog<br/>Execution Logs<br/>Performance Data"]
        T4["factbilling<br/>Cost Data<br/>By Service"]
        T5["minietlreport<br/>Extraction Metrics<br/>Run History"]
    end

    subgraph GCP["GCP Data Sources"]
        API["GCP Resource APIs<br/>Cloud Resource Manager"]
        CL["Cloud Logging API<br/>Execution Logs"]
        CB["GCP Billing Export<br/>Cost and Usage"]
    end

    subgraph GCPSVCS["GCP Services Tracked"]
        CF["Cloud Functions"]
        DF["Dataflow"]
        CS["Cloud Scheduler"]
        WF["Cloud Workflows"]
        CR["Cloud Run"]
        BQT["BigQuery"]
        GCS["Cloud Storage"]
    end

    FE -->|HTTP Requests| BE
    BE -->|REST API| ORCH
    ORCH -->|Invoke Parallel| AG1
    ORCH -->|Invoke Parallel| AG2
    ORCH -->|Invoke Parallel| AG3

    AG1 -->|Analyze| T1
    AG1 -->|Analyze| T2
    AG2 -->|Analyze| T3
    AG3 -->|Analyze| T4

    MINI -->|Extract| API
    MINI -->|Extract| CL
    MINI -->|Extract| CB

    API -->|Discover| CF
    API -->|Discover| DF
    API -->|Discover| CS
    API -->|Discover| WF
    API -->|Discover| CR
    API -->|Discover| BQT
    API -->|Discover| GCS

    MINI -->|Load SCD2| T1
    MINI -->|Load Lineage| T2
    MINI -->|Load| T3
    MINI -->|Load| T4
    MINI -->|Record| T5

    BE -->|Query| BQ

    style CloudRun fill:#4285F4,stroke:#1967D2,color:#fff
    style ADK fill:#EA4335,stroke:#C5221F,color:#fff
    style BQ fill:#1E88E5,stroke:#0D47A1,color:#fff
    style GCP fill:#5E7CE0,stroke:#3F51B5,color:#fff
    style GCPSVCS fill:#34A853,stroke:#137333,color:#fff
    style AG1 fill:#FF6D00,stroke:#E65100,color:#fff
    style AG2 fill:#00BCD4,stroke:#006064,color:#fff
    style AG3 fill:#8BC34A,stroke:#558B2F,color:#fff
```

---

## Diagram 2: Data Flow Pipeline

```mermaid
graph LR
    subgraph Extract["Extraction Phase"]
        EXT1["Inventory Extract<br/>GCP APIs"]
        EXT2["Logs Extract<br/>Cloud Logging"]
        EXT3["Billing Extract<br/>GCP Billing"]
    end

    subgraph Transform["Transform Phase"]
        T1["Parse and Map<br/>Inventory to Objects"]
        T2["Parse Logs<br/>Extract Metrics"]
        T3["Aggregate Costs<br/>By Service"]
    end

    subgraph Staging["Staging Phase"]
        S1["Create Staging Table<br/>etlobjectscd2_staging"]
        S2["Prepare Log Records<br/>Generate IDs"]
        S3["Prepare Billing Records<br/>Match Objects"]
    end

    subgraph Load["Load Phase"]
        L1["SCD2 MERGE<br/>Atomic Update"]
        L2["Insert to factlog<br/>Execution Logs"]
        L3["Insert to factbilling<br/>Cost Data"]
    end

    subgraph BQData["BigQuery Tables"]
        BQ1["etlobjectscd2<br/>24 Objects<br/>Active Records"]
        BQ2["etledges<br/>Lineage<br/>Dependencies"]
        BQ3["factlog<br/>18 Logs<br/>Recent"]
        BQ4["factbilling<br/>65 Records<br/>Past Month"]
        BQ5["minietlreport<br/>Metrics<br/>Tracking"]
    end

    subgraph Analysis["Analysis Phase"]
        A1["Architect Agent<br/>Change Tracking<br/>Impact Analysis"]
        A2["Ops Agent<br/>Performance Analysis<br/>Anomaly Detection"]
        A3["FinOps Agent<br/>Cost Analysis<br/>Optimization"]
    end

    subgraph Output["Output Phase"]
        O1["Results<br/>Configuration Changes"]
        O2["Results<br/>Performance Metrics"]
        O3["Results<br/>Cost Insights"]
    end

    subgraph Display["Visualization"]
        DASH["Streamlit Dashboard<br/>Interactive Exploration"]
    end

    EXT1 --> T1
    EXT2 --> T2
    EXT3 --> T3

    T1 --> S1
    T2 --> S2
    T3 --> S3

    S1 --> L1
    S2 --> L2
    S3 --> L3

    L1 --> BQ1
    L1 --> BQ2
    L2 --> BQ3
    L3 --> BQ4
    L1 --> BQ5

    BQ1 --> A1
    BQ2 --> A1
    BQ3 --> A2
    BQ4 --> A3

    A1 --> O1
    A2 --> O2
    A3 --> O3

    O1 --> DASH
    O2 --> DASH
    O3 --> DASH

    style Extract fill:#FFA726,stroke:#F57C00,color:#fff
    style Transform fill:#66BB6A,stroke:#388E3C,color:#fff
    style Staging fill:#AB47BC,stroke:#7B1FA2,color:#fff
    style Load fill:#EC407A,stroke:#C2185B,color:#fff
    style BQData fill:#29B6F6,stroke:#0277BD,color:#fff
    style Analysis fill:#EF5350,stroke:#D32F2F,color:#fff
    style Output fill:#FFA726,stroke:#F57C00,color:#fff
    style Display fill:#FFEB3B,stroke:#F57F17,color:#000
```

---

## Diagram 3: Agent Orchestration Flow

```mermaid
graph TD
    USER["User Request<br/>GET /api/agents/analyze/OBJ0001"]
    BE["Backend API<br/>Flask"]
    ORCH["Agent Orchestrator<br/>Google ADK"]

    subgraph AgentExec["Parallel Agent Execution<br/>Time: ~0-10 seconds"]
        direction LR
        ARC["Architect Agent<br/>Query etlobjectscd2<br/>Query etledges<br/>Analyze Changes"]
        OPS["Ops Agent<br/>Query factlog<br/>Calculate Trends<br/>Detect Anomalies"]
        FIN["FinOps Agent<br/>Query factbilling<br/>Aggregate Costs<br/>Find Savings"]
    end

    subgraph Results["Agent Results"]
        R1["Configuration Changes<br/>Impact Assessment<br/>Version History"]
        R2["Performance Metrics<br/>Anomalies<br/>SLA Status"]
        R3["Cost Breakdown<br/>Trends<br/>Recommendations"]
    end

    AGGS["Result Aggregation<br/>Correlation"]
    RESP["Unified Response<br/>JSON"]
    DASH["Streamlit Dashboard<br/>Display Results"]

    USER --> BE
    BE --> ORCH

    ORCH -->|Spawn Parallel| ARC
    ORCH -->|Spawn Parallel| OPS
    ORCH -->|Spawn Parallel| FIN

    ARC --> R1
    OPS --> R2
    FIN --> R3

    R1 --> AGGS
    R2 --> AGGS
    R3 --> AGGS

    AGGS --> RESP
    RESP --> DASH

    style USER fill:#FFB74D,stroke:#F57C00,color:#fff
    style BE fill:#4CAF50,stroke:#388E3C,color:#fff
    style ORCH fill:#FF7043,stroke:#D84315,color:#fff
    style ARC fill:#FF6D00,stroke:#E65100,color:#fff
    style OPS fill:#00BCD4,stroke:#006064,color:#fff
    style FIN fill:#8BC34A,stroke:#558B2F,color:#fff
    style AGGS fill:#673AB7,stroke:#512DA8,color:#fff
    style RESP fill:#3F51B5,stroke:#1A237E,color:#fff
    style DASH fill:#FFEB3B,stroke:#F57F17,color:#000
```

---

## Diagram 4: Data Schema Relationships

```mermaid
graph TB
    subgraph Objects["Object Registry<br/>SCD2 Versioning"]
        OBJ["etlobjectscd2<br/>object_id PK<br/>version, effective_dates<br/>status, metadata"]
    end

    subgraph Lineage["Dependency Graph"]
        EDGE["etledges<br/>source_object_id FK<br/>target_object_id FK<br/>edge_type, is_active"]
    end

    subgraph Metrics["Execution Metrics"]
        LOG["factlog<br/>object_id FK<br/>run_date, timestamps<br/>duration, status<br/>error_message"]
    end

    subgraph Costs["Cost Tracking"]
        BILL["factbilling<br/>object_id FK<br/>service, cost_usd<br/>compute_units"]
    end

    subgraph Report["Extraction Report"]
        REP["minietlreport<br/>run_id, run_date<br/>extraction_phase<br/>record_counts<br/>status, duration"]
    end

    OBJ -->|links to| LOG
    OBJ -->|links to| BILL
    OBJ -->|source in| EDGE
    OBJ -->|target in| EDGE
    LOG -->|tracked in| REP
    BILL -->|tracked in| REP

    style OBJ fill:#1E88E5,stroke:#0D47A1,color:#fff
    style EDGE fill:#43A047,stroke:#2E7D32,color:#fff
    style LOG fill:#FB8C00,stroke:#E65100,color:#fff
    style BILL fill:#E53935,stroke:#C62828,color:#fff
    style REP fill:#6A1B9A,stroke:#4A148C,color:#fff
```

---

## Diagram 5: Extraction Timeline

```mermaid
graph LR
    T0["0s<br/>Start"]
    T1["2s<br/>Init<br/>BigQuery"]
    T2["5s<br/>Discover<br/>24 Objects"]
    T3["8s<br/>Load<br/>Staging"]
    T4["15s<br/>MERGE<br/>Complete"]
    T5["20s<br/>Logs<br/>Extract"]
    T6["35s<br/>Logs<br/>Insert"]
    T7["40s<br/>Billing<br/>Extract"]
    T8["50s<br/>Billing<br/>Insert"]
    T9["55s<br/>Record<br/>Metrics"]
    T10["60s<br/>Done"]

    T0 -->|Inventory| T1
    T1 --> T2
    T2 --> T3
    T3 --> T4
    T4 -->|Logs| T5
    T5 --> T6
    T6 -->|Billing| T7
    T7 --> T8
    T8 --> T9
    T9 --> T10

    style T0 fill:#90CAF9,stroke:#1976D2,color:#fff
    style T1 fill:#90CAF9,stroke:#1976D2,color:#fff
    style T2 fill:#90CAF9,stroke:#1976D2,color:#fff
    style T3 fill:#90CAF9,stroke:#1976D2,color:#fff
    style T4 fill:#4CAF50,stroke:#2E7D32,color:#fff
    style T5 fill:#FFA726,stroke:#F57C00,color:#fff
    style T6 fill:#FFA726,stroke:#F57C00,color:#fff
    style T7 fill:#EF5350,stroke:#C62828,color:#fff
    style T8 fill:#EF5350,stroke:#C62828,color:#fff
    style T9 fill:#AB47BC,stroke:#6A1B9A,color:#fff
    style T10 fill:#4CAF50,stroke:#2E7D32,color:#fff
```

---

## Diagram 6: Cloud Run Service Interactions

```mermaid
graph TB
    subgraph Internet["Internet Users"]
        USER["End Users<br/>Web Browser"]
    end

    subgraph CloudRun["Google Cloud Run"]
        FE["Frontend Service<br/>Port 8501<br/>Streamlit App"]
        BE["Backend Service<br/>Port 5000<br/>Flask API"]
        MINI["minietl Function<br/>Triggered<br/>ETL Jobs"]
    end

    subgraph GCP["Google Cloud Platform"]
        BQ["BigQuery<br/>minietl Dataset"]
        CL["Cloud Logging"]
        API["Resource APIs"]
        BILL["Billing Export"]
    end

    subgraph Sched["Scheduling"]
        SCHED["Cloud Scheduler<br/>Triggers minietl<br/>Daily 2am UTC"]
    end

    USER -->|HTTPS| FE
    FE -->|HTTP API| BE
    BE -->|SQL Queries| BQ
    BE -->|SDK Calls| API

    SCHED -->|HTTP Trigger| MINI
    MINI -->|Extract| API
    MINI -->|Query| CL
    MINI -->|Query| BILL
    MINI -->|SQL INSERT| BQ

    BQ -->|Logs| CL

    style FE fill:#FFEB3B,stroke:#F57F17,color:#000
    style BE fill:#4CAF50,stroke:#2E7D32,color:#fff
    style MINI fill:#9C27B0,stroke:#6A1B9A,color:#fff
    style BQ fill:#2196F3,stroke:#0D47A1,color:#fff
    style CL fill:#FF9800,stroke:#E65100,color:#fff
    style API fill:#4CAF50,stroke:#2E7D32,color:#fff
    style SCHED fill:#757575,stroke:#212121,color:#fff
```

---

## Diagram 7: Agent Decision Tree

```mermaid
graph TD
    REQ["API Request<br/>Analyze Object"]
    ORCH["Orchestrator<br/>Fan-out to Agents"]

    subgraph ARC_FLOW["Architect Agent Flow"]
        ARC_Q["Query SCD2<br/>Get All Versions"]
        ARC_T["Track Changes<br/>Compare Records"]
        ARC_I["Analyze Impact<br/>Walk Dependencies"]
        ARC_R["Return Results<br/>Changes and Impact"]
    end

    subgraph OPS_FLOW["Ops Agent Flow"]
        OPS_Q["Query Logs<br/>Get Executions"]
        OPS_C["Calculate Stats<br/>Duration Trends"]
        OPS_A["Detect Anomalies<br/>Compare Baselines"]
        OPS_R["Return Results<br/>Metrics and Issues"]
    end

    subgraph FIN_FLOW["FinOps Agent Flow"]
        FIN_Q["Query Billing<br/>Get Costs"]
        FIN_S["Sum Costs<br/>Aggregate by Service"]
        FIN_O["Find Optimization<br/>Calculate Savings"]
        FIN_R["Return Results<br/>Costs and Recs"]
    end

    MERGE["Merge Results<br/>Correlate Findings"]
    FINAL["Return to Dashboard<br/>Unified View"]

    REQ --> ORCH

    ORCH -->|Parallel| ARC_Q
    ORCH -->|Parallel| OPS_Q
    ORCH -->|Parallel| FIN_Q

    ARC_Q --> ARC_T
    ARC_T --> ARC_I
    ARC_I --> ARC_R

    OPS_Q --> OPS_C
    OPS_C --> OPS_A
    OPS_A --> OPS_R

    FIN_Q --> FIN_S
    FIN_S --> FIN_O
    FIN_O --> FIN_R

    ARC_R --> MERGE
    OPS_R --> MERGE
    FIN_R --> MERGE

    MERGE --> FINAL

    style REQ fill:#FFB74D,stroke:#F57C00,color:#fff
    style ORCH fill:#FF7043,stroke:#D84315,color:#fff
    style ARC_Q fill:#FF6D00,stroke:#E65100,color:#fff
    style ARC_T fill:#FF6D00,stroke:#E65100,color:#fff
    style ARC_I fill:#FF6D00,stroke:#E65100,color:#fff
    style ARC_R fill:#FF6D00,stroke:#E65100,color:#fff
    style OPS_Q fill:#00BCD4,stroke:#006064,color:#fff
    style OPS_C fill:#00BCD4,stroke:#006064,color:#fff
    style OPS_A fill:#00BCD4,stroke:#006064,color:#fff
    style OPS_R fill:#00BCD4,stroke:#006064,color:#fff
    style FIN_Q fill:#8BC34A,stroke:#558B2F,color:#fff
    style FIN_S fill:#8BC34A,stroke:#558B2F,color:#fff
    style FIN_O fill:#8BC34A,stroke:#558B2F,color:#fff
    style FIN_R fill:#8BC34A,stroke:#558B2F,color:#fff
    style MERGE fill:#673AB7,stroke:#512DA8,color:#fff
    style FINAL fill:#4CAF50,stroke:#2E7D32,color:#fff
```

---

## Diagram Legend

### Colors Used

| Color | Meaning |
|-------|---------|
| 🔵 Blue | Data Layer - BigQuery |
| 🟢 Green | Processing - Transform, Load, Complete |
| 🟠 Orange | Extraction - Input Data |
| 🔴 Red | Analysis - FinOps Agent |
| 🟦 Cyan | Analysis - Ops Agent |
| 🟨 Yellow | UI - Display, User Interaction |
| 🟣 Purple | Orchestration, Staging |
| 🟧 Orange-Red | Architect Agent |

### Diagram Overview

1. **Overall System Architecture** - Complete system with all components
2. **Data Flow Pipeline** - Extract → Transform → Load → Analyze → Display
3. **Agent Orchestration** - Parallel agent execution and result aggregation
4. **Data Schema Relationships** - How tables relate to each other
5. **Extraction Timeline** - Timing for each phase
6. **Cloud Run Service Interactions** - How services communicate
7. **Agent Decision Tree** - How each agent analyzes data independently
