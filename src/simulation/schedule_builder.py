"""Flight schedule builder for simulation runs.

Generates a time-ordered list of flight dicts with arrivals linked to
departures via turnaround time, using calibration profiles for realistic
traffic distributions.
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Optional

from src.calibration.profile import AirportProfile
from src.ingestion.schedule_generator import (
    _select_airline,
    _generate_flight_number,
    _select_destination,
    _select_aircraft,
    _generate_delay,
    _get_flights_per_hour,
)
from src.simulation.config import SimulationConfig

logger = logging.getLogger(__name__)


def _calibrated_turnaround(
    aircraft_type: str,
    airline_code: str,
    profile: AirportProfile,
) -> float:
    """Compute turnaround using calibration data when available.

    Re-exported from engine for backward compatibility. Uses BTS OTP turnaround
    stats from the airport profile as baseline, with aircraft-category and
    airline adjustments. Falls back to critical-path DAG model when no
    calibration data exists.
    """
    from src.simulation.engine import _calibrated_turnaround as _engine_calibrated
    return _engine_calibrated(aircraft_type, airline_code, profile)


class ScheduleBuilder:
    """Builds a flight schedule for a simulation run.

    Subclass and override individual methods to customize schedule strategies.
    """

    def __init__(
        self,
        config: SimulationConfig,
        profile: AirportProfile,
        scenario=None,
    ) -> None:
        self.config = config
        self.profile = profile
        self.scenario = scenario

    def build(self) -> list[dict]:
        """Generate the full schedule: arrivals + linked deps + surplus + injections."""
        schedule: list[dict] = []

        arrivals = self._generate_arrivals()
        schedule.extend(arrivals)

        linked, linked_count = self._link_departures(arrivals)
        schedule.extend(linked)

        surplus = self._generate_surplus_departures(linked_count)
        schedule.extend(surplus)

        fighters = self._inject_fighter_sorties()
        schedule.extend(fighters)

        traffic = self._inject_traffic_modifiers()
        schedule.extend(traffic)

        schedule.sort(key=lambda f: f["scheduled_time"])

        logger.info(
            "Generated schedule: %d arrivals, %d departures (%d linked, %d overnight) over %.1fh",
            sum(1 for f in schedule if f["flight_type"] == "arrival"),
            sum(1 for f in schedule if f["flight_type"] == "departure"),
            linked_count,
            len(surplus),
            self.config.effective_duration_hours(),
        )

        return schedule

    def _generate_arrivals(self) -> list[dict]:
        """Generate arrivals distributed across hours using profile-weighted demand."""
        start = self.config.effective_start_time()
        duration_h = self.config.effective_duration_hours()
        profile = self.profile
        local_iata = self.config.airport

        n_hours = int(duration_h) + (1 if duration_h % 1 > 0 else 0)
        hour_weights: list[float] = []
        for h_offset in range(n_hours):
            clock_hour = (start.hour + h_offset) % 24
            day_offset = (start.hour + h_offset) // 24
            dow = (start.weekday() + day_offset) % 7
            w = _get_flights_per_hour(clock_hour, airport_profile=profile, day_of_week=dow)
            hour_weights.append(max(w, 1.0))

        if not hour_weights:
            hour_weights = [1.0]

        total_weight = sum(hour_weights)
        arrivals: list[dict] = []
        arrival_count = 0

        for h_idx, weight in enumerate(hour_weights):
            flights_this_hour = max(1, round(self.config.arrivals * weight / total_weight))
            if h_idx == len(hour_weights) - 1:
                flights_this_hour = max(0, self.config.arrivals - arrival_count)

            for _ in range(flights_this_hour):
                if arrival_count >= self.config.arrivals:
                    break

                airline_code, airline_name = _select_airline(profile=profile)
                flight_number = _generate_flight_number(airline_code)
                origin = _select_destination("arrival", airline_code, profile=profile)
                aircraft = _select_aircraft(origin, airline_code=airline_code, profile=profile)
                minute = random.randint(0, 59)
                scheduled_time = start + timedelta(hours=h_idx, minutes=minute)
                delay_minutes, delay_code, delay_reason = _generate_delay(profile=profile)

                arrivals.append({
                    "flight_number": flight_number,
                    "airline": airline_name,
                    "airline_code": airline_code,
                    "origin": origin,
                    "destination": local_iata,
                    "aircraft_type": aircraft,
                    "flight_type": "arrival",
                    "scheduled_time": scheduled_time.isoformat(),
                    "delay_minutes": delay_minutes,
                    "delay_code": delay_code,
                    "delay_reason": delay_reason,
                })
                arrival_count += 1

        return arrivals

    def _link_departures(self, arrivals: list[dict]) -> tuple[list[dict], int]:
        """Link departures to arrivals via turnaround time (same aircraft/airline)."""
        start = self.config.effective_start_time()
        end_time = start + timedelta(hours=self.config.effective_duration_hours())
        profile = self.profile
        local_iata = self.config.airport

        departures: list[dict] = []
        linked_count = 0
        linkable = min(len(arrivals), self.config.departures)

        for arr in arrivals[:linkable]:
            turnaround = _calibrated_turnaround(arr["aircraft_type"], arr["airline_code"], profile)
            arr_time = datetime.fromisoformat(arr["scheduled_time"])
            dep_time = arr_time + timedelta(minutes=turnaround)

            if dep_time >= end_time:
                continue

            destination = _select_destination("departure", arr["airline_code"], profile=profile)
            delay_minutes, delay_code, delay_reason = _generate_delay(profile=profile)

            departures.append({
                "flight_number": _generate_flight_number(arr["airline_code"]),
                "airline": arr["airline"],
                "airline_code": arr["airline_code"],
                "origin": local_iata,
                "destination": destination,
                "aircraft_type": arr["aircraft_type"],
                "flight_type": "departure",
                "scheduled_time": dep_time.isoformat(),
                "delay_minutes": delay_minutes,
                "delay_code": delay_code,
                "delay_reason": delay_reason,
                "linked_arrival": arr["flight_number"],
            })
            linked_count += 1

        return departures, linked_count

    def _generate_surplus_departures(self, linked_count: int) -> list[dict]:
        """Generate surplus independent departures (overnight-parked aircraft)."""
        start = self.config.effective_start_time()
        duration_h = self.config.effective_duration_hours()
        profile = self.profile
        local_iata = self.config.airport

        surplus_count = self.config.departures - linked_count
        if surplus_count <= 0:
            return []

        early_window_h = min(2.0, duration_h)
        departures: list[dict] = []

        for _ in range(surplus_count):
            airline_code, airline_name = _select_airline(profile=profile)
            destination = _select_destination("departure", airline_code, profile=profile)
            aircraft = _select_aircraft(destination, airline_code=airline_code, profile=profile)
            minute = random.randint(0, int(early_window_h * 60) - 1)
            scheduled_time = start + timedelta(minutes=minute)
            delay_minutes, delay_code, delay_reason = _generate_delay(profile=profile)

            departures.append({
                "flight_number": _generate_flight_number(airline_code),
                "airline": airline_name,
                "airline_code": airline_code,
                "origin": local_iata,
                "destination": destination,
                "aircraft_type": aircraft,
                "flight_type": "departure",
                "scheduled_time": scheduled_time.isoformat(),
                "delay_minutes": delay_minutes,
                "delay_code": delay_code,
                "delay_reason": delay_reason,
            })

        return departures

    def _inject_fighter_sorties(self) -> list[dict]:
        """Easter egg: inject Ukrainian Air Force fighter jet sorties for UA airports."""
        from src.ingestion.schedule_generator import FIGHTER_JETS
        from src.ingestion.airport_table import AIRPORTS as _apt

        local_iata = self.config.airport
        entry = _apt.get(local_iata)
        if not entry:
            for iata, e in _apt.items():
                if e[2] == local_iata:
                    entry = e
                    break
        if not entry or entry[3] != "UA":
            return []

        start = self.config.effective_start_time()
        duration_h = self.config.effective_duration_hours()

        ua_airports = [code for code, e in _apt.items() if e[3] == "UA" and code != local_iata]
        if not ua_airports:
            ua_airports = [local_iata]

        # ~18% of total expected flights as fighter sorties
        total_expected = self.config.arrivals + self.config.departures
        n_sorties = max(4, int(total_expected * 0.18))

        sorties: list[dict] = []
        for _ in range(n_sorties):
            aircraft = random.choice(FIGHTER_JETS)
            flight_num = f"UAF{random.randint(100, 999)}"
            hour = random.uniform(0, duration_h)
            sched_time = start + timedelta(hours=hour)
            dest = random.choice(ua_airports)

            sorties.append({
                "flight_number": flight_num,
                "airline": "Ukrainian Air Force",
                "airline_code": "UAF",
                "origin": local_iata,
                "destination": dest,
                "aircraft_type": aircraft,
                "flight_type": "departure",
                "scheduled_time": sched_time.isoformat(),
                "delay_minutes": 0,
                "delay_code": None,
                "delay_reason": None,
                "scenario_injected": True,
            })

            return_time = sched_time + timedelta(minutes=random.randint(30, 90))
            if return_time < start + timedelta(hours=duration_h):
                sorties.append({
                    "flight_number": f"UAF{random.randint(100, 999)}",
                    "airline": "Ukrainian Air Force",
                    "airline_code": "UAF",
                    "origin": dest,
                    "destination": local_iata,
                    "aircraft_type": aircraft,
                    "flight_type": "arrival",
                    "scheduled_time": return_time.isoformat(),
                    "delay_minutes": 0,
                    "delay_code": None,
                    "delay_reason": None,
                    "scenario_injected": True,
                })

        n_fighters = len(sorties)
        if n_fighters:
            logger.info("Easter egg: injected %d Ukrainian Air Force fighter sorties", n_fighters)
        return sorties

    def _inject_traffic_modifiers(self) -> list[dict]:
        """Inject extra flights from scenario traffic modifiers."""
        if not self.scenario:
            return []

        start = self.config.effective_start_time()
        profile = self.profile
        local_iata = self.config.airport
        injected: list[dict] = []

        for mod in self.scenario.traffic_modifiers:
            if mod.type == "ground_stop":
                continue
            base_time = start
            if mod.time:
                h, m = map(int, mod.time.split(":"))
                base_time = start.replace(hour=h, minute=m, second=0, microsecond=0)

            for i in range(mod.extra_arrivals):
                offset_min = random.randint(0, 20)
                sched_time = base_time + timedelta(minutes=offset_min + i * 3)
                airline_code, airline_name = _select_airline(profile=profile)
                origin = mod.diversion_origin or _select_destination("arrival", airline_code, profile=profile)
                aircraft = _select_aircraft(origin, airline_code=airline_code, profile=profile)
                injected.append({
                    "flight_number": _generate_flight_number(airline_code),
                    "airline": airline_name,
                    "airline_code": airline_code,
                    "origin": origin,
                    "destination": local_iata,
                    "aircraft_type": aircraft,
                    "flight_type": "arrival",
                    "scheduled_time": sched_time.isoformat(),
                    "delay_minutes": 0,
                    "delay_code": None,
                    "delay_reason": f"Diversion from {mod.diversion_origin}" if mod.diversion_origin else "Traffic surge",
                    "scenario_injected": True,
                })

            for i in range(mod.extra_departures):
                offset_min = random.randint(0, 20)
                sched_time = base_time + timedelta(minutes=offset_min + i * 3)
                airline_code, airline_name = _select_airline(profile=profile)
                dest = _select_destination("departure", airline_code, profile=profile)
                aircraft = _select_aircraft(dest, airline_code=airline_code, profile=profile)
                injected.append({
                    "flight_number": _generate_flight_number(airline_code),
                    "airline": airline_name,
                    "airline_code": airline_code,
                    "origin": local_iata,
                    "destination": dest,
                    "aircraft_type": aircraft,
                    "flight_type": "departure",
                    "scheduled_time": sched_time.isoformat(),
                    "delay_minutes": 0,
                    "delay_code": None,
                    "delay_reason": "Traffic surge",
                    "scenario_injected": True,
                })

        if injected:
            logger.info("Injected %d flights from scenario traffic modifiers", len(injected))
        return injected
