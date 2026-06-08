---
id: 58
title: "Exempt gate edges from building crossing penalty in taxiway graph"
area: routing
status: complete
priority: P0
committed: c5fdffc
---

## Problem

On PROD KSFO, aircraft routed to E-gates (east side) cross through terminal building instead of approaching from the east taxiway. The geometry fallback fix (`be123c3`) only applies when OSM graph is unavailable — on prod, `graph.find_route()` is the primary path.

## Root Cause

`_penalize_building_edges()` in `src/routing/taxiway_graph.py` penalizes ALL edges whose sample points fall inside a terminal building polygon. Gate nodes physically sit inside the terminal polygon (gates ARE in the terminal). So every gate→taxiway edge gets the 1000× penalty — including legitimate apron-access edges.

Since ALL paths to a gate must use at least one penalized gate edge, the penalty is constant across all approach directions. Dijkstra selects routes based on the non-penalized portion only, which may go around the wrong side of the building.

## Fix

1. Track gate node IDs in `self._gate_nodes: set[int]` during `build_from_config`
2. In `_penalize_building_edges`, skip edges where either endpoint is a gate node
3. Dijkstra now sees true distances for gate hops → prefers shorter apron-side path

## Files Changed

- `src/routing/taxiway_graph.py` — gate node tracking + exemption logic
- `tests/routing/test_taxiway_graph_spatial_index.py` — new test: `test_gate_edges_exempt_from_building_penalty`

## Verification

- 242 taxi/routing tests pass
- New test proves gate edges inside building polygon retain normal weight
- Deploy to prod and visually confirm E-gate aircraft approach from east
