#!/usr/bin/env python3
"""Analyze 10-airport simulation outputs for anomalies and produce visual report.

Usage:
    uv run python scripts/analyze_simulations.py
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

# ── Configuration ──────────────────────────────────────────────────────────
SIMULATION_DIR = Path("simulation_output")
REPORT_DIR = Path("simulation_output/report")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

AIRPORT_REGION = {
    "SFO": "North America (West)",
    "JFK": "North America (East)",
    "LHR": "Europe (UK)",
    "FRA": "Europe (Central)",
    "DXB": "Middle East",
    "NRT": "East Asia",
    "SIN": "Southeast Asia",
    "GRU": "South America",
    "SYD": "Oceania",
    "JNB": "Africa",
}

EXPECTED_WEATHER = {
    "SFO": ["thunderstorm", "fog"],
    "JFK": ["snow", "freezing_rain"],
    "LHR": ["fog", "wind_shift"],
    "FRA": ["freezing_rain", "snow", "wind_shift"],
    "DXB": ["sandstorm", "dust", "haze"],
    "NRT": ["thunderstorm"],
    "SIN": ["rain", "thunderstorm"],
    "GRU": ["thunderstorm"],
    "SYD": ["smoke", "thunderstorm"],
    "JNB": ["thunderstorm", "haze"],
}

AIRPORT_COORDS = {
    "SFO": (37.6213, -122.379),
    "JFK": (40.6413, -73.7781),
    "LHR": (51.4700, -0.4543),
    "FRA": (50.0379, 8.5622),
    "DXB": (25.2532, 55.3657),
    "NRT": (35.7647, 140.3864),
    "SIN": (1.3644, 103.9915),
    "GRU": (-23.4356, -46.4731),
    "SYD": (-33.9461, 151.1772),
    "JNB": (-26.1367, 28.2411),
}


# ── Data Loading ───────────────────────────────────────────────────────────
def load_simulation(filepath: Path) -> dict:
    with open(filepath) as f:
        return json.load(f)


def load_all_simulations() -> dict[str, dict]:
    sims = {}
    for fp in sorted(SIMULATION_DIR.glob("simulation_*_1000_*.json")):
        data = load_simulation(fp)
        airport = data.get("config", {}).get("airport", fp.stem.split("_")[1].upper())
        sims[airport] = data
        print(f"  Loaded {airport}: {fp.name} ({fp.stat().st_size / 1024 / 1024:.1f} MB)")
    return sims


# ── Anomaly Detection ──────────────────────────────────────────────────────
class AnomalyReport:
    def __init__(self):
        self.anomalies: list[dict] = []
        self.warnings: list[dict] = []
        self.stats: dict[str, dict] = {}

    def add_anomaly(self, airport: str, category: str, message: str, severity: str = "ERROR"):
        self.anomalies.append({
            "airport": airport, "category": category,
            "message": message, "severity": severity,
        })

    def add_warning(self, airport: str, category: str, message: str):
        self.warnings.append({
            "airport": airport, "category": category, "message": message,
        })


def check_coordinate_bounds(airport: str, data: dict, report: AnomalyReport):
    """Check that position snapshots are within reasonable bounds of airport."""
    expected_lat, expected_lon = AIRPORT_COORDS.get(airport, (0, 0))
    snapshots = data.get("position_snapshots", [])
    if not snapshots:
        report.add_anomaly(airport, "coordinates", "No position snapshots found")
        return

    lats = [s["latitude"] for s in snapshots if s.get("latitude")]
    lons = [s["longitude"] for s in snapshots if s.get("longitude")]

    if not lats or not lons:
        report.add_anomaly(airport, "coordinates", "Missing lat/lon in snapshots")
        return

    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)
    lat_range = lat_max - lat_min
    lon_range = lon_max - lon_min

    # Flights should be within ~2 degrees of airport center (approach/departure corridors)
    max_offset = 3.0
    if abs(np.mean(lats) - expected_lat) > max_offset:
        report.add_anomaly(airport, "coordinates",
            f"Mean latitude {np.mean(lats):.4f} is {abs(np.mean(lats) - expected_lat):.2f} deg from expected {expected_lat}")
    if abs(np.mean(lons) - expected_lon) > max_offset:
        report.add_anomaly(airport, "coordinates",
            f"Mean longitude {np.mean(lons):.4f} is {abs(np.mean(lons) - expected_lon):.2f} deg from expected {expected_lon}")

    # Check for NaN or extreme values
    nan_count = sum(1 for s in snapshots if s.get("latitude") is None or s.get("longitude") is None)
    if nan_count > 0:
        report.add_anomaly(airport, "coordinates", f"{nan_count} snapshots with null coordinates")

    return {
        "lat_range": (lat_min, lat_max),
        "lon_range": (lon_min, lon_max),
        "lat_spread": lat_range,
        "lon_spread": lon_range,
        "mean_lat": np.mean(lats),
        "mean_lon": np.mean(lons),
    }


def check_altitude_consistency(airport: str, data: dict, report: AnomalyReport):
    """Check altitude makes sense for flight phases."""
    snapshots = data.get("position_snapshots", [])
    ground_alts = [s["altitude"] for s in snapshots if s.get("on_ground") and s.get("altitude") is not None]
    air_alts = [s["altitude"] for s in snapshots if not s.get("on_ground") and s.get("altitude") is not None]

    issues = {}
    if ground_alts:
        # Ground altitude should be near 0 (or airport elevation)
        max_ground = max(ground_alts)
        if max_ground > 500:
            report.add_warning(airport, "altitude",
                f"Max ground altitude is {max_ground:.0f}ft (expected <500ft)")
        issues["ground_max"] = max_ground
        issues["ground_mean"] = np.mean(ground_alts)

    if air_alts:
        # Airborne altitude should be > 0
        below_zero = sum(1 for a in air_alts if a < 0)
        if below_zero > 0:
            report.add_anomaly(airport, "altitude",
                f"{below_zero} airborne snapshots with negative altitude")
        above_50k = sum(1 for a in air_alts if a > 50000)
        if above_50k > 0:
            report.add_anomaly(airport, "altitude",
                f"{above_50k} snapshots with altitude > 50,000ft")
        issues["air_max"] = max(air_alts)
        issues["air_mean"] = np.mean(air_alts)

    return issues


def check_phase_transitions(airport: str, data: dict, report: AnomalyReport):
    """Check phase transitions are logically valid."""
    transitions = data.get("phase_transitions", [])
    valid_transitions = {
        ("scheduled", "approaching"), ("approaching", "landing"), ("approaching", "go_around"),
        ("approaching", "diverted"), ("landing", "taxi_to_gate"), ("taxi_to_gate", "parked"),
        ("parked", "pushback"), ("pushback", "taxi_to_runway"), ("taxi_to_runway", "departing"),
        ("departing", "departed"), ("scheduled", "parked"),  # direct gate assignment for departures
        ("go_around", "approaching"),  # retry after go-around
        ("approaching", "holding"),  # weather hold
        ("holding", "approaching"),  # resume after hold
    }
    invalid_count = 0
    invalid_examples = []
    for t in transitions:
        pair = (t.get("from_phase"), t.get("to_phase"))
        if pair not in valid_transitions:
            invalid_count += 1
            if len(invalid_examples) < 3:
                invalid_examples.append(f"{pair[0]} -> {pair[1]}")

    if invalid_count > 0:
        report.add_warning(airport, "phase_transitions",
            f"{invalid_count} unexpected transitions: {', '.join(invalid_examples)}")

    return {"total": len(transitions), "invalid": invalid_count}


def check_weather_alignment(airport: str, data: dict, report: AnomalyReport):
    """Check that weather events match expected regional weather."""
    scenario_events = data.get("scenario_events", [])
    weather_events = [e for e in scenario_events if e.get("event_type") == "weather"]

    if not weather_events:
        report.add_warning(airport, "weather", "No weather scenario events recorded")
        return {"types": [], "count": 0}

    weather_types = set()
    for e in weather_events:
        desc = e.get("description", "").lower()
        wtype = e.get("type", "")
        if wtype:
            weather_types.add(wtype)
        # Extract from description
        for t in ["thunderstorm", "fog", "snow", "sandstorm", "dust", "smoke",
                   "haze", "rain", "freezing_rain", "wind_shift", "clear"]:
            if t in desc:
                weather_types.add(t)

    expected = set(EXPECTED_WEATHER.get(airport, []))
    missing = expected - weather_types
    if missing:
        report.add_warning(airport, "weather",
            f"Expected weather types not found: {missing}. Got: {weather_types}")

    return {"types": list(weather_types), "count": len(weather_events)}


def check_flight_counts(airport: str, data: dict, report: AnomalyReport):
    """Check flight counts match config."""
    config = data.get("config", {})
    summary = data.get("summary", {})
    schedule = data.get("schedule", [])

    expected_arr = config.get("arrivals", 500)
    expected_dep = config.get("departures", 500)
    actual_arr = summary.get("arrivals", 0)
    actual_dep = summary.get("departures", 0)

    # With scenario injections, actual can exceed expected
    if actual_arr < expected_arr:
        report.add_warning(airport, "flight_counts",
            f"Fewer arrivals than configured: {actual_arr} < {expected_arr}")
    if actual_dep < expected_dep:
        report.add_warning(airport, "flight_counts",
            f"Fewer departures than configured: {actual_dep} < {expected_dep}")

    return {
        "config_arrivals": expected_arr,
        "config_departures": expected_dep,
        "actual_arrivals": actual_arr,
        "actual_departures": actual_dep,
        "total": summary.get("total_flights", 0),
        "spawned": summary.get("spawned_count", 0),
        "cancellation_rate": summary.get("cancellation_rate_pct", 0),
    }


def check_gate_utilization(airport: str, data: dict, report: AnomalyReport):
    """Check gate events make sense."""
    gate_events = data.get("gate_events", [])
    summary = data.get("summary", {})

    gates_used = summary.get("gate_utilization_gates_used", 0)
    if gates_used == 0:
        report.add_anomaly(airport, "gates", "No gates used in simulation")

    # Check for orphan occupy/release events
    occupies = [e for e in gate_events if e.get("event_type") == "occupy"]
    releases = [e for e in gate_events if e.get("event_type") == "release"]

    return {
        "gates_used": gates_used,
        "occupy_events": len(occupies),
        "release_events": len(releases),
    }


def check_timing_consistency(airport: str, data: dict, report: AnomalyReport):
    """Check temporal consistency of events."""
    snapshots = data.get("position_snapshots", [])
    if len(snapshots) < 2:
        return {}

    times = [s["time"] for s in snapshots[:100]]  # Sample first 100
    # Check timestamps are monotonically increasing (within same flight)
    flights = defaultdict(list)
    for s in snapshots:
        flights[s.get("icao24", "")].append(s["time"])

    out_of_order = 0
    for fid, ftimes in flights.items():
        for i in range(1, len(ftimes)):
            if ftimes[i] < ftimes[i-1]:
                out_of_order += 1
                break

    if out_of_order > 0:
        report.add_anomaly(airport, "timing",
            f"{out_of_order} flights with out-of-order timestamps")

    return {"flights_tracked": len(flights), "out_of_order": out_of_order}


# ── Visualization ──────────────────────────────────────────────────────────
def plot_summary_dashboard(all_sims: dict[str, dict], report: AnomalyReport):
    """Create a comprehensive summary dashboard."""
    airports = list(all_sims.keys())
    regions = [AIRPORT_REGION.get(a, "Unknown") for a in airports]

    fig = plt.figure(figsize=(24, 20))
    fig.suptitle("Airport Digital Twin — 10-Airport Simulation Report\n"
                 "1,000 flights per airport with region-appropriate weather scenarios",
                 fontsize=16, fontweight="bold", y=0.98)

    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.35, wspace=0.3)

    # 1. Flight counts bar chart
    ax1 = fig.add_subplot(gs[0, 0])
    arrivals = [all_sims[a]["summary"]["arrivals"] for a in airports]
    departures = [all_sims[a]["summary"]["departures"] for a in airports]
    x = np.arange(len(airports))
    w = 0.35
    ax1.bar(x - w/2, arrivals, w, label="Arrivals", color="#2196F3")
    ax1.bar(x + w/2, departures, w, label="Departures", color="#FF9800")
    ax1.set_xticks(x)
    ax1.set_xticklabels(airports, rotation=45, ha="right")
    ax1.set_ylabel("Count")
    ax1.set_title("Flight Counts (Arrivals vs Departures)")
    ax1.legend()
    ax1.grid(axis="y", alpha=0.3)

    # 2. Spawned vs Cancelled
    ax2 = fig.add_subplot(gs[0, 1])
    spawned = [all_sims[a]["summary"]["spawned_count"] for a in airports]
    total = [all_sims[a]["summary"]["total_flights"] for a in airports]
    cancelled = [t - s for t, s in zip(total, spawned)]
    ax2.bar(x, spawned, label="Spawned", color="#4CAF50")
    ax2.bar(x, cancelled, bottom=spawned, label="Cancelled/Not Spawned", color="#F44336")
    ax2.set_xticks(x)
    ax2.set_xticklabels(airports, rotation=45, ha="right")
    ax2.set_ylabel("Flights")
    ax2.set_title("Flight Completion (Spawned vs Cancelled)")
    ax2.legend()
    ax2.grid(axis="y", alpha=0.3)

    # 3. On-time performance
    ax3 = fig.add_subplot(gs[0, 2])
    on_time = [all_sims[a]["summary"]["on_time_pct"] for a in airports]
    colors = ["#4CAF50" if v > 50 else "#FF9800" if v > 25 else "#F44336" for v in on_time]
    bars = ax3.bar(x, on_time, color=colors)
    ax3.set_xticks(x)
    ax3.set_xticklabels(airports, rotation=45, ha="right")
    ax3.set_ylabel("On-Time %")
    ax3.set_title("On-Time Performance (< 15min delay)")
    ax3.axhline(y=50, color="gray", linestyle="--", alpha=0.5, label="50% threshold")
    ax3.set_ylim(0, 100)
    ax3.legend()
    ax3.grid(axis="y", alpha=0.3)
    for bar, val in zip(bars, on_time):
        ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"{val:.0f}%", ha="center", va="bottom", fontsize=8)

    # 4. Average capacity hold delay
    ax4 = fig.add_subplot(gs[1, 0])
    avg_hold = [all_sims[a]["summary"]["avg_capacity_hold_min"] for a in airports]
    max_hold = [all_sims[a]["summary"]["max_capacity_hold_min"] for a in airports]
    ax4.bar(x - w/2, avg_hold, w, label="Avg Hold", color="#9C27B0")
    ax4.bar(x + w/2, max_hold, w, label="Max Hold", color="#E91E63")
    ax4.set_xticks(x)
    ax4.set_xticklabels(airports, rotation=45, ha="right")
    ax4.set_ylabel("Minutes")
    ax4.set_title("Capacity Hold Delay (Avg / Max)")
    ax4.legend()
    ax4.grid(axis="y", alpha=0.3)

    # 5. Scenario disruption events
    ax5 = fig.add_subplot(gs[1, 1])
    go_arounds = [all_sims[a]["summary"].get("total_go_arounds", 0) for a in airports]
    diversions = [all_sims[a]["summary"].get("total_diversions", 0) for a in airports]
    holdings = [all_sims[a]["summary"].get("total_holdings", 0) for a in airports]
    cancellations = [all_sims[a]["summary"].get("total_cancellations", 0) for a in airports]

    ax5.bar(x - 0.3, go_arounds, 0.2, label="Go-Arounds", color="#FF5722")
    ax5.bar(x - 0.1, diversions, 0.2, label="Diversions", color="#795548")
    ax5.bar(x + 0.1, holdings, 0.2, label="Holdings", color="#607D8B")
    ax5.bar(x + 0.3, cancellations, 0.2, label="Cancellations", color="#F44336")
    ax5.set_xticks(x)
    ax5.set_xticklabels(airports, rotation=45, ha="right")
    ax5.set_ylabel("Event Count")
    ax5.set_title("Disruption Events by Type")
    ax5.legend(fontsize=8)
    ax5.grid(axis="y", alpha=0.3)

    # 6. Peak simultaneous flights
    ax6 = fig.add_subplot(gs[1, 2])
    peak = [all_sims[a]["summary"]["peak_simultaneous_flights"] for a in airports]
    gates = [all_sims[a]["summary"]["gate_utilization_gates_used"] for a in airports]
    ax6.bar(x - w/2, peak, w, label="Peak Simultaneous", color="#00BCD4")
    ax6.bar(x + w/2, gates, w, label="Gates Used", color="#8BC34A")
    ax6.set_xticks(x)
    ax6.set_xticklabels(airports, rotation=45, ha="right")
    ax6.set_ylabel("Count")
    ax6.set_title("Peak Simultaneous Flights & Gate Utilization")
    ax6.legend()
    ax6.grid(axis="y", alpha=0.3)

    # 7. Weather events timeline (heatmap-style)
    ax7 = fig.add_subplot(gs[2, :2])
    hours = list(range(24))
    weather_matrix = np.zeros((len(airports), 24))
    for i, a in enumerate(airports):
        for e in all_sims[a].get("scenario_events", []):
            if e.get("event_type") == "weather":
                try:
                    t = datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
                    h = t.hour
                    sev = e.get("severity", "light")
                    val = {"light": 1, "moderate": 2, "severe": 3}.get(sev, 1)
                    weather_matrix[i, h] = max(weather_matrix[i, h], val)
                except Exception:
                    pass

    im = ax7.imshow(weather_matrix, aspect="auto", cmap="YlOrRd",
                    interpolation="nearest", vmin=0, vmax=3)
    ax7.set_yticks(range(len(airports)))
    ax7.set_yticklabels([f"{a} ({AIRPORT_REGION.get(a, '')})" for a in airports], fontsize=9)
    ax7.set_xticks(hours)
    ax7.set_xticklabels([f"{h:02d}" for h in hours])
    ax7.set_xlabel("Hour of Day (UTC)")
    ax7.set_title("Weather Severity Timeline (0=Clear, 1=Light, 2=Moderate, 3=Severe)")
    plt.colorbar(im, ax=ax7, shrink=0.6, label="Severity")

    # 8. Anomaly summary
    ax8 = fig.add_subplot(gs[2, 2])
    ax8.axis("off")
    anomaly_text = "ANOMALY SUMMARY\n" + "=" * 30 + "\n\n"
    if report.anomalies:
        anomaly_text += f"ERRORS: {len(report.anomalies)}\n"
        for a in report.anomalies[:8]:
            anomaly_text += f"  [{a['airport']}] {a['category']}: {a['message'][:50]}\n"
    else:
        anomaly_text += "ERRORS: 0 (all clean)\n"

    anomaly_text += f"\nWARNINGS: {len(report.warnings)}\n"
    for w in report.warnings[:8]:
        anomaly_text += f"  [{w['airport']}] {w['category']}: {w['message'][:50]}\n"
    if len(report.warnings) > 8:
        anomaly_text += f"  ... and {len(report.warnings) - 8} more\n"

    ax8.text(0.05, 0.95, anomaly_text, transform=ax8.transAxes,
             fontsize=8, verticalalignment="top", fontfamily="monospace",
             bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

    plt.savefig(REPORT_DIR / "01_summary_dashboard.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 01_summary_dashboard.png")


def plot_hourly_traffic(all_sims: dict[str, dict]):
    """Plot hourly traffic distribution per airport."""
    fig, axes = plt.subplots(2, 5, figsize=(25, 10), sharey=True)
    fig.suptitle("Hourly Traffic Distribution by Airport", fontsize=14, fontweight="bold")

    airports = list(all_sims.keys())
    for idx, (ax, airport) in enumerate(zip(axes.flatten(), airports)):
        schedule = all_sims[airport].get("schedule", [])
        arr_hours = []
        dep_hours = []
        for f in schedule:
            try:
                t = datetime.fromisoformat(f["scheduled_time"].replace("Z", "+00:00"))
                if f["flight_type"] == "arrival":
                    arr_hours.append(t.hour)
                else:
                    dep_hours.append(t.hour)
            except Exception:
                pass

        hours = range(24)
        arr_counts = [arr_hours.count(h) for h in hours]
        dep_counts = [dep_hours.count(h) for h in hours]

        ax.bar(hours, arr_counts, alpha=0.7, label="Arrivals", color="#2196F3")
        ax.bar(hours, dep_counts, bottom=arr_counts, alpha=0.7, label="Departures", color="#FF9800")
        ax.set_title(f"{airport}\n({AIRPORT_REGION.get(airport, '')})", fontsize=10)
        ax.set_xlabel("Hour")
        if idx % 5 == 0:
            ax.set_ylabel("Flights")
        ax.set_xticks([0, 6, 12, 18, 23])
        ax.grid(axis="y", alpha=0.3)
        if idx == 0:
            ax.legend(fontsize=7)

    plt.tight_layout()
    plt.savefig(REPORT_DIR / "02_hourly_traffic.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 02_hourly_traffic.png")


def plot_coordinate_scatter(all_sims: dict[str, dict]):
    """Plot aircraft position scatter per airport (sampled)."""
    fig, axes = plt.subplots(2, 5, figsize=(25, 10))
    fig.suptitle("Aircraft Position Scatter (sampled, colored by phase)", fontsize=14, fontweight="bold")

    phase_colors = {
        "approaching": "#2196F3",
        "landing": "#FF9800",
        "taxi_to_gate": "#4CAF50",
        "parked": "#9E9E9E",
        "pushback": "#9C27B0",
        "taxi_to_runway": "#00BCD4",
        "departing": "#F44336",
        "departed": "#795548",
    }

    airports = list(all_sims.keys())
    for idx, (ax, airport) in enumerate(zip(axes.flatten(), airports)):
        snapshots = all_sims[airport].get("position_snapshots", [])
        # Sample every Nth snapshot for performance
        sample_rate = max(1, len(snapshots) // 3000)
        sampled = snapshots[::sample_rate]

        for phase, color in phase_colors.items():
            pts = [(s["longitude"], s["latitude"]) for s in sampled if s.get("phase") == phase]
            if pts:
                lons, lats = zip(*pts)
                ax.scatter(lons, lats, s=1, alpha=0.3, c=color, label=phase)

        exp_lat, exp_lon = AIRPORT_COORDS.get(airport, (0, 0))
        ax.plot(exp_lon, exp_lat, "r*", markersize=10, zorder=10)
        ax.set_title(f"{airport}", fontsize=10)
        ax.set_aspect("equal")
        ax.grid(alpha=0.2)
        if idx == 0:
            ax.legend(fontsize=5, markerscale=5, loc="upper left")

    plt.tight_layout()
    plt.savefig(REPORT_DIR / "03_position_scatter.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 03_position_scatter.png")


def plot_altitude_profiles(all_sims: dict[str, dict]):
    """Plot altitude distribution by phase per airport."""
    fig, axes = plt.subplots(2, 5, figsize=(25, 10))
    fig.suptitle("Altitude Distribution by Flight Phase", fontsize=14, fontweight="bold")

    airports = list(all_sims.keys())
    for idx, (ax, airport) in enumerate(zip(axes.flatten(), airports)):
        snapshots = all_sims[airport].get("position_snapshots", [])
        phase_alts = defaultdict(list)
        sample_rate = max(1, len(snapshots) // 5000)
        for s in snapshots[::sample_rate]:
            alt = s.get("altitude", 0)
            phase = s.get("phase", "unknown")
            if alt is not None:
                phase_alts[phase].append(alt)

        phases_order = ["approaching", "landing", "taxi_to_gate", "parked",
                        "pushback", "taxi_to_runway", "departing", "departed"]
        data_to_plot = []
        labels = []
        for p in phases_order:
            if p in phase_alts and phase_alts[p]:
                data_to_plot.append(phase_alts[p])
                labels.append(p[:6])

        if data_to_plot:
            bp = ax.boxplot(data_to_plot, labels=labels, patch_artist=True)
            for patch in bp["boxes"]:
                patch.set_facecolor("#64B5F6")
        ax.set_title(f"{airport}", fontsize=10)
        ax.set_ylabel("Altitude (ft)" if idx % 5 == 0 else "")
        ax.tick_params(axis="x", rotation=45, labelsize=7)
        ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(REPORT_DIR / "04_altitude_profiles.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 04_altitude_profiles.png")


def plot_disruption_timeline(all_sims: dict[str, dict]):
    """Plot scenario events as a timeline for each airport."""
    fig, axes = plt.subplots(10, 1, figsize=(20, 25), sharex=True)
    fig.suptitle("Scenario Events Timeline by Airport", fontsize=14, fontweight="bold", y=1.0)

    event_colors = {
        "weather": "#FF9800",
        "runway": "#F44336",
        "ground": "#9C27B0",
        "traffic": "#2196F3",
        "capacity": "#607D8B",
        "curfew": "#795548",
        "go_around": "#FF5722",
        "diversion": "#E91E63",
        "cancellation": "#B71C1C",
    }

    airports = list(all_sims.keys())
    for idx, (ax, airport) in enumerate(zip(axes, airports)):
        events = all_sims[airport].get("scenario_events", [])
        for e in events:
            try:
                t = datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
                hour = t.hour + t.minute / 60
                etype = e.get("event_type", "unknown")
                color = event_colors.get(etype, "#999999")
                ax.axvline(x=hour, color=color, alpha=0.15, linewidth=1)
                ax.scatter(hour, 0.5, c=color, s=8, alpha=0.5, zorder=5)
            except Exception:
                pass

        ax.set_ylabel(f"{airport}\n{AIRPORT_REGION.get(airport, '')}", fontsize=9, rotation=0, labelpad=80)
        ax.set_yticks([])
        ax.set_xlim(0, 24)
        ax.grid(axis="x", alpha=0.3)
        if idx == 0:
            # Legend
            for etype, color in event_colors.items():
                ax.scatter([], [], c=color, s=30, label=etype)
            ax.legend(fontsize=7, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.8))

    axes[-1].set_xlabel("Hour of Day (UTC)")
    plt.tight_layout()
    plt.savefig(REPORT_DIR / "05_disruption_timeline.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 05_disruption_timeline.png")


def plot_cancellation_analysis(all_sims: dict[str, dict]):
    """Cancellation rate vs weather severity scatter."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    fig.suptitle("Cancellation & Delay Analysis", fontsize=14, fontweight="bold")

    airports = list(all_sims.keys())

    # 1. Cancellation rate vs total scenario events
    cancel_rates = [all_sims[a]["summary"]["cancellation_rate_pct"] for a in airports]
    scenario_counts = [all_sims[a]["summary"].get("total_scenario_events", 0) for a in airports]
    ax1.scatter(scenario_counts, cancel_rates, s=100, c="#F44336", edgecolors="black", zorder=5)
    for a, sc, cr in zip(airports, scenario_counts, cancel_rates):
        ax1.annotate(f" {a}", (sc, cr), fontsize=9)
    ax1.set_xlabel("Total Scenario Events")
    ax1.set_ylabel("Cancellation Rate (%)")
    ax1.set_title("Cancellation Rate vs Scenario Disruption Intensity")
    ax1.grid(alpha=0.3)

    # 2. Avg delay vs on-time %
    avg_hold = [all_sims[a]["summary"]["avg_capacity_hold_min"] for a in airports]
    on_time = [all_sims[a]["summary"]["on_time_pct"] for a in airports]
    colors = ["#4CAF50" if ot > 50 else "#FF9800" if ot > 25 else "#F44336" for ot in on_time]
    ax2.scatter(avg_hold, on_time, s=100, c=colors, edgecolors="black", zorder=5)
    for a, ah, ot in zip(airports, avg_hold, on_time):
        ax2.annotate(f" {a}", (ah, ot), fontsize=9)
    ax2.set_xlabel("Avg Capacity Hold (min)")
    ax2.set_ylabel("On-Time %")
    ax2.set_title("On-Time Performance vs Average Delay")
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(REPORT_DIR / "06_cancellation_analysis.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 06_cancellation_analysis.png")


def plot_world_map_summary(all_sims: dict[str, dict]):
    """Plot airports on a simple world map with KPIs."""
    fig, ax = plt.subplots(figsize=(18, 10))
    ax.set_title("Global Airport Simulation Overview — 10 Airports, 10,000+ Flights",
                  fontsize=14, fontweight="bold")

    # Simple world outline (continental boundaries approximation)
    ax.set_xlim(-180, 180)
    ax.set_ylim(-60, 75)
    ax.set_facecolor("#E8F4FD")
    ax.grid(alpha=0.2)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    airports = list(all_sims.keys())
    for airport in airports:
        lat, lon = AIRPORT_COORDS.get(airport, (0, 0))
        summary = all_sims[airport]["summary"]

        # Bubble size = total flights
        size = summary["total_flights"] / 5
        # Color = on-time %
        on_time = summary["on_time_pct"]
        color = "#4CAF50" if on_time > 50 else "#FF9800" if on_time > 25 else "#F44336"

        ax.scatter(lon, lat, s=size, c=color, alpha=0.7, edgecolors="black", linewidth=1, zorder=5)
        label = (f"{airport}\n"
                 f"{summary['total_flights']} flights\n"
                 f"OTP: {on_time:.0f}%\n"
                 f"Cancel: {summary['cancellation_rate_pct']:.0f}%")
        ax.annotate(label, (lon, lat), fontsize=7, fontweight="bold",
                   xytext=(10, 10), textcoords="offset points",
                   bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    # Legend
    ax.scatter([], [], s=100, c="#4CAF50", label="OTP > 50%")
    ax.scatter([], [], s=100, c="#FF9800", label="OTP 25-50%")
    ax.scatter([], [], s=100, c="#F44336", label="OTP < 25%")
    ax.legend(loc="lower left", fontsize=10)

    plt.tight_layout()
    plt.savefig(REPORT_DIR / "07_world_map.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 07_world_map.png")


# ── Report Generation ──────────────────────────────────────────────────────
def generate_text_report(all_sims: dict[str, dict], report: AnomalyReport) -> str:
    """Generate a text summary report."""
    lines = []
    lines.append("=" * 80)
    lines.append("AIRPORT DIGITAL TWIN — MULTI-AIRPORT SIMULATION ANALYSIS REPORT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 80)
    lines.append("")

    # Overview
    total_flights = sum(d["summary"]["total_flights"] for d in all_sims.values())
    total_snapshots = sum(d["summary"]["total_position_snapshots"] for d in all_sims.values())
    total_events = sum(d["summary"].get("total_scenario_events", 0) for d in all_sims.values())

    lines.append("OVERVIEW")
    lines.append("-" * 40)
    lines.append(f"  Airports simulated:      {len(all_sims)}")
    lines.append(f"  Total flights:           {total_flights:,}")
    lines.append(f"  Total position snapshots: {total_snapshots:,}")
    lines.append(f"  Total scenario events:   {total_events:,}")
    lines.append(f"  Regions covered:         {len(set(AIRPORT_REGION.get(a, '') for a in all_sims))}")
    lines.append("")

    # Per-airport summary table
    lines.append("PER-AIRPORT SUMMARY")
    lines.append("-" * 40)
    header = f"{'Airport':<6} {'Region':<25} {'Flights':>8} {'Spawned':>8} {'OTP%':>6} {'Cancel%':>8} {'AvgHold':>8} {'GoAr':>5} {'Div':>5} {'Scenario'}"
    lines.append(header)
    lines.append("-" * len(header))

    for airport in sorted(all_sims.keys()):
        s = all_sims[airport]["summary"]
        scenario = s.get("scenario_name", "N/A")
        lines.append(
            f"{airport:<6} "
            f"{AIRPORT_REGION.get(airport, 'Unknown'):<25} "
            f"{s['total_flights']:>8} "
            f"{s['spawned_count']:>8} "
            f"{s['on_time_pct']:>5.1f}% "
            f"{s['cancellation_rate_pct']:>7.1f}% "
            f"{s['avg_capacity_hold_min']:>7.1f}m "
            f"{s.get('total_go_arounds', 0):>5} "
            f"{s.get('total_diversions', 0):>5} "
            f"{scenario}"
        )
    lines.append("")

    # Weather alignment check
    lines.append("WEATHER ALIGNMENT CHECK")
    lines.append("-" * 40)
    for airport in sorted(all_sims.keys()):
        events = all_sims[airport].get("scenario_events", [])
        weather_types = set()
        for e in events:
            if e.get("event_type") == "weather":
                wtype = e.get("type", "")
                if wtype:
                    weather_types.add(wtype)
                desc = e.get("description", "").lower()
                for t in ["thunderstorm", "fog", "snow", "sandstorm", "dust", "smoke",
                           "haze", "rain", "freezing_rain", "wind_shift"]:
                    if t in desc:
                        weather_types.add(t)

        expected = set(EXPECTED_WEATHER.get(airport, []))
        status = "OK" if expected.issubset(weather_types) else "MISMATCH"
        lines.append(f"  {airport}: {status} — Got: {sorted(weather_types)} | Expected: {sorted(expected)}")
    lines.append("")

    # Anomalies
    lines.append("ANOMALY DETECTION RESULTS")
    lines.append("-" * 40)
    if report.anomalies:
        lines.append(f"  ERRORS ({len(report.anomalies)}):")
        for a in report.anomalies:
            lines.append(f"    [{a['severity']}] {a['airport']} — {a['category']}: {a['message']}")
    else:
        lines.append("  ERRORS: 0 (all clean)")

    lines.append("")
    if report.warnings:
        lines.append(f"  WARNINGS ({len(report.warnings)}):")
        for w in report.warnings:
            lines.append(f"    [WARN] {w['airport']} — {w['category']}: {w['message']}")
    else:
        lines.append("  WARNINGS: 0")

    lines.append("")
    lines.append("VISUALIZATIONS")
    lines.append("-" * 40)
    lines.append("  01_summary_dashboard.png     — KPI overview across all airports")
    lines.append("  02_hourly_traffic.png        — Hourly traffic distribution")
    lines.append("  03_position_scatter.png      — Aircraft position scatter by phase")
    lines.append("  04_altitude_profiles.png     — Altitude distribution by phase")
    lines.append("  05_disruption_timeline.png   — Scenario event timeline")
    lines.append("  06_cancellation_analysis.png — Cancellation & delay correlation")
    lines.append("  07_world_map.png             — Global overview with KPIs")
    lines.append("")
    lines.append("=" * 80)
    lines.append("END OF REPORT")
    lines.append("=" * 80)

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    print("Loading simulation outputs...")
    all_sims = load_all_simulations()

    if not all_sims:
        print("ERROR: No simulation files found in simulation_output/")
        sys.exit(1)

    print(f"\nLoaded {len(all_sims)} airports. Running anomaly checks...")
    report = AnomalyReport()

    for airport, data in sorted(all_sims.items()):
        print(f"  Checking {airport}...")
        check_coordinate_bounds(airport, data, report)
        check_altitude_consistency(airport, data, report)
        check_phase_transitions(airport, data, report)
        check_weather_alignment(airport, data, report)
        check_flight_counts(airport, data, report)
        check_gate_utilization(airport, data, report)
        check_timing_consistency(airport, data, report)

    print(f"\n  Anomalies: {len(report.anomalies)} errors, {len(report.warnings)} warnings")

    print("\nGenerating visualizations...")
    plot_summary_dashboard(all_sims, report)
    plot_hourly_traffic(all_sims)
    plot_coordinate_scatter(all_sims)
    plot_altitude_profiles(all_sims)
    plot_disruption_timeline(all_sims)
    plot_cancellation_analysis(all_sims)
    plot_world_map_summary(all_sims)

    print("\nGenerating text report...")
    report_text = generate_text_report(all_sims, report)
    report_path = REPORT_DIR / "simulation_analysis_report.txt"
    with open(report_path, "w") as f:
        f.write(report_text)
    print(f"  Saved: {report_path}")

    # Print report to console
    print("\n" + report_text)


if __name__ == "__main__":
    main()
