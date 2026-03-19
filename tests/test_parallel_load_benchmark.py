"""Benchmark: parallel vs sequential UC airport config loading.

Simulates realistic SQL query latency (2-3s per query) to measure
the speedup from ThreadPoolExecutor parallelization in load_airport_config().
"""

import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import pytest

from src.persistence.airport_repository import AirportRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMULATED_QUERY_LATENCY = 2.5  # seconds per UC query (realistic average)
NUM_TABLES = 10  # gates, terminals, runways, taxiways, aprons, buildings,
                 # hangars, helipads, parking_positions, osm_runways

FAKE_META = [{
    "icao_code": "KSFO",
    "iata_code": "SFO",
    "name": "San Francisco International Airport",
    "operator": "City of San Francisco",
    "data_sources": ["osm"],
    "osm_timestamp": "2026-03-01T00:00:00Z",
}]

FAKE_GATE_ROW = {
    "ref": "A1", "osm_id": 12345, "name": "Gate A1",
    "terminal": "International", "level": "1", "operator": "United",
    "elevation": 4.0, "latitude": 37.6155, "longitude": -122.39,
    "position_x": 100.0, "position_y": 0.0, "position_z": 50.0,
}

FAKE_TERMINAL_ROW = {
    "terminal_id": "KSFO_T1", "osm_id": 123, "name": "Terminal 1",
    "terminal_type": "terminal", "operator": None, "level": None,
    "height": 15.0, "center_lat": 37.615, "center_lon": -122.39,
    "position_x": 0, "position_y": 0, "position_z": 0,
    "width": 200, "depth": 100,
    "polygon_json": '[{"x":0,"y":0,"z":0}]',
    "geo_polygon_json": '[{"latitude":37.615,"longitude":-122.39}]',
    "color": None,
}


def _make_slow_execute(latency: float):
    """Create a mock _execute that sleeps to simulate query latency."""
    call_count = {"n": 0}

    def slow_execute(sql, **kwargs):
        call_count["n"] += 1
        time.sleep(latency)
        if "airport_metadata" in sql:
            return FAKE_META
        if "gates" in sql:
            return [FAKE_GATE_ROW]
        if "terminals" in sql:
            return [FAKE_TERMINAL_ROW]
        # All other tables return empty
        return []

    return slow_execute, call_count


def _make_repo():
    repo = AirportRepository.__new__(AirportRepository)
    repo._client = MagicMock()
    repo._warehouse_id = "test"
    repo._catalog = "test_catalog"
    repo._schema = "test_schema"
    repo._tables_initialized = True
    repo._use_sql_connector = False
    repo._host = None
    repo._http_path = None
    repo._use_oauth = False
    repo._token = None
    return repo


# ---------------------------------------------------------------------------
# Sequential baseline (what we had before)
# ---------------------------------------------------------------------------

def _load_airport_config_sequential(repo, icao_code):
    """Original sequential implementation for comparison."""
    repo._ensure_tables()

    meta_rows = repo._execute(
        f"SELECT * FROM {repo._table('airport_metadata')} WHERE icao_code = '{icao_code}'"
    )
    if not meta_rows:
        return None
    meta = meta_rows[0]

    gates = repo._load_gates(icao_code)
    terminals = repo._load_terminals(icao_code)
    runways = repo._load_runways(icao_code)
    taxiways = repo._load_taxiways(icao_code)
    aprons = repo._load_aprons(icao_code)
    buildings = repo._load_buildings(icao_code)
    hangars = repo._load_hangars(icao_code)
    helipads = repo._load_helipads(icao_code)
    parking_positions = repo._load_parking_positions(icao_code)
    osm_runways = repo._load_osm_runways(icao_code)

    return {
        "source": "LAKEHOUSE",
        "gates": gates,
        "terminals": terminals,
        "runways": runways,
        "osmTaxiways": taxiways,
        "osmAprons": aprons,
        "buildings": buildings,
        "osmHangars": hangars,
        "osmHelipads": helipads,
        "osmParkingPositions": parking_positions,
        "osmRunways": osm_runways,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParallelLoadBenchmark:
    """Benchmark sequential vs parallel load_airport_config()."""

    @pytest.mark.parametrize("latency", [0.5, 1.0, 2.5])
    def test_sequential_wall_time(self, latency):
        """Sequential: wall time ~ (1 + NUM_TABLES) * latency."""
        repo = _make_repo()
        slow_exec, call_count = _make_slow_execute(latency)
        repo._execute = slow_exec

        start = time.perf_counter()
        result = _load_airport_config_sequential(repo, "KSFO")
        elapsed = time.perf_counter() - start

        assert result is not None
        assert result["source"] == "LAKEHOUSE"
        assert len(result["gates"]) == 1
        # 1 metadata + 10 table queries = 11 total
        assert call_count["n"] == 11
        expected_min = (NUM_TABLES + 1) * latency * 0.9
        assert elapsed >= expected_min, (
            f"Sequential took {elapsed:.2f}s, expected >= {expected_min:.2f}s"
        )
        print(f"\n  Sequential ({latency}s latency): {elapsed:.2f}s "
              f"({call_count['n']} queries)")

    @pytest.mark.parametrize("latency", [0.5, 1.0, 2.5])
    def test_parallel_wall_time(self, latency):
        """Parallel: wall time ~ latency (metadata) + latency (10 parallel)."""
        repo = _make_repo()
        slow_exec, call_count = _make_slow_execute(latency)
        repo._execute = slow_exec

        start = time.perf_counter()
        result = repo.load_airport_config("KSFO")
        elapsed = time.perf_counter() - start

        assert result is not None
        assert result["source"] == "LAKEHOUSE"
        assert len(result["gates"]) == 1
        assert call_count["n"] == 11
        # Parallel: metadata (1 * latency) + all 10 in parallel (~ 1 * latency)
        # Allow 2x buffer for thread scheduling overhead
        expected_max = latency * 4
        assert elapsed <= expected_max, (
            f"Parallel took {elapsed:.2f}s, expected <= {expected_max:.2f}s"
        )
        print(f"\n  Parallel   ({latency}s latency): {elapsed:.2f}s "
              f"({call_count['n']} queries)")

    def test_speedup_ratio(self):
        """Verify parallel is at least 3x faster than sequential."""
        latency = 1.0
        runs = 3
        seq_times = []
        par_times = []

        for _ in range(runs):
            # Sequential
            repo = _make_repo()
            slow_exec, _ = _make_slow_execute(latency)
            repo._execute = slow_exec
            start = time.perf_counter()
            _load_airport_config_sequential(repo, "KSFO")
            seq_times.append(time.perf_counter() - start)

            # Parallel
            repo2 = _make_repo()
            slow_exec2, _ = _make_slow_execute(latency)
            repo2._execute = slow_exec2
            start = time.perf_counter()
            repo2.load_airport_config("KSFO")
            par_times.append(time.perf_counter() - start)

        avg_seq = statistics.mean(seq_times)
        avg_par = statistics.mean(par_times)
        speedup = avg_seq / avg_par

        print(f"\n  === SPEEDUP BENCHMARK (latency={latency}s) ===")
        print(f"  Sequential avg: {avg_seq:.2f}s")
        print(f"  Parallel   avg: {avg_par:.2f}s")
        print(f"  Speedup:        {speedup:.1f}x")

        assert speedup >= 3.0, f"Expected >= 3x speedup, got {speedup:.1f}x"

    def test_parallel_data_integrity(self):
        """Verify all data is correctly assembled after parallel load."""
        repo = _make_repo()
        # No latency — just check correctness
        slow_exec, _ = _make_slow_execute(0.0)
        repo._execute = slow_exec

        result = repo.load_airport_config("KSFO")

        assert result["source"] == "LAKEHOUSE"
        assert result["icaoCode"] == "KSFO"
        assert result["iataCode"] == "SFO"
        assert result["airportName"] == "San Francisco International Airport"
        assert len(result["gates"]) == 1
        assert result["gates"][0]["ref"] == "A1"
        assert len(result["terminals"]) == 1
        assert result["terminals"][0]["name"] == "Terminal 1"
        # Empty tables should return []
        assert result["runways"] == []
        assert result["osmTaxiways"] == []
        assert result["osmAprons"] == []
        assert result["buildings"] == []
        assert result["osmHangars"] == []
        assert result["osmHelipads"] == []
        assert result["osmParkingPositions"] == []
        assert result["osmRunways"] == []

    def test_parallel_single_table_failure_graceful(self):
        """If one table query fails, others still load."""
        repo = _make_repo()

        call_count = {"n": 0}

        def failing_execute(sql, **kwargs):
            call_count["n"] += 1
            if "airport_metadata" in sql:
                return FAKE_META
            if "gates" in sql:
                raise RuntimeError("Simulated gates query failure")
            if "terminals" in sql:
                return [FAKE_TERMINAL_ROW]
            return []

        repo._execute = failing_execute

        result = repo.load_airport_config("KSFO")

        assert result is not None
        # Gates failed — should be empty list (graceful degradation)
        assert result["gates"] == []
        # Terminals should still be loaded
        assert len(result["terminals"]) == 1


class TestRealisticLatencyProfile:
    """Simulate realistic latency distribution across tables."""

    def test_variable_latency_parallel(self):
        """Tables have different latencies; parallel bounded by slowest."""
        # Simulate: some tables fast (0.3s), some slow (3s)
        table_latencies = {
            "airport_metadata": 0.5,
            "gates": 2.0,
            "terminals": 3.0,  # slowest
            "runways": 1.5,
            "taxiways": 1.0,
            "aprons": 0.8,
            "buildings": 0.5,
            "hangars": 0.3,
            "helipads": 0.3,
            "parking_positions": 0.5,
            "osm_runways": 1.0,
        }

        def variable_execute(sql, **kwargs):
            for table, lat in table_latencies.items():
                if table in sql:
                    time.sleep(lat)
                    if table == "airport_metadata":
                        return FAKE_META
                    if table == "gates":
                        return [FAKE_GATE_ROW]
                    if table == "terminals":
                        return [FAKE_TERMINAL_ROW]
                    return []
            return []

        # Sequential
        repo_seq = _make_repo()
        repo_seq._execute = variable_execute
        start = time.perf_counter()
        _load_airport_config_sequential(repo_seq, "KSFO")
        seq_time = time.perf_counter() - start

        # Parallel
        repo_par = _make_repo()
        repo_par._execute = variable_execute
        start = time.perf_counter()
        repo_par.load_airport_config("KSFO")
        par_time = time.perf_counter() - start

        total_latency = sum(table_latencies.values())
        max_table_latency = max(
            v for k, v in table_latencies.items() if k != "airport_metadata"
        )
        speedup = seq_time / par_time

        print(f"\n  === VARIABLE LATENCY BENCHMARK ===")
        print(f"  Total query latency:  {total_latency:.1f}s")
        print(f"  Slowest table query:  {max_table_latency:.1f}s")
        print(f"  Sequential wall time: {seq_time:.2f}s")
        print(f"  Parallel wall time:   {par_time:.2f}s")
        print(f"  Speedup:              {speedup:.1f}x")
        print(f"  Theoretical max:      {total_latency / (table_latencies['airport_metadata'] + max_table_latency):.1f}x")

        assert speedup >= 2.0, f"Expected >= 2x speedup, got {speedup:.1f}x"
