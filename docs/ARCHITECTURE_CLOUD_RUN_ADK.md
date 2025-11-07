# SyncFlow Architecture: Cloud Run + Google ADK Multi-Agent System

## Executive Summary

SyncFlow is a multi-agent intelligence system deployed on Google Cloud Run that provides comprehensive GCP management through three specialized agents:
- **Architect Agent** - Configuration & Lineage Intelligence
- **Ops Agent** - Performance & Reliability Intelligence
- **FinOps Agent** - Cost Optimization Intelligence

All agents work in parallel, analyzing the same GCP infrastructure from different perspectives.

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      GOOGLE CLOUD RUN                           │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │              FRONTEND SERVICE                            │ │
│  │  - Streamlit Dashboard (Python)                          │ │
│  │  - Interactive Data Exploration                          │ │
│  │  - Real-time Visualization                              │ │
│  └──────────┬───────────────────────────────────────────────┘ │
│             │ HTTP Requests                                    │
│  ┌──────────▼───────────────────────────────────────────────┐ │
│  │              BACKEND SERVICE                             │ │
│  │  - Flask REST API (Python)                               │ │
│  │  - Data Query & Analysis                                 │ │
│  │  - Agent Orchestration                                   │ │
│  └──────────┬───────────────────────────────────────────────┘ │
│             │                                                  │
│  ┌──────────▼───────────────────────────────────────────────┐ │
│  │          MINIETL CLOUD RUN FUNCTION                      │ │
│  │  - ETL Orchestrator (Python)                             │ │
│  │  - Inventory Extraction (GCP API)                        │ │
│  │  - Logs Extraction (Cloud Logging)                       │ │
│  │  - Billing Extraction (GCP Billing Export)               │ │
│  └──────────┬───────────────────────────────────────────────┘ │
│             │                                                  │
└─────────────┼──────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 GOOGLE BIGQUERY (minietl dataset)               │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐   │
│  │ etlobjectscd2     etledges    factlog    factbilling  │   │
│  │ - SCD2 History    - Lineage   - Logs     - Costs      │   │
│  │ - Config versions - Deps      - Perf     - By service │   │
│  │ - Version history - Relationships - Duration - Budget │   │
│  └────────────────────────────────────────────────────────┘   │
└─────────────┬─────────────────────────────────────────────────┘
              │
┌─────────────▼─────────────────────────────────────────────────┐
│         GOOGLE ADK - MULTI-AGENT INTELLIGENCE LAYER            │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ AGENT ORCHESTRATOR - Coordinates Parallel Execution    │ │
│  └────────┬─────────────┬─────────────┬───────────────────┘ │
│           │             │             │                      │
│  ┌────────▼──────┐  ┌──▼──────────┐  ┌─▼──────────────┐    │
│  │ ARCHITECT     │  │    OPS      │  │    FINOPS      │    │
│  │   AGENT       │  │   AGENT     │  │    AGENT       │    │
│  ├───────────────┤  ├─────────────┤  ├────────────────┤    │
│  │ Config Track  │  │ Performance │  │ Cost Analysis  │    │
│  │ Lineage Deps  │  │ Reliability │  │ Optimization   │    │
│  │ Change Impact │  │ Anomalies   │  │ Savings Calc   │    │
│  │ Version Hist  │  │ SLA Monitor │  │ Resource ROI   │    │
│  └────────┬──────┘  └──┬──────────┘  └─┬──────────────┘    │
│           │             │             │                      │
└───────────┼─────────────┼─────────────┼──────────────────────┘
            │             │             │
            ▼             ▼             ▼
        Analysis Results (Parallel)
            │             │             │
            └─────────────┼─────────────┘
                          ▼
              FRONTEND DASHBOARD
              (Correlated Insights)
```

---

## Component Details

### 1. CLOUD RUN SERVICES

#### 1.1 Frontend Service (Streamlit Dashboard)
- **Purpose**: Interactive visualization and exploration
- **Technology**: Streamlit framework (Python)
- **Features**:
  - Object browser with filtering
  - Lineage visualization
  - Performance metrics charts
  - Cost analysis dashboards
  - Agent analysis results display

**Endpoints**:
- `/` - Dashboard home
- `/objects` - Object inventory browser
- `/lineage` - Dependency visualization
- `/performance` - Performance metrics
- `/costs` - Cost breakdown
- `/agents` - Multi-agent analysis results

#### 1.2 Backend API Service (Flask)
- **Purpose**: Programmatic access and agent orchestration
- **Technology**: Flask REST API (Python)
- **Key Responsibilities**:
  - Query BigQuery data
  - Invoke agent analysis
  - Aggregate results
  - Handle API requests

**API Endpoints**:
```
GET  /api/health                    - Health check
GET  /api/stats                     - System statistics
GET  /api/objects                   - List all objects
GET  /api/objects/<id>              - Object details
GET  /api/objects/<id>/history      - Version history
GET  /api/lineage/<id>/upstream     - Upstream dependencies
GET  /api/lineage/<id>/downstream   - Downstream dependencies
GET  /api/agents/analyze/<id>       - Run all 3 agents (parallel)
GET  /api/agents/doc/<id>           - Architect agent only
GET  /api/agents/log/<id>           - Ops agent only
GET  /api/agents/cost/<id>          - FinOps agent only
GET  /api/metrics/<id>/executions   - Execution logs
GET  /api/metrics/<id>/costs        - Cost metrics
```

#### 1.3 minietl Cloud Run Function
- **Purpose**: ETL data extraction and loading
- **Technology**: Python cloud function
- **Execution**: Triggered by Cloud Scheduler
- **Functions**:
  - Extract GCP resource inventory
  - Extract execution logs from Cloud Logging
  - Extract cost data from GCP billing export
  - Apply SCD2 MERGE for atomic updates
  - Track metrics in minietlreport table

**Three Extraction Phases**:

1. **INVENTORY EXTRACTION**
   - Source: GCP Resource APIs (Cloud Resource Manager)
   - Objects: Cloud Functions, Dataflow, Scheduler, Workflows, Cloud Run, BigQuery, etc.
   - Logic: Full scan, SCD2 versioning, delta support
   - Output: etlobjectscd2, etledges tables

2. **LOGS EXTRACTION**
   - Source: Cloud Logging API
   - Logs: Execution logs from all GCP services
   - Logic: Query by resource name, parse timestamps, map to objects
   - Output: factlog table
   - Fields: log_id, object_id, run_date, status, error_message, created_at, duration_seconds

3. **BILLING EXTRACTION**
   - Source: GCP Billing Export (BigQuery table)
   - Data: Cost and usage metrics by service
   - Logic: Parse service names, aggregate by date and service, map to objects
   - Output: factbilling table
   - Fields: object_id, run_date, service, cost_usd, compute_units, slot_hours

---

### 2. BIGQUERY DATA LAYER

#### Table: etlobjectscd2 (SCD Type 2)
```
Column              Type        Mode        Description
────────────────────────────────────────────────────────
log_id              STRING      REQUIRED    Unique log identifier
object_id           STRING      REQUIRED    Unique object ID (OBJ001, OBJ002, etc.)
object_type         STRING      REQUIRED    Type (FUNCTION, DATAFLOW, TRIGGER, etc.)
name                STRING      REQUIRED    Human-readable name
parent_id           STRING      NULLABLE    Parent object reference
gcp_resource_name   STRING      NULLABLE    Full GCP resource path
description         STRING      NULLABLE    Object description
effective_start     DATE        NULLABLE    SCD2: Version active from
effective_end       DATE        NULLABLE    SCD2: Version active until
version             INTEGER     REQUIRED    SCD2: Version number
status              STRING      REQUIRED    ACTIVE, ARCHIVED, DELETED
created_at          TIMESTAMP   NULLABLE    Creation timestamp
updated_at          TIMESTAMP   NULLABLE    Last update timestamp
metadata            JSON        NULLABLE    Additional properties
priority            STRING      NULLABLE    Architect priority assignment
architect_notes     STRING      NULLABLE    Architect review notes
is_decommission     BOOLEAN     NULLABLE    Flag for removal
decommission_reason STRING      NULLABLE    Why marked for removal
```

#### Table: etledges (Lineage)
```
Column              Type        Mode        Description
────────────────────────────────────────────────────────
edge_id             STRING      REQUIRED    Unique edge ID
source_object_id    STRING      REQUIRED    Source object
target_object_id    STRING      REQUIRED    Target object
edge_type           STRING      REQUIRED    INVOKES, TRIGGERS, WRITES_TO, READS_FROM, etc.
source_name         STRING      NULLABLE    Cached source name
target_name         STRING      NULLABLE    Cached target name
method              STRING      NULLABLE    How they interact (HTTP POST, etc.)
is_active           BOOLEAN     REQUIRED    Whether edge is currently active
created_at          TIMESTAMP   NULLABLE    Creation timestamp
```

#### Table: factlog (Execution Logs)
```
Column              Type        Mode        Description
────────────────────────────────────────────────────────
log_id              STRING      REQUIRED    Unique log identifier (UUID)
object_id           STRING      REQUIRED    Reference to ETL object
run_date            DATE        REQUIRED    Date of execution
start_time          TIME        NULLABLE    Start time (HH:MM:SS)
end_time            TIME        NULLABLE    End time (HH:MM:SS)
duration_min        INTEGER     REQUIRED    Duration in minutes
duration_seconds    FLOAT64     NULLABLE    Duration in seconds
status              STRING      REQUIRED    SUCCESS, FAILED, WARNING
error_message       STRING      NULLABLE    Error details if failed
created_at          TIMESTAMP   NULLABLE    Log creation timestamp
records_processed   INTEGER     NULLABLE    Records processed count
rows_processed      INTEGER     NULLABLE    Rows processed count
bytes_processed     FLOAT64     NULLABLE    Bytes processed
```

#### Table: factbilling (Cost Data)
```
Column              Type        Mode        Description
────────────────────────────────────────────────────────
object_id           STRING      REQUIRED    Reference to ETL object
run_date            DATE        REQUIRED    Date of cost
service             STRING      REQUIRED    GCP service name
cost_usd            FLOAT64     REQUIRED    Cost in USD
compute_units       FLOAT64     NULLABLE    Compute units consumed
slot_hours          FLOAT64     NULLABLE    BigQuery slot hours
```

#### Table: minietlreport (Extraction Metrics)
```
Column                  Type        Mode        Description
────────────────────────────────────────────────────────────
run_id                  STRING      REQUIRED    Unique extraction run ID
run_date                DATE        REQUIRED    Date of extraction
run_timestamp           TIMESTAMP   REQUIRED    Timestamp of extraction
extraction_phase        STRING      REQUIRED    INVENTORY, LOGS, or BILLING
etlobjectscd2_new       INTEGER     NULLABLE    New records in etlobjectscd2
etlobjectscd2_updated   INTEGER     NULLABLE    Updated records in etlobjectscd2
etlobjectscd2_total     INTEGER     NULLABLE    Total records affected
factlog_inserted        INTEGER     NULLABLE    Rows inserted in factlog
factbilling_inserted    INTEGER     NULLABLE    Rows inserted in factbilling
status                  STRING      REQUIRED    SUCCESS, FAILED, SKIPPED
error_message           STRING      NULLABLE    Error details if failed
duration_sec            INTEGER     NULLABLE    Duration in seconds
```

---

### 3. GOOGLE ADK - MULTI-AGENT INTELLIGENCE

#### 3.1 Agent Orchestrator
- **Role**: Coordinates execution of all three agents
- **Pattern**: Parallel execution with result aggregation
- **Execution Model**:
  - Invoke all 3 agents simultaneously
  - Collect results with ~5-15 second timeout
  - Aggregate and correlate findings
  - Return unified response to Backend

#### 3.2 Architect Agent (DocAgent)
**Purpose**: Configuration & Lineage Intelligence

**Analysis**:
- Configuration change tracking (SCD2 history)
- Impact analysis (upstream/downstream dependencies)
- Architecture evolution (version history)
- Lineage completeness and accuracy

**Inputs**:
- etlobjectscd2 (SCD2 history)
- etledges (lineage graph)

**Outputs**:
- Change timeline
- Modified fields with before/after values
- Affected downstream components
- Audit trail with timestamps

**Use Cases**:
- What changed and when?
- Who made the change?
- What else was affected?
- Is architecture documentation current?

#### 3.3 Ops Agent (LogAgent)
**Purpose**: Performance & Reliability Intelligence

**Analysis**:
- Duration trends (improving/degrading)
- Success rate patterns
- Failure analysis and root causes
- Performance anomalies (2+ std deviations)
- SLA compliance and breach detection
- Throughput and scalability trends

**Inputs**:
- factlog (execution logs)

**Outputs**:
- Performance metrics (avg, min, max duration)
- Trend indicators (up/down/stable)
- Anomaly flags with severity
- SLA status
- Recommendation for remediation

**Use Cases**:
- Why is job X slow?
- Is performance degrading over time?
- Which jobs are unreliable?
- Do we have capacity issues?
- What needs immediate attention?

#### 3.4 FinOps Agent (CloudFnOAgent)
**Purpose**: Cost Optimization Intelligence

**Analysis**:
- Cost aggregation by service
- Cost trends over time
- Cost per execution
- Resource efficiency metrics
- Cost reduction opportunities
- Estimated savings from optimizations

**Inputs**:
- factbilling (cost data)
- factlog (usage metrics)

**Outputs**:
- Cost breakdown by service
- Month-over-month trends
- Cost per job
- Top cost drivers
- Optimization recommendations with ROI

**Use Cases**:
- Where is money being spent?
- Is cost increasing or decreasing?
- Which services have best ROI?
- What optimizations would save money?
- What's the projected savings?

---

## Data Flow Diagram

### Complete Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA EXTRACTION PHASE                        │
└─────────────────────────────────────────────────────────────────┘

1. INVENTORY EXTRACTION
   GCP Resource APIs
        │
        ├─ Cloud Resource Manager
        ├─ Cloud Functions API
        ├─ Dataflow API
        ├─ Cloud Scheduler API
        ├─ Workflows API
        └─ Other service APIs
        │
        ▼
   Extract 24 GCP Objects
        │
        ▼
   Assign Object IDs (OBJ001, OBJ002, ...)
        │
        ▼
   Create Staging Table (temporary)
        │
        ▼
   Prepare 24 SCD2 Records
        │
        ▼
   Load to Staging Table
        │
        ▼
   Execute MERGE (atomic SCD2 update)
        │
        ▼
   etlobjectscd2 + etledges Tables
        └─ Status: RECORDED

2. LOGS EXTRACTION
   Cloud Logging API
        │
        ├─ Query by resource name
        ├─ Filter by date range (past 7 days)
        └─ Parse log entries
        │
        ▼
   Transform to Log Records
        │
        ├─ Generate log_id (UUID)
        ├─ Map to object_id
        ├─ Extract status (success/warning/error)
        ├─ Parse timestamps
        └─ Extract error messages
        │
        ▼
   Insert 18 Log Records to factlog
        └─ Status: RECORDED

3. BILLING EXTRACTION
   GCP Billing Export (BigQuery)
        │
        ├─ Query past 30 days
        ├─ Group by date + service
        └─ Parse service names
        │
        ▼
   Transform to Billing Records
        │
        ├─ Map service to object_type
        ├─ Find matching object
        ├─ Aggregate costs
        └─ Calculate metrics
        │
        ▼
   Insert 65 Billing Records to factbilling
        └─ Status: RECORDED

┌─────────────────────────────────────────────────────────────────┐
│                    DATA ANALYSIS PHASE                           │
└─────────────────────────────────────────────────────────────────┘

User requests: /api/agents/analyze/OBJ0001

Backend Orchestrator
        │
        ├─────────────┬─────────────┬──────────────┐
        │             │             │              │
        ▼             ▼             ▼              ▼
   Architect Agent  Ops Agent  FinOps Agent   (Parallel)
        │             │             │
        │             │             │
   Analyze SCD2   Analyze       Analyze
   + lineage      factlog       factbilling
        │             │             │
        ▼             ▼             ▼
   Config          Performance   Cost
   Changes         Trends        Analysis
        │             │             │
        └─────────────┼─────────────┘
                      │
                      ▼
              Aggregate Results
                      │
                      ▼
           Return to Frontend Dashboard
```

---

## Execution Sequence

### Full Extraction Run (Sequential)

```
Time  Component              Action                      Status
────────────────────────────────────────────────────────────────
  0s  minietl starts        Load config                 START
  1s  minietl              Initialize BigQuery client   INIT
  2s  Inventory Extraction Query GCP Resource Manager   QUERY
  5s  Inventory Extraction Discover 24 objects          FOUND
  6s  Inventory Extraction Create staging table         CREATE
  8s  Inventory Extraction Load 24 records to staging   LOAD
 10s  Inventory Extraction Execute MERGE operation      MERGE
 15s  Inventory Extraction Complete, tables updated     DONE

 16s  Logs Extraction       Query Cloud Logging API     QUERY
 30s  Logs Extraction       Parse 18 log entries        PARSE
 32s  Logs Extraction       Insert to factlog table     INSERT
 35s  Logs Extraction       Complete                    DONE

 36s  Billing Extraction    Query GCP billing export    QUERY
 40s  Billing Extraction    Aggregate 65 records        AGGR
 42s  Billing Extraction    Insert to factbilling       INSERT
 45s  Billing Extraction    Complete                    DONE

 46s  Record Metrics        Insert to minietlreport     RECORD
 50s  All Done              Summary                     SUCCESS

Total Duration: 50 seconds
```

### Agent Analysis Flow (Parallel)

```
Time  Component              Action                      Duration
────────────────────────────────────────────────────────────────
  0s  Backend receives      /api/agents/analyze/OBJ0001 REQUEST
  1s  Orchestrator spawns   All 3 agents                SPAWN

  1s  Architect Agent       Query etlobjectscd2         START (Parallel)
  1s  Ops Agent             Query factlog               START (Parallel)
  1s  FinOps Agent          Query factbilling           START (Parallel)

  3s  Architect Agent       Analyze changes             PROC
  3s  Ops Agent             Calculate trends            PROC
  3s  FinOps Agent          Aggregate costs             PROC

  8s  Architect Agent       Return findings             DONE
  8s  Ops Agent             Return metrics              DONE
  8s  FinOps Agent          Return analysis             DONE

  9s  Orchestrator          Aggregate results           AGGS
 10s  Backend returns       Unified response            RETURN

Total Analysis Time: 10 seconds (all agents in parallel)
```

---

## Technology Stack

### Backend Infrastructure
- **Platform**: Google Cloud Run
- **Runtime**: Python 3.10+
- **Framework**: Flask (Backend API)
- **UI**: Streamlit (Frontend Dashboard)

### Data Storage
- **Warehouse**: Google BigQuery
- **Dataset**: minietl
- **Tables**: 5 (etlobjectscd2, etledges, factlog, factbilling, minietlreport)

### Data Sources
- **Inventory**: GCP Resource Manager API
- **Logs**: Cloud Logging API
- **Billing**: GCP Billing Export (BigQuery)

### Agent Framework
- **Framework**: Google ADK (Agent Development Kit)
- **Pattern**: Multi-agent orchestration
- **Execution**: Parallel with aggregation
- **Agents**: 3 specialized (Architect, Ops, FinOps)

### Development Tools
- **IaC**: Terraform (Cloud Run deployment)
- **VCS**: Git
- **Testing**: pytest
- **Monitoring**: Cloud Logging, Cloud Monitoring

---

## Scaling Considerations

### Current Capacity
- **Objects**: 24 tracked resources
- **Logs**: ~18 entries per extraction (Cloud Logging)
- **Cost records**: 65+ per month
- **Query latency**: <10 seconds for agent analysis

### Scaling Points

| Component | Current | Bottleneck | Solution |
|-----------|---------|-----------|----------|
| Objects | 24 | SCD2 versioning | Shard by prefix |
| Logs | 18/run | Cloud Logging API limits | Batch queries |
| Billing | 65/month | Aggregation query | Materialized views |
| Agent latency | 10s | Parallel execution | Add caching |
| API throughput | Single Flask | Request queue | Add Load Balancer |

### Optimization Opportunities
1. **BigQuery Optimization**
   - Partition etlobjectscd2 by run_date
   - Cluster by object_type
   - Use materialized views for common queries

2. **Agent Performance**
   - Cache agent results for 1 hour
   - Implement incremental analysis
   - Add result pagination

3. **Cloud Run Scaling**
   - Set min instances = 2
   - Set max instances = 100
   - Configure concurrency = 80

---

## Security Considerations

### Current Implementation
- Service account authentication (service-account.json)
- Private BigQuery dataset

### Production Improvements Needed
- [ ] OAuth2/OIDC authentication for API users
- [ ] Role-based access control (RBAC)
- [ ] API key management
- [ ] Secrets stored in Secret Manager
- [ ] VPC-SC for network isolation
- [ ] Audit logging for all agent access
- [ ] Data encryption at rest and in transit

---

## Deployment Architecture

### Local Development
```
localhost:8501 (Streamlit Frontend)
    ↓
localhost:5000 (Flask Backend)
    ↓
BigQuery (minietl dataset)
```

### Cloud Deployment
```
Cloud Run Service 1 (Frontend)
    ↓ HTTP
Cloud Run Service 2 (Backend)
    ↓
Cloud Run Job (minietl ETL)
    ↓ SQL
BigQuery (minietl dataset)
    ↓ APIs
GCP Services (Inventory, Logs, Billing)
```

### Service Connections
```
Frontend → Backend: REST API over HTTPS
Backend → BigQuery: Private Service Connection
minietl → GCP APIs: Service Account Auth
minietl → BigQuery: Service Account Auth
All → Cloud Logging: Automatic via Cloud Run
```

---

## Monitoring & Observability

### Key Metrics
```
Frontend Metrics:
  - Page load time
  - API response time
  - Error rate

Backend Metrics:
  - API endpoint latency
  - BigQuery query duration
  - Agent execution time
  - Error rate

minietl Metrics:
  - Extraction duration
  - Records processed
  - Success/failure rate
  - Data quality scores

Agent Metrics:
  - Analysis time
  - Result accuracy
  - Cache hit rate
  - Execution frequency
```

### Log Aggregation
- All services log to Cloud Logging
- Structured JSON logging
- Correlation IDs for tracing
- Error alerting on failures

---

## Future Enhancements

### Phase 2: Advanced Features
- [ ] Gemini AI integration for smarter recommendations
- [ ] Real-time change detection (pub/sub streaming)
- [ ] Cost forecasting with ML
- [ ] Automated remediation actions
- [ ] Mobile app for alerts

### Phase 3: Enterprise Features
- [ ] Multi-tenant support
- [ ] Custom agent definitions
- [ ] Workflow automation
- [ ] Integration with ServiceNow/Jira
- [ ] Cost showback/chargeback

### Phase 4: Platform
- [ ] Marketplace for agent plugins
- [ ] Agent-to-agent communication
- [ ] Cross-project aggregation
- [ ] Multi-cloud support

---

## References

### Key Files
- `/backend/syncflow_server.py` - Main Flask application
- `/backend/bigquery_loader.py` - BigQuery operations
- `/backend/logs_explorer.py` - Cloud Logging integration
- `/backend/billing_extractor.py` - Cost data processing
- `/minietl/minietl_cli_enhanced.py` - ETL orchestrator
- `/frontend/dashboard.py` - Streamlit UI

### Configuration
- `.env` - Environment variables
- `config/config.json` - Project configuration
- `terraform/` - Infrastructure as Code

---

## Contact & Support

For questions about the architecture:
- Review README.md for quick start
- Check dev/ folder for detailed task documentation
- See QUICK_START.md for deployment guide
