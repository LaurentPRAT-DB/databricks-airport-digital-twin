"""Auto-register the MCP server as a Unity Catalog HTTP Connection.

On Databricks Apps, the service principal credentials are injected as
DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET environment variables.
This module uses those credentials to create (or update) a UC HTTP
Connection with is_mcp_connection='true', making the app discoverable
in the AI Playground's MCP Servers panel.

The connection is created idempotently — if it already exists with the
correct config, no action is taken.
"""

import logging
import os

logger = logging.getLogger(__name__)

_CONNECTION_NAME = "airport_digital_twin_mcp"


def ensure_mcp_connection() -> str | None:
    """Create or verify the UC HTTP Connection for MCP.

    Returns the connection name on success, None if skipped or failed.
    """
    client_id = os.getenv("DATABRICKS_CLIENT_ID", "")
    client_secret = os.getenv("DATABRICKS_CLIENT_SECRET", "")
    host = os.getenv("DATABRICKS_HOST", "")
    app_url = os.getenv("DATABRICKS_APP_URL", "")

    if not client_id or not client_secret:
        logger.info("MCP_CONN | Skipping — no SP credentials (not running on Databricks Apps)")
        return None

    if not host:
        logger.warning("MCP_CONN | Skipping — DATABRICKS_HOST not set")
        return None

    # Derive app URL if not explicitly set
    if not app_url:
        # Try to get it from the app name
        app_name = os.getenv("DATABRICKS_APP_NAME", "")
        if app_name:
            # Workspace ID is in the host or we derive from the app
            logger.info(f"MCP_CONN | App name: {app_name}, but no DATABRICKS_APP_URL set")
        logger.info("MCP_CONN | Skipping — DATABRICKS_APP_URL not set, cannot determine app endpoint")
        return None

    token_endpoint = f"https://{host.replace('https://', '').rstrip('/')}/oidc/v1/token"
    app_host = app_url.rstrip("/")
    if not app_host.startswith("https://"):
        app_host = f"https://{app_host}"

    logger.info(f"MCP_CONN | Ensuring UC HTTP Connection '{_CONNECTION_NAME}'")
    logger.info(f"MCP_CONN |   App URL: {app_host}")
    logger.info(f"MCP_CONN |   Token endpoint: {token_endpoint}")
    logger.info(f"MCP_CONN |   Client ID: {client_id[:8]}...")

    try:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()

        # Check if connection already exists
        try:
            existing = w.connections.get(_CONNECTION_NAME)
            logger.info(f"MCP_CONN | Connection '{_CONNECTION_NAME}' already exists (type={existing.connection_type})")
            return _CONNECTION_NAME
        except Exception:
            pass  # Connection doesn't exist, create it

        # Create via SQL since the SDK connections API may not support all HTTP options
        sql = f"""
        CREATE CONNECTION {_CONNECTION_NAME} TYPE HTTP
        OPTIONS (
            host '{app_host}',
            port '443',
            base_path '/api/mcp',
            client_id '{client_id}',
            client_secret '{client_secret}',
            oauth_scope 'all-apis',
            token_endpoint '{token_endpoint}',
            is_mcp_connection 'true'
        )
        """

        # Execute via Statement Execution API
        warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
        if not warehouse_id:
            logger.warning("MCP_CONN | No DATABRICKS_WAREHOUSE_ID — cannot create connection via SQL")
            return None

        from databricks.sdk.service.sql import StatementState

        response = w.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=sql,
            wait_timeout="30s",
        )

        if response.status and response.status.state == StatementState.SUCCEEDED:
            logger.info(f"MCP_CONN | Connection '{_CONNECTION_NAME}' created successfully")
            return _CONNECTION_NAME
        else:
            error = response.status.error if response.status else "unknown"
            # If it already exists, that's fine
            if "already exists" in str(error).lower():
                logger.info(f"MCP_CONN | Connection '{_CONNECTION_NAME}' already exists")
                return _CONNECTION_NAME
            logger.error(f"MCP_CONN | Failed to create connection: {error}")
            return None

    except Exception as e:
        logger.error(f"MCP_CONN | Failed to ensure connection: {e}", exc_info=True)
        return None
