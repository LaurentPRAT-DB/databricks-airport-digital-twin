# Airport Digital Twin

## What This Is

A comprehensive airport digital twin demo application that showcases the full Databricks platform stack. Built as a Databricks App using the APX framework (FastAPI + React + Three.js), it visualizes real-time airport operations through 2D maps, 3D visualizations, and AI/BI dashboards — all powered by live flight data.

## Core Value

Demonstrate end-to-end data flow through Databricks (ingest → stream → ML → visualize) with a visually compelling, interactive airport model that customers can explore.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Real-time flight data ingestion from APIs (FlightAware, ADS-B, or similar)
- [ ] Structured Streaming pipeline processing flight events
- [ ] Delta Live Tables for data transformation and quality
- [ ] Unity Catalog integration for data governance and lineage
- [ ] ML model for flight delay prediction
- [ ] ML model for gate assignment optimization
- [ ] ML model for congestion/bottleneck prediction
- [ ] MLflow for model tracking and serving
- [ ] 2D interactive airport map with live flight overlays
- [ ] 3D airport visualization using Three.js
- [ ] AI/BI Lakeview dashboards for analytics
- [ ] Genie integration for natural language queries
- [ ] Generic/fictional airport layout (not tied to specific real airport)
- [ ] Databricks App deployment using APX framework

### Out of Scope

- Real airport-specific layouts (SFO, JFK, etc.) — keeping it generic for flexibility
- Passenger-level simulation — focusing on flight operations
- Historical replay mode — focusing on real-time demo
- Mobile-specific UI — desktop-first for demo presentations

## Context

This is a customer demonstration tool for Databricks Field Engineering. The goal is to show prospects and customers what's possible with the Databricks platform through an engaging, visually impressive domain (airports). The demo should highlight:

- **Streaming capabilities**: Real-time data from flight APIs flowing through Structured Streaming
- **ML/AI**: Multiple models making predictions visible in the UI
- **Unity Catalog**: Governance, lineage tracking, data discovery
- **AI/BI**: Lakeview dashboards and Genie natural language interface

The airport domain is chosen for its visual appeal and familiar complexity — everyone understands airports, making it easy to explain the underlying data patterns.

## Constraints

- **Platform**: Databricks Apps (APX framework — FastAPI backend, React frontend)
- **Frontend**: React + Three.js for 3D visualization capabilities
- **Data**: Must work with real flight APIs (cost and rate limits may apply)
- **Deployment**: Must deploy and run within Databricks workspace

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| APX framework | Standard Databricks App pattern, FastAPI + React | — Pending |
| Generic airport | Flexibility, no licensing concerns with real layouts | — Pending |
| Real flight APIs | More impressive than synthetic data, shows real streaming | — Pending |
| Multiple ML models | Showcases breadth of ML capabilities | — Pending |
| Three.js for 3D | Industry standard, React integration available | — Pending |

---
*Last updated: 2026-03-05 after initialization*
