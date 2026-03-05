# Domain Pitfalls: Airport Digital Twin Demo

**Domain:** Airport Digital Twin / Databricks Demo Application
**Researched:** 2026-03-05
**Overall Confidence:** MEDIUM (based on training data; web verification unavailable)

---

## Critical Pitfalls

Mistakes that cause demo failures, rewrites, or major credibility loss during customer presentations.

### Pitfall 1: Flight API Rate Limit Exhaustion During Demo

**What goes wrong:** Demo crashes or freezes mid-presentation because API rate limits are hit. FlightAware AeroAPI, OpenSky Network, and ADS-B Exchange all have strict rate limits. A demo showing "real-time" data that suddenly stops updating is worse than synthetic data.

**Why it happens:**
- Developers test with small batches, not sustained polling
- Rate limits vary by tier (free tiers are severely limited)
- Multiple concurrent users during demo hit shared quota
- No caching layer means redundant API calls

**Consequences:**
- Demo stops updating during customer presentation
- Error messages appear in UI
- Loss of credibility ("this isn't production-ready")

**Prevention:**
1. **Implement aggressive caching**: Cache flight data for 30-60 seconds minimum
2. **Use fallback data**: Pre-record realistic flight data as backup
3. **Monitor quota usage**: Dashboard showing remaining API calls
4. **Choose API tier carefully**: FlightAware free tier = 1000 queries/month; production demos need paid tier
5. **Implement circuit breaker**: Gracefully degrade to cached/synthetic data

**Detection (warning signs):**
- HTTP 429 errors in logs
- Increasing latency on API calls
- Data timestamps not updating

**Phase to address:** Phase 1 (Data Ingestion) - Build caching and fallback from day one

**Confidence:** MEDIUM - Rate limit structures confirmed in training data; exact current limits should be verified with API documentation

---

### Pitfall 2: Three.js Memory Leaks Causing Browser Crashes

**What goes wrong:** 3D visualization becomes sluggish or crashes after 10-15 minutes of demo use. Browser tab consumes gigabytes of RAM. This is embarrassing during extended customer sessions.

**Why it happens:**
- Geometries and materials not properly disposed when objects are removed
- Textures loaded repeatedly without reuse
- Event listeners not cleaned up on component unmount
- React re-renders creating duplicate Three.js objects

**Consequences:**
- Browser tab crashes mid-demo
- Progressive slowdown (FPS drops from 60 to single digits)
- Customer laptop fans spin up loudly
- Need to refresh page repeatedly

**Prevention:**
1. **Strict disposal protocol**: Call `geometry.dispose()`, `material.dispose()`, `texture.dispose()` on every removal
2. **Use object pooling**: Reuse aircraft/vehicle objects instead of creating new ones
3. **React integration carefully**: Use `useEffect` cleanup functions, consider react-three-fiber
4. **Monitor memory**: Add dev-only memory stats overlay (Three.js `Stats.js`)
5. **Limit scene complexity**: Cap maximum visible aircraft, use LOD (Level of Detail)

**Detection (warning signs):**
- `performance.memory.usedJSHeapSize` growing continuously
- FPS counter showing decline over time
- Browser dev tools showing increasing detached DOM nodes

**Phase to address:** Phase 2 (3D Visualization) - Architecture decision, not an afterthought

**Confidence:** HIGH - Well-documented Three.js behavior in training data

---

### Pitfall 3: Structured Streaming Checkpoint Corruption

**What goes wrong:** Streaming job fails to restart after interruption, requiring manual checkpoint deletion. During demo, this means "let me restart everything" which kills momentum.

**Why it happens:**
- Changing streaming query schema without clearing checkpoints
- Renaming columns or changing transformations mid-stream
- Testing different query variations against same checkpoint location
- Cluster preemption during checkpoint write

**Consequences:**
- Stream fails with cryptic checkpoint errors
- Manual intervention required to clear checkpoints
- Data loss or duplicate processing if handled incorrectly
- Demo downtime

**Prevention:**
1. **Version checkpoint paths**: Include schema version in checkpoint path (`/checkpoints/v1/flights`)
2. **Separate dev/demo checkpoints**: Never share checkpoint locations
3. **Implement checkpoint recovery script**: Automated cleanup with safeguards
4. **Use Trigger.AvailableNow for demos**: Better control than continuous
5. **Test restart scenarios**: Include cluster restart in testing

**Detection (warning signs):**
- `StreamingQueryException` with checkpoint metadata errors
- Schema mismatch exceptions on restart
- Stream progress stuck at 0

**Phase to address:** Phase 1 (Data Ingestion / Streaming Pipeline)

**Confidence:** HIGH - Common Databricks Structured Streaming issue in training data

---

### Pitfall 4: Demo Dependency on Live External Services

**What goes wrong:** Demo fails because FlightAware is down, Databricks workspace has issues, or network is slow at customer site. External dependencies are single points of failure.

**Why it happens:**
- Over-reliance on real-time external APIs
- No offline fallback mode
- Network assumptions (low latency, high bandwidth)
- No health checks for external services

**Consequences:**
- Complete demo failure through no fault of your own
- Scrambling to explain "this usually works"
- Customer questions product reliability

**Prevention:**
1. **Build offline mode**: Full demo capability with synthetic data
2. **Cache aggressively**: Last-known-good data always available
3. **Health check dashboard**: Show service status before demo
4. **Pre-flight checklist**: Verify all services 30 min before demo
5. **Graceful degradation UI**: Show "using cached data" vs crashing

**Detection (warning signs):**
- Pre-demo health checks failing
- Unusual latency on external calls
- Empty responses from APIs

**Phase to address:** Phase 1 (Architecture) and Phase 4 (Demo Hardening)

**Confidence:** HIGH - Standard demo engineering principle

---

## Moderate Pitfalls

Issues that cause friction but can be recovered from during demo.

### Pitfall 5: 3D Performance on Customer Hardware

**What goes wrong:** Demo runs smoothly on developer's M3 MacBook Pro but stutters on customer's older Windows laptop or when projected to external display.

**Why it happens:**
- Development on high-end hardware
- No testing on range of devices
- External displays often trigger software rendering
- WebGL capabilities vary significantly

**Prevention:**
1. **Test on mid-tier hardware**: Target 3-year-old laptop performance
2. **Build quality settings**: Low/Medium/High presets user can toggle
3. **Detect capabilities**: WebGL feature detection, auto-adjust quality
4. **Provide 2D fallback**: Full functionality without 3D for worst case
5. **Limit default scene complexity**: Don't show 500 aircraft by default

**Detection (warning signs):**
- FPS drops below 30 on test devices
- Long initial load times
- WebGL context creation warnings

**Phase to address:** Phase 2 (3D Visualization) - Build quality tiers from start

**Confidence:** MEDIUM - Common WebGL issue

---

### Pitfall 6: Delta Live Tables Pipeline Failures During Demo

**What goes wrong:** DLT pipeline shows red/failed status in UI when you navigate to show data lineage. Customers see errors instead of elegant data flow.

**Why it happens:**
- Pipeline not refreshed before demo
- Schema drift from upstream API changes
- Expectations (data quality rules) failing on edge cases
- Cluster startup time causing timeouts

**Prevention:**
1. **Pre-demo pipeline refresh**: Run pipeline 1 hour before
2. **Lenient expectations for demo**: Warn instead of fail on quality issues
3. **Use Development mode**: Faster iteration, less strict
4. **Keep pipeline simple**: 3-4 tables maximum for demo
5. **Pre-warm clusters**: Start clusters before demo

**Detection (warning signs):**
- Pipeline status not "Completed" in UI
- Event log showing expectation failures
- Long "Starting" status on tables

**Phase to address:** Phase 1 (Data Pipeline)

**Confidence:** MEDIUM - Based on DLT behavior patterns

---

### Pitfall 7: React State Desync with Real-Time Data

**What goes wrong:** UI shows stale data, incorrect counts, or flickering as real-time updates conflict with React state management.

**Why it happens:**
- Race conditions between WebSocket updates and REST fetches
- Multiple components subscribing to same data differently
- Optimistic updates conflicting with server truth
- React batching interfering with real-time updates

**Prevention:**
1. **Single source of truth**: One real-time data store (Zustand/Redux)
2. **Timestamp all data**: Always show data age in UI
3. **Use React Query/SWR**: Built-in stale-while-revalidate
4. **Debounce UI updates**: Don't re-render on every message
5. **Clear loading/stale states**: Obvious UI indicators

**Detection (warning signs):**
- Console warnings about state updates on unmounted components
- Flickering UI elements
- Data counts not matching between views

**Phase to address:** Phase 2 (Frontend Architecture)

**Confidence:** MEDIUM - Common React real-time pattern issue

---

### Pitfall 8: MLflow Model Serving Cold Start

**What goes wrong:** First prediction request after demo start takes 30+ seconds because model endpoint needs to warm up. Awkward silence during demo.

**Why it happens:**
- Serverless model endpoints scale to zero
- Model not pre-loaded before demo
- Large model files need download time
- Dependencies need initialization

**Prevention:**
1. **Pre-warm endpoints**: Script that calls each model before demo
2. **Use provisioned concurrency**: Keep minimum instances warm
3. **Show loading indicator**: "Model loading..." vs frozen UI
4. **Cache predictions**: Common scenarios pre-computed
5. **Keep models small**: Sub-second inference target

**Detection (warning signs):**
- Endpoint status showing "Scaling" in workspace UI
- First request latency >> subsequent requests
- Timeout errors on initial calls

**Phase to address:** Phase 3 (ML Integration)

**Confidence:** MEDIUM - Common MLflow serving pattern

---

## Minor Pitfalls

Annoyances that don't break the demo but reduce polish.

### Pitfall 9: Inconsistent Airport Data Model

**What goes wrong:** Gate numbers don't match between 2D map, 3D view, and dashboard. Terminal names inconsistent. Confusion when explaining data flow.

**Why it happens:**
- Different data sources for different views
- No single source of truth for airport layout
- Hardcoded values scattered across codebase
- API data doesn't match synthetic layout

**Prevention:**
1. **Define airport schema first**: Single JSON/YAML defining all gates, terminals
2. **Generate views from schema**: 2D, 3D, and dashboards read same source
3. **Use fictional but consistent names**: Terminal A, B, C with gates A1-A20, etc.
4. **Validate at build time**: Schema validation tests

**Phase to address:** Phase 1 (Data Model)

**Confidence:** HIGH - Standard data modeling issue

---

### Pitfall 10: Genie/AI Queries Returning Unexpected Results

**What goes wrong:** Customer asks natural language question and gets wrong or confusing answer, raising questions about AI capabilities.

**Why it happens:**
- Training data doesn't match demo schema
- Ambiguous column names
- Missing semantic layer configuration
- Edge case queries not tested

**Prevention:**
1. **Prepare scripted queries**: Know which questions work well
2. **Configure semantic layer**: Clear column descriptions, relationships
3. **Test extensively**: 50+ query variations before demo
4. **Have graceful recovery**: "Let me rephrase that" ready
5. **Limit scope**: Only enable Genie on clean, well-documented tables

**Phase to address:** Phase 4 (AI/BI Integration)

**Confidence:** MEDIUM - Based on Genie behavior patterns

---

### Pitfall 11: Unity Catalog Permission Errors

**What goes wrong:** Demo of data governance features fails because service principal doesn't have correct permissions. "Access denied" errors undermine trust message.

**Why it happens:**
- Demo account permissions not fully configured
- Different workspace setup than development
- Service principal vs user permissions differ
- Catalog/schema/table permission inheritance confusion

**Prevention:**
1. **Document all required permissions**: Checklist for workspace setup
2. **Test with demo service principal**: Don't rely on admin access
3. **Create dedicated demo catalog**: Full control, no interference
4. **Automate permission setup**: Terraform/script for reproducibility

**Phase to address:** Phase 1 (Infrastructure)

**Confidence:** MEDIUM - Common Unity Catalog setup issue

---

## Databricks-Specific Gotchas

### Pitfall 12: Databricks App Cold Start Time

**What goes wrong:** App takes 60+ seconds to become responsive after first access. Customer staring at loading screen.

**Why it happens:**
- Databricks Apps spin down when idle
- Python environment initialization
- Database connections need establishment
- No keep-alive mechanism

**Prevention:**
1. **Pre-access the app**: Open it 5 minutes before demo
2. **Implement health endpoint**: Quick response to keep alive
3. **Lazy load heavy features**: Basic UI fast, 3D loads async
4. **Show loading progress**: Skeleton screens, progress bar

**Phase to address:** Phase 4 (Deployment)

**Confidence:** MEDIUM - Based on Databricks Apps architecture

---

### Pitfall 13: Workspace Cluster Policies Blocking Resources

**What goes wrong:** Demo streaming job fails because workspace cluster policy doesn't allow required node types or configurations.

**Why it happens:**
- Demo workspace has stricter policies than dev
- Customer workspace policies unknown
- GPU nodes needed for visualization server not allowed
- Spot instances preempted mid-demo

**Prevention:**
1. **Test in restricted workspace**: Mirror customer constraints
2. **Document minimum requirements**: Instance types, DBUs needed
3. **Avoid specialty instances**: Standard nodes only
4. **Use workspace admin account for demos**: Bypass policies if possible

**Phase to address:** Phase 4 (Deployment)

**Confidence:** MEDIUM - Common enterprise Databricks constraint

---

## Phase-Specific Warning Matrix

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Data Ingestion | API Rate Limits (#1) | Cache layer + fallback data |
| Data Ingestion | Checkpoint Corruption (#3) | Versioned checkpoint paths |
| Streaming Pipeline | External Service Dependency (#4) | Offline mode + health checks |
| 3D Visualization | Memory Leaks (#2) | Disposal protocol + object pooling |
| 3D Visualization | Hardware Performance (#5) | Quality presets + 2D fallback |
| Frontend | React State Desync (#7) | Single state store + timestamps |
| ML Integration | Cold Start Latency (#8) | Pre-warm scripts + caching |
| AI/BI Dashboards | Genie Query Failures (#10) | Scripted queries + semantic layer |
| Deployment | Unity Catalog Permissions (#11) | Permission checklist + automation |
| Deployment | App Cold Start (#12) | Pre-access + lazy loading |
| Demo Hardening | All external dependencies | Offline mode as first-class feature |

---

## Prevention Strategy Summary

### Architecture-Level Preventions

1. **Offline-First Design**: Build the entire demo to work without external services. Add real-time as enhancement, not requirement.

2. **Aggressive Caching Everywhere**:
   - API responses: 30-60 second cache
   - 3D assets: Browser cache + service worker
   - ML predictions: Common scenarios pre-computed
   - Database queries: Result caching

3. **Graceful Degradation UI**: Every component should have three states:
   - Live data (green indicator)
   - Cached data (yellow indicator with timestamp)
   - Offline/synthetic data (gray indicator)

4. **Resource Management Protocol**: Strict memory/connection cleanup. No leaks tolerated.

### Process-Level Preventions

1. **Pre-Demo Checklist** (run 30 minutes before):
   - [ ] All external APIs responding
   - [ ] Streaming jobs running
   - [ ] DLT pipeline status green
   - [ ] ML endpoints warm (make test prediction)
   - [ ] App responsive (not cold)
   - [ ] Clusters running (if applicable)

2. **Fallback Scripts**: One-command recovery for common failures:
   - `./scripts/fallback-offline.sh`: Switch to synthetic data
   - `./scripts/warm-ml.sh`: Pre-warm all ML endpoints
   - `./scripts/reset-streams.sh`: Clear checkpoints and restart

3. **Demo Environment Isolation**: Dedicated workspace with:
   - Demo-specific catalog
   - Pre-configured permissions
   - Known cluster policies
   - No shared resources

### Testing Preventions

1. **Chaos Testing for Demo**: Regularly test failure scenarios:
   - API returning errors
   - Slow network (throttle to 3G)
   - Cluster preemption mid-stream
   - Browser refresh mid-demo

2. **Hardware Matrix Testing**: Test on:
   - 3-year-old Windows laptop
   - External projector/display
   - Customer's typical browser (often Chrome with many extensions)

3. **Extended Run Testing**: Let demo run for 1 hour and verify:
   - No memory growth
   - No FPS degradation
   - No stale data

---

## Sources and Confidence Notes

**Source hierarchy for this research:**
- Training data knowledge (primary source due to tool unavailability)
- Direct experience patterns with similar technologies

**Validation recommended:**
- FlightAware/OpenSky current pricing and rate limits
- Databricks Apps latest documentation
- Three.js r150+ optimization guides
- MLflow model serving warm-up patterns

**Confidence assessment:**
| Area | Confidence | Reason |
|------|------------|--------|
| Three.js memory | HIGH | Well-documented behavior |
| Streaming checkpoints | HIGH | Common Databricks pattern |
| API rate limits | MEDIUM | Specific limits should be verified |
| Databricks Apps | MEDIUM | Platform may have evolved |
| Genie behavior | MEDIUM | Feature actively developing |
| Demo reliability | HIGH | Standard demo engineering |

---

*This document should be validated against current official documentation. API rate limits and Databricks platform features may have changed since training data cutoff.*
