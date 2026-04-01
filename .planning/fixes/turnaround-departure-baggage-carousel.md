# Fix: Turnaround Departure Info + Baggage Carousel Clarity

## Context

User selected flight UAL815 (sim00005), just parked at gate D15. Three issues:

1. **Est. Departure has no flight number** — Shows "Est. Departure 10:29 AM" but doesn't say which flight departs. The turnaround timing model computes arrival_time + total_minutes but no departing flight is identified. We need to find the next departure at the same gate from the FIDS schedule.
2. **Baggage carousel "C5" looks like a gate** — Badge shows C5 (carousel 5), easily confused with gate C5. Should say "Carousel 5".
3. **Baggage shows "Delivered 100%" with "0 Delivered"** — Progress bar at 100% but 0 count. Likely a timing issue with the baggage generator for just-parked flights — need to verify.

---

## Fix 1: Show departing flight number on turnaround panel

### Backend

**`src/ingestion/schedule_generator.py`** — New function:
```python
def find_departure_at_gate(gate: str, airport: str = "SFO") -> Optional[dict]:
    """Find next scheduled departure at a specific gate."""
```
- Search cached schedule + live flights for `flight_type == "departure"` AND `gate == gate`
- Filter: `scheduled_time > now - 15min` (include recently departed)
- Sort by time, return first (soonest) match

**`app/backend/models/gse.py`** — Add to `TurnaroundStatus`:
```python
departing_flight: Optional[str] = Field(None, description="Next departure flight number from this gate")
```

**`app/backend/services/gse_service.py`** — In `get_turnaround_status()`:
- Replace `find_scheduled_departure(callsign)` with `find_departure_at_gate(effective_gate)`
- Set `turnaround.departing_flight` from result
- Keep using result's `scheduled_time` for `estimated_departure`

### Frontend

**`app/frontend/src/components/FlightDetail/TurnaroundTimeline.tsx`**:
- Add `departing_flight: string | null` to `TurnaroundStatus` interface
- Change "Est. Departure" line to show: `UAL123 — 10:29 AM` when `departing_flight` is set

---

## Fix 2: Clarify carousel label

**`app/frontend/src/components/Baggage/BaggageStatus.tsx`** line 85:
- `C{stats.carousel}` -> `Carousel {stats.carousel}`

---

## Fix 3: Verify baggage consistency

Check if 100%/0 issue persists after recent `_NON_BAGGAGE_PHASES` fix. If parked phase still shows inconsistent data, investigate `generate_bags_for_flight` timing.

---

## Files to modify

| File | Change |
|------|--------|
| `src/ingestion/schedule_generator.py` | Add `find_departure_at_gate()` |
| `app/backend/models/gse.py` | Add `departing_flight` field |
| `app/backend/services/gse_service.py` | Gate-based departure lookup |
| `app/frontend/src/components/FlightDetail/TurnaroundTimeline.tsx` | Show departing flight number |
| `app/frontend/src/components/Baggage/BaggageStatus.tsx` | Clarify carousel label |

## Verification

1. `uv run pytest tests/ -k "schedule or turnaround or baggage" -v`
2. `cd app/frontend && npm test -- --run`
3. Build + deploy, verify turnaround shows departing flight + carousel is labeled
