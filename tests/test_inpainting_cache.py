"""Tests for inpainting tile cache and cache reload (reprocessing).

Covers:
- Lakebase tile cache: store, retrieve, freshness (ETag), eviction, stats
- Inpainting API routes: /status, /cache-stats, /cache, /clean-tile, /reprocess
- Two-phase tile loading: cache hit, stale detection, background re-inpaint
"""

import base64
import io
import json
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.backend.main import app

pytestmark = pytest.mark.api


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_lakebase():
    """A mock LakebaseService with tile cache methods."""
    service = MagicMock()
    service.is_available = True
    service.get_cached_tile.return_value = None
    service.store_cached_tile.return_value = True
    service.clear_tile_cache.return_value = 0
    service.get_tile_cache_stats.return_value = {
        "total_tiles": 10,
        "total_aircraft_removed": 5,
        "airports_covered": 2,
        "avg_processing_ms": 1200,
        "oldest_tile": "2026-04-01T00:00:00+00:00",
        "newest_tile": "2026-05-10T12:00:00+00:00",
        "cache_size": "4 MB",
    }
    service.get_cached_tile_urls.return_value = []
    return service


@pytest.fixture
def sample_image_b64():
    """A minimal 2x2 white PNG encoded as base64."""
    from PIL import Image
    img = Image.new("RGB", (2, 2), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


@pytest.fixture
def sample_image_bytes():
    """Minimal PNG image bytes."""
    from PIL import Image
    img = Image.new("RGB", (2, 2), (200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Lakebase tile cache unit tests
# ---------------------------------------------------------------------------

class TestLakebaseTileCacheOperations:
    """Unit tests for tile cache methods in LakebaseService."""

    def _make_service(self, mock_conn):
        """Create a LakebaseService with mocked connections."""
        import os
        env_vars = {"LAKEBASE_CONNECTION_STRING": "postgresql://user:pass@host:5432/db"}
        with patch.dict(os.environ, env_vars, clear=True):
            with patch("app.backend.services.lakebase_service.PSYCOPG2_AVAILABLE", True):
                from app.backend.services.lakebase_service import LakebaseService
                service = LakebaseService()
                service._tile_cache_ensured = True  # Skip table creation
                service._get_connection = Mock(return_value=mock_conn)
                service._get_read_connection = Mock(return_value=mock_conn)
                return service

    def _mock_conn_with_cursor(self, fetchone_result=None, fetchall_result=None, rowcount=0):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = fetchone_result
        mock_cursor.fetchall.return_value = fetchall_result or []
        mock_cursor.rowcount = rowcount
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        return mock_conn, mock_cursor

    def test_get_cached_tile_miss(self):
        """Cache miss returns None."""
        mock_conn, mock_cursor = self._mock_conn_with_cursor(fetchone_result=None)
        service = self._make_service(mock_conn)

        result = service.get_cached_tile(15, 100, 200)
        assert result is None

    def test_get_cached_tile_hit(self):
        """Cache hit returns image bytes and metadata."""
        cached_row = {
            "inpainted_image": memoryview(b"fake_png_data"),
            "aircraft_count": 3,
            "original_etag": '"abc123"',
            "original_last_modified": "Mon, 01 Apr 2026 00:00:00 GMT",
            "detections_json": '[{"x1": 10, "y1": 10, "x2": 50, "y2": 50}]',
        }
        mock_conn, _ = self._mock_conn_with_cursor(fetchone_result=cached_row)
        service = self._make_service(mock_conn)

        result = service.get_cached_tile(15, 100, 200)
        assert result is not None
        assert result["image_bytes"] == b"fake_png_data"
        assert result["aircraft_count"] == 3
        assert result["etag"] == '"abc123"'

    def test_get_cached_tile_etag_match(self):
        """Cache hit with matching ETag returns the cached tile."""
        cached_row = {
            "inpainted_image": memoryview(b"cached_image"),
            "aircraft_count": 1,
            "original_etag": '"etag_v1"',
            "original_last_modified": None,
            "detections_json": "[]",
        }
        mock_conn, _ = self._mock_conn_with_cursor(fetchone_result=cached_row)
        service = self._make_service(mock_conn)

        result = service.get_cached_tile(15, 100, 200, source_etag='"etag_v1"')
        assert result is not None
        assert result["image_bytes"] == b"cached_image"

    def test_get_cached_tile_etag_mismatch_returns_none(self):
        """Cache with mismatched ETag is treated as stale (returns None)."""
        cached_row = {
            "inpainted_image": memoryview(b"old_image"),
            "aircraft_count": 2,
            "original_etag": '"etag_v1"',
            "original_last_modified": None,
            "detections_json": "[]",
        }
        mock_conn, _ = self._mock_conn_with_cursor(fetchone_result=cached_row)
        service = self._make_service(mock_conn)

        result = service.get_cached_tile(15, 100, 200, source_etag='"etag_v2"')
        assert result is None

    def test_get_cached_tile_no_source_etag_ignores_freshness(self):
        """Without source_etag, any cached version is returned (no freshness check)."""
        cached_row = {
            "inpainted_image": memoryview(b"any_image"),
            "aircraft_count": 0,
            "original_etag": '"old_etag"',
            "original_last_modified": None,
            "detections_json": None,
        }
        mock_conn, _ = self._mock_conn_with_cursor(fetchone_result=cached_row)
        service = self._make_service(mock_conn)

        result = service.get_cached_tile(15, 100, 200, source_etag=None)
        assert result is not None

    def test_store_cached_tile_upserts(self):
        """Store inserts or updates a tile in the cache."""
        mock_conn, mock_cursor = self._mock_conn_with_cursor()
        service = self._make_service(mock_conn)

        result = service.store_cached_tile(
            zoom=15, tile_x=100, tile_y=200,
            image_bytes=b"clean_image",
            aircraft_count=2,
            detections_json='[{"x1": 10}]',
            source_etag='"new_etag"',
            source_last_modified="Tue, 10 May 2026 12:00:00 GMT",
            airport_icao="KSFO",
            processing_time_ms=1500,
        )
        assert result is True
        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO satellite_tile_cache" in sql
        assert "ON CONFLICT" in sql

    def test_store_cached_tile_unavailable(self):
        """Store returns False when service unavailable."""
        import os
        with patch.dict(os.environ, {}, clear=True):
            from app.backend.services.lakebase_service import LakebaseService
            service = LakebaseService()
            result = service.store_cached_tile(
                zoom=15, tile_x=1, tile_y=1,
                image_bytes=b"x", aircraft_count=0,
            )
            assert result is False

    def test_clear_tile_cache_all(self):
        """Clear all tiles."""
        mock_conn, mock_cursor = self._mock_conn_with_cursor(rowcount=5)
        service = self._make_service(mock_conn)

        deleted = service.clear_tile_cache()
        assert deleted == 5
        sql = mock_cursor.execute.call_args[0][0]
        assert "DELETE FROM satellite_tile_cache" in sql
        assert "WHERE" not in sql

    def test_clear_tile_cache_by_airport(self):
        """Clear tiles for a specific airport."""
        mock_conn, mock_cursor = self._mock_conn_with_cursor(rowcount=3)
        service = self._make_service(mock_conn)

        deleted = service.clear_tile_cache("ksfo")
        assert deleted == 3
        sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE airport_icao" in sql

    def test_get_tile_cache_stats(self):
        """Stats query returns aggregated cache info."""
        stats_row = {
            "total_tiles": 42,
            "total_aircraft_removed": 15,
            "airports_covered": 3,
            "avg_processing_ms": 980,
            "oldest_tile": "2026-03-15T00:00:00+00:00",
            "newest_tile": "2026-05-12T10:00:00+00:00",
            "cache_size": "12 MB",
        }
        mock_conn, _ = self._mock_conn_with_cursor(fetchone_result=stats_row)
        service = self._make_service(mock_conn)

        result = service.get_tile_cache_stats()
        assert result["total_tiles"] == 42
        assert result["cache_size"] == "12 MB"

    def test_get_cached_tile_urls_all(self):
        """Get all cached tile metadata."""
        rows = [
            {"tile_key": "15/100/200", "zoom": 15, "tile_x": 100, "tile_y": 200, "original_etag": '"e1"'},
            {"tile_key": "15/101/200", "zoom": 15, "tile_x": 101, "tile_y": 200, "original_etag": '"e2"'},
        ]
        mock_conn, mock_cursor = self._mock_conn_with_cursor(fetchall_result=rows)
        service = self._make_service(mock_conn)

        result = service.get_cached_tile_urls()
        assert len(result) == 2
        assert result[0]["tile_key"] == "15/100/200"

    def test_get_cached_tile_urls_by_airport(self):
        """Get cached tile metadata filtered by airport."""
        rows = [{"tile_key": "15/50/60", "zoom": 15, "tile_x": 50, "tile_y": 60, "original_etag": '"e3"'}]
        mock_conn, mock_cursor = self._mock_conn_with_cursor(fetchall_result=rows)
        service = self._make_service(mock_conn)

        result = service.get_cached_tile_urls("EDDF")
        assert len(result) == 1
        sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE airport_icao" in sql

    @patch("random.random", return_value=0.005)
    def test_eviction_triggers_on_low_random(self, mock_random):
        """Eviction runs when random < 0.01."""
        mock_conn, mock_cursor = self._mock_conn_with_cursor(rowcount=2)
        service = self._make_service(mock_conn)

        service._maybe_evict_old_tiles(max_age_days=30)
        sql = mock_cursor.execute.call_args[0][0]
        assert "DELETE FROM satellite_tile_cache" in sql
        assert "updated_at" in sql

    @patch("random.random", return_value=0.5)
    def test_eviction_skips_on_high_random(self, mock_random):
        """Eviction is skipped most of the time (random > 0.01)."""
        mock_conn, mock_cursor = self._mock_conn_with_cursor()
        service = self._make_service(mock_conn)

        service._maybe_evict_old_tiles(max_age_days=30)
        mock_cursor.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Inpainting API route tests
# ---------------------------------------------------------------------------

class TestInpaintingStatusEndpoint:
    """Tests for GET /api/inpainting/status."""

    def test_status_returns_cache_stats(self, client, mock_lakebase):
        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            with patch("app.backend.api.inpainting._DATABRICKS_HOST", ""):
                response = client.get("/api/inpainting/status")
        assert response.status_code == 200
        data = response.json()
        assert "cache" in data
        assert data["cache"]["total_tiles"] == 10


class TestInpaintingCacheStatsEndpoint:
    """Tests for GET /api/inpainting/cache-stats."""

    def test_cache_stats_success(self, client, mock_lakebase):
        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            response = client.get("/api/inpainting/cache-stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_tiles"] == 10
        assert data["airports_covered"] == 2

    def test_cache_stats_unavailable(self, client):
        mock_service = MagicMock()
        mock_service.get_tile_cache_stats.return_value = None
        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_service):
            response = client.get("/api/inpainting/cache-stats")
        assert response.status_code == 200
        assert "error" in response.json()


class TestInpaintingClearCacheEndpoint:
    """Tests for DELETE /api/inpainting/cache."""

    def test_clear_all(self, client, mock_lakebase):
        mock_lakebase.clear_tile_cache.return_value = 15
        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            response = client.delete("/api/inpainting/cache")
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 15
        mock_lakebase.clear_tile_cache.assert_called_once_with(None)

    def test_clear_by_airport(self, client, mock_lakebase):
        mock_lakebase.clear_tile_cache.return_value = 5
        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            response = client.delete("/api/inpainting/cache?airport_icao=KJFK")
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 5
        assert data["airport_icao"] == "KJFK"


class TestCleanTileCacheFlow:
    """Tests for POST /api/inpainting/clean-tile cache interactions."""

    def test_cache_hit_returns_cached_image(self, client, mock_lakebase, sample_image_bytes):
        """When cache has a fresh tile, return it without calling serving endpoint."""
        mock_lakebase.get_cached_tile.return_value = {
            "image_bytes": sample_image_bytes,
            "aircraft_count": 2,
            "etag": '"etag1"',
            "last_modified": None,
            "detections": '[{"x1": 10}]',
        }
        tile_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/15/200/100"

        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            with patch("app.backend.api.inpainting.httpx.AsyncClient") as mock_httpx:
                # Mock the HEAD request for source ETag
                mock_head_resp = MagicMock()
                mock_head_resp.headers = {"ETag": '"etag1"'}
                mock_client_instance = AsyncMock()
                mock_client_instance.head.return_value = mock_head_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_httpx.return_value = mock_client_instance

                response = client.post(f"/api/inpainting/clean-tile?url={tile_url}")

        assert response.status_code == 200
        assert response.headers["X-Cache"] == "HIT"
        assert response.headers["X-Aircraft-Count"] == "2"

    def test_cache_only_miss_returns_204(self, client, mock_lakebase):
        """cache_only=true with no cached tile returns 204."""
        mock_lakebase.get_cached_tile.return_value = None
        tile_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/15/200/100"

        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            with patch("app.backend.api.inpainting.httpx.AsyncClient") as mock_httpx:
                mock_head_resp = MagicMock()
                mock_head_resp.headers = {"ETag": '"new_etag"'}
                mock_client_instance = AsyncMock()
                mock_client_instance.head.return_value = mock_head_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_httpx.return_value = mock_client_instance

                response = client.post(f"/api/inpainting/clean-tile?url={tile_url}&cache_only=true")

        assert response.status_code == 204
        assert response.headers["X-Cache"] == "MISS"

    def test_cache_only_stale_returns_stale_image(self, client, mock_lakebase, sample_image_bytes):
        """cache_only=true with stale tile returns image with X-Cache: STALE."""
        # First call (with ETag) returns None (stale), second call (without ETag) returns cached
        mock_lakebase.get_cached_tile.side_effect = [
            None,  # ETag mismatch
            {"image_bytes": sample_image_bytes, "aircraft_count": 1, "etag": '"old"', "detections": "[]"},
        ]
        tile_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/15/200/100"

        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            with patch("app.backend.api.inpainting.httpx.AsyncClient") as mock_httpx:
                mock_head_resp = MagicMock()
                mock_head_resp.headers = {"ETag": '"new_etag"'}
                mock_client_instance = AsyncMock()
                mock_client_instance.head.return_value = mock_head_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_httpx.return_value = mock_client_instance

                response = client.post(f"/api/inpainting/clean-tile?url={tile_url}&cache_only=true")

        assert response.status_code == 200
        assert response.headers["X-Cache"] == "STALE"

    def test_no_url_no_file_returns_400(self, client):
        """Missing both url and file returns 400."""
        response = client.post("/api/inpainting/clean-tile")
        assert response.status_code == 400


class TestReprocessEndpoint:
    """Tests for POST /api/inpainting/reprocess."""

    def test_reprocess_no_cached_tiles(self, client, mock_lakebase):
        """No cached tiles means nothing to reprocess."""
        mock_lakebase.get_cached_tile_urls.return_value = []
        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            response = client.post("/api/inpainting/reprocess")
        assert response.status_code == 200
        data = response.json()
        assert data["checked"] == 0
        assert data["stale"] == 0
        assert data["reprocessed"] == 0

    def test_reprocess_all_fresh(self, client, mock_lakebase):
        """All tiles have matching ETags — nothing to reprocess."""
        mock_lakebase.get_cached_tile_urls.return_value = [
            {"tile_key": "15/100/200", "zoom": 15, "tile_x": 100, "tile_y": 200, "original_etag": '"etag1"'},
        ]

        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            with patch("app.backend.api.inpainting.httpx.AsyncClient") as mock_httpx:
                mock_head_resp = MagicMock()
                mock_head_resp.status_code = 200
                mock_head_resp.headers = {"ETag": '"etag1"'}

                mock_client_instance = AsyncMock()
                mock_client_instance.head.return_value = mock_head_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_httpx.return_value = mock_client_instance

                with patch("app.backend.api.inpainting._get_auth_token", return_value="test_token"):
                    response = client.post("/api/inpainting/reprocess")

        assert response.status_code == 200
        data = response.json()
        assert data["checked"] == 1
        assert data["stale"] == 0
        assert data["reprocessed"] == 0

    def test_reprocess_stale_tile_success(self, client, mock_lakebase, sample_image_b64):
        """Stale tile gets re-inpainted and stored in cache."""
        mock_lakebase.get_cached_tile_urls.return_value = [
            {"tile_key": "15/100/200", "zoom": 15, "tile_x": 100, "tile_y": 200, "original_etag": '"old_etag"'},
        ]

        from PIL import Image
        img = Image.new("RGB", (2, 2), (100, 100, 100))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        tile_bytes = buf.getvalue()

        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            with patch("app.backend.api.inpainting.httpx.AsyncClient") as mock_httpx:
                mock_head_resp = MagicMock()
                mock_head_resp.status_code = 200
                mock_head_resp.headers = {"ETag": '"new_etag"'}

                mock_get_resp = MagicMock()
                mock_get_resp.status_code = 200
                mock_get_resp.content = tile_bytes
                mock_get_resp.headers = {"ETag": '"new_etag"', "Last-Modified": "Mon, 12 May 2026"}
                mock_get_resp.raise_for_status = Mock()

                mock_post_resp = MagicMock()
                mock_post_resp.status_code = 200
                mock_post_resp.raise_for_status = Mock()
                mock_post_resp.json.return_value = {
                    "predictions": [
                        {"clean_image_b64": sample_image_b64, "aircraft_count": 1, "detections": "[]"}
                    ]
                }

                mock_client_instance = AsyncMock()
                mock_client_instance.head.return_value = mock_head_resp
                mock_client_instance.get.return_value = mock_get_resp
                mock_client_instance.post.return_value = mock_post_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_httpx.return_value = mock_client_instance

                with patch("app.backend.api.inpainting._get_auth_token", return_value="test_token"):
                    response = client.post("/api/inpainting/reprocess?airport_icao=KSFO")

        assert response.status_code == 200
        data = response.json()
        assert data["checked"] == 1
        assert data["stale"] == 1
        assert data["reprocessed"] == 1
        assert data["errors"] == 0
        mock_lakebase.store_cached_tile.assert_called_once()

    def test_reprocess_requires_auth(self, client, mock_lakebase):
        """Reprocess requires authentication."""
        mock_lakebase.get_cached_tile_urls.return_value = [
            {"tile_key": "15/1/1", "zoom": 15, "tile_x": 1, "tile_y": 1, "original_etag": '"x"'},
        ]
        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            with patch("app.backend.api.inpainting._get_auth_token", return_value=None):
                response = client.post("/api/inpainting/reprocess")
        assert response.status_code == 401

    def test_reprocess_by_airport(self, client, mock_lakebase):
        """Reprocess filters by airport_icao."""
        mock_lakebase.get_cached_tile_urls.return_value = []
        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            response = client.post("/api/inpainting/reprocess?airport_icao=EDDF")
        assert response.status_code == 200
        mock_lakebase.get_cached_tile_urls.assert_called_once_with("EDDF")


class TestCleanTileEndToEnd:
    """Integration-style tests for the full clean-tile flow."""

    def test_full_flow_miss_inpaint_cache(self, client, mock_lakebase, sample_image_b64, sample_image_bytes):
        """On cache miss: fetch tile, call serving, cache result, return clean tile."""
        mock_lakebase.get_cached_tile.return_value = None
        tile_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/15/200/100"

        with patch("app.backend.api.inpainting.get_lakebase_service", return_value=mock_lakebase):
            with patch("app.backend.api.inpainting.httpx.AsyncClient") as mock_httpx:
                # HEAD for ETag
                mock_head_resp = MagicMock()
                mock_head_resp.headers = {"ETag": '"source_etag"', "Last-Modified": "Mon, 12 May 2026"}

                # GET for full tile
                mock_get_resp = MagicMock()
                mock_get_resp.status_code = 200
                mock_get_resp.content = sample_image_bytes
                mock_get_resp.headers = {"ETag": '"source_etag"', "Last-Modified": "Mon, 12 May 2026"}
                mock_get_resp.raise_for_status = Mock()

                # POST to serving endpoint
                mock_post_resp = MagicMock()
                mock_post_resp.status_code = 200
                mock_post_resp.raise_for_status = Mock()
                mock_post_resp.json.return_value = {
                    "dataframe_split": {
                        "data": [[sample_image_b64, 2, '[{"x1":10,"y1":10,"x2":50,"y2":50}]']]
                    }
                }

                mock_client_instance = AsyncMock()
                mock_client_instance.head.return_value = mock_head_resp
                mock_client_instance.get.return_value = mock_get_resp
                mock_client_instance.post.return_value = mock_post_resp
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_httpx.return_value = mock_client_instance

                with patch("app.backend.api.inpainting._get_auth_token", return_value="token"):
                    response = client.post(
                        f"/api/inpainting/clean-tile?url={tile_url}&airport_icao=KSFO"
                    )

        assert response.status_code == 200
        assert response.headers["X-Cache"] == "MISS"
        assert response.headers["X-Aircraft-Count"] == "2"
        assert int(response.headers["X-Processing-Ms"]) >= 0
        # Verify tile was cached
        mock_lakebase.store_cached_tile.assert_called_once()
        call_kwargs = mock_lakebase.store_cached_tile.call_args
        assert call_kwargs[1]["zoom"] == 15 or call_kwargs.kwargs.get("zoom") == 15


class TestWakeEndpoint:
    """Tests for POST /api/inpainting/wake."""

    def test_wake_no_token(self, client):
        """Wake without auth returns 401."""
        with patch("app.backend.api.inpainting._get_auth_token", return_value=None):
            response = client.post("/api/inpainting/wake")
        assert response.status_code == 401

    def test_wake_already_ready(self, client):
        """Wake when endpoint already running returns ready status."""
        with patch("app.backend.api.inpainting._get_auth_token", return_value="tok"):
            with patch("app.backend.api.inpainting._DATABRICKS_HOST", "https://workspace.databricks.com"):
                with patch("app.backend.api.inpainting.httpx.AsyncClient") as mock_httpx:
                    mock_status_resp = MagicMock()
                    mock_status_resp.status_code = 200
                    mock_status_resp.json.return_value = {"state": {"ready": "READY"}}

                    mock_client_instance = AsyncMock()
                    mock_client_instance.get.return_value = mock_status_resp
                    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                    mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                    mock_httpx.return_value = mock_client_instance

                    response = client.post("/api/inpainting/wake")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"
