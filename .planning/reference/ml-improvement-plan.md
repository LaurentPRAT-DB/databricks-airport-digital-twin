thorough gap analysis across each model, structured by what SOTA research reveals your current implementation is missing.

---

## Model-by-model feature gap analysis

### 1. Delay predictor — biggest gaps

The current feature set (`hour_of_day`, `altitude_category`, `velocity_normalized`, `heading_quadrant`, `flight_distance_category`) completely misses the single most important signal in SOTA delay research: **reactionary/propagation delay**.

EUROCONTROL's 2024 data shows reactionary (knock-on) delay accounts for 46% of all delay minutes across the European network, yet your model has zero features encoding whether the inbound aircraft was already delayed. Research on delay propagation shows the key capability is computing reactionary delays and understanding delay evolution through the network — essentially, the delay on flight N is largely predicted by the delay on flight N-1 for the same tail number.

The second major gap: **no actual weather features**. The model uses altitude and velocity as crude proxies, but SOTA pre-tactical delay research identifies flight timing, airport demand, and weather conditions as the crucial feature groups. Wind speed, visibility, and ceiling are absent — yet these are already computed in your simulation environment for the OBT model (`wind_speed_kt`, `visibility_sm` are OBT features).

Third: **no airport load/demand features**. The concurrent flight count that your congestion model computes is not fed back into delay prediction, despite being a strong predictor. The STPN approach (SpatioTemporal Propagation Network) uses a multi-graph convolution model to account for geographic proximity and airline schedules from a spatial perspective, combined with temporal self-attention to capture delay propagation — your model uses neither.

**High-value additions, in priority order:**

| Feature | Source | Effort |
|---|---|---|
| `inbound_delay_minutes` (same tail number) | Live flight state | Low — already tracked in sim |
| `airport_load_ratio` (flights in last 30min / capacity) | Congestion model output | Low — reuse existing computation |
| `wind_speed_kt`, `visibility_sm` | Already in OBT features | Very low — pass-through |
| `scheduled_buffer_min` | Schedule | Low |
| Rolling 1h delay rate at origin | ATFM data or sim state | Medium |

The model type (rule-based heuristic) is acceptable for the demo use case, but adding these features as calibration multipliers would meaningfully improve face validity for SITA/IATA audiences.

---

### 2. Congestion predictor — structural limitation

The current model counts flights in bounding boxes and applies capacity ratio thresholds. The fundamental issue is that **capacity is not static** — SOTA approaches model it as a function of runway configuration, weather state, and sequencing.

The hourly profile scaling (up to 1.5x for peak hours) is a reasonable proxy, but it goes in the wrong direction: at peak hours, *effective* capacity per slot is actually lower (less margin, less recovery time), so congestion onset should be more sensitive, not less.

More actionable: **ASMA (Arrival Sequencing and Metering Area) additional time** is the metric EUROCONTROL uses as an ANS-related congestion proxy. Additional ASMA time measures the difference between observed travel time from 40NM radius entry to landing vs a reference time per entry sector, aircraft type, and landing runway — and has a direct impact on fuel burn and emissions. Your congestion model could approximate this with the distance-to-runway computation already in the Gate Recommender, without a significant rewrite.

**Key addition:** feed `congestion_level` output back into the delay predictor as a feature. Right now these two models are isolated but in reality they're strongly coupled.

---

### 3. OBT model — closest to SOTA, but gaps in key features

This is your most sophisticated model. The feature set of 18 variables is well-designed. Gaps compared to literature:

**Missing: previous turnaround duration for same tail/gate.** De Falco et al. developed probabilistic ML models to forecast aircraft turnaround times and TOBT at major European airports, specifically focused on turnaround operations as critical contributors to reactionary delays. A key finding across that body of work is that historical turnaround performance of the same airline at the same gate (or airport) is among the strongest features. Your model has `airline_code` and `gate_id_prefix` as categoricals, but no rolling historical performance feature.

**Missing: ground handling crew load.** The number of concurrent turnarounds sharing the same GSE pool is not represented. `concurrent_gate_ops` captures some of this, but doesn't distinguish between narrow/wide operations (which have very different GSE contention profiles).

**Missing: connection pax pressure.** Whether passengers on this flight have tight connections (common in hub airports) creates real schedule pressure that experienced handlers know about. This is an `is_hub_connecting_flight` boolean that could be derived from airline/route type.

**Quantile calibration — a significant strength to highlight.** Your CQR (Conformalized Quantile Regression) implementation for P10/P90 intervals is genuinely aligned with SOTA. Research on pre-tactical turnaround forecasting shows that advanced neural network architectures can retain 94–97% of real-data predictive performance while maintaining feature importance patterns informative for operational decision-making. The two-stage (T-90 → T-park → T-board) cascade is also directly parallel to current best practice. This architecture is solid.

**Training data concern:** Training exclusively on simulation JSONs creates a distribution shift risk. The A-CDM adapter and transfer learning module address this correctly in principle, but the quality of the sim-generated training data depends heavily on how realistic the simulation's turnaround phase transitions are. The OBT fallback values (45/90/35 min) come from the GSE model's hardcoded constants — if the simulation just oscillates around these values, the trained model is learning the simulator, not reality.

---

### 4. Gate recommender — feature weights worth revisiting

The 40/20/15/15/10 scoring split is reasonable but the literature suggests **proximity to runway should carry much more weight for time-sensitive situations**. When `delay_minutes > 0`, fast taxi time can partially offset the delay — a 5-minute taxi savings matters for a 10-minute delay. Consider making the proximity weight a function of `delay_minutes`:

```python
proximity_weight = min(0.30, 0.10 + (delay_minutes / 100) * 0.20)
# redistributed from operator match when delay > 0
```

Also missing: **remote stand preference for wide-body aircraft in congestion**. When the apron is at HIGH/CRITICAL, pushing wide-body arrivals to remote stands (with bussing) is standard practice at Heathrow, CDG, and most SITA customer airports. The `is_remote_stand` binary is in the OBT features but not fed back into gate scoring.

---

### Visualizing the dependency gaps---

### Priority improvement roadmap

**Tier 1 — Low effort, high impact (leverage what you already have):**

1. Pass `wind_speed_kt` and `visibility_sm` from the OBT feature set into the Delay predictor. These are already computed in your weather simulation layer.
2. Add `congestion_level` (output of CongestionPredictor) as an input feature to DelayPredictor. The models run in the same registry — this is a one-liner.
3. Feed `delay_minutes` back from DelayPredictor into Gate Recommender scoring as a dynamic proximity weight.

**Tier 2 — Medium effort, narrative-valuable for demos:**

4. Add `inbound_delay_minutes` as a feature to both Delay and OBT models. In the simulation context this means tracking the last delay event for each tail number. The uncertainty in pre-tactical prediction stems from weather, air traffic congestion, technical issues, crew availability, and cascading delays from earlier flights — this is the cascading delay signal, and it's the most defensible feature addition to an aviation audience.
5. Add `is_hub_connecting_pressure` (boolean derived from airline/route type) to OBT features — relevant for SITA customers who run hub operations.

**Tier 3 — Architecture consideration for post-demo:**

6. The two-stage OBT cascade (T-90 → T-park → T-board) is already SOTA-aligned. The main risk is sim-to-real distribution shift in training. The A-CDM transfer learning module is the right solution, but its effectiveness depends on A-CDM data being available at the target airport. For non-A-CDM airports (many regional SITA customers), consider adding a lightweight empirical calibration step using just OTP15 and average delay from the EUROCONTROL/Eurostat sources we found earlier — those map directly to `AirportProfile.delay_rate` and `mean_delay_minutes` already.