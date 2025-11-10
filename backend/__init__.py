"""
Mini ETL - GCP ETL Metadata Management System with SCD Type 2 Tracking

A comprehensive system for cataloging, tracking, and managing GCP ETL objects
with complete lineage tracking and operational metrics.

Modules:
    - models: Data models and BigQuery schemas
    - bigquery_loader: BigQuery operations
    - inventory_collector: GCP inventory collection
    - lineage_extractor: ETL lineage extraction
    - object_assigner: Object ID assignment
    - scd2_processor: SCD Type 2 maintenance logic
    - api: REST API endpoints
"""

__version__ = "0.1.0"
__author__ = "Claude Code"
