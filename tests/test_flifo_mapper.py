"""Tests for FLIFO response mapper."""

from src.ingestion.flifo_mapper import map_flifo_record, map_flifo_response


class TestFlifoMapper:
    def _sample_record(self):
        return {
            "flightNumber": "UA1234",
            "airline": {"iataCode": "UA", "icaoCode": "UAL", "name": "United Airlines"},
            "departure": {
                "iataCode": "LAX",
                "icaoCode": "KLAX",
                "scheduledTime": "2026-06-01T14:30:00Z",
            },
            "arrival": {
                "iataCode": "SFO",
                "icaoCode": "KSFO",
                "scheduledTime": "2026-06-01T15:45:00Z",
                "estimatedTime": "2026-06-01T15:50:00Z",
                "actualTime": None,
                "terminal": "1",
                "gate": "B12",
                "baggageBelt": "3",
            },
            "statusCode": "DL",
            "statusDescription": "Delayed",
            "delayMinutes": 5,
            "delayCode": "81",
            "aircraft": {"registration": "N12345", "iataType": "320", "icaoType": "A320"},
            "codeshares": [{"flightNumber": "LH7234", "airline": {"iataCode": "LH"}}],
            "updatedAt": "2026-06-01T14:00:00Z",
        }

    def test_maps_arrival(self):
        result = map_flifo_record(self._sample_record(), "SFO")
        assert result["flight_number"] == "UA1234"
        assert result["flight_type"] == "arrival"
        assert result["origin"] == "LAX"
        assert result["destination"] == "SFO"
        assert result["status"] == "delayed"
        assert result["delay_minutes"] == 5
        assert result["delay_reason"] == "81"
        assert result["gate"] == "B12"
        assert result["terminal"] == "1"
        assert result["belt"] == "3"
        assert result["registration"] == "N12345"
        assert result["codeshares"] == ["LH7234"]
        assert result["aircraft_type"] == "A320"
        assert result["data_source"] == "flifo"

    def test_maps_departure(self):
        record = self._sample_record()
        result = map_flifo_record(record, "LAX")
        assert result["flight_type"] == "departure"
        assert result["origin"] == "LAX"
        assert result["destination"] == "SFO"
        assert result["belt"] is None

    def test_maps_cancelled(self):
        record = self._sample_record()
        record["statusCode"] = "CX"
        result = map_flifo_record(record, "SFO")
        assert result["status"] == "cancelled"

    def test_maps_boarding(self):
        record = self._sample_record()
        record["statusCode"] = "BD"
        result = map_flifo_record(record, "SFO")
        assert result["status"] == "boarding"

    def test_map_full_response(self):
        response = {
            "flightRecords": [self._sample_record()],
            "totalRecords": 1,
            "airport": "SFO",
        }
        results = map_flifo_response(response, "SFO")
        assert len(results) == 1
        assert results[0]["flight_number"] == "UA1234"

    def test_direction_filter(self):
        response = {
            "flightRecords": [self._sample_record()],
            "totalRecords": 1,
        }
        arrivals = map_flifo_response(response, "SFO", direction="arrival")
        departures = map_flifo_response(response, "SFO", direction="departure")
        assert len(arrivals) == 1
        assert len(departures) == 0

    def test_unknown_status_defaults_scheduled(self):
        record = self._sample_record()
        record["statusCode"] = "ZZ"
        result = map_flifo_record(record, "SFO")
        assert result["status"] == "scheduled"

    def test_missing_codeshares(self):
        record = self._sample_record()
        record["codeshares"] = []
        result = map_flifo_record(record, "SFO")
        assert result["codeshares"] is None

    def test_no_codeshares_key(self):
        record = self._sample_record()
        del record["codeshares"]
        result = map_flifo_record(record, "SFO")
        assert result["codeshares"] is None
