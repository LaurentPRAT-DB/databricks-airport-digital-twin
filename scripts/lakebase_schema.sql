-- Lakebase Schema for Airport Digital Twin
-- Run this script to create the flight_status table in Lakebase PostgreSQL

-- Flight status table (mirrors Gold layer schema)
CREATE TABLE IF NOT EXISTS flight_status (
    icao24 VARCHAR(6) PRIMARY KEY,
    callsign VARCHAR(10),
    origin_country VARCHAR(100),
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    altitude DOUBLE PRECISION,
    velocity DOUBLE PRECISION,
    heading DOUBLE PRECISION,
    on_ground BOOLEAN DEFAULT FALSE,
    vertical_rate DOUBLE PRECISION,
    last_seen TIMESTAMP WITH TIME ZONE NOT NULL,
    flight_phase VARCHAR(20) NOT NULL DEFAULT 'unknown',
    data_source VARCHAR(20) NOT NULL DEFAULT 'opensky',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for efficient time-based queries
CREATE INDEX IF NOT EXISTS idx_flight_status_last_seen
ON flight_status(last_seen DESC);

-- Index for flight phase filtering
CREATE INDEX IF NOT EXISTS idx_flight_status_phase
ON flight_status(flight_phase);

-- Index for geographic queries (if using PostGIS)
-- CREATE INDEX IF NOT EXISTS idx_flight_status_location
-- ON flight_status USING GIST (ST_MakePoint(longitude, latitude));

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for automatic timestamp updates
DROP TRIGGER IF EXISTS update_flight_status_updated_at ON flight_status;
CREATE TRIGGER update_flight_status_updated_at
    BEFORE UPDATE ON flight_status
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Clean up stale data (older than 1 hour)
-- Run this periodically via a scheduled job
-- DELETE FROM flight_status WHERE last_seen < NOW() - INTERVAL '1 hour';

COMMENT ON TABLE flight_status IS 'Real-time flight status data synced from Delta Gold layer';
COMMENT ON COLUMN flight_status.icao24 IS 'Unique ICAO 24-bit aircraft address (hex)';
COMMENT ON COLUMN flight_status.callsign IS 'Aircraft callsign (e.g., UAL123)';
COMMENT ON COLUMN flight_status.flight_phase IS 'Computed phase: ground, climbing, cruising, descending, unknown';
