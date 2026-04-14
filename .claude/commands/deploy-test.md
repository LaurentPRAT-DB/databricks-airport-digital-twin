# Post-Deploy Test & Fix Loop

Run the deployed app test suite, analyze failures, fix them, redeploy, and re-test.

## Workflow

1. **Run the test script** against the live deployed app:
   ```bash
   bash scripts/test_deployed_app.sh
   ```

2. **Analyze results**: Parse the output for FAIL lines. For each failure:
   - Identify the failing test (T1-T7) and the assertion
   - Check the actual values vs expected
   - Read the app logs if needed: `databricks apps get-logs airport-digital-twin-dev --profile FEVM_SERVERLESS_STABLE`

3. **Diagnose**: Based on the failure:
   - T1 (health): App crashed on startup — check logs for Python traceback
   - T2 (flights): No synthetic flights — check fallback.py state, gate loading
   - T3 (config): OSM data missing — check airport_config_service initialization
   - T4 (activate): Airport switch rejected — check routes.py activate endpoint
   - T5 (positions): Flights at wrong coordinates — check apply_airport_offset, gate positions, set_airport_center
   - T6 (quality): NaN/null positions — check trajectory generation, coordinate math
   - T7 (switch back): SFO regression — check reset_airport_offset, reset_synthetic_state

4. **Fix**: Implement the fix in the relevant source file(s).

5. **Local verification**: Run unit tests to confirm the fix doesn't break anything:
   ```bash
   uv run pytest tests/test_trajectory_coherence.py -v
   ```

6. **Rebuild, commit, redeploy**:
   ```bash
   cd app/frontend && npm run build && cd ../..
   git add -f <files> app/frontend/dist/
   git commit -m "fix: <description>"
   databricks bundle deploy --target dev
   # Wait for app to restart, then re-run tests
   ```

7. **Re-test**: Run `bash scripts/test_deployed_app.sh` again to confirm the fix.

8. **Report**: Summarize what failed, what was fixed, and the final test results.

## Key files

- Test script: `scripts/test_deployed_app.sh`
- Backend API: `app/backend/api/routes.py` (airport switch), `app/backend/main.py` (startup)
- Flight generation: `src/ingestion/fallback.py` (gates, trajectories, runway data)
- Simulation engine: `src/simulation/engine.py`
- Airport config: `app/backend/services/airport_config_service.py`

## Notes

- The test script uses `databricks auth token --profile FEVM_SERVERLESS_STABLE` for OAuth
- Airport switch takes ~15-20s (OSM load + gate reload + demo generation)
- App restart after deploy takes 1-3 minutes — poll `databricks apps get` until RUNNING
- The script tests KSFO (default) -> MMMX -> KSFO round-trip
