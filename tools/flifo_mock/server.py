"""FLIFO mock server — mimics SITA FlightInfo API v2.

Run: uv run uvicorn tools.flifo_mock.server:app --port 8089
"""

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query

from tools.flifo_mock.auth import issue_token, validate_token
from tools.flifo_mock.generator import generate_flights
from tools.flifo_mock.models import FlightResponse, TokenResponse

# When embedded in main app, skip auth (already behind Databricks auth)
_EMBEDDED_MODE = os.getenv("FLIFO_MOCK_MODE", "").lower() in ("true", "1", "yes")


def _no_auth():
    """No-op auth dependency for embedded mode."""
    return "embedded"


_auth_dep = _no_auth if _EMBEDDED_MODE else validate_token

app = FastAPI(
    title="FLIFO Mock Server",
    description="Local mock of SITA FlightInfo API v2 for development",
    version="0.1.0",
)


@app.post("/oauth/token", response_model=TokenResponse)
def get_token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
):
    """OAuth2 client credentials token endpoint."""
    if grant_type != "client_credentials":
        raise HTTPException(status_code=400, detail="Only client_credentials grant_type supported")

    token = issue_token(client_id, client_secret)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid client credentials")

    return TokenResponse(access_token=token)


@app.get("/flightinfo/v2/flights/airport/{airport_iata}", response_model=FlightResponse)
def get_flights_by_airport(
    airport_iata: str,
    direction: Optional[str] = Query(None, description="arrival or departure"),
    fromDate: Optional[str] = Query(None, description="ISO datetime start"),
    toDate: Optional[str] = Query(None, description="ISO datetime end"),
    status: Optional[str] = Query(None, description="Filter by status code"),
    limit: int = Query(30, ge=1, le=200),
    _token: str = Depends(_auth_dep),
):
    """Get flights for an airport — main FLIFO endpoint."""
    airport_iata = airport_iata.upper()

    from_time = None
    to_time = None
    if fromDate:
        from_time = datetime.fromisoformat(fromDate.replace("Z", "+00:00"))
    if toDate:
        to_time = datetime.fromisoformat(toDate.replace("Z", "+00:00"))

    records = generate_flights(
        airport_iata=airport_iata,
        direction=direction,
        from_time=from_time,
        to_time=to_time,
        count=limit,
    )

    if status:
        records = [r for r in records if r.statusCode == status.upper()]

    return FlightResponse(
        flightRecords=records,
        totalRecords=len(records),
        airport=airport_iata,
        direction=direction,
    )


@app.get("/flightinfo/v2/flights/airline/{airline_iata}", response_model=FlightResponse)
def get_flights_by_airline(
    airline_iata: str,
    direction: Optional[str] = Query(None),
    fromDate: Optional[str] = Query(None),
    toDate: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
    _token: str = Depends(_auth_dep),
):
    """Get flights for an airline across all airports."""
    airline_iata = airline_iata.upper()

    from_time = None
    to_time = None
    if fromDate:
        from_time = datetime.fromisoformat(fromDate.replace("Z", "+00:00"))
    if toDate:
        to_time = datetime.fromisoformat(toDate.replace("Z", "+00:00"))

    # Generate from a "world" airport perspective, then filter by airline
    records = generate_flights(
        airport_iata="SFO",
        direction=direction,
        from_time=from_time,
        to_time=to_time,
        count=limit * 5,
    )
    records = [r for r in records if r.airline.iataCode == airline_iata][:limit]

    return FlightResponse(
        flightRecords=records,
        totalRecords=len(records),
        airport="*",
        direction=direction,
    )


@app.get("/flightinfo/v2/flights/{flight_number}", response_model=FlightResponse)
def get_flight_by_number(
    flight_number: str,
    _token: str = Depends(_auth_dep),
):
    """Get a specific flight by flight number."""
    # Generate a single record matching this flight number
    airline_code = "".join(c for c in flight_number if c.isalpha())
    from tools.flifo_mock.generator import AIRLINES

    airline = next((a for a in AIRLINES if a["iata"] == airline_code.upper()), AIRLINES[0])

    from tools.flifo_mock.models import AircraftInfo, AirlineInfo, AirportPoint, FlightRecord
    import random

    now = datetime.now(timezone.utc)
    rng = random.Random(hash(flight_number))

    from tools.flifo_mock.generator import (
        AIRCRAFT_TYPES,
        DESTINATIONS,
        _generate_registration,
        _pick_status_for_time,
    )

    scheduled = now + __import__("datetime").timedelta(minutes=rng.randint(-60, 180))
    aircraft_type = rng.choices(AIRCRAFT_TYPES, weights=[a["weight"] for a in AIRCRAFT_TYPES], k=1)[0]
    dest_pool = DESTINATIONS["domestic_us"] + DESTINATIONS["europe"]
    origin = rng.choice(dest_pool)
    destination = rng.choice([d for d in dest_pool if d != origin])

    minutes_to = (scheduled - now).total_seconds() / 60
    status_code, status_desc, delay_min, delay_code = _pick_status_for_time(minutes_to, "arrival", rng)

    record = FlightRecord(
        flightNumber=flight_number.upper(),
        airline=AirlineInfo(iataCode=airline["iata"], icaoCode=airline["icao"], name=airline["name"]),
        departure=AirportPoint(iataCode=origin, icaoCode=f"K{origin}", scheduledTime=scheduled.strftime("%Y-%m-%dT%H:%M:%SZ")),
        arrival=AirportPoint(iataCode=destination, icaoCode=f"K{destination}", scheduledTime=(scheduled + __import__("datetime").timedelta(hours=rng.randint(1, 8))).strftime("%Y-%m-%dT%H:%M:%SZ")),
        statusCode=status_code,
        statusDescription=status_desc,
        delayMinutes=delay_min,
        delayCode=delay_code,
        aircraft=AircraftInfo(registration=_generate_registration(airline, rng), iataType=aircraft_type["iata"], icaoType=aircraft_type["icao"]),
        codeshares=[],
        updatedAt=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    return FlightResponse(
        flightRecords=[record],
        totalRecords=1,
        airport="*",
    )


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "flifo-mock", "version": "0.1.0"}
