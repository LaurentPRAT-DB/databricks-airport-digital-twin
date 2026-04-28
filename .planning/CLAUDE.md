# .planning/ — Project Knowledge Base

## How to use this directory

- **Before starting work**, search here for prior analysis on the topic
- Fix docs contain root cause analysis — don't re-investigate what's already known
- Feature plans contain architectural decisions — respect them unless explicitly revisiting
- All files have YAML frontmatter (`status`, `area`, `related`) for grep-based filtering

## Quick lookup

| Need | Look in |
|------|---------|
| Bug already investigated? | `fixes/fix-<topic>.md` or `fixes/<nn>-<topic>/` |
| Feature already planned? | `features/<nn>-<topic>/PLAN.md` |
| Is it in the backlog? | `backlog/<topic>.md` or `backlog/<nn>-<topic>.md` |
| Test strategy exists? | `test/<topic>.md` |
| ML model details? | `reference/ml-models-reference.md` |
| Adding a new airport? | `reference/adding-new-airport.md` |
| Calibration system status? | `reference/calibration-status.md` |
| Architecture rationale? | `research/ARCHITECTURE.md` |
| Known domain pitfalls? | `research/PITFALLS.md` |
| Tech stack decisions? | `research/STACK.md` |
| UX/code quality issues? | `audits/` |
| Validation coverage gaps? | `validation-gaps/` |

## File naming conventions

- `fix-*` — bug investigation + resolution
- `<nn>-*` (numbered) — planned feature or fix (execution order)
- `backlog-*` or unnumbered in backlog/ — proposed but not yet planned
- `test-plan-*` or in `test/` — verification strategy

## Frontmatter fields

```yaml
---
status: done | active | backlog | archived
area: simulation | frontend | ml | pipeline | deployment | data | ux | infrastructure
related: [sibling-file.md]
---
```

Use these for targeted searches:
```bash
grep -rl "area: simulation" .planning/
grep -rl "status: active" .planning/
grep -rl "related:.*go-around" .planning/
```

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `research/` | Pre-build research: architecture, stack, pitfalls, calibration data strategy |
| `milestones/` | 5-phase build (all complete): data foundation → platform demo |
| `features/` | Implemented feature plans with PLAN.md, RESEARCH.md, SUMMARY.md |
| `fixes/` | Bug investigations: root cause, fix approach, verification |
| `backlog/` | Future work: proposed features, improvements, integrations |
| `test/` | Test plans, validation strategies, diagnostic reports |
| `audits/` | Code reviews, UX audits, quality assessments |
| `reference/` | Living reference docs: ML models, calibration, airport onboarding |
| `validation-gaps/` | Known gaps in test/validation coverage |
