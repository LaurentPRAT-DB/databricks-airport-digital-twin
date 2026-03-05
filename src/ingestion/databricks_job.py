"""Databricks job wrapper for OpenSky API polling.

This module provides a wrapper function for running the poll job
in Databricks, with proper logging and result formatting.
"""

import logging
from datetime import datetime
from typing import Any, Dict

from src.config.settings import settings
from src.ingestion.poll_job import poll_and_write


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_poll_job() -> Dict[str, Any]:
    """
    Execute a single poll cycle and return results.

    This function wraps poll_and_write with logging and result formatting
    suitable for Databricks job monitoring.

    Returns:
        Dict containing:
            - timestamp: ISO format timestamp of execution
            - count: Number of flight states written
            - duration: Execution time in seconds
            - status: "success" or "error"
            - error: Error message if status is "error"
    """
    start_time = datetime.utcnow()
    logger.info(f"Starting poll job at {start_time.isoformat()}")

    result: Dict[str, Any] = {
        "timestamp": start_time.isoformat(),
        "count": 0,
        "duration": 0.0,
        "status": "success",
    }

    try:
        count = poll_and_write(
            landing_path=settings.LANDING_PATH,
            bbox=settings.SFO_BBOX,
        )
        result["count"] = count
        logger.info(f"Successfully wrote {count} flight states")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.error(f"Poll job failed: {e}")

    end_time = datetime.utcnow()
    duration = (end_time - start_time).total_seconds()
    result["duration"] = duration

    logger.info(f"Poll job completed in {duration:.2f}s with status: {result['status']}")

    return result
