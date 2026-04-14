# UI E2E Test & Fix Loop

Run the Playwright UI exerciser against the deployed app, analyze failures, fix them, redeploy, and re-test.

## Workflow

1. **Run the UI test** against the live deployed app:
   ```bash
   uv run python scripts/test_ui_e2e.py
   ```

2. **Read the JSON report**:
   ```bash
   cat test-results/ui_e2e_report.json
   ```

3. **Analyze results**: For each scenario with status `fail`:
   - Check the `details` field for what went wrong
   - Check `console_errors` for JavaScript exceptions
   - View any failure screenshots in `test-results/`
   - Diagnose:
     - S1 (load): App startup issue — check backend logs
     - S2 (flights): API not returning data — check fallback.py
     - S3 (click): UI selectors changed — update test locators
     - S4 (view toggle): 2D/3D switch broke — check ViewManager
     - S5/S7 (airport switch): Switch failed or positions wrong — check routes.py activate, apply_airport_offset
     - S6 (verify positions): Flights at wrong coordinates — check fallback.py gate generation
     - S8 (switch back): KSFO regression — check reset flow
     - S9 (report): Modal missing — check SimReport component
     - S10 (console errors): Uncaught JS exceptions — fix source

4. **Fix**: Implement the fix in the relevant source file(s).

5. **Local verification**:
   ```bash
   uv run pytest tests/test_trajectory_coherence.py -v
   cd app/frontend && npm test -- --run && cd ../..
   ```

6. **Rebuild, commit, redeploy**:
   ```bash
   cd app/frontend && npm run build && cd ../..
   git add <files> app/frontend/dist/
   git commit -m "fix: <description>"
   databricks bundle deploy --target dev
   ```

7. **Wait for app restart** (~1-3 min), then **re-run** the UI test.

8. **Report**: Summarize what failed, what was fixed, and the final test results.

## Options

- `--headed` — Run with visible browser for debugging
- `--url URL` — Override app URL
- `--profile PROFILE` — Override Databricks CLI profile

## Key files

- Test script: `scripts/test_ui_e2e.py`
- Report output: `test-results/ui_e2e_report.json`
- Failure screenshots: `test-results/*_fail.png`
- Final state screenshot: `test-results/final_state.png`
