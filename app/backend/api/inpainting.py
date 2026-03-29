"""Inpainting API — proxy to the aircraft removal serving endpoint.

Accepts satellite tile images (by URL or direct upload), sends them
through the YOLO + LaMa inpainting serving endpoint, and returns
clean tiles with aircraft removed.
"""

import base64
import io
import logging
import os
from functools import lru_cache
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import Response

logger = logging.getLogger(__name__)

inpainting_router = APIRouter(prefix="/api/inpainting", tags=["inpainting"])

_DATABRICKS_HOST = os.getenv("DATABRICKS_HOST", "")
_SERVING_ENDPOINT_NAME = os.getenv(
    "INPAINTING_ENDPOINT_NAME", "airport-dt-aircraft-inpainting-dev"
)

# Simple in-memory cache for cleaned tiles (tile_url -> clean_image_bytes)
_tile_cache: dict[str, bytes] = {}
_CACHE_MAX_SIZE = 500


def _get_serving_url() -> str:
    """Build the serving endpoint URL."""
    host = _DATABRICKS_HOST.rstrip("/")
    if not host.startswith("http"):
        host = f"https://{host}"
    return f"{host}/serving-endpoints/{_SERVING_ENDPOINT_NAME}/invocations"


def _get_auth_token(request: Request) -> Optional[str]:
    """Extract OAuth token from request for on-behalf-of auth."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    # Databricks Apps: token may be injected by the platform
    return os.getenv("DATABRICKS_TOKEN")


@inpainting_router.get("/status")
async def inpainting_status():
    """Health check for the inpainting serving endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            host = _DATABRICKS_HOST.rstrip("/")
            if not host.startswith("http"):
                host = f"https://{host}"
            url = f"{host}/api/2.0/serving-endpoints/{_SERVING_ENDPOINT_NAME}"
            token = os.getenv("DATABRICKS_TOKEN", "")
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                data = resp.json()
                state = data.get("state", {}).get("ready", "UNKNOWN")
                return {"status": "ok", "endpoint": _SERVING_ENDPOINT_NAME, "ready": state}
            return {"status": "error", "endpoint": _SERVING_ENDPOINT_NAME, "http_status": resp.status_code}
    except Exception as e:
        return {"status": "error", "endpoint": _SERVING_ENDPOINT_NAME, "error": str(e)}


@inpainting_router.post("/clean-tile")
async def clean_tile(
    request: Request,
    url: Optional[str] = Query(None, description="Satellite tile URL to fetch and clean"),
    file: Optional[UploadFile] = File(None, description="Direct image upload"),
):
    """Remove aircraft from a satellite tile image.

    Either provide a tile URL (fetched server-side) or upload an image directly.
    Returns the cleaned PNG image.
    """
    # Get the input image
    if url:
        # Check cache
        if url in _tile_cache:
            logger.debug("Cache hit for tile: %s", url[:80])
            return Response(content=_tile_cache[url], media_type="image/png")

        # Fetch the tile
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                image_bytes = resp.content
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch tile: {e}")
    elif file:
        image_bytes = await file.read()
    else:
        raise HTTPException(status_code=400, detail="Provide either 'url' query param or upload a file")

    # Encode for serving endpoint
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Call the serving endpoint
    token = _get_auth_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="No auth token available")

    serving_url = _get_serving_url()
    payload = {
        "dataframe_split": {
            "columns": ["image_b64"],
            "data": [[image_b64]],
        }
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                serving_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Serving endpoint error: %s", e)
        raise HTTPException(status_code=502, detail=f"Inpainting endpoint error: {e}")

    # Parse response
    result = resp.json()
    try:
        predictions = result.get("predictions", result.get("dataframe_split", {}))
        if isinstance(predictions, dict):
            data = predictions.get("data", [[]])[0]
            clean_b64 = data[0] if data else ""
        elif isinstance(predictions, list):
            clean_b64 = predictions[0].get("clean_image_b64", "")
        else:
            clean_b64 = ""
    except (KeyError, IndexError) as e:
        logger.error("Unexpected serving response: %s", result)
        raise HTTPException(status_code=502, detail="Unexpected response from inpainting endpoint")

    clean_bytes = base64.b64decode(clean_b64)

    # Cache the result
    if url and len(_tile_cache) < _CACHE_MAX_SIZE:
        _tile_cache[url] = clean_bytes

    return Response(content=clean_bytes, media_type="image/png")
