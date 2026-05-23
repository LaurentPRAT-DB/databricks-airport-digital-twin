---
status: proposed
area: simulation
priority: high
effort: large
related:
  - .planning/backlog/simulation-engine-refactor.md
---

# CRAP Ratio Reduction: Test-Guarded Refactoring Prompt

## Usage

Feed this prompt to Claude Code to execute the refactoring. It will discover current state, write characterization tests, then refactor incrementally with differential validation.

---

## Prompt

**Task: Reduce CRAP ratio on three critical complexity hotspots via safe, test-guarded refactoring.**

I have a Python codebase with high-complexity functions flagged by `radon`. I want to lower the CRAP ratio on the three critical files below without changing behavior. Safety is the absolute priority. Work one file at a time, worst-first, and pause for my review between files.

**Targets (in order):**
1. `_flight_lifecycle.py::_update_flight_state` — CC 219, rank F, MI 0.00 (the state-machine monster; a PhaseResolver refactor is the intended direction)
2. `_generation.py::generate_synthetic_trajectory` (CC 91, F) and `generate_synthetic_flights` (CC 70, F) — legacy trajectory generator
3. `engine.py::_update_all_flights` (CC 34, E) and `_apply_resolution` (CC 31, E) — ScheduleBuilder + PhaseResolver extractions are the intended direction

**Phase 0 — Discover the current state (don't assume).**
Tell me what test coverage exists today for each target before touching anything. Run the existing test suite, run `coverage` against these files specifically, and run `radon cc -s` and `radon mi`. Report a baseline table: CC, MI, coverage %, and CRAP per target function. If there are no tests, say so plainly.

**Phase 1 — Preserve the original and characterize it.**
For the file you're working on, keep the original implementation importable in parallel (e.g. a `_original` copy or a pinned reference module) so the new code can be validated against it. Then write tests that capture the *current* behavior of the original across a wide input range — edge cases, boundaries, and realistic states — covering as many branches of the high-CC functions as you can. These assert what the code does today, not what it ideally should do. (Coverage is half the CRAP equation, so this step lowers CRAP on its own.)

**Phase 2 — Refactor against the original.**
You decide the best validation technique (differential testing both versions on identical inputs, golden snapshots, property-based checks, or a mix) — whatever most convincingly proves the refactored code matches the original. State which you chose and why. Refactor incrementally in small commits; after each meaningful change, prove the new version's behavior is identical to the preserved original. Any divergence is a regression — stop and fix before continuing.

**Phase 3 — Verify and report.**
Re-run radon and coverage. Give me a before/after table of CC, MI, coverage, and CRAP for the file's targets. Confirm the suite passes and the new code still matches the original.

**Constraints:**
- Don't change public signatures or external behavior without flagging it first.
- Keep the original reference versions in the tree until I confirm removal.
- Prefer many small, reviewable commits over a big rewrite.
- If reducing complexity would require a real behavior change (essential vs. accidental complexity), stop and ask.
- Work one file at a time; after Phase 3 for a file, pause and wait for my go-ahead before the next.

Start with Phase 0 across all three files (so I see the full picture), then proceed to Phase 1 on `_update_flight_state` only and stop for my review.

---

## Notes

- Phase 0 is the critical discovery step. If coverage is near-zero on `_update_flight_state` (CC 219), the bulk of the effort is writing characterization tests, not the refactor itself.
- The PhaseResolver and ScheduleBuilder designs in `simulation-engine-refactor.md` provide the target architecture for files 1 and 3.
- File 2 (`_generation.py`) is legacy code mostly superseded by the simulation engine — refactoring there may be lower value.
- CRAP formula: `CRAP(m) = comp(m)^2 * (1 - cov(m)/100)^3 + comp(m)` — coverage improvements alone dramatically reduce CRAP on high-CC functions.

## Baseline (2026-05-23)

| File | Function | CC | Rank | MI |
|------|----------|---:|:----:|---:|
| `_flight_lifecycle.py` | `_update_flight_state` | 219 | F | 0.00 |
| `_generation.py` | `generate_synthetic_trajectory` | 91 | F | 3.08 |
| `_generation.py` | `generate_synthetic_flights` | 70 | F | 3.08 |
| `engine.py` | `_update_all_flights` | 34 | E | 0.28 |
| `engine.py` | `_apply_resolution` | 31 | E | 0.28 |

Overall codebase average: **A (4.9)**
