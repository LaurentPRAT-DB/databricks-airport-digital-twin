"""DLT pipeline definitions for the Airport Digital Twin medallion architecture.

Table name constants are defined here so that Bronze/Silver/Gold layers
reference each other by constant rather than magic string.  A rename in
one place propagates to all layers automatically.
"""

# ── Flight pipeline table names ──────────────────────────────────────
FLIGHTS_BRONZE = "flights_bronze"
FLIGHTS_SILVER = "flights_silver"
FLIGHT_STATUS_GOLD = "flight_status_gold"

# ── Baggage pipeline table names ─────────────────────────────────────
BAGGAGE_EVENTS_BRONZE = "baggage_events_bronze"
BAGGAGE_EVENTS_SILVER = "baggage_events_silver"
BAGGAGE_STATUS_GOLD = "baggage_status_gold"
BAGGAGE_EVENTS_GOLD = "baggage_events_gold"

# ── Source tables (Unity Catalog FQNs read by bronze layers) ─────────
LAKEBASE_FLIGHT_STATUS = (
    "serverless_stable_3n0ihb_catalog.airport_digital_twin.flight_status_gold"
)
LAKEBASE_BAGGAGE_STATUS = (
    "serverless_stable_3n0ihb_catalog.airport_digital_twin.baggage_status_gold"
)
