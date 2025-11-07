import logging
import os
import traceback
from typing import Dict, Iterable

from flask import Request, jsonify

from minietl_cli_enhanced import MinietlEnhancedCLI


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_SUPPORTED_TYPES = {"inventory", "logs", "billing", "all"}


def _fetch_latest_metadata(cli: MinietlEnhancedCLI, extraction_type: str) -> Dict[str, object]:
    """Fetch the most recent metadata entry for an extraction type."""
    table = f"{cli.project_id}.{cli.dataset_id}.minietl_metadata"
    query = (
        "SELECT records_extracted, extraction_timestamp, status "
        f"FROM `{table}` "
        f"WHERE extraction_type = '{extraction_type}' "
        "ORDER BY extraction_timestamp DESC "
        "LIMIT 1"
    )

    try:
        rows = list(cli.bq_manager.client.query(query).result())
    except Exception as exc:  # BigQuery client handles its own logging
        logger.warning("Failed to load extraction metadata for %s: %s", extraction_type, exc, exc_info=True)
        return {"error": str(exc)}

    if not rows:
        return {}

    row = rows[0]
    timestamp = row.get("extraction_timestamp")
    return {
        "records_extracted": row.get("records_extracted"),
        "extraction_timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp,
        "status": row.get("status"),
    }


def _resolve_extraction_type(request: Request) -> str:
    """Determine the requested extraction type from query params or JSON body."""
    extraction_type = (request.args.get("extraction_type") or "").strip().lower()
    if not extraction_type and request.is_json:
        body = request.get_json(silent=True) or {}
        extraction_type = str(body.get("extraction_type", "")).strip().lower()

    return extraction_type or "all"


def _run_inventory(cli: MinietlEnhancedCLI) -> bool:
    """Execute inventory extraction."""
    return cli.run_inventory_extraction()


def _run_logs(cli: MinietlEnhancedCLI) -> bool:
    """Execute logs extraction in delta mode."""
    return cli.run_logs_extraction(days_back=7, delta=True)


def _run_billing(cli: MinietlEnhancedCLI) -> bool:
    """Execute billing extraction in delta mode."""
    return cli.run_billing_extraction(delta=True)


def _compile_metadata(cli: MinietlEnhancedCLI, extraction_types: Iterable[str]) -> Dict[str, Dict[str, object]]:
    """Gather latest metadata for the executed extraction types."""
    return {etype: _fetch_latest_metadata(cli, etype) for etype in extraction_types}


def minietl_http_handler(request: Request):
    """
    Cloud Function HTTP entry point.

    Query parameters:
        extraction_type: inventory | logs | billing | all (default=all)
    """
    extraction_type = _resolve_extraction_type(request)
    if extraction_type not in _SUPPORTED_TYPES:
        message = f"Unsupported extraction_type '{extraction_type}'. Expected one of {sorted(_SUPPORTED_TYPES)}."
        logger.error(message)
        return jsonify({"status": "error", "message": message}), 400

    project_id = os.getenv("MINIETL_PROJECT_ID", "prismatic-smoke-463810-c1")
    dataset_id = os.getenv("MINIETL_DATASET_ID", "minietl")

    try:
        cli = MinietlEnhancedCLI(
            sa_path=None,
            project_id=project_id,
            dataset_id=dataset_id,
            use_default_credentials=True,
        )
    except Exception as exc:
        logger.error("Failed to initialize MinietlEnhancedCLI: %s", exc, exc_info=True)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Failed to initialize extractor.",
                    "details": str(exc),
                }
            ),
            500,
        )

    execution_results: Dict[str, bool] = {}
    try:
        if extraction_type == "inventory":
            execution_results["inventory"] = _run_inventory(cli)
        elif extraction_type == "logs":
            execution_results["logs"] = _run_logs(cli)
        elif extraction_type == "billing":
            execution_results["billing"] = _run_billing(cli)
        else:  # all
            inventory_success = _run_inventory(cli)
            execution_results["inventory"] = inventory_success
            if inventory_success:
                execution_results["logs"] = _run_logs(cli)
                execution_results["billing"] = _run_billing(cli)
            else:
                logger.error("Inventory extraction failed. Skipping logs and billing extractions.")
    except Exception as exc:
        logger.error("Extraction execution raised an exception: %s", exc, exc_info=True)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Extraction execution failed.",
                    "details": str(exc),
                    "trace": traceback.format_exc(),
                }
            ),
            500,
        )

    metadata = _compile_metadata(cli, execution_results.keys())

    overall_success = bool(execution_results) and all(execution_results.values())
    if len(execution_results) == 1:
        etype = next(iter(execution_results))
        extracted_summary: object = metadata.get(etype, {}).get("records_extracted")
    else:
        extracted_summary = {
            etype: metadata.get(etype, {}).get("records_extracted") for etype in execution_results
        }

    response_body = {
        "status": "success" if overall_success else "error",
        "extraction_type": extraction_type,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "extracted": extracted_summary,
        "results": {
            etype: {
                "success": success,
                "records_extracted": metadata.get(etype, {}).get("records_extracted"),
                "metadata": metadata.get(etype, {}),
            }
            for etype, success in execution_results.items()
        },
    }

    status_code = 200 if overall_success else 500
    return jsonify(response_body), status_code


# Alias expected by Google Cloud Functions
def main(request: Request):
    """Entry point used by GCF deployment."""
    return minietl_http_handler(request)
