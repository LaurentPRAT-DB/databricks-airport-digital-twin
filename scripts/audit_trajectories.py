#!/usr/bin/env python3
"""Audit simulation trajectory quality — flight-by-flight analysis.

Usage:
    uv run python scripts/audit_trajectories.py <simulation_output.json>
    uv run python scripts/audit_trajectories.py <simulation_output.json> --flight UAL1328
    uv run python scripts/audit_trajectories.py <simulation_output.json> --phase approaching
    uv run python scripts/audit_trajectories.py <simulation_output.json> --csv audit_report.csv
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ── Constants ──────────────────────────────────────────────────────────

PHASE_MAX_SPEED_KTS = {
    "approaching": 250,
    "landing": 180,
    "taxi_to_gate": 30,
    "parked": 2,
    "pushback": 10,
    "taxi_to_runway": 30,
    "takeoff": 200,
    "departing": 500,
    "climbing": 500,
    "enroute": 550,
}

PHASE_ALT_RANGE = {
    "taxi_to_gate": (0, 50),
    "parked": (0, 10),
    "pushback": (0, 10),
    "taxi_to_runway": (0, 50),
    "takeoff": (0, 2000),
    "landing": (0, 500),
}

EARTH_RADIUS_NM = 3440.065
EARTH_RADIUS_FT = 6_371_000 * 3.28084


def haversine_nm(lat1, lon1, lat2, lon2):
    """Distance in nautical miles between two points."""
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def haversine_ft(lat1, lon1, lat2, lon2):
    return haversine_nm(lat1, lon1, lat2, lon2) * 6076.12


def bearing_between(lat1, lon1, lat2, lon2):
    """Initial bearing from point 1 to point 2 in degrees."""
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(r2)
    y = math.cos(r1) * math.sin(r2) - math.sin(r1) * math.cos(r2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def heading_diff(h1, h2):
    """Smallest angle between two headings (0-180)."""
    d = abs(h1 - h2) % 360
    return min(d, 360 - d)


# ── Data structures ───────────────────────────────────────────────────

@dataclass
class Snapshot:
    time: str
    lat: float
    lon: float
    alt: float
    velocity: float
    heading: float
    phase: str
    on_ground: bool
    aircraft_type: str
    vertical_rate: float = 0.0
    assigned_gate: str | None = None


@dataclass
class PhaseSegment:
    phase: str
    snapshots: list[Snapshot] = field(default_factory=list)

    @property
    def duration_s(self):
        if len(self.snapshots) < 2:
            return 0
        from datetime import datetime
        t0 = datetime.fromisoformat(self.snapshots[0].time)
        t1 = datetime.fromisoformat(self.snapshots[-1].time)
        return (t1 - t0).total_seconds()


@dataclass
class Violation:
    severity: str  # "error", "warn", "info"
    phase: str
    metric: str
    message: str
    value: float | str = 0


@dataclass
class FlightAudit:
    callsign: str
    icao24: str
    aircraft_type: str
    phases_seen: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    phase_segments: list[PhaseSegment] = field(default_factory=list)
    total_snapshots: int = 0

    # Summary metrics
    max_speed: float = 0
    max_alt: float = 0
    max_heading_jump: float = 0
    max_alt_jump: float = 0
    max_speed_jump: float = 0
    total_distance_nm: float = 0

    @property
    def grade(self):
        errors = sum(1 for v in self.violations if v.severity == "error")
        warns = sum(1 for v in self.violations if v.severity == "warn")
        if errors >= 3:
            return "F"
        elif errors >= 1:
            return "D"
        elif warns >= 3:
            return "C"
        elif warns >= 1:
            return "B"
        else:
            return "A"


# ── Audit checks ──────────────────────────────────────────────────────

def audit_speed(flight: FlightAudit, segment: PhaseSegment):
    """Check speed is within expected range for the phase."""
    max_allowed = PHASE_MAX_SPEED_KTS.get(segment.phase)
    if max_allowed is None:
        return
    for s in segment.snapshots:
        effective_limit = max_allowed
        if s.alt < 10000 and segment.phase in ("departing", "climbing", "approaching"):
            effective_limit = min(effective_limit, 250)
        if s.velocity > effective_limit * 1.1:
            flight.violations.append(Violation(
                severity="error" if s.velocity > effective_limit * 1.5 else "warn",
                phase=segment.phase,
                metric="overspeed",
                message=f"{s.velocity:.0f}kts exceeds {effective_limit}kts at {s.alt:.0f}ft",
                value=s.velocity,
            ))
            break


def audit_altitude(flight: FlightAudit, segment: PhaseSegment):
    """Check altitude is within expected range for ground phases."""
    alt_range = PHASE_ALT_RANGE.get(segment.phase)
    if alt_range is None:
        return
    lo, hi = alt_range
    for s in segment.snapshots:
        if s.alt > hi:
            flight.violations.append(Violation(
                severity="error" if s.alt > hi * 3 else "warn",
                phase=segment.phase,
                metric="altitude_violation",
                message=f"Alt {s.alt:.0f}ft outside [{lo},{hi}]ft for {segment.phase}",
                value=s.alt,
            ))
            break


def audit_heading_continuity(flight: FlightAudit, segment: PhaseSegment):
    """Check for sudden heading reversals (>100deg between snapshots)."""
    max_jump = 0
    for i in range(1, len(segment.snapshots)):
        diff = heading_diff(segment.snapshots[i - 1].heading, segment.snapshots[i].heading)
        max_jump = max(max_jump, diff)
        if diff > 100 and segment.phase not in ("enroute", "pushback"):
            flight.violations.append(Violation(
                severity="warn",
                phase=segment.phase,
                metric="heading_reversal",
                message=f"Heading jump {diff:.0f}deg at {segment.snapshots[i].time}",
                value=diff,
            ))
            break
    flight.max_heading_jump = max(flight.max_heading_jump, max_jump)


def audit_altitude_continuity(flight: FlightAudit, segment: PhaseSegment):
    """Check for unrealistic altitude jumps between snapshots."""
    max_jump = 0
    for i in range(1, len(segment.snapshots)):
        diff = abs(segment.snapshots[i].alt - segment.snapshots[i - 1].alt)
        max_jump = max(max_jump, diff)
        if diff > 1300 and segment.phase not in ("enroute",):
            flight.violations.append(Violation(
                severity="warn" if diff < 2000 else "error",
                phase=segment.phase,
                metric="altitude_jump",
                message=f"Altitude jump {diff:.0f}ft at {segment.snapshots[i].time}",
                value=diff,
            ))
            break
    flight.max_alt_jump = max(flight.max_alt_jump, max_jump)


def audit_speed_continuity(flight: FlightAudit, segment: PhaseSegment):
    """Check for unrealistic speed changes between snapshots."""
    for i in range(1, len(segment.snapshots)):
        diff = abs(segment.snapshots[i].velocity - segment.snapshots[i - 1].velocity)
        flight.max_speed_jump = max(flight.max_speed_jump, diff)
        if diff > 80:
            flight.violations.append(Violation(
                severity="warn",
                phase=segment.phase,
                metric="speed_jump",
                message=f"Speed change {diff:.0f}kts at {segment.snapshots[i].time}",
                value=diff,
            ))
            break


def audit_ground_track(flight: FlightAudit, segment: PhaseSegment):
    """Check if ground movement heading matches actual track direction."""
    if segment.phase not in ("taxi_to_gate", "taxi_to_runway"):
        return
    mismatches = 0
    for i in range(1, len(segment.snapshots)):
        s0, s1 = segment.snapshots[i - 1], segment.snapshots[i]
        dist = haversine_ft(s0.lat, s0.lon, s1.lat, s1.lon)
        if dist < 10:  # skip if stationary
            continue
        actual_track = bearing_between(s0.lat, s0.lon, s1.lat, s1.lon)
        reported_heading = s1.heading
        diff = heading_diff(actual_track, reported_heading)
        if diff > 60:
            mismatches += 1
    if mismatches > 3:
        flight.violations.append(Violation(
            severity="warn",
            phase=segment.phase,
            metric="track_heading_mismatch",
            message=f"{mismatches} snapshots where actual track ≠ reported heading (>60deg)",
            value=mismatches,
        ))


def audit_approach_glideslope(flight: FlightAudit, segment: PhaseSegment):
    """Check approach glideslope angle (should be 2.5-3.5 degrees)."""
    if segment.phase != "approaching" or len(segment.snapshots) < 5:
        return
    s_start = segment.snapshots[0]
    s_end = segment.snapshots[-1]
    dist_nm = haversine_nm(s_start.lat, s_start.lon, s_end.lat, s_end.lon)
    if dist_nm < 1:
        return
    alt_diff_ft = s_start.alt - s_end.alt
    if alt_diff_ft <= 0:
        flight.violations.append(Violation(
            severity="warn",
            phase="approaching",
            metric="no_descent",
            message=f"No altitude loss during approach ({s_start.alt:.0f} → {s_end.alt:.0f}ft)",
            value=0,
        ))
        return
    dist_ft = dist_nm * 6076.12
    gs_angle = math.degrees(math.atan2(alt_diff_ft, dist_ft))
    if gs_angle < 1.5 or gs_angle > 8.0:
        flight.violations.append(Violation(
            severity="warn",
            phase="approaching",
            metric="glideslope",
            message=f"Glideslope {gs_angle:.1f}deg (expected 2.5-3.5deg)",
            value=gs_angle,
        ))


def audit_taxi_distance(flight: FlightAudit, segment: PhaseSegment):
    """Check taxi distance is reasonable (not teleporting, not looping)."""
    if segment.phase not in ("taxi_to_gate", "taxi_to_runway"):
        return
    total_ft = 0
    for i in range(1, len(segment.snapshots)):
        s0, s1 = segment.snapshots[i - 1], segment.snapshots[i]
        total_ft += haversine_ft(s0.lat, s0.lon, s1.lat, s1.lon)
    total_nm = total_ft / 6076.12
    if total_nm > 5:
        flight.violations.append(Violation(
            severity="warn",
            phase=segment.phase,
            metric="excessive_taxi",
            message=f"Taxi distance {total_nm:.1f}nm seems excessive",
            value=total_nm,
        ))
    if total_ft < 50 and len(segment.snapshots) > 3:
        flight.violations.append(Violation(
            severity="info",
            phase=segment.phase,
            metric="no_movement",
            message=f"Taxi segment {total_ft:.0f}ft with {len(segment.snapshots)} snapshots — stuck?",
            value=total_ft,
        ))


def audit_parked_movement(flight: FlightAudit, segment: PhaseSegment):
    """Check parked aircraft aren't moving."""
    if segment.phase != "parked" or len(segment.snapshots) < 2:
        return
    s0 = segment.snapshots[0]
    max_drift = 0
    for s in segment.snapshots[1:]:
        drift = haversine_ft(s0.lat, s0.lon, s.lat, s.lon)
        max_drift = max(max_drift, drift)
    if max_drift > 100:
        flight.violations.append(Violation(
            severity="warn",
            phase="parked",
            metric="parked_drift",
            message=f"Parked aircraft drifted {max_drift:.0f}ft",
            value=max_drift,
        ))


ALL_CHECKS = [
    audit_speed,
    audit_altitude,
    audit_heading_continuity,
    audit_altitude_continuity,
    audit_speed_continuity,
    audit_ground_track,
    audit_approach_glideslope,
    audit_taxi_distance,
    audit_parked_movement,
]


# ── Main audit logic ──────────────────────────────────────────────────

def parse_snapshots(raw: list[dict]) -> dict[str, list[Snapshot]]:
    """Group snapshots by callsign."""
    flights: dict[str, list[Snapshot]] = defaultdict(list)
    for r in raw:
        s = Snapshot(
            time=r["time"],
            lat=float(r["latitude"]),
            lon=float(r["longitude"]),
            alt=float(r["altitude"]),
            velocity=float(r["velocity"]),
            heading=float(r["heading"]),
            phase=r["phase"],
            on_ground=r.get("on_ground", False),
            aircraft_type=r.get("aircraft_type", "?"),
            vertical_rate=float(r.get("vertical_rate", 0)),
            assigned_gate=r.get("assigned_gate"),
        )
        flights[r["callsign"]].append(s)
    return flights


def segment_by_phase(snapshots: list[Snapshot]) -> list[PhaseSegment]:
    """Split a flight's snapshots into contiguous phase segments."""
    segments: list[PhaseSegment] = []
    for s in snapshots:
        if not segments or segments[-1].phase != s.phase:
            segments.append(PhaseSegment(phase=s.phase, snapshots=[s]))
        else:
            segments[-1].snapshots.append(s)
    return segments


def audit_flight(callsign: str, snapshots: list[Snapshot]) -> FlightAudit:
    """Run all audit checks on a single flight."""
    fa = FlightAudit(
        callsign=callsign,
        icao24=snapshots[0].time,  # placeholder
        aircraft_type=snapshots[0].aircraft_type,
        total_snapshots=len(snapshots),
    )

    segments = segment_by_phase(snapshots)
    fa.phase_segments = segments
    fa.phases_seen = [seg.phase for seg in segments]

    # Compute summary metrics
    for s in snapshots:
        fa.max_speed = max(fa.max_speed, s.velocity)
        fa.max_alt = max(fa.max_alt, s.alt)

    # Total distance
    for i in range(1, len(snapshots)):
        fa.total_distance_nm += haversine_nm(
            snapshots[i - 1].lat, snapshots[i - 1].lon,
            snapshots[i].lat, snapshots[i].lon,
        )

    # Run checks on each segment
    for seg in segments:
        for check in ALL_CHECKS:
            check(fa, seg)

    return fa


# ── Output ────────────────────────────────────────────────────────────

def print_summary(audits: list[FlightAudit], airport: str):
    grade_counts = defaultdict(int)
    for a in audits:
        grade_counts[a.grade] += 1

    total_violations = sum(len(a.violations) for a in audits)
    errors = sum(1 for a in audits for v in a.violations if v.severity == "error")
    warns = sum(1 for a in audits for v in a.violations if v.severity == "warn")

    print(f"\n{'═' * 72}")
    print(f"  TRAJECTORY AUDIT — {airport}")
    print(f"{'═' * 72}")
    print(f"  Flights audited:  {len(audits)}")
    print(f"  Total violations: {total_violations} ({errors} errors, {warns} warnings)")
    print(f"  Grade distribution: ", end="")
    for g in ("A", "B", "C", "D", "F"):
        if grade_counts[g]:
            print(f"{g}={grade_counts[g]}  ", end="")
    print()

    # Violation breakdown by metric
    metric_counts: dict[str, int] = defaultdict(int)
    for a in audits:
        for v in a.violations:
            metric_counts[v.metric] += 1
    if metric_counts:
        print(f"\n  Violations by type:")
        for metric, count in sorted(metric_counts.items(), key=lambda x: -x[1]):
            print(f"    {metric:30s} {count:4d}")

    print(f"\n{'─' * 72}")


def print_flight_detail(audit: FlightAudit):
    print(f"\n  [{audit.grade}] {audit.callsign} ({audit.aircraft_type}) — "
          f"{audit.total_snapshots} snapshots, {audit.total_distance_nm:.1f}nm")
    print(f"      Phases: {' → '.join(audit.phases_seen)}")
    print(f"      Max speed: {audit.max_speed:.0f}kts  Max alt: {audit.max_alt:.0f}ft  "
          f"Max hdg jump: {audit.max_heading_jump:.0f}°  Max alt jump: {audit.max_alt_jump:.0f}ft")

    if audit.violations:
        for v in audit.violations:
            icon = "✗" if v.severity == "error" else "⚠" if v.severity == "warn" else "ℹ"
            print(f"      {icon} [{v.phase}] {v.message}")
    else:
        print(f"      ✓ No violations")

    # Phase segment breakdown
    for seg in audit.phase_segments:
        if len(seg.snapshots) < 2:
            continue
        speeds = [s.velocity for s in seg.snapshots]
        alts = [s.alt for s in seg.snapshots]
        dist = sum(
            haversine_ft(seg.snapshots[i - 1].lat, seg.snapshots[i - 1].lon,
                         seg.snapshots[i].lat, seg.snapshots[i].lon)
            for i in range(1, len(seg.snapshots))
        )
        print(f"      {seg.phase:20s} {seg.duration_s:6.0f}s  "
              f"spd {min(speeds):5.0f}-{max(speeds):5.0f}kts  "
              f"alt {min(alts):6.0f}-{max(alts):6.0f}ft  "
              f"dist {dist / 6076.12:5.1f}nm  "
              f"pts={len(seg.snapshots)}")


def write_csv(audits: list[FlightAudit], path: str):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "callsign", "aircraft_type", "grade", "snapshots",
            "distance_nm", "max_speed", "max_alt", "max_heading_jump",
            "max_alt_jump", "errors", "warnings", "phases", "violations",
        ])
        for a in audits:
            errs = sum(1 for v in a.violations if v.severity == "error")
            warns = sum(1 for v in a.violations if v.severity == "warn")
            viols = "; ".join(f"[{v.phase}] {v.message}" for v in a.violations)
            w.writerow([
                a.callsign, a.aircraft_type, a.grade, a.total_snapshots,
                f"{a.total_distance_nm:.1f}", f"{a.max_speed:.0f}", f"{a.max_alt:.0f}",
                f"{a.max_heading_jump:.0f}", f"{a.max_alt_jump:.0f}",
                errs, warns, " → ".join(a.phases_seen), viols,
            ])
    print(f"\n  CSV report: {path}")


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Audit simulation trajectory quality")
    parser.add_argument("input", help="Simulation output JSON file")
    parser.add_argument("--flight", help="Only audit a specific callsign")
    parser.add_argument("--phase", help="Only show violations in a specific phase")
    parser.add_argument("--csv", help="Write CSV report to this path")
    parser.add_argument("--grade", help="Only show flights with this grade or worse (A/B/C/D/F)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-flight detail")
    parser.add_argument("--top", type=int, default=20, help="Show top N worst flights (default: 20)")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {path}...")
    with open(path) as f:
        data = json.load(f)

    airport = data.get("config", {}).get("airport", "???")
    snapshots = data.get("position_snapshots", [])
    if not snapshots:
        # Try frames format (frontend-style)
        frames = data.get("frames", {})
        for ts_snaps in frames.values():
            snapshots.extend(ts_snaps)

    print(f"Airport: {airport}, {len(snapshots)} position snapshots")

    flights = parse_snapshots(snapshots)
    print(f"Flights: {len(flights)}")

    # Filter
    if args.flight:
        flights = {k: v for k, v in flights.items() if args.flight.upper() in k.upper()}
        if not flights:
            print(f"No flights matching '{args.flight}'")
            sys.exit(1)

    # Audit
    audits = []
    for callsign, snaps in sorted(flights.items()):
        audit = audit_flight(callsign, snaps)
        audits.append(audit)

    # Filter by grade
    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    if args.grade:
        threshold = grade_order.get(args.grade.upper(), 0)
        audits = [a for a in audits if grade_order.get(a.grade, 0) >= threshold]

    # Filter violations by phase
    if args.phase:
        for a in audits:
            a.violations = [v for v in a.violations if v.phase == args.phase]

    # Print summary
    print_summary(audits, airport)

    # Sort by severity (worst first)
    audits.sort(key=lambda a: (-grade_order.get(a.grade, 0), -len(a.violations)))

    # Print details
    if args.verbose or args.flight:
        for a in audits:
            print_flight_detail(a)
    else:
        # Top N worst
        worst = audits[:args.top]
        if worst:
            print(f"\n  Top {len(worst)} worst flights:")
            for a in worst:
                print_flight_detail(a)

    if args.csv:
        write_csv(audits, args.csv)

    # Exit code based on worst grade
    worst_grade = max((grade_order.get(a.grade, 0) for a in audits), default=0)
    sys.exit(1 if worst_grade >= 3 else 0)  # fail on D or F


if __name__ == "__main__":
    main()
