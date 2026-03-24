# Strategic Gap 7: METAR Historical Replay

**Validation tests blocked:** D01 (Weather Event Replay)

**Current state:** Scenario system supports authored weather events (132 YAML configs). Disruption response logic is detailed. But scenarios are hand-authored, not derived from historical observations.

---

## Architecture

### Module location
`src/simulation/metar_replay.py` — new module
`src/ingestion/metar_parser.py` — METAR string parser

### Core flow
```
Historical METAR archive → Parse → Map to WeatherEvent sequence → Inject into scenario timeline
```

### METAR sources
1. **Iowa State ASOS/AWOS**: Free, covers all US airports
   - URL: `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py`
   - Format: CSV with timestamp, station, raw METAR
2. **OGIMET**: International coverage
   - URL: `https://www.ogimet.com/cgi-bin/getmetar`
3. **Local cache**: Download once per airport, store in `data/metar/`

### METAR parser
Parse raw METAR string → structured observation:
```python
@dataclass
class MetarObservation:
    timestamp: datetime
    station: str
    wind_direction: int      # degrees
    wind_speed_kt: int
    wind_gust_kt: Optional[int]
    visibility_sm: float
    ceiling_ft: Optional[int]
    temperature_c: float
    dewpoint_c: float
    altimeter_inhg: float
    flight_category: str     # VFR/MVFR/IFR/LIFR
    weather_phenomena: list[str]  # RA, SN, FG, TS, etc.
    raw: str
```

Use `python-metar` library (pip installable) or implement minimal parser for the subset we need.

### Weather event mapper
Map METAR sequence → scenario WeatherEvent sequence:

| METAR condition | Maps to | Severity |
|----------------|---------|----------|
| TS (thunderstorm) | WeatherEvent("thunderstorm") | ceiling/vis dependent |
| FG/BR (fog/mist) | WeatherEvent("fog") | visibility dependent |
| SN/FZRA | WeatherEvent("snow"/"freezing_rain") | accumulation rate |
| Wind > 25kt | WeatherEvent("wind_shift") | gust factor |
| VIS < 1SM | Auto IFR/LIFR | capacity reduction |

Transitions between conditions create event start/end times.

### Replay workflow
```python
def replay_weather_day(station: str, date: date) -> Scenario:
    """Fetch historical METARs and generate a scenario."""
    observations = fetch_metar_archive(station, date)
    events = map_observations_to_events(observations)
    return Scenario(
        name=f"replay_{station}_{date}",
        events=events,
    )
```

---

## Implementation phases

### Phase 1: METAR parser + archive fetcher (3 days)
- Parse METAR strings to structured observations
- Fetch from Iowa State archive API
- Cache in `data/metar/{station}/{date}.csv`
- Unit tests with known METAR strings

### Phase 2: Event mapper (3 days)
- Map METAR observations to WeatherEvent parameters
- Handle transitions (fog onset → fog clearing)
- Compute event duration from consecutive observations
- Generate runway config changes from wind shifts

### Phase 3: Scenario integration (2 days)
- Generate Scenario YAML from METAR replay
- Inject into simulation engine via existing scenario timeline
- Validation: compare sim recovery curve vs actual ops data

### Phase 4: Recovery curve comparison (1 week)
- Fetch historical flight data for the replay date (BTS T100/ASPM)
- Compare sim departure rate recovery vs actual
- Score: recovery timeline within 30 min at 2-hour horizon
- **Validates:** D01

---

## Data requirements
- Iowa State METAR archive access (free, no auth)
- Historical flight data for validation dates (BTS On-Time Performance)
- Known disruption events for test cases (e.g., SFO fog events)

## Test cases for initial validation
1. **SFO fog event**: SFO gets ~100 fog days/year, well-documented IFR impact
2. **JFK winter storm**: Snow + ground stop + recovery
3. **DFW thunderstorm**: Severe TS with ground delay program

## Estimated effort
Total: ~2.5 weeks
Phase 1-2 alone (parser + mapper) enables automated scenario generation.
Phase 3-4 enables D01 validation.
