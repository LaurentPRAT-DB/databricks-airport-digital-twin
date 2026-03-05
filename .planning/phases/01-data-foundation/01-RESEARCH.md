# Phase 1: Data Foundation - Research

**Researched:** 2026-03-05
**Domain:** Real-time flight data ingestion, Delta Live Tables, Unity Catalog, Structured Streaming
**Confidence:** MEDIUM

## Summary

Phase 1 establishes the data foundation for the Airport Digital Twin by implementing a medallion architecture (Bronze/Silver/Gold) using Delta Live Tables (DLT) with real-time flight data from OpenSky Network API. The core challenge is building a reliable streaming pipeline that maintains <60 second latency from API poll to Gold table while gracefully handling API unavailability with fallback data.

The recommended approach uses DLT for declarative ETL with built-in data quality expectations, Unity Catalog for governance and lineage tracking, and Structured Streaming with checkpoint management for fault tolerance. OpenSky Network provides free flight position data with 400 API credits/day for anonymous users (10-second resolution) or 4000-8000 credits/day for authenticated users (5-second resolution). A bounding-box query strategy minimizes credit usage while capturing relevant airport traffic.

**Primary recommendation:** Use DLT pipelines with @dlt.table decorators for Bronze/Silver/Gold transformations, implement a polling job that writes raw JSON to a landing zone (not directly to Bronze), and configure Unity Catalog schemas per medallion tier (bronze, silver, gold) for clear governance.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DATA-01 | System ingests real-time flight data from OpenSky Network API | OpenSky API documented with endpoints, rate limits, and response schema; use `/states/all` with bounding box |
| DATA-02 | System provides fallback to cached/synthetic data when API unavailable | Implement circuit breaker pattern with local JSON cache and synthetic data generator |
| DATA-03 | DLT pipeline transforms raw data through Bronze to Silver to Gold layers | DLT @dlt.table decorator pattern with expectations for data quality gates |
| DATA-04 | All tables registered in Unity Catalog with proper governance | Unity Catalog 3-tier namespace (catalog.schema.table) with medallion schemas |
| DATA-05 | Data lineage tracked and visible in Unity Catalog | DLT automatically captures lineage; Unity Catalog displays in Lineage tab |
| STRM-01 | Structured Streaming processes flight position updates in near real-time | Auto Loader for Bronze ingestion; streaming tables in DLT for Silver/Gold |
| STRM-02 | Stream handles late-arriving data and out-of-order events gracefully | Watermarking with withWatermark() on position timestamp; dropDuplicates() on icao24+time |
| STRM-03 | Streaming checkpoints are resilient to schema changes | Versioned checkpoint paths per pipeline version; checkpoint location in DLT managed automatically |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Delta Live Tables | Serverless | Declarative ETL pipelines | Databricks-native, automatic lineage, built-in data quality expectations |
| Unity Catalog | Latest | Data governance and lineage | Databricks standard for governance, required for AI/BI features in later phases |
| Structured Streaming | Spark 3.5+ | Real-time data processing | Native Spark streaming, integrates with Delta Lake checkpointing |
| Auto Loader | Included | Streaming file ingestion | Schema inference, exactly-once semantics, handles schema evolution |
| requests | 2.31+ | HTTP client for API polling | Standard Python HTTP library, well-maintained |
| pydantic | 2.5+ | Data validation | Type-safe response parsing, JSON serialization |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | 8.2+ | Retry logic | API call resilience with exponential backoff |
| circuitbreaker | 1.4+ | Circuit breaker pattern | Prevent cascade failures when OpenSky is down |
| Faker | 22.0+ | Synthetic data generation | Fallback data when API unavailable |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Auto Loader | Kafka + Spark Streaming | Kafka adds infrastructure complexity; Auto Loader is sufficient for polling-to-file pattern |
| requests | httpx | httpx offers async; not needed since polling job is sequential |
| DLT | Raw Spark notebooks | Loses automatic lineage, expectations, and managed checkpoints |

**Installation (Python ingestion job):**
```bash
pip install requests pydantic tenacity circuitbreaker Faker
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── ingestion/                 # API polling and landing zone writes
│   ├── __init__.py
│   ├── opensky_client.py      # OpenSky API client with auth + retry
│   ├── fallback.py            # Synthetic data generator
│   ├── circuit_breaker.py     # Failover logic
│   └── poll_job.py            # Databricks job entrypoint
├── pipelines/                 # DLT pipeline definitions
│   ├── bronze.py              # Raw data ingestion
│   ├── silver.py              # Cleaned/normalized data
│   └── gold.py                # Aggregated flight status
├── schemas/                   # Pydantic models and Spark schemas
│   ├── opensky.py             # API response models
│   └── flight.py              # Domain models
└── config/
    └── settings.py            # Environment configuration
data/
├── landing/                   # Raw JSON from API polling
├── fallback/                  # Cached/synthetic data for offline mode
└── checkpoints/               # Streaming checkpoint location (managed by cluster)
```

### Pattern 1: Polling Job to Landing Zone
**What:** A Databricks Job polls OpenSky API at fixed intervals, writing raw JSON to a landing zone (cloud storage path). DLT Auto Loader then streams from landing zone to Bronze.
**When to use:** Always - decouples API polling from streaming pipeline, enables replay and debugging.
**Example:**
```python
# src/ingestion/poll_job.py
# Source: Standard Databricks ingestion pattern

import json
from datetime import datetime
from pathlib import Path
from opensky_client import OpenSkyClient
from fallback import generate_synthetic_flights
from circuit_breaker import api_circuit_breaker

def poll_and_write(landing_path: str, bbox: dict):
    """Poll OpenSky API and write to landing zone."""
    client = OpenSkyClient()
    timestamp = datetime.utcnow().isoformat()

    try:
        if api_circuit_breaker.state == "open":
            # API marked as down - use fallback
            data = generate_synthetic_flights(count=50)
            source = "synthetic"
        else:
            data = client.get_states(bbox=bbox)
            source = "opensky"
    except Exception as e:
        api_circuit_breaker.record_failure()
        data = generate_synthetic_flights(count=50)
        source = "fallback"

    # Write to landing zone with metadata
    output = {
        "timestamp": timestamp,
        "source": source,
        "states": data
    }

    output_path = f"{landing_path}/{timestamp.replace(':', '-')}.json"
    # In Databricks, use dbutils.fs.put() or write to mounted storage
    with open(output_path, 'w') as f:
        json.dump(output, f)

    return len(data.get("states", []))
```

### Pattern 2: DLT Bronze Layer with Auto Loader
**What:** Auto Loader streams JSON files from landing zone, preserving raw data with ingestion metadata.
**When to use:** Bronze table - never transform raw data, add metadata only.
**Example:**
```python
# src/pipelines/bronze.py
# Source: Databricks DLT documentation pattern

import dlt
from pyspark.sql.functions import current_timestamp, input_file_name

@dlt.table(
    name="flights_bronze",
    comment="Raw flight data from OpenSky API",
    table_properties={
        "quality": "bronze",
        "pipelines.autoOptimize.managed": "true"
    }
)
def flights_bronze():
    return (
        spark.readStream
        .format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.schemaLocation", "/mnt/data/schemas/bronze")
        .option("cloudFiles.inferColumnTypes", "true")
        .load("/mnt/data/landing/")
        .withColumn("_ingested_at", current_timestamp())
        .withColumn("_source_file", input_file_name())
    )
```

### Pattern 3: DLT Silver Layer with Data Quality
**What:** Transform Bronze to Silver with schema enforcement, data quality expectations, and deduplication.
**When to use:** Silver table - apply business rules and data quality gates.
**Example:**
```python
# src/pipelines/silver.py
# Source: Databricks DLT expectations pattern

import dlt
from pyspark.sql.functions import col, explode, from_unixtime, to_timestamp

@dlt.table(
    name="flights_silver",
    comment="Cleaned and normalized flight positions"
)
@dlt.expect_or_drop("valid_position", "latitude IS NOT NULL AND longitude IS NOT NULL")
@dlt.expect_or_drop("valid_icao24", "icao24 IS NOT NULL AND LENGTH(icao24) = 6")
@dlt.expect("valid_altitude", "baro_altitude >= 0 OR baro_altitude IS NULL")
def flights_silver():
    return (
        dlt.read_stream("flights_bronze")
        .select(
            col("timestamp").alias("poll_timestamp"),
            col("source").alias("data_source"),
            explode("states").alias("state")
        )
        .select(
            col("poll_timestamp"),
            col("data_source"),
            col("state")[0].alias("icao24"),
            col("state")[1].alias("callsign"),
            col("state")[2].alias("origin_country"),
            from_unixtime(col("state")[3]).alias("position_time"),
            from_unixtime(col("state")[4]).alias("last_contact"),
            col("state")[5].cast("double").alias("longitude"),
            col("state")[6].cast("double").alias("latitude"),
            col("state")[7].cast("double").alias("baro_altitude"),
            col("state")[8].cast("boolean").alias("on_ground"),
            col("state")[9].cast("double").alias("velocity"),
            col("state")[10].cast("double").alias("true_track"),
            col("state")[11].cast("double").alias("vertical_rate"),
            col("state")[13].cast("double").alias("geo_altitude"),
            col("state")[14].alias("squawk"),
            col("state")[16].cast("int").alias("position_source"),
            col("state")[17].cast("int").alias("category")
        )
        .withWatermark("position_time", "2 minutes")
        .dropDuplicates(["icao24", "position_time"])
    )
```

### Pattern 4: DLT Gold Layer for Flight Status
**What:** Aggregate Silver data into current flight status with computed fields.
**When to use:** Gold table - business-ready views for downstream consumers.
**Example:**
```python
# src/pipelines/gold.py
# Source: Databricks DLT aggregation pattern

import dlt
from pyspark.sql.functions import col, max, first, when, lit
from pyspark.sql.window import Window

@dlt.table(
    name="flight_status_gold",
    comment="Current status of all tracked flights"
)
def flight_status_gold():
    # Get latest position for each aircraft
    return (
        dlt.read_stream("flights_silver")
        .groupBy("icao24")
        .agg(
            max("position_time").alias("last_seen"),
            first("callsign", ignorenulls=True).alias("callsign"),
            first("origin_country").alias("origin_country"),
            first("longitude").alias("longitude"),
            first("latitude").alias("latitude"),
            first("baro_altitude").alias("altitude"),
            first("velocity").alias("velocity"),
            first("true_track").alias("heading"),
            first("on_ground").alias("on_ground"),
            first("vertical_rate").alias("vertical_rate"),
            first("data_source").alias("data_source")
        )
        .withColumn(
            "flight_phase",
            when(col("on_ground"), lit("ground"))
            .when(col("vertical_rate") > 5, lit("climbing"))
            .when(col("vertical_rate") < -5, lit("descending"))
            .otherwise(lit("cruising"))
        )
    )
```

### Anti-Patterns to Avoid
- **Direct API write to Delta:** Never write API responses directly to Bronze tables - use landing zone for replay/debugging capability
- **Shared checkpoints:** Never share checkpoint locations between development and production pipelines - causes corruption
- **Missing watermarks:** Always use watermarks on streaming aggregations to bound state and handle late data
- **Hardcoded credentials:** Never embed API credentials in code - use Databricks secrets
- **Unbounded state:** Avoid streaming aggregations without watermarks - causes OOM on long-running streams

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema evolution | Custom migration scripts | Auto Loader schema inference | Handles new fields automatically, tracks schema history |
| Data quality | Custom validation functions | DLT expectations | Built-in quarantine tables, metrics, UI visibility |
| Exactly-once semantics | Custom deduplication | Structured Streaming + Delta | Delta provides idempotent writes, checkpointing handles failures |
| Lineage tracking | Custom metadata tables | Unity Catalog | Automatic lineage capture, cross-pipeline visibility |
| Retry logic | Manual retry loops | tenacity library | Exponential backoff, jitter, configurable strategies |
| Circuit breaker | Custom state tracking | circuitbreaker library | Proven pattern, automatic state transitions |
| Data catalog | Custom schema registry | Unity Catalog | Industry standard, integrates with AI/BI features |

**Key insight:** DLT abstracts away significant streaming complexity (checkpoints, state management, schema evolution). Fighting DLT's opinions creates maintenance burden without benefit.

## Common Pitfalls

### Pitfall 1: OpenSky API Credit Exhaustion
**What goes wrong:** API returns 429 during demo because credits exhausted
**Why it happens:** Global queries (no bounding box) use 4 credits each; 400 anonymous credits = 100 requests = ~16 minutes at 10-second polling
**How to avoid:**
1. Always use bounding box (<25 sq deg = 1 credit)
2. Poll every 30-60 seconds, not 10 seconds
3. Implement circuit breaker with fallback data
4. Create authenticated account (4000+ credits/day)
**Warning signs:** x-rate-limit-remaining header decreasing rapidly; 429 responses

### Pitfall 2: Streaming Checkpoint Corruption
**What goes wrong:** Pipeline fails to restart after schema change with checkpoint error
**Why it happens:** Checkpoints encode schema; schema changes invalidate checkpoints
**How to avoid:**
1. Use Auto Loader's `cloudFiles.schemaLocation` for schema evolution
2. Version checkpoint paths with pipeline version
3. DLT manages checkpoints automatically - don't override paths
4. For major schema changes, create new pipeline version with fresh checkpoints
**Warning signs:** StreamingQueryException on restart; "schema doesn't match checkpoint" errors

### Pitfall 3: Late Data Dropped Silently
**What goes wrong:** Valid flight positions missing from Silver/Gold tables
**Why it happens:** Watermark too aggressive; late data dropped without visibility
**How to avoid:**
1. Set watermark generously (2-5 minutes for position data)
2. Monitor DLT metrics for dropped late events
3. Use expectations to track data quality, not silent drops
4. For demo, prefer showing stale data over missing data
**Warning signs:** Row counts drop unexpectedly; flights "disappear" from Gold table

### Pitfall 4: Synthetic Data Schema Drift
**What goes wrong:** Pipeline fails because synthetic fallback data has different schema than real API data
**Why it happens:** Synthetic data generator not updated when API schema changes
**How to avoid:**
1. Generate synthetic data from same Pydantic models as API parsing
2. Write schema validation tests that compare real vs synthetic output
3. Cache real API responses for offline validation
**Warning signs:** Type errors in Silver transformations; null columns from synthetic data

### Pitfall 5: Unity Catalog Permission Errors
**What goes wrong:** DLT pipeline fails with permission denied on table creation
**Why it happens:** Service principal or user lacks CREATE TABLE on target schema
**How to avoid:**
1. Create catalog/schemas before running DLT pipeline
2. Grant explicit permissions to pipeline owner: USE CATALOG, USE SCHEMA, CREATE TABLE
3. Use dedicated service principal for pipelines, not personal accounts
**Warning signs:** AccessDeniedException; "User does not have CREATE permission"

## Code Examples

Verified patterns from official sources:

### OpenSky API Client with Retry and Auth
```python
# src/ingestion/opensky_client.py
# Source: OpenSky Network API documentation + tenacity patterns

import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel
from typing import Optional, List
import os

class StateVector(BaseModel):
    icao24: str
    callsign: Optional[str]
    origin_country: str
    time_position: Optional[int]
    last_contact: int
    longitude: Optional[float]
    latitude: Optional[float]
    baro_altitude: Optional[float]
    on_ground: bool
    velocity: Optional[float]
    true_track: Optional[float]
    vertical_rate: Optional[float]
    sensors: Optional[List[int]]
    geo_altitude: Optional[float]
    squawk: Optional[str]
    spi: bool
    position_source: int
    category: Optional[int] = None

class OpenSkyResponse(BaseModel):
    time: int
    states: Optional[List[List]] = None

class OpenSkyClient:
    BASE_URL = "https://opensky-network.org/api"
    AUTH_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

    def __init__(self):
        self.client_id = os.getenv("OPENSKY_CLIENT_ID")
        self.client_secret = os.getenv("OPENSKY_CLIENT_SECRET")
        self._token = None

    def _get_token(self) -> Optional[str]:
        """Get OAuth2 token for authenticated access."""
        if not self.client_id or not self.client_secret:
            return None

        response = requests.post(
            self.AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret
            }
        )
        if response.ok:
            self._token = response.json().get("access_token")
        return self._token

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def get_states(
        self,
        bbox: Optional[dict] = None,
        icao24: Optional[List[str]] = None
    ) -> OpenSkyResponse:
        """
        Fetch current state vectors.

        Args:
            bbox: Bounding box dict with keys: lamin, lamax, lomin, lomax
            icao24: List of ICAO24 addresses to filter

        Returns:
            OpenSkyResponse with time and states array
        """
        params = {}
        if bbox:
            params.update(bbox)
        if icao24:
            for addr in icao24:
                params.setdefault("icao24", []).append(addr)

        headers = {}
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = requests.get(
            f"{self.BASE_URL}/states/all",
            params=params,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        return OpenSkyResponse(**response.json())

# Example usage for SFO area (approx 500km x 500km = 1 API credit)
SFO_BBOX = {
    "lamin": 36.0,  # South
    "lamax": 39.0,  # North
    "lomin": -124.0,  # West
    "lomax": -121.0   # East
}
```

### Circuit Breaker for API Fallback
```python
# src/ingestion/circuit_breaker.py
# Source: Standard circuit breaker pattern

from circuitbreaker import circuit, CircuitBreakerError
from datetime import datetime
import json
import os

class APICircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = datetime.utcnow()
        if self.failures >= self.failure_threshold:
            self.state = "open"

    def record_success(self):
        self.failures = 0
        self.state = "closed"

    def can_execute(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            elapsed = (datetime.utcnow() - self.last_failure_time).seconds
            if elapsed >= self.recovery_timeout:
                self.state = "half-open"
                return True
            return False
        return True  # half-open allows one attempt

api_circuit_breaker = APICircuitBreaker()
```

### Synthetic Data Generator
```python
# src/ingestion/fallback.py
# Source: Faker library patterns for realistic test data

from faker import Faker
import random
from datetime import datetime
from typing import List, Dict

fake = Faker()

# Common airline callsign prefixes
CALLSIGN_PREFIXES = ["UAL", "DAL", "AAL", "SWA", "JBU", "ASA", "FFT", "SKW"]

def generate_synthetic_flights(
    count: int = 50,
    bbox: dict = None
) -> Dict:
    """
    Generate synthetic flight data matching OpenSky API format.

    Returns dict with 'time' and 'states' matching API response structure.
    """
    if bbox is None:
        bbox = {"lamin": 36.0, "lamax": 39.0, "lomin": -124.0, "lomax": -121.0}

    current_time = int(datetime.utcnow().timestamp())
    states = []

    for _ in range(count):
        # Generate realistic ICAO24 (6 hex chars)
        icao24 = fake.hexify(text="^^^^^^", upper=False)

        # Generate callsign
        callsign = random.choice(CALLSIGN_PREFIXES) + str(random.randint(100, 9999))
        callsign = callsign.ljust(8)  # Pad to 8 chars

        # Generate position within bbox
        lat = random.uniform(bbox["lamin"], bbox["lamax"])
        lon = random.uniform(bbox["lomin"], bbox["lomax"])

        # Generate realistic flight parameters
        on_ground = random.random() < 0.1  # 10% on ground
        altitude = 0 if on_ground else random.uniform(1000, 12000)
        velocity = random.uniform(0, 50) if on_ground else random.uniform(150, 280)
        heading = random.uniform(0, 360)
        vertical_rate = 0 if on_ground else random.uniform(-10, 10)

        state = [
            icao24,                           # 0: icao24
            callsign,                         # 1: callsign
            "United States",                  # 2: origin_country
            current_time - random.randint(0, 10),  # 3: time_position
            current_time - random.randint(0, 5),   # 4: last_contact
            lon,                              # 5: longitude
            lat,                              # 6: latitude
            altitude,                         # 7: baro_altitude
            on_ground,                        # 8: on_ground
            velocity,                         # 9: velocity
            heading,                          # 10: true_track
            vertical_rate,                    # 11: vertical_rate
            None,                             # 12: sensors
            altitude + random.uniform(-50, 50),  # 13: geo_altitude
            f"{random.randint(1000, 7777):04d}",  # 14: squawk
            False,                            # 15: spi
            0,                                # 16: position_source (ADS-B)
            random.randint(2, 6)              # 17: category
        ]
        states.append(state)

    return {
        "time": current_time,
        "states": states
    }
```

### Unity Catalog Setup SQL
```sql
-- Unity Catalog namespace setup
-- Run once before DLT pipeline deployment

-- Create catalog for the project
CREATE CATALOG IF NOT EXISTS airport_digital_twin;
USE CATALOG airport_digital_twin;

-- Create medallion schemas
CREATE SCHEMA IF NOT EXISTS bronze
  COMMENT 'Raw ingested data from external sources';

CREATE SCHEMA IF NOT EXISTS silver
  COMMENT 'Cleaned and validated data';

CREATE SCHEMA IF NOT EXISTS gold
  COMMENT 'Business-ready aggregated data';

-- Grant permissions to pipeline service principal
-- Replace {service_principal_id} with actual ID
GRANT USE CATALOG ON CATALOG airport_digital_twin TO `{service_principal_id}`;
GRANT USE SCHEMA ON SCHEMA bronze TO `{service_principal_id}`;
GRANT USE SCHEMA ON SCHEMA silver TO `{service_principal_id}`;
GRANT USE SCHEMA ON SCHEMA gold TO `{service_principal_id}`;
GRANT CREATE TABLE ON SCHEMA bronze TO `{service_principal_id}`;
GRANT CREATE TABLE ON SCHEMA silver TO `{service_principal_id}`;
GRANT CREATE TABLE ON SCHEMA gold TO `{service_principal_id}`;
```

### DLT Pipeline Configuration
```json
{
  "name": "airport_digital_twin_pipeline",
  "storage": "/mnt/data/dlt/airport",
  "target": "airport_digital_twin",
  "continuous": true,
  "development": false,
  "clusters": [
    {
      "label": "default",
      "autoscale": {
        "min_workers": 1,
        "max_workers": 4,
        "mode": "ENHANCED"
      }
    }
  ],
  "libraries": [
    {"notebook": {"path": "/Repos/airport-digital-twin/src/pipelines/bronze"}},
    {"notebook": {"path": "/Repos/airport-digital-twin/src/pipelines/silver"}},
    {"notebook": {"path": "/Repos/airport-digital-twin/src/pipelines/gold"}}
  ],
  "configuration": {
    "pipelines.trigger.interval": "30 seconds"
  }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Basic auth for OpenSky | OAuth2 client credentials | March 2025 | New accounts require OAuth2; legacy accounts deprecated |
| Manual checkpoint management | DLT managed checkpoints | DLT GA | No manual checkpoint paths needed in DLT |
| Hive metastore | Unity Catalog | 2023+ | Required for lineage, AI/BI, governance features |
| Separate streaming + batch | DLT unified | DLT GA | Single pipeline definition handles both modes |
| Manual schema registry | Auto Loader schema inference | Auto Loader GA | Automatic schema evolution tracking |

**Deprecated/outdated:**
- OpenSky basic auth (username/password): Deprecated for new accounts, use OAuth2 client credentials
- Hive metastore for new projects: Unity Catalog is required for modern Databricks features
- Manual Structured Streaming checkpoints in DLT: DLT manages checkpoints automatically

## Open Questions

1. **Airport bounding box definition**
   - What we know: Need lat/lon bounds to minimize API credits
   - What's unclear: Which airport(s) to target; demo may want generic or specific airport
   - Recommendation: Start with SFO-area bounding box (36-39N, 124-121W), make configurable

2. **Polling frequency vs. API credits**
   - What we know: Anonymous = 400 credits/day; authenticated = 4000+/day; small bbox = 1 credit
   - What's unclear: Exact polling frequency needed for <60s latency requirement
   - Recommendation: 30-second polling with authenticated account (4000/30sec = ~133 requests = 133 credits << 4000)

3. **DLT pipeline mode: triggered vs. continuous**
   - What we know: Continuous = always running, triggered = scheduled batches
   - What's unclear: Cost implications for demo vs. always-on
   - Recommendation: Use triggered mode for development (cheaper), continuous for demo

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-spark |
| Config file | pytest.ini (Wave 0 setup) |
| Quick run command | `pytest tests/unit -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | OpenSky API returns valid flight data | integration | `pytest tests/integration/test_opensky.py::test_api_returns_states -x` | Wave 0 |
| DATA-02 | Fallback activates when API fails | unit | `pytest tests/unit/test_fallback.py::test_circuit_breaker -x` | Wave 0 |
| DATA-03 | DLT transforms Bronze to Silver to Gold | integration | Manual - DLT pipeline run | manual-only (DLT) |
| DATA-04 | Tables exist in Unity Catalog | integration | `pytest tests/integration/test_unity_catalog.py::test_tables_exist -x` | Wave 0 |
| DATA-05 | Lineage visible in catalog | manual | Manual - Unity Catalog UI | manual-only (UI) |
| STRM-01 | Streaming processes updates in <60s | integration | `pytest tests/integration/test_latency.py::test_end_to_end_latency -x` | Wave 0 |
| STRM-02 | Late data handled with watermark | unit | `pytest tests/unit/test_streaming.py::test_watermark_late_data -x` | Wave 0 |
| STRM-03 | Checkpoints survive restart | integration | Manual - DLT pipeline restart | manual-only (DLT) |

### Sampling Rate
- **Per task commit:** `pytest tests/unit -x -q` (~10 seconds)
- **Per wave merge:** `pytest tests/ -v` (~60 seconds)
- **Phase gate:** Full suite green + manual DLT verification before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/conftest.py` - Pytest fixtures including Spark session
- [ ] `tests/unit/__init__.py` - Unit test package
- [ ] `tests/integration/__init__.py` - Integration test package
- [ ] `pytest.ini` - Pytest configuration
- [ ] Framework install: `pip install pytest pytest-spark pyspark` - if Databricks Connect not used

*(DLT pipeline testing is manual-only; no programmatic test harness for DLT expectations)*

## Sources

### Primary (HIGH confidence)
- OpenSky Network API Documentation (https://openskynetwork.github.io/opensky-api/) - API endpoints, rate limits, OAuth2 flow, response schema
- OpenSky GitHub README - Python client example, authentication patterns

### Secondary (MEDIUM confidence)
- Training data on Databricks DLT patterns - @dlt.table decorator, expectations, Auto Loader
- Training data on Databricks Unity Catalog - 3-tier namespace, lineage, permissions
- Training data on Structured Streaming - watermarks, checkpoints, exactly-once semantics

### Tertiary (LOW confidence - needs validation)
- DLT continuous vs. triggered mode cost implications - verify with Databricks pricing docs
- Unity Catalog permission model changes - verify current syntax in Databricks docs
- Auto Loader cloudFiles options - verify current options in Databricks docs

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - Core Databricks patterns well-known, but verify current versions and syntax
- Architecture: MEDIUM - Standard medallion architecture, verify DLT-specific configuration options
- Pitfalls: HIGH - Rate limits, checkpoint corruption, and late data handling are well-documented failure modes
- OpenSky API: HIGH - Directly verified from official documentation

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (30 days - stable domain)
