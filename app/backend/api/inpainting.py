"""Inpainting API — proxy to the aircraft removal serving endpoint.

Accepts satellite tile images (by URL or direct upload), sends them
through the YOLO + LaMa inpainting serving endpoint, and returns
clean tiles with aircraft removed.

Tile results are cached in Lakebase (PostgreSQL) so subsequent requests
for the same tile are served from cache.  Source ETag/Last-Modified headers
are stored alongside the cached tile — when the satellite provider updates
imagery, the cache is automatically invalidated and re-inpainted.
"""

import asyncio
import base64
import json
import logging
import os
import re
import time
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import Response

from app.backend.services.lakebase_service import get_lakebase_service

logger = logging.getLogger(__name__)

inpainting_router = APIRouter(prefix="/api/inpainting", tags=["inpainting"])

_DATABRICKS_HOST = os.getenv("DATABRICKS_HOST", "")
_SERVING_ENDPOINT_NAME = os.getenv(
    "INPAINTING_ENDPOINT_NAME", "airport-dt-aircraft-inpainting-dev"
)

# Esri tile URL pattern: .../tile/{z}/{y}/{x}
_TILE_COORD_RE = re.compile(r"/tile/(\d+)/(\d+)/(\d+)")


def _get_serving_url() -> str:
    """Build the serving endpoint URL."""
    host = _DATABRICKS_HOST.rstrip("/")
    if not host.startswith("http"):
        host = f"https://{host}"
    return f"{host}/serving-endpoints/{_SERVING_ENDPOINT_NAME}/invocations"


def _get_auth_token(request: Request) -> Optional[str]:
    """Get an auth token for calling the serving endpoint.

    Priority:
    1. Bearer token from incoming request (on-behalf-of / external caller)
    2. DATABRICKS_TOKEN env var
    3. WorkspaceClient M2M OAuth (Databricks Apps ambient credentials)
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    if tok := os.getenv("DATABRICKS_TOKEN"):
        return tok
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        return w.config.authenticate()["Authorization"].removeprefix("Bearer ")
    except Exception as e:
        logger.warning("WorkspaceClient auth failed: %s", e)
    return None


def _parse_tile_coords(url: str) -> tuple[int, int, int] | None:
    """Extract (zoom, x, y) from an Esri tile URL."""
    m = _TILE_COORD_RE.search(url)
    if m:
        z, y, x = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (z, x, y)
    return None


@inpainting_router.get("/status")
async def inpainting_status(request: Request):
    """Health check for the inpainting serving endpoint + cache stats."""
    # Check serving endpoint first (fast) — don't block on Lakebase
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            host = _DATABRICKS_HOST.rstrip("/")
            if not host.startswith("http"):
                host = f"https://{host}"
            url = f"{host}/api/2.0/serving-endpoints/{_SERVING_ENDPOINT_NAME}"
            token = _get_auth_token(request) or ""
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                data = resp.json()
                state = data.get("state", {}).get("ready", "UNKNOWN")
                result = {
                    "status": "ok",
                    "endpoint": _SERVING_ENDPOINT_NAME,
                    "ready": state,
                }
            else:
                result = {
                    "status": "error",
                    "endpoint": _SERVING_ENDPOINT_NAME,
                    "http_status": resp.status_code,
                }
    except Exception as e:
        result = {
            "status": "error",
            "endpoint": _SERVING_ENDPOINT_NAME,
            "error": str(e),
        }

    # Fetch cache stats in a thread — Lakebase connection is synchronous
    # and can hang if credentials are refreshing or endpoint is cold
    import asyncio
    try:
        lakebase = get_lakebase_service()
        result["cache"] = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, lakebase.get_tile_cache_stats),
            timeout=5.0,
        )
    except Exception:
        result["cache"] = None

    return result


# Minimal 1x1 white PNG for wake-up ping (68 bytes)
_WAKE_PING_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
    "Nl7BcQAAAABJRU5ErkJggg=="
)


@inpainting_router.post("/wake")
async def wake_endpoint(request: Request):
    """Trigger scale-up of the inpainting serving endpoint.

    Scale-to-zero endpoints wake on any invocation request.
    We send a tiny 1x1 PNG to trigger the wake without blocking —
    the request will queue while the endpoint scales up.
    """
    # First check if already ready
    token = _get_auth_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="No auth token available")

    host = _DATABRICKS_HOST.rstrip("/")
    if not host.startswith("http"):
        host = f"https://{host}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            status_url = f"{host}/api/2.0/serving-endpoints/{_SERVING_ENDPOINT_NAME}"
            resp = await client.get(
                status_url, headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code == 200:
                state = resp.json().get("state", {}).get("ready", "UNKNOWN")
                if state == "READY":
                    return {"status": "ready", "message": "Endpoint is already running"}
    except httpx.HTTPError:
        pass  # Proceed to wake attempt anyway

    # Send a fire-and-forget invocation to trigger scale-up
    serving_url = _get_serving_url()
    payload = {
        "dataframe_split": {
            "columns": ["image_b64"],
            "data": [[_WAKE_PING_B64]],
        }
    }

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Don't wait for the full response — just send the request
            # The endpoint will start scaling up even if we time out
            await client.post(
                serving_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.TimeoutException:
        pass  # Expected — endpoint is cold, request queued
    except httpx.HTTPError:
        pass  # Endpoint will still wake from the attempt

    return {
        "status": "waking",
        "message": "Wake-up request sent. Endpoint is scaling up (may take 2-5 minutes).",
    }


@inpainting_router.get("/cache-stats")
async def cache_stats():
    """Return tile cache statistics from Lakebase."""
    lakebase = get_lakebase_service()
    stats = lakebase.get_tile_cache_stats()
    if stats:
        return stats
    return {"error": "Lakebase tile cache not available"}


@inpainting_router.delete("/cache")
async def clear_cache(
    airport_icao: Optional[str] = Query(None, description="Airport ICAO to clear (all if omitted)"),
):
    """Clear cached inpainted tiles from Lakebase."""
    lakebase = get_lakebase_service()
    deleted = lakebase.clear_tile_cache(airport_icao)
    return {"deleted": deleted, "airport_icao": airport_icao}


_ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


@inpainting_router.post("/reprocess")
async def reprocess_stale_tiles(
    request: Request,
    airport_icao: Optional[str] = Query(None, description="Airport ICAO to reprocess (all if omitted)"),
):
    """Re-inpaint tiles whose satellite source imagery has been updated.

    Checks ETag of each cached tile against the current source. Only tiles
    with mismatched ETags are re-processed. Tiles with matching ETags are kept.
    Returns a summary of how many tiles were checked and reprocessed.
    """
    lakebase = get_lakebase_service()
    cached_tiles = lakebase.get_cached_tile_urls(airport_icao)
    if not cached_tiles:
        return {"checked": 0, "stale": 0, "reprocessed": 0, "errors": 0}

    token = _get_auth_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="No auth token available")

    stale_count = 0
    reprocessed = 0
    errors = 0

    serving_url = _get_serving_url()

    async with httpx.AsyncClient(timeout=300) as client:
        for tile in cached_tiles:
            z, tx, ty = tile["zoom"], tile["tile_x"], tile["tile_y"]
            cached_etag = tile.get("original_etag")

            tile_url = _ESRI_TILE_URL.replace("{z}", str(z)).replace("{y}", str(ty)).replace("{x}", str(tx))

            # Check current source ETag
            try:
                head_resp = await client.head(tile_url)
                current_etag = head_resp.headers.get("ETag")
            except httpx.HTTPError:
                continue

            if current_etag and cached_etag and current_etag == cached_etag:
                continue  # Still fresh

            stale_count += 1

            # Fetch fresh tile and re-inpaint
            try:
                tile_resp = await client.get(tile_url)
                tile_resp.raise_for_status()
                image_bytes = tile_resp.content
                source_etag = tile_resp.headers.get("ETag")
                source_last_modified = tile_resp.headers.get("Last-Modified")
            except httpx.HTTPError:
                errors += 1
                continue

            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            payload = {"dataframe_split": {"columns": ["image_b64"], "data": [[image_b64]]}}

            try:
                resp = await client.post(
                    serving_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                errors += 1
                continue

            result = resp.json()
            try:
                predictions = result.get("predictions", result.get("dataframe_split", {}))
                if isinstance(predictions, dict):
                    data = predictions.get("data", [[]])[0]
                    clean_b64 = data[0] if data else ""
                    aircraft_count = data[1] if len(data) > 1 else 0
                    detections_json = data[2] if len(data) > 2 else "[]"
                elif isinstance(predictions, list):
                    pred = predictions[0]
                    clean_b64 = pred.get("clean_image_b64", "")
                    aircraft_count = pred.get("aircraft_count", 0)
                    detections_json = pred.get("detections", "[]")
                else:
                    errors += 1
                    continue
            except (KeyError, IndexError):
                errors += 1
                continue

            clean_bytes = base64.b64decode(clean_b64)
            lakebase.store_cached_tile(
                zoom=z, tile_x=tx, tile_y=ty,
                image_bytes=clean_bytes,
                aircraft_count=int(aircraft_count),
                detections_json=detections_json if isinstance(detections_json, str) else json.dumps(detections_json),
                source_etag=source_etag,
                source_last_modified=source_last_modified,
                airport_icao=airport_icao,
            )
            reprocessed += 1

    return {
        "checked": len(cached_tiles),
        "stale": stale_count,
        "reprocessed": reprocessed,
        "errors": errors,
    }


@inpainting_router.post("/clean-tile")
async def clean_tile(
    request: Request,
    url: Optional[str] = Query(None, description="Satellite tile URL to fetch and clean"),
    airport_icao: Optional[str] = Query(None, description="Airport ICAO code for cache tagging"),
    cache_only: bool = Query(False, description="Only check cache, never call inpainting endpoint"),
    file: Optional[UploadFile] = File(None, description="Direct image upload"),
):
    """Remove aircraft from a satellite tile image.

    Either provide a tile URL (fetched server-side) or upload an image directly.
    Returns the cleaned PNG image.

    Cache flow:
    1. Parse tile coords from URL
    2. Fetch source tile headers (ETag/Last-Modified) for freshness check
    3. Check Lakebase cache — if hit with matching ETag, return cached
    4. On miss: if cache_only, return stale cached tile (X-Cache: STALE) or 204 (X-Cache: MISS)
    5. Otherwise: fetch full tile, call serving endpoint, cache result
    """
    lakebase = get_lakebase_service()
    tile_coords = _parse_tile_coords(url) if url else None

    if url:
        # --- Step 1: Check Lakebase cache first ---
        if tile_coords:
            z, tx, ty = tile_coords

            # HEAD request to get source ETag without downloading the full tile
            source_etag = None
            source_last_modified = None
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    head_resp = await client.head(url)
                    source_etag = head_resp.headers.get("ETag")
                    source_last_modified = head_resp.headers.get("Last-Modified")
            except httpx.HTTPError:
                pass  # Proceed without freshness check

            cached = lakebase.get_cached_tile(z, tx, ty, source_etag=source_etag)
            if cached:
                logger.debug("Lakebase cache hit for tile %d/%d/%d", z, tx, ty)
                resp_headers = {
                    "X-Cache": "HIT",
                    "X-Aircraft-Count": str(cached["aircraft_count"]),
                }
                if cached.get("detections"):
                    resp_headers["X-Detections"] = (
                        cached["detections"] if isinstance(cached["detections"], str)
                        else json.dumps(cached["detections"])
                    )
                return Response(
                    content=cached["image_bytes"],
                    media_type="image/png",
                    headers=resp_headers,
                )

            # Fresh cache miss — in cache_only mode, try returning stale version
            if cache_only:
                stale = lakebase.get_cached_tile(z, tx, ty, source_etag=None)
                if stale:
                    logger.debug("Returning stale cached tile for %d/%d/%d", z, tx, ty)
                    stale_headers = {
                        "X-Cache": "STALE",
                        "X-Aircraft-Count": str(stale["aircraft_count"]),
                    }
                    if stale.get("detections"):
                        stale_headers["X-Detections"] = (
                            stale["detections"] if isinstance(stale["detections"], str)
                            else json.dumps(stale["detections"])
                        )
                    return Response(
                        content=stale["image_bytes"],
                        media_type="image/png",
                        headers=stale_headers,
                    )
                return Response(status_code=204, headers={"X-Cache": "MISS"})

        # cache_only with no tile coords or no URL — nothing to check
        if cache_only:
            return Response(status_code=204, headers={"X-Cache": "MISS"})

        # --- Step 2: Fetch the full tile ---
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                image_bytes = resp.content
                if not source_etag:
                    source_etag = resp.headers.get("ETag")
                if not source_last_modified:
                    source_last_modified = resp.headers.get("Last-Modified")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch tile: {e}")

    elif file:
        image_bytes = await file.read()
    else:
        raise HTTPException(status_code=400, detail="Provide either 'url' query param or upload a file")

    # --- Step 3: Call the serving endpoint ---
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

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

    # GPU cold start can take 3-5 minutes; retry with backoff
    t0 = time.monotonic()
    max_attempts = 3
    resp = None
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    serving_url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                break
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(
                "Serving endpoint timeout (attempt %d/%d, %.0fs elapsed)",
                attempt + 1, max_attempts, time.monotonic() - t0,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503 and attempt < max_attempts - 1:
                last_error = e
                logger.warning(
                    "Serving endpoint 503 (scaling up), retry in %ds", 10 * (attempt + 1),
                )
                await asyncio.sleep(10 * (attempt + 1))
            else:
                logger.error("Serving endpoint error: %s", e)
                raise HTTPException(status_code=502, detail=f"Inpainting endpoint error: {e}")
        except httpx.HTTPError as e:
            logger.error("Serving endpoint error: %s", e)
            raise HTTPException(status_code=502, detail=f"Inpainting endpoint error: {e}")

    if resp is None:
        logger.error("Serving endpoint failed after %d attempts: %s", max_attempts, last_error)
        raise HTTPException(
            status_code=503,
            detail=f"Inpainting endpoint not responding (cold start may be in progress). Try again in a minute.",
        )

    processing_ms = int((time.monotonic() - t0) * 1000)

    # Parse response
    result = resp.json()
    try:
        predictions = result.get("predictions", result.get("dataframe_split", {}))
        if isinstance(predictions, dict):
            data = predictions.get("data", [[]])[0]
            clean_b64 = data[0] if data else ""
            aircraft_count = data[1] if len(data) > 1 else 0
            detections_json = data[2] if len(data) > 2 else "[]"
        elif isinstance(predictions, list):
            pred = predictions[0]
            clean_b64 = pred.get("clean_image_b64", "")
            aircraft_count = pred.get("aircraft_count", 0)
            detections_json = pred.get("detections", "[]")
        else:
            clean_b64 = ""
            aircraft_count = 0
            detections_json = "[]"
    except (KeyError, IndexError):
        logger.error("Unexpected serving response: %s", result)
        raise HTTPException(status_code=502, detail="Unexpected response from inpainting endpoint")

    clean_bytes = base64.b64decode(clean_b64)

    # --- Step 4: Cache the result in Lakebase ---
    if tile_coords:
        z, tx, ty = tile_coords
        lakebase.store_cached_tile(
            zoom=z, tile_x=tx, tile_y=ty,
            image_bytes=clean_bytes,
            aircraft_count=int(aircraft_count),
            detections_json=detections_json if isinstance(detections_json, str) else json.dumps(detections_json),
            source_etag=source_etag,
            source_last_modified=source_last_modified,
            airport_icao=airport_icao,
            processing_time_ms=processing_ms,
        )

    det_str = detections_json if isinstance(detections_json, str) else json.dumps(detections_json)
    return Response(
        content=clean_bytes,
        media_type="image/png",
        headers={
            "X-Cache": "MISS",
            "X-Aircraft-Count": str(aircraft_count),
            "X-Processing-Ms": str(processing_ms),
            "X-Detections": det_str,
        },
    )
