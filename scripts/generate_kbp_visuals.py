"""Generate visualizations for KBP Easter Egg simulation data."""

import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import Counter
from pathlib import Path
import numpy as np

OUTPUT_DIR = Path("data/kbp_easter_egg")
OUTPUT_DIR.mkdir(exist_ok=True)

with open("simulation_output_kbp.json") as f:
    data = json.load(f)

flights = data["schedule"]
positions = data["position_snapshots"]
phases = data["phase_transitions"]

FIGHTERS = {"F14", "F15", "F16", "F18", "F22", "F35"}
UA_BLUE = "#005BBB"
UA_YELLOW = "#FFD500"
DARK_BG = "#1a1a2e"
GRID_COLOR = "#333355"

plt.rcParams.update({
    'figure.facecolor': DARK_BG,
    'axes.facecolor': '#16213e',
    'axes.edgecolor': GRID_COLOR,
    'axes.labelcolor': 'white',
    'text.color': 'white',
    'xtick.color': '#aaaaaa',
    'ytick.color': '#aaaaaa',
    'grid.color': GRID_COLOR,
    'grid.alpha': 0.3,
    'font.family': 'sans-serif',
})

# ──────────────────────────────────────────────────────────────
# 1. Flight Mix Pie Chart
# ──────────────────────────────────────────────────────────────
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

n_fighter = sum(1 for f in flights if f["aircraft_type"] in FIGHTERS)
n_commercial = len(flights) - n_fighter

ax1.pie(
    [n_commercial, n_fighter],
    labels=[f"Commercial\n({n_commercial})", f"Fighter Jets\n({n_fighter})"],
    colors=["#4a90d9", UA_YELLOW],
    autopct="%1.0f%%",
    textprops={"color": "white", "fontsize": 14},
    wedgeprops={"edgecolor": DARK_BG, "linewidth": 2},
    startangle=90,
)
ax1.set_title("Traffic Mix", fontsize=16, fontweight="bold", pad=20)

# Aircraft type breakdown
types = Counter(f["aircraft_type"] for f in flights)
fighter_types = {k: v for k, v in types.items() if k in FIGHTERS}
commercial_types = {k: v for k, v in types.items() if k not in FIGHTERS}

labels = list(commercial_types.keys()) + list(fighter_types.keys())
sizes = list(commercial_types.values()) + list(fighter_types.values())
colors = ["#4a90d9"] * len(commercial_types) + [UA_YELLOW] * len(fighter_types)

# Vary blue shades for commercial
blues = plt.cm.Blues(np.linspace(0.4, 0.8, len(commercial_types)))
colors = list(blues) + [UA_YELLOW] * len(fighter_types)

ax2.barh(labels, sizes, color=colors, edgecolor=DARK_BG)
ax2.set_title("Aircraft Types", fontsize=16, fontweight="bold", pad=20)
ax2.set_xlabel("Count")
ax2.invert_yaxis()
for i, (label, size) in enumerate(zip(labels, sizes)):
    ax2.text(size + 0.3, i, str(size), va="center", fontsize=11, color="white")

fig.suptitle("KBP Easter Egg — Flight Composition", fontsize=20, fontweight="bold", y=0.98)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "viz_flight_mix.png", dpi=150, bbox_inches="tight")
plt.close()
print("1. Flight mix chart saved")

# ──────────────────────────────────────────────────────────────
# 2. Airline Distribution
# ──────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 7))

airlines = Counter(f.get("airline_code", "???") for f in flights)
names = {
    "AUI": "Ukraine Intl Airlines",
    "UAF": "Ukrainian Air Force",
    "LMU": "Lumo Airlines",
    "TVS": "Travel Service",
    "SBI": "S7 Airlines",
    "KZR": "Air Astana",
    "CSA": "Czech Airlines",
    "AHY": "Azerbaijan Airlines",
    "AFL": "Aeroflot",
    "ELY": "El Al",
    "LOT": "LOT Polish",
    "THY": "Turkish Airlines",
    "ELL": "Estonian Air",
}

sorted_airlines = airlines.most_common()
labels = [f"{code} ({names.get(code, code)})" for code, _ in sorted_airlines]
counts = [c for _, c in sorted_airlines]
colors = [UA_YELLOW if code == "UAF" else UA_BLUE if code == "AUI" else "#4a90d9"
          for code, _ in sorted_airlines]

bars = ax.barh(labels, counts, color=colors, edgecolor=DARK_BG)
ax.set_title("Airline Distribution", fontsize=18, fontweight="bold", pad=20)
ax.set_xlabel("Number of Flights")
ax.invert_yaxis()

for bar, count in zip(bars, counts):
    ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height()/2,
            str(count), va="center", fontsize=11, color="white")

# Legend
mil_patch = mpatches.Patch(color=UA_YELLOW, label="Military (Easter Egg)")
ukr_patch = mpatches.Patch(color=UA_BLUE, label="Ukrainian Carrier")
com_patch = mpatches.Patch(color="#4a90d9", label="International Carrier")
ax.legend(handles=[mil_patch, ukr_patch, com_patch], loc="lower right", fontsize=10)

fig.suptitle("KBP Easter Egg — Airlines at Boryspil", fontsize=20, fontweight="bold", y=0.98)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "viz_airlines.png", dpi=150, bbox_inches="tight")
plt.close()
print("2. Airline chart saved")

# ──────────────────────────────────────────────────────────────
# 3. Hourly Distribution
# ──────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 6))

hours_commercial = Counter()
hours_fighter = Counter()
for f in flights:
    t = f.get("scheduled_time", "")
    if "T" in t:
        h = int(t.split("T")[1][:2])
        if f["aircraft_type"] in FIGHTERS:
            hours_fighter[h] += 1
        else:
            hours_commercial[h] += 1

x = range(24)
comm = [hours_commercial.get(h, 0) for h in x]
fight = [hours_fighter.get(h, 0) for h in x]

ax.bar(x, comm, color=UA_BLUE, label="Commercial", edgecolor=DARK_BG)
ax.bar(x, fight, bottom=comm, color=UA_YELLOW, label="Fighter Jets", edgecolor=DARK_BG)
ax.set_xlabel("Hour of Day")
ax.set_ylabel("Number of Flights")
ax.set_title("Hourly Traffic Distribution", fontsize=18, fontweight="bold", pad=20)
ax.set_xticks(range(0, 24, 2))
ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)], rotation=45)
ax.legend(loc="upper left", fontsize=11)
ax.grid(axis="y", alpha=0.3)

fig.suptitle("KBP Easter Egg — 24-Hour Pattern", fontsize=20, fontweight="bold", y=0.98)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "viz_hourly.png", dpi=150, bbox_inches="tight")
plt.close()
print("3. Hourly chart saved")

# ──────────────────────────────────────────────────────────────
# 4. Fighter Jet Sortie Map (route diagram)
# ──────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 10))

# Ukrainian cities
cities = {
    "KBP": (30.89, 50.34, "Kyiv (KBP)"),
    "ODS": (30.68, 46.43, "Odesa"),
    "SIP": (33.97, 44.69, "Simferopol"),
    "OZH": (35.31, 47.87, "Zaporizhzhia"),
    "UDJ": (22.26, 48.63, "Uzhhorod"),
    "LWO": (23.96, 49.81, "Lviv"),
}

# Draw Ukraine outline (simplified)
ax.set_xlim(20, 40)
ax.set_ylim(43, 53)

# Plot cities
for code, (lon, lat, name) in cities.items():
    color = UA_YELLOW if code == "KBP" else "white"
    size = 200 if code == "KBP" else 100
    ax.scatter(lon, lat, s=size, c=color, zorder=5, edgecolors=DARK_BG, linewidth=2)
    offset = (0.3, 0.3)
    ax.annotate(name, (lon, lat), xytext=(lon + offset[0], lat + offset[1]),
                fontsize=11, color=color, fontweight="bold" if code == "KBP" else "normal")

# Draw fighter routes
fighter_flights = [f for f in flights if f["aircraft_type"] in FIGHTERS]
route_counts = Counter()
for f in fighter_flights:
    org = f.get("origin", "?")
    dst = f.get("destination", "?")
    key = tuple(sorted([org, dst]))
    route_counts[key] += 1

for (a, b), count in route_counts.items():
    if a in cities and b in cities:
        x1, y1 = cities[a][0], cities[a][1]
        x2, y2 = cities[b][0], cities[b][1]
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="<->", color=UA_YELLOW,
                                    lw=1.5 + count * 0.5, alpha=0.8))
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ax.text(mx, my + 0.2, f"{count} sorties", ha="center",
                fontsize=9, color=UA_YELLOW, alpha=0.9,
                bbox=dict(boxstyle="round,pad=0.2", facecolor=DARK_BG, alpha=0.8))

ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.set_title("Ukrainian Air Force Sortie Routes", fontsize=18, fontweight="bold", pad=20)
ax.set_aspect("equal")
ax.grid(True, alpha=0.2)

# Add fighter type legend
type_counts = Counter(f["aircraft_type"] for f in fighter_flights)
legend_text = "  ".join(f"{t}: {c}" for t, c in type_counts.most_common())
ax.text(0.5, -0.05, f"Aircraft: {legend_text}", transform=ax.transAxes,
        ha="center", fontsize=11, color=UA_YELLOW)

fig.suptitle("KBP Easter Egg — Fighter Jet Operations", fontsize=20, fontweight="bold", y=0.98)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "viz_sortie_map.png", dpi=150, bbox_inches="tight")
plt.close()
print("4. Sortie map saved")

# ──────────────────────────────────────────────────────────────
# 5. Flight Timeline (Gantt-style)
# ──────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(16, 10))

# Sort flights by scheduled time
sorted_flights = sorted(flights, key=lambda f: f.get("scheduled_time", ""))

for i, f in enumerate(sorted_flights):
    t = f.get("scheduled_time", "")
    if "T" not in t:
        continue
    hour = int(t.split("T")[1][:2])
    minute = int(t.split("T")[1][3:5])
    start = hour + minute / 60

    is_fighter = f["aircraft_type"] in FIGHTERS
    color = UA_YELLOW if is_fighter else UA_BLUE
    width = 0.3 if is_fighter else 0.5  # shorter bar for fighters (quick turnaround)
    alpha = 0.9 if is_fighter else 0.6

    direction = ">" if f.get("flight_type") == "departure" else "<"
    ax.barh(i, width, left=start, color=color, alpha=alpha, edgecolor=DARK_BG, height=0.8)

    label = f"{f['flight_number']} ({f['aircraft_type']})"
    if is_fighter:
        ax.text(start + width + 0.1, i, label, va="center", fontsize=7,
                color=UA_YELLOW, fontweight="bold")

ax.set_xlabel("Hour of Day")
ax.set_ylabel("Flight #")
ax.set_title("Flight Timeline", fontsize=18, fontweight="bold", pad=20)
ax.set_xticks(range(0, 25, 2))
ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 25, 2)])
ax.set_xlim(0, 24)
ax.grid(axis="x", alpha=0.3)

mil_patch = mpatches.Patch(color=UA_YELLOW, label="UAF Fighter Jet")
com_patch = mpatches.Patch(color=UA_BLUE, alpha=0.6, label="Commercial")
ax.legend(handles=[mil_patch, com_patch], loc="upper right", fontsize=11)

fig.suptitle("KBP Easter Egg — 24h Flight Timeline", fontsize=20, fontweight="bold", y=0.98)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "viz_timeline.png", dpi=150, bbox_inches="tight")
plt.close()
print("5. Timeline chart saved")

# ──────────────────────────────────────────────────────────────
# 6. Position Track Map (lat/lon scatter)
# ──────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 10))

# Sample positions (every 10th to avoid overplotting)
comm_lats, comm_lons = [], []
fight_lats, fight_lons = [], []

for i, p in enumerate(positions):
    if i % 5 != 0:
        continue
    lat = p.get("latitude", 0)
    lon = p.get("longitude", 0)
    if not lat or not lon:
        continue
    if p.get("aircraft_type", "") in FIGHTERS:
        fight_lats.append(lat)
        fight_lons.append(lon)
    else:
        comm_lats.append(lat)
        comm_lons.append(lon)

ax.scatter(comm_lons, comm_lats, s=1, c=UA_BLUE, alpha=0.3, label="Commercial")
ax.scatter(fight_lons, fight_lats, s=3, c=UA_YELLOW, alpha=0.6, label="Fighter Jets")

# Mark KBP
ax.scatter([30.89], [50.34], s=300, c="red", marker="*", zorder=10, label="KBP Airport")

ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.set_title("Flight Position Tracks", fontsize=18, fontweight="bold", pad=20)
ax.legend(loc="upper right", fontsize=11)
ax.set_aspect("equal")
ax.grid(True, alpha=0.2)

fig.suptitle("KBP Easter Egg — Radar View", fontsize=20, fontweight="bold", y=0.98)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "viz_tracks.png", dpi=150, bbox_inches="tight")
plt.close()
print("6. Position tracks saved")

print(f"\nAll visualizations saved to {OUTPUT_DIR}/")
