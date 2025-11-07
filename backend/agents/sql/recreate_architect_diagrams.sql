-- Architect diagrams table rebuild script
-- Replace the project and dataset IDs if your environment differs.

DROP TABLE IF EXISTS `prismatic-smoke-463810-c1.minietl.architect_diagrams`;

CREATE TABLE `prismatic-smoke-463810-c1.minietl.architect_diagrams` (
  diagram_id STRING NOT NULL,
  object_id STRING NOT NULL,
  diagram_name STRING,
  diagram_format STRING NOT NULL,
  diagram_text STRING NOT NULL,
  is_active BOOL NOT NULL,
  generated_at TIMESTAMP NOT NULL
);
