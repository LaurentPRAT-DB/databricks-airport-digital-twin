---
title: "Simulation Report Chat with Aviation RAG"
status: proposed
area: simulation, assistant
priority: high
related:
  - feat/simulation-report-generation
  - unified-assistant
---

# Simulation Report Chat with Aviation Knowledge

## Goal

Add an interactive chat panel to the simulation report that can answer follow-up questions, generate recommendations with quantified impact estimates, and leverage aviation domain knowledge (FAA/ICAO standards).

## Approach

### 1. Report-Level Chat Panel

Unlike the existing event-level mini-chat (per-event explain), this is a full chat attached to the report with the **entire simulation context** (KPIs, events, weather, schedule, phase transitions) available as conversation context.

- Floating chat panel within the report view
- Full simulation data passed as system context
- Multi-turn conversation with memory of prior exchanges
- Can reference specific events, flights, time periods

### 2. Aviation Knowledge via RAG

No pre-trained aviation-specific LLM exists publicly. Best approach: **RAG with authoritative sources** + expert system prompt.

**Knowledge sources to index:**
- FAA Advisory Circular AC 150/5060-5 (Airport Capacity and Delay)
- ICAO Doc 9157 (Aerodrome Design Manual)
- ACRP Research Reports (airport operations best practices)
- FAA 7110.65 (Air Traffic Control procedures — separation standards)
- BTS On-Time Performance benchmarks by airport
- Airport-specific calibration profiles (already in UC Volume)
- Historical simulation results (past scenario runs for comparison)

**Implementation options:**
- Vector store in Databricks (Delta table + VS index on UC Volume docs)
- Mosaic AI Vector Search for retrieval
- Chunk PDFs/docs → embed → retrieve top-k context per query

### 3. Expert System Prompt with Benchmarks

Bake in FAA/ICAO reference data directly in the system prompt:
- Standard arrival rates by airport category (small/medium/large hub)
- IFR vs VFR capacity reduction factors (typically 30-50% reduction)
- Acceptable delay thresholds (FAA: >15min = delayed)
- Go-around rates (industry avg: 1-3% of approaches)
- Standard separation minima (3/4/5/6 NM based on wake category)
- Turnaround benchmarks by aircraft type (narrow-body: 35-50min, wide-body: 60-90min)

### 4. Recommendation Engine

The chat should proactively offer recommendations with impact estimates:
- "Adding a 3rd parallel approach stream could increase AAR by ~20 ops/hr"
- "Reducing minimum departure separation from 90s to 60s (CSPO) would save ~12 min avg delay"
- "Moving to EMAS-equipped runway ends would allow reduced RESA, freeing 300m for taxiway"

**Impact quantification via what-if simulation:**
- Chat can trigger parametric re-runs with modified inputs
- Compare KPIs between baseline and modified scenario
- Present delta: "Recommendation: close RWY 01L/19R during peak → saves 3 conflict events, costs +4.2min avg taxi time"

### 5. Implementation Phases

**Phase A: Report-level chat (quick win)**
- Add chat panel to SimulationReport component
- Pass full simulation JSON as system context
- Use existing `/api/assistant/ask` with custom system prompt
- Aviation-expert persona with hardcoded benchmarks

**Phase B: RAG pipeline (medium effort)**
- Upload FAA/ICAO documents to UC Volume
- Build vector search index (Mosaic AI VS or FAISS on Databricks)
- Add retrieval step before LLM call: query → retrieve relevant passages → augment prompt
- Endpoint: `/api/assistant/report-chat` with RAG context

**Phase C: What-if simulation (high effort)**
- Chat can invoke simulation engine with modified parameters
- Tool-calling: `run_simulation(params)` returns KPI comparison
- Requires backend job queue (simulation takes 30-60s)
- Present results as "before vs after" table

## Technical Notes

- Model: `databricks-claude-sonnet-4-5` (already deployed, supports function calling)
- Vector search: Databricks Mosaic AI Vector Search (serverless, auto-scaling)
- Document chunking: 512-token chunks with 64-token overlap, section-aware splitting
- Embedding model: `databricks-gte-large-en` (already available on workspace)
- Storage: UC Volume `aviation_knowledge` for source documents, Delta table for embeddings

## Success Criteria

- User can ask follow-up questions about any aspect of the simulation report
- Recommendations cite specific FAA/ICAO standards or benchmarks
- Impact estimates are quantified (delay minutes, capacity ops/hr, cost implications)
- Phase C: user can say "what if we close runway X?" and get a simulated answer
