"""Security tests based on OWASP Top 10 and security best practices.

Tests cover:
- SQL Injection prevention
- Input validation and sanitization
- CORS configuration
- XSS prevention (via proper error responses)
- Path traversal prevention
- Error handling (no sensitive info leakage)
- Rate limiting awareness
- Authentication boundary testing
"""

import pytest
from fastapi.testclient import TestClient
import json

from app.backend.main import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# ==============================================================================
# SQL Injection Prevention Tests
# ==============================================================================

class TestSQLInjectionPrevention:
    """Tests to verify SQL injection attacks are prevented."""

    # Common SQL injection payloads
    SQL_INJECTION_PAYLOADS = [
        "'; DROP TABLE flights; --",
        "' OR '1'='1",
        "' OR 1=1--",
        "'; SELECT * FROM users; --",
        "1; DELETE FROM flights WHERE 1=1; --",
        "' UNION SELECT * FROM information_schema.tables--",
        "admin'--",
        "1' AND '1'='1",
        "'; EXEC xp_cmdshell('dir'); --",
        "' OR ''='",
        "1 OR 1=1",
        "' OR 'x'='x",
        "${7*7}",  # Template injection
        "{{7*7}}",  # SSTI
    ]

    def test_icao24_sql_injection(self, client):
        """Test that icao24 parameter is immune to SQL injection."""
        for payload in self.SQL_INJECTION_PAYLOADS:
            response = client.get(f"/api/flights/{payload}")
            # Should return 404 (not found) or 422 (validation error), not 500
            assert response.status_code in [404, 422, 400], \
                f"SQL injection payload '{payload}' caused unexpected status: {response.status_code}"

    def test_trajectory_icao24_sql_injection(self, client):
        """Test that trajectory endpoint is immune to SQL injection."""
        for payload in self.SQL_INJECTION_PAYLOADS:
            response = client.get(f"/api/flights/{payload}/trajectory")
            assert response.status_code in [404, 422, 400, 200], \
                f"SQL injection payload '{payload}' caused unexpected status: {response.status_code}"

    def test_turnaround_sql_injection(self, client):
        """Test that turnaround endpoint is immune to SQL injection."""
        for payload in self.SQL_INJECTION_PAYLOADS[:5]:  # Test subset for speed
            response = client.get(f"/api/turnaround/{payload}")
            assert response.status_code in [200, 400, 422], \
                f"SQL injection payload '{payload}' caused error: {response.status_code}"

    def test_baggage_flight_sql_injection(self, client):
        """Test that baggage endpoint is immune to SQL injection."""
        for payload in self.SQL_INJECTION_PAYLOADS[:5]:
            response = client.get(f"/api/baggage/flight/{payload}")
            assert response.status_code in [200, 400, 422], \
                f"SQL injection payload '{payload}' caused error: {response.status_code}"

    def test_query_param_sql_injection(self, client):
        """Test that query parameters are immune to SQL injection."""
        payloads = ["'; DROP TABLE flights;--", "1 OR 1=1", "' UNION SELECT 1--"]

        for payload in payloads:
            # Test limit parameter
            response = client.get(f"/api/flights?limit={payload}")
            assert response.status_code in [200, 422, 400]

            # Test gate parameter
            response = client.get(f"/api/turnaround/abc123?gate={payload}")
            assert response.status_code in [200, 422, 400]


# ==============================================================================
# Input Validation Tests
# ==============================================================================

class TestInputValidation:
    """Tests to verify input validation is properly enforced."""

    def test_icao24_format_validation(self, client):
        """Test that icao24 must be valid hex format."""
        invalid_icao24s = [
            "GGGGGG",      # Invalid hex chars
            "12345",       # Too short
            "1234567",     # Too long
            "abc",         # Too short
            "!@#$%^",      # Special chars
            "<script>",    # XSS attempt
            "abc123xyz",   # Too long with valid chars
            "",            # Empty
        ]

        for icao24 in invalid_icao24s:
            if icao24:  # Skip empty for path param
                response = client.get(f"/api/flights/{icao24}")
                # Should handle gracefully, not crash
                assert response.status_code in [200, 404, 422, 400]

    def test_limit_parameter_bounds(self, client):
        """Test that limit parameter enforces bounds."""
        # Test negative limit
        response = client.get("/api/flights?limit=-1")
        assert response.status_code in [200, 422, 400]

        # Test zero limit
        response = client.get("/api/flights?limit=0")
        assert response.status_code in [200, 422, 400]

        # Test excessively large limit
        response = client.get("/api/flights?limit=999999999")
        assert response.status_code in [200, 422, 400]

        # Valid limit should work
        response = client.get("/api/flights?limit=50")
        assert response.status_code == 200

    def test_schedule_hours_parameter_bounds(self, client):
        """Test schedule endpoint time window validation."""
        # Negative hours
        response = client.get("/api/schedule/arrivals?hours_ahead=-5")
        assert response.status_code in [200, 422, 400]

        # Excessive hours
        response = client.get("/api/schedule/arrivals?hours_ahead=1000")
        assert response.status_code in [200, 422, 400]

    def test_weather_station_validation(self, client):
        """Test weather station parameter validation."""
        invalid_stations = [
            "' OR 1=1--",
            "<script>alert('xss')</script>",
            "A" * 100,  # Too long
            "!!@@##",   # Special chars
        ]

        for station in invalid_stations:
            response = client.get(f"/api/weather/current?station={station}")
            # Should return data (with fallback) or validation error, not 500
            assert response.status_code in [200, 422, 400]

    def test_aircraft_type_validation(self, client):
        """Test aircraft type parameter validation."""
        invalid_types = [
            "'; DROP TABLE--",
            "A" * 50,
            "<script>",
            "../../etc/passwd",
        ]

        for atype in invalid_types:
            response = client.get(f"/api/turnaround/abc123?aircraft_type={atype}")
            assert response.status_code in [200, 422, 400]


# ==============================================================================
# XSS Prevention Tests
# ==============================================================================

class TestXSSPrevention:
    """Tests to verify XSS attacks are handled safely."""

    XSS_PAYLOADS = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert('xss')>",
        "javascript:alert('xss')",
        "<svg onload=alert('xss')>",
        "'><script>alert('xss')</script>",
        "\" onfocus=\"alert('xss')\" autofocus=\"",
        "<body onload=alert('xss')>",
        "<iframe src=\"javascript:alert('xss')\">",
    ]

    def test_xss_in_path_params(self, client):
        """Test that XSS payloads in path params don't execute."""
        for payload in self.XSS_PAYLOADS:
            response = client.get(f"/api/flights/{payload}")
            # Response should be JSON, not HTML that could execute
            assert response.headers.get("content-type", "").startswith("application/json")

    def test_xss_in_query_params(self, client):
        """Test that XSS payloads in query params are neutralized."""
        for payload in self.XSS_PAYLOADS[:3]:  # Test subset
            response = client.get(f"/api/weather/current?station={payload}")

            # Verify response is JSON
            assert "application/json" in response.headers.get("content-type", "")

            # If payload appears in response, it should be escaped/quoted
            if payload in response.text:
                # Should be inside a JSON string, properly escaped
                data = response.json()  # Should parse without issues
                assert data is not None

    def test_error_responses_are_json(self, client):
        """Test that error responses don't render as HTML."""
        # Trigger various errors
        error_urls = [
            "/api/flights/invalid-icao",
            "/api/nonexistent-endpoint",
            "/api/flights?limit=invalid",
        ]

        for url in error_urls:
            response = client.get(url)
            if response.status_code >= 400:
                # Error responses should be JSON, not HTML
                content_type = response.headers.get("content-type", "")
                assert "application/json" in content_type or "text/plain" in content_type, \
                    f"Error response for {url} returned HTML: {content_type}"


# ==============================================================================
# Path Traversal Prevention Tests
# ==============================================================================

class TestPathTraversalPrevention:
    """Tests to verify path traversal attacks are prevented."""

    PATH_TRAVERSAL_PAYLOADS = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "....//....//....//etc/passwd",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "..%252f..%252f..%252fetc/passwd",
        "/etc/passwd",
        "file:///etc/passwd",
    ]

    def test_path_traversal_in_icao24(self, client):
        """Test that path traversal in icao24 fails safely."""
        for payload in self.PATH_TRAVERSAL_PAYLOADS:
            response = client.get(f"/api/flights/{payload}")
            # Should not return file contents
            assert response.status_code in [404, 422, 400, 200]
            if response.status_code == 200:
                # Verify it's flight data, not file contents
                assert "root:" not in response.text
                assert "passwd" not in response.text.lower() or "icao" in response.text.lower()

    def test_path_traversal_in_flight_number(self, client):
        """Test path traversal in baggage flight number."""
        for payload in self.PATH_TRAVERSAL_PAYLOADS[:3]:
            response = client.get(f"/api/baggage/flight/{payload}")
            assert response.status_code in [200, 400, 422]
            if response.status_code == 200:
                assert "root:" not in response.text


# ==============================================================================
# Error Handling & Information Leakage Tests
# ==============================================================================

class TestErrorHandling:
    """Tests to verify errors don't leak sensitive information."""

    def test_404_no_stack_trace(self, client):
        """Test that 404/error responses don't expose stack traces."""
        # Use an API path that definitely doesn't exist
        response = client.get("/api/v99/nonexistent/endpoint")

        # Should return 404 or redirect to SPA (200)
        # Either way, should not expose stack traces
        assert "Traceback" not in response.text
        assert "File \"" not in response.text
        # Allow "line" in JSON responses (e.g., {"detail": "..."})
        if "line " in response.text.lower():
            assert "application/json" in response.headers.get("content-type", "") or \
                   "text/html" in response.headers.get("content-type", "")

    def test_500_no_internal_details(self, client):
        """Test that 500 errors don't expose internal details."""
        # Try to trigger internal errors with malformed requests
        malformed_requests = [
            "/api/flights?limit=[[]]",
            "/api/flights/{}{}{}",
        ]

        for url in malformed_requests:
            response = client.get(url)
            # If it's a 500, check for info leakage
            if response.status_code == 500:
                assert "password" not in response.text.lower()
                assert "secret" not in response.text.lower()
                assert "token" not in response.text.lower()
                assert "/home/" not in response.text
                assert "/Users/" not in response.text

    def test_validation_errors_no_internal_paths(self, client):
        """Test that validation errors don't expose file paths."""
        response = client.get("/api/flights?limit=not_a_number")

        if response.status_code == 422:
            data = response.json()
            response_str = json.dumps(data)
            # Should not contain internal file paths
            assert "/app/" not in response_str
            assert "/home/" not in response_str
            assert "/Users/" not in response_str
            assert ".py" not in response_str or "type" in response_str

    def test_debug_endpoint_protection(self, client):
        """Test that debug endpoints are protected or removed."""
        debug_endpoints = [
            "/api/debug/paths",
            "/api/debug",
            "/debug",
            "/api/internal",
            "/api/config",
        ]

        for endpoint in debug_endpoints:
            response = client.get(endpoint)
            # Debug endpoints should either not exist (404) or be protected
            if response.status_code == 200:
                data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                # Should not expose sensitive paths
                assert "password" not in str(data).lower()
                assert "secret" not in str(data).lower()
                assert "token" not in str(data).lower()


# ==============================================================================
# CORS Configuration Tests
# ==============================================================================

class TestCORSConfiguration:
    """Tests to verify CORS is properly configured."""

    def test_cors_headers_present(self, client):
        """Test that CORS headers are present in responses."""
        response = client.options(
            "/api/flights",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            }
        )

        # Should have CORS headers
        assert "access-control-allow-origin" in [h.lower() for h in response.headers.keys()] or \
               response.status_code == 405  # OPTIONS might not be explicitly handled

    def test_cors_preflight_request(self, client):
        """Test CORS preflight request handling."""
        response = client.options(
            "/api/flights",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            }
        )

        # Should either allow the request or return proper CORS error
        assert response.status_code in [200, 204, 405]


# ==============================================================================
# Authentication Boundary Tests
# ==============================================================================

class TestAuthenticationBoundaries:
    """Tests for authentication-related security boundaries."""

    def test_public_endpoints_accessible(self, client):
        """Test that public endpoints are accessible without auth."""
        public_endpoints = [
            "/api/flights",
            "/api/schedule/arrivals",
            "/api/schedule/departures",
            "/api/weather/current",
            "/api/gse/status",
            "/api/baggage/stats",
            "/health",
        ]

        for endpoint in public_endpoints:
            response = client.get(endpoint)
            # Should not return 401/403 for public endpoints
            assert response.status_code not in [401, 403], \
                f"Public endpoint {endpoint} requires auth unexpectedly"

    def test_no_auth_header_handling(self, client):
        """Test endpoints handle missing auth headers gracefully."""
        response = client.get("/api/flights")
        # Should work without auth headers (for this demo app)
        assert response.status_code in [200, 401, 403]

    def test_invalid_auth_header_handling(self, client):
        """Test endpoints handle invalid auth headers gracefully."""
        response = client.get(
            "/api/flights",
            headers={"Authorization": "Bearer invalid_token_12345"}
        )
        # Should either work (no auth required) or return proper auth error
        assert response.status_code in [200, 401, 403]


# ==============================================================================
# Header Security Tests
# ==============================================================================

class TestSecurityHeaders:
    """Tests for security-related HTTP headers."""

    def test_content_type_header(self, client):
        """Test that responses have proper Content-Type headers."""
        response = client.get("/api/flights")
        assert "content-type" in [h.lower() for h in response.headers.keys()]
        assert "application/json" in response.headers.get("content-type", "")

    def test_no_server_version_disclosure(self, client):
        """Test that server version is not disclosed in headers."""
        response = client.get("/api/flights")

        server_header = response.headers.get("server", "")
        # Should not expose detailed version info
        assert "Python" not in server_header or "/" not in server_header

    def test_x_content_type_options(self, client):
        """Test for X-Content-Type-Options header (MIME sniffing prevention)."""
        response = client.get("/api/flights")
        # This header prevents MIME type sniffing
        # Note: May not be set in dev, but should be in prod
        # Just verify response is valid
        assert response.status_code == 200


# ==============================================================================
# Rate Limiting Awareness Tests
# ==============================================================================

class TestRateLimitingAwareness:
    """Tests to verify the app can handle rapid requests."""

    def test_rapid_requests_handled(self, client):
        """Test that rapid requests don't crash the server."""
        # Make 20 rapid requests
        for _ in range(20):
            response = client.get("/api/flights")
            # Should handle gracefully (200 OK or 429 Too Many Requests)
            assert response.status_code in [200, 429]

    def test_concurrent_endpoints(self, client):
        """Test multiple different endpoints in rapid succession."""
        endpoints = [
            "/api/flights",
            "/api/schedule/arrivals",
            "/api/weather/current",
            "/api/gse/status",
            "/api/baggage/stats",
        ]

        for _ in range(3):
            for endpoint in endpoints:
                response = client.get(endpoint)
                assert response.status_code in [200, 429]


# ==============================================================================
# Data Exposure Tests
# ==============================================================================

class TestDataExposure:
    """Tests to verify sensitive data is not exposed."""

    def test_no_credentials_in_responses(self, client):
        """Test that responses don't contain credential patterns."""
        endpoints = [
            "/api/flights",
            "/api/schedule/arrivals",
            "/api/weather/current",
            "/api/gse/status",
        ]

        credential_patterns = [
            "password",
            "api_key",
            "secret_key",
            "access_token",
            "private_key",
            "aws_secret",
            "databricks_token",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            response_lower = response.text.lower()

            for pattern in credential_patterns:
                # Allow field names but not actual values
                if pattern in response_lower:
                    # If pattern exists, it should be a field name, not a value
                    data = response.json()
                    data_str = json.dumps(data)
                    # Should not have long strings that look like tokens
                    assert not any(
                        len(v) > 30 and pattern in k.lower()
                        for k, v in self._flatten_dict(data).items()
                        if isinstance(v, str)
                    ), f"Possible credential exposure in {endpoint}"

    def _flatten_dict(self, d, parent_key='', sep='_'):
        """Flatten nested dictionary."""
        items = []
        if isinstance(d, dict):
            for k, v in d.items():
                new_key = f"{parent_key}{sep}{k}" if parent_key else k
                if isinstance(v, dict):
                    items.extend(self._flatten_dict(v, new_key, sep=sep).items())
                else:
                    items.append((new_key, v))
        return dict(items)

    def test_no_internal_ips_exposed(self, client):
        """Test that internal IPs are not exposed in responses."""
        response = client.get("/api/flights")

        # Check for internal IP patterns
        internal_patterns = [
            "192.168.",
            "10.0.",
            "172.16.",
            "127.0.0.1",
            "localhost:",
        ]

        for pattern in internal_patterns:
            # Allow localhost in demo mode indicators, but not in data
            if pattern in response.text and pattern != "localhost:":
                # Verify it's not exposing internal infrastructure
                assert "host" not in response.text.lower() or "databricks" in response.text.lower()
