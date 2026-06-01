"""Tests for ICAO ↔ IATA callsign reconciliation."""

from src.ingestion.callsign_reconciler import (
    to_iata,
    to_icao,
    normalize,
    are_same_flight,
)


class TestToIata:
    def test_icao_to_iata(self):
        assert to_iata("UAL123") == "UA123"
        assert to_iata("BAW456") == "BA456"
        assert to_iata("DLH789") == "LH789"
        assert to_iata("DAL100") == "DL100"
        assert to_iata("SWA3456") == "WN3456"

    def test_already_iata(self):
        assert to_iata("UA123") == "UA123"
        assert to_iata("BA456") == "BA456"

    def test_unknown_prefix(self):
        assert to_iata("XYZ999") is None

    def test_non_standard_format(self):
        assert to_iata("") is None
        assert to_iata("123") is None
        assert to_iata("A") is None

    def test_strips_whitespace(self):
        assert to_iata("  UAL123  ") == "UA123"

    def test_case_insensitive(self):
        assert to_iata("ual123") == "UA123"


class TestToIcao:
    def test_iata_to_icao(self):
        assert to_icao("UA123") == "UAL123"
        assert to_icao("BA456") == "BAW456"
        assert to_icao("LH789") == "DLH789"
        assert to_icao("DL100") == "DAL100"
        assert to_icao("WN3456") == "SWA3456"

    def test_already_icao(self):
        assert to_icao("UAL123") == "UAL123"

    def test_unknown_prefix(self):
        assert to_icao("ZZ999") is None


class TestNormalize:
    def test_icao_normalized_to_iata(self):
        assert normalize("UAL123") == "UA123"
        assert normalize("BAW456") == "BA456"

    def test_iata_stays_iata(self):
        assert normalize("UA123") == "UA123"

    def test_unknown_passes_through(self):
        assert normalize("XYZ999") == "XYZ999"

    def test_whitespace_stripped(self):
        assert normalize("  UAL123  ") == "UA123"


class TestAreSameFlight:
    def test_icao_equals_iata(self):
        assert are_same_flight("UAL123", "UA123") is True
        assert are_same_flight("BAW456", "BA456") is True
        assert are_same_flight("DLH789", "LH789") is True

    def test_same_format_same_flight(self):
        assert are_same_flight("UA123", "UA123") is True
        assert are_same_flight("UAL123", "UAL123") is True

    def test_different_flights(self):
        assert are_same_flight("UAL123", "UA456") is False
        assert are_same_flight("UAL123", "DAL123") is False

    def test_regional_carriers(self):
        assert are_same_flight("RYR1296", "FR1296") is True
        assert are_same_flight("EZY100", "U2100") is True

    def test_middle_east(self):
        assert are_same_flight("UAE500", "EK500") is True
        assert are_same_flight("ETD200", "EY200") is True
        assert are_same_flight("QTR800", "QR800") is True

    def test_asia_pacific(self):
        assert are_same_flight("ANA100", "NH100") is True
        assert are_same_flight("JAL200", "JL200") is True
        assert are_same_flight("SIA300", "SQ300") is True
        assert are_same_flight("KAL400", "KE400") is True
