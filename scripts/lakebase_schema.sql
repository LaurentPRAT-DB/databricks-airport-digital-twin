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


-- ============================================================================
-- Weather Observations Table (METAR/TAF)
-- ============================================================================

CREATE TABLE IF NOT EXISTS weather_observations (
    station VARCHAR(4) PRIMARY KEY,
    observation_time TIMESTAMP WITH TIME ZONE NOT NULL,
    wind_direction INT,
    wind_speed_kts INT DEFAULT 0,
    wind_gust_kts INT,
    visibility_sm DECIMAL(4,1) NOT NULL,
    clouds JSONB DEFAULT '[]'::jsonb,
    temperature_c INT NOT NULL,
    dewpoint_c INT NOT NULL,
    altimeter_inhg DECIMAL(5,2) NOT NULL,
    weather JSONB DEFAULT '[]'::jsonb,
    flight_category VARCHAR(4) NOT NULL,
    raw_metar TEXT,
    taf_text TEXT,
    taf_valid_from TIMESTAMP WITH TIME ZONE,
    taf_valid_to TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_weather_obs_time
ON weather_observations(observation_time DESC);

DROP TRIGGER IF EXISTS update_weather_observations_updated_at ON weather_observations;
CREATE TRIGGER update_weather_observations_updated_at
    BEFORE UPDATE ON weather_observations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE weather_observations IS 'Current METAR/TAF weather observations for airports';
COMMENT ON COLUMN weather_observations.station IS 'ICAO station identifier (e.g., KSFO)';
COMMENT ON COLUMN weather_observations.flight_category IS 'VFR, MVFR, IFR, or LIFR';


-- ============================================================================
-- Flight Schedule Table (FIDS)
-- ============================================================================

CREATE TABLE IF NOT EXISTS flight_schedule (
    id SERIAL PRIMARY KEY,
    flight_number VARCHAR(10) NOT NULL,
    airline VARCHAR(100),
    airline_code VARCHAR(4),
    origin VARCHAR(4) NOT NULL,
    destination VARCHAR(4) NOT NULL,
    scheduled_time TIMESTAMP WITH TIME ZONE NOT NULL,
    estimated_time TIMESTAMP WITH TIME ZONE,
    actual_time TIMESTAMP WITH TIME ZONE,
    gate VARCHAR(10),
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    delay_minutes INT DEFAULT 0,
    delay_reason VARCHAR(100),
    aircraft_type VARCHAR(10),
    flight_type VARCHAR(10) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_flight_schedule UNIQUE(flight_number, scheduled_time)
);

CREATE INDEX IF NOT EXISTS idx_schedule_time
ON flight_schedule(scheduled_time);

CREATE INDEX IF NOT EXISTS idx_schedule_type
ON flight_schedule(flight_type);

CREATE INDEX IF NOT EXISTS idx_schedule_status
ON flight_schedule(status);

DROP TRIGGER IF EXISTS update_flight_schedule_updated_at ON flight_schedule;
CREATE TRIGGER update_flight_schedule_updated_at
    BEFORE UPDATE ON flight_schedule
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE flight_schedule IS 'Flight schedule for FIDS display (arrivals and departures)';
COMMENT ON COLUMN flight_schedule.flight_type IS 'Either "arrival" or "departure"';
COMMENT ON COLUMN flight_schedule.status IS 'scheduled, on_time, delayed, boarding, departed, arrived, cancelled';


-- ============================================================================
-- Baggage Status Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS baggage_status (
    flight_number VARCHAR(10) PRIMARY KEY,
    total_bags INT DEFAULT 0,
    checked_in INT DEFAULT 0,
    loaded INT DEFAULT 0,
    unloaded INT DEFAULT 0,
    on_carousel INT DEFAULT 0,
    loading_progress_pct INT DEFAULT 0,
    connecting_bags INT DEFAULT 0,
    misconnects INT DEFAULT 0,
    carousel INT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

DROP TRIGGER IF EXISTS update_baggage_status_updated_at ON baggage_status;
CREATE TRIGGER update_baggage_status_updated_at
    BEFORE UPDATE ON baggage_status
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE baggage_status IS 'Baggage handling status per flight';
COMMENT ON COLUMN baggage_status.loading_progress_pct IS 'Percentage of bags loaded (0-100)';


-- ============================================================================
-- GSE Fleet Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS gse_fleet (
    unit_id VARCHAR(20) PRIMARY KEY,
    gse_type VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'available',
    assigned_flight VARCHAR(10),
    assigned_gate VARCHAR(10),
    position_x DECIMAL(8,2) DEFAULT 0.0,
    position_y DECIMAL(8,2) DEFAULT 0.0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gse_fleet_type
ON gse_fleet(gse_type);

CREATE INDEX IF NOT EXISTS idx_gse_fleet_status
ON gse_fleet(status);

DROP TRIGGER IF EXISTS update_gse_fleet_updated_at ON gse_fleet;
CREATE TRIGGER update_gse_fleet_updated_at
    BEFORE UPDATE ON gse_fleet
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE gse_fleet IS 'Ground Support Equipment fleet inventory';
COMMENT ON COLUMN gse_fleet.gse_type IS 'pushback_tug, fuel_truck, belt_loader, etc.';
COMMENT ON COLUMN gse_fleet.status IS 'available, en_route, servicing, returning, maintenance';


-- ============================================================================
-- GSE Turnaround Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS gse_turnaround (
    icao24 VARCHAR(6) PRIMARY KEY,
    flight_number VARCHAR(10),
    gate VARCHAR(10),
    arrival_time TIMESTAMP WITH TIME ZONE,
    current_phase VARCHAR(30) NOT NULL DEFAULT 'arrival_taxi',
    phase_progress_pct INT DEFAULT 0,
    total_progress_pct INT DEFAULT 0,
    estimated_departure TIMESTAMP WITH TIME ZONE,
    aircraft_type VARCHAR(10),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gse_turnaround_gate
ON gse_turnaround(gate);

CREATE INDEX IF NOT EXISTS idx_gse_turnaround_phase
ON gse_turnaround(current_phase);

DROP TRIGGER IF EXISTS update_gse_turnaround_updated_at ON gse_turnaround;
CREATE TRIGGER update_gse_turnaround_updated_at
    BEFORE UPDATE ON gse_turnaround
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE gse_turnaround IS 'Active aircraft turnaround operations';
COMMENT ON COLUMN gse_turnaround.current_phase IS 'Turnaround phase: deboarding, refueling, boarding, etc.';
