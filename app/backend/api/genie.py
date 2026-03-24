"""Genie Conversation API proxy — relays natural language questions to a Databricks Genie Space."""

import logging
import os
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

genie_router = APIRouter(prefix="/api/genie", tags=["genie"])

GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID", "01f12612fa6314ae943d0526f5ae3a00")
_POLL_INTERVAL = 1.5  # seconds between polls
_MAX_POLL_TIME = 120  # max seconds to wait for Genie response


class AskRequest(BaseModel):
    question: str


class FollowupRequest(BaseModel):
    conversation_id: str
    question: str


class GenieResponse(BaseModel):
    conversation_id: str | None = None
    message_id: str | None = None
    status: str = "UNKNOWN"
    sql: str | None = None
    columns: list[str] | None = None
    data: list[list] | None = None
    row_count: int = 0
    text_response: str | None = None
    error: str | None = None


def _get_databricks_auth(request: Request) -> tuple[str, str]:
    """Extract Databricks host and auth token for API calls.

    In Databricks Apps the user's OAuth token is forwarded in the Authorization header.
    Falls back to SDK ambient credentials for local development.
    """
    host = os.getenv("DATABRICKS_HOST", "")
    if host and not host.startswith("http"):
        host = f"https://{host}"

    # Try user's forwarded token first (Databricks Apps OBO)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        if token:
            return host, token

    # Fallback: SDK ambient credentials (local dev / service principal)
    try:
        from databricks.sdk.core import Config
        cfg = Config()
        host = host or cfg.host
        token = cfg.token
        if token:
            return host, token
        # Try to generate a token from the config
        headers = cfg.authenticate()
        auth = headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return host, auth[len("Bearer "):]
    except Exception as e:
        logger.debug(f"SDK auth fallback failed: {e}")

    raise HTTPException(status_code=503, detail="No Databricks authentication available")


async def _genie_api(
    method: str,
    path: str,
    host: str,
    token: str,
    json_body: dict | None = None,
) -> dict:
    """Make a request to the Databricks Genie REST API."""
    url = f"{host}/api/2.0/genie/spaces/{GENIE_SPACE_ID}{path}"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        else:
            resp = await client.post(url, headers=headers, json=json_body or {})

    if resp.status_code >= 400:
        detail = resp.text[:500]
        logger.warning(f"Genie API {method} {path} failed ({resp.status_code}): {detail}")
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.json()


def _parse_message_response(msg: dict) -> GenieResponse:
    """Parse a Genie message response into our normalized format."""
    status = msg.get("status", "UNKNOWN")
    conversation_id = msg.get("conversation_id")
    message_id = msg.get("id")

    result = GenieResponse(
        conversation_id=conversation_id,
        message_id=message_id,
        status=status,
    )

    # Text content
    content = msg.get("content")
    if content:
        result.text_response = content

    # Attachments contain SQL queries and results
    attachments = msg.get("attachments", [])
    for attachment in attachments:
        # SQL query attachment
        query = attachment.get("query")
        if query:
            result.sql = query.get("query") or query.get("sql")
            # Description can also contain useful text
            desc = query.get("description")
            if desc and not result.text_response:
                result.text_response = desc

        # Result attachment
        att_text = attachment.get("text")
        if att_text and not result.text_response:
            result.text_response = att_text

    # Ensure text_response is always set for terminal statuses
    if not result.text_response:
        if status == "FAILED":
            result.text_response = result.error or "Genie could not process this question."
        elif status == "CANCELLED":
            result.text_response = "The query was cancelled."

    return result


async def _poll_message(
    host: str,
    token: str,
    conversation_id: str,
    message_id: str,
) -> GenieResponse:
    """Poll a Genie message until it reaches a terminal state."""
    start = time.monotonic()

    while time.monotonic() - start < _MAX_POLL_TIME:
        msg = await _genie_api(
            "GET",
            f"/conversations/{conversation_id}/messages/{message_id}",
            host,
            token,
        )
        status = msg.get("status", "")
        if status not in ("EXECUTING_QUERY", "FETCHING_METADATA", "ASKING_AI", ""):
            result = _parse_message_response(msg)

            # If completed with a query, fetch the query result
            if status == "COMPLETED":
                for attachment in msg.get("attachments", []):
                    query = attachment.get("query")
                    if query:
                        att_id = attachment.get("id")
                        if att_id:
                            try:
                                query_result = await _genie_api(
                                    "GET",
                                    f"/conversations/{conversation_id}/messages/{message_id}/query-result/{att_id}",
                                    host,
                                    token,
                                )
                                stmt = query_result.get("statement_response", {})
                                manifest = stmt.get("manifest", {})
                                columns = [c.get("name", "") for c in manifest.get("schema", {}).get("columns", [])]
                                result_data = stmt.get("result", {})
                                data_array = result_data.get("data_array", [])
                                result.columns = columns
                                result.data = data_array
                                result.row_count = len(data_array)
                            except Exception as e:
                                logger.warning(f"Failed to fetch query result: {e}")
            return result

        await _async_sleep(_POLL_INTERVAL)

    return GenieResponse(
        status="TIMEOUT",
        error="Genie response timed out",
        text_response="The query took too long to complete. Try a simpler question or try again later.",
        conversation_id=conversation_id,
        message_id=message_id,
    )


async def _async_sleep(seconds: float):
    """Async sleep."""
    import asyncio
    await asyncio.sleep(seconds)


@genie_router.post("/ask", response_model=GenieResponse)
async def ask_genie(body: AskRequest, request: Request):
    """Start a new Genie conversation with a question."""
    try:
        host, token = _get_databricks_auth(request)
    except HTTPException as e:
        return GenieResponse(
            status="FAILED",
            error=e.detail,
            text_response="The assistant service is not available. Please try again later.",
        )

    try:
        resp = await _genie_api(
            "POST",
            "/start-conversation",
            host,
            token,
            json_body={"content": body.question},
        )
    except HTTPException as e:
        error_msg = e.detail[:200] if e.detail else f"HTTP {e.status_code}"
        if e.status_code == 403:
            text = "Access denied. You may not have permission to use the assistant."
        elif e.status_code == 404:
            text = "The Genie Space could not be found. It may have been deleted."
        else:
            text = f"The assistant encountered an error. Please try again."
        return GenieResponse(status="FAILED", error=error_msg, text_response=text)
    except Exception as e:
        logger.error(f"Genie start-conversation failed: {e}")
        return GenieResponse(
            status="FAILED",
            error=str(e),
            text_response="Failed to connect to the assistant. Please try again.",
        )

    conversation_id = resp.get("conversation_id")
    message_id = resp.get("message_id")

    if not conversation_id or not message_id:
        return GenieResponse(
            status="FAILED",
            error="Missing conversation_id or message_id in response",
            text_response="The assistant returned an unexpected response. Please try again.",
        )

    return await _poll_message(host, token, conversation_id, message_id)


@genie_router.post("/followup", response_model=GenieResponse)
async def followup_genie(body: FollowupRequest, request: Request):
    """Send a follow-up message in an existing Genie conversation."""
    try:
        host, token = _get_databricks_auth(request)
    except HTTPException as e:
        return GenieResponse(
            conversation_id=body.conversation_id,
            status="FAILED",
            error=e.detail,
            text_response="The assistant service is not available. Please try again later.",
        )

    try:
        resp = await _genie_api(
            "POST",
            f"/conversations/{body.conversation_id}/messages",
            host,
            token,
            json_body={"content": body.question},
        )
    except HTTPException as e:
        error_msg = e.detail[:200] if e.detail else f"HTTP {e.status_code}"
        if e.status_code == 403:
            text = "Access denied. You may not have permission to use the assistant."
        elif e.status_code == 404:
            text = "The conversation could not be found. Please start a new one."
        else:
            text = "The assistant encountered an error. Please try again."
        return GenieResponse(
            conversation_id=body.conversation_id,
            status="FAILED",
            error=error_msg,
            text_response=text,
        )
    except Exception as e:
        logger.error(f"Genie followup failed: {e}")
        return GenieResponse(
            conversation_id=body.conversation_id,
            status="FAILED",
            error=str(e),
            text_response="Failed to connect to the assistant. Please try again.",
        )

    message_id = resp.get("message_id") or resp.get("id")
    if not message_id:
        return GenieResponse(
            conversation_id=body.conversation_id,
            status="FAILED",
            error="Missing message_id in response",
            text_response="The assistant returned an unexpected response. Please try again.",
        )

    return await _poll_message(host, token, body.conversation_id, message_id)


@genie_router.get("/space")
async def get_genie_space_info():
    """Return the configured Genie Space ID for the frontend."""
    return {"space_id": GENIE_SPACE_ID}
