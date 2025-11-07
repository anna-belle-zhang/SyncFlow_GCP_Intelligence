-- BigQuery DDL for architect diagrams storage
-- Supply PROJECT_ID and DATASET_ID via environment variables when running `envsubst`.
-- Drop the table if it already exists (optional).
DROP TABLE IF EXISTS `${PROJECT_ID}.${DATASET_ID}.architect_diagrams`;

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_ID}.architect_diagrams` (
  diagram_id STRING NOT NULL,
  object_id STRING NOT NULL,
  diagram_name STRING,
  diagram_format STRING NOT NULL,
  diagram_text STRING NOT NULL,
  is_active BOOL NOT NULL,
  generated_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_architect_diagrams_object
ON `${PROJECT_ID}.${DATASET_ID}.architect_diagrams` (object_id);
