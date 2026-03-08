# Development Philosophy & Best Practices

**Author:** Laurent Prat
**Last Updated:** 2026-03-08
**Purpose:** Define how I build software, capturing patterns and practices for consistency and AI-assisted development.

---

## Core Principles

### 1. Iterative & Incremental Development
- Build features in small, testable increments
- Validate each increment before moving to the next
- Prefer working software over comprehensive planning
- Ship early, iterate often

### 2. Demo-First Mindset
- Build for demonstrability - every feature should be visually impressive
- Use synthetic data generation to create realistic scenarios without external dependencies
- Prioritize UI/UX polish - first impressions matter for demos

### 3. Pragmatic Engineering
- Solve the problem at hand, don't over-engineer
- Technical debt is acceptable when time-constrained - document it for later
- Perfect is the enemy of good - ship it, then improve

---

## Architecture Patterns

### Backend (Python/FastAPI)
```
app/backend/
├── api/routes.py          # All API endpoints, thin layer
├── models/                # Pydantic models for validation
│   └── {feature}.py       # One file per domain
├── services/              # Business logic layer
│   └── {feature}_service.py
└── main.py                # FastAPI app setup
```

**Principles:**
- Routes are thin - delegate to services
- Services contain business logic
- Models define data contracts (Pydantic for validation)
- Synthetic generators live in `src/ingestion/` or `src/ml/`

### Frontend (React/TypeScript)
```
app/frontend/src/
├── components/            # Feature-based organization
│   └── {Feature}/
│       └── {Feature}.tsx  # Self-contained component
├── context/               # React Context for global state
├── hooks/                 # Custom hooks for data fetching
├── config/                # Configuration and constants
└── types/                 # TypeScript interfaces
```

**Principles:**
- Components are self-contained with their own state management
- Use Context for cross-component state (e.g., selected flight)
- Hooks encapsulate API calls and caching logic
- Tailwind CSS for styling - no separate CSS files

### Data Flow
```
User Action → Component → Context/Hook → API Call → Service → Generator/DB
                 ↑                                              ↓
                 └──────────────── Response ←──────────────────┘
```

---

## Development Workflow

### 1. Feature Implementation
```
1. Understand requirements (ask clarifying questions)
2. Design data model first (Pydantic models)
3. Build backend (generator → service → routes)
4. Build frontend (component with mock data → connect to API)
5. Test manually via UI
6. Write automated tests
7. Commit with descriptive message
```

### 2. Commit Strategy
- **Atomic commits**: One logical change per commit
- **Descriptive messages**: Follow conventional commits format
  ```
  feat(scope): add new feature
  fix(scope): fix bug description
  docs: update documentation
  test: add/update tests
  refactor: code restructuring
  ```
- **Co-author AI**: Always credit AI assistance
  ```
  Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
  ```

### 3. Testing Strategy

**API Tests (pytest)**
- Test happy path first
- Test edge cases (empty inputs, invalid params)
- Test error responses
- Performance tests for synthetic generators

**UI Tests (Chrome DevTools MCP)**
- Create numbered test plan in markdown
- Test visual elements render correctly
- Test user interactions (click, type, navigate)
- Test state changes (selection, filtering)
- Check for console errors

### 4. Documentation
- **Implementation Reports**: Document what was built, by whom, time taken
- **Debugging Guides**: curl commands, common issues, solutions
- **Extension Guides**: How to add features, integrate with external APIs
- **Architecture Diagrams**: ASCII art for quick understanding

---

## AI-Assisted Development

### When to Use AI Agents
- **Explore agent**: Codebase research, finding patterns
- **Parallel agents**: Independent tasks (e.g., 4 features simultaneously)
- **Direct implementation**: When context is clear and task is focused

### Effective AI Prompting
1. **Be specific**: Include file paths, function names, expected behavior
2. **Provide context**: Share relevant code snippets, error messages
3. **Iterate**: Start broad, refine based on results
4. **Trust but verify**: Review AI-generated code before committing

### AI Limitations Learned
- Agent teams work better with smaller, focused tasks
- Provide complete context in prompts (don't assume agents remember)
- Consider worktree isolation for parallel file edits
- Agents may go idle - this is normal, send follow-up messages

---

## Technology Stack Preferences

### Python
- **Package manager**: `uv` (not pip)
- **Testing**: `pytest` with fixtures
- **API framework**: FastAPI with Pydantic
- **Database**: Databricks Delta tables via Unity Catalog

### JavaScript/TypeScript
- **Framework**: React with TypeScript
- **Styling**: Tailwind CSS
- **3D**: Three.js with React Three Fiber
- **Build**: Vite

### Deployment
- **Always use DABs** (Databricks Asset Bundles)
- **Profile**: Use workspace-specific profiles
- Build frontend before deploying: `npm run build`
- Deploy with: `databricks bundle deploy --target {env}`

### Infrastructure
- **Databricks Apps (APX)**: FastAPI + React in single deployment
- **Unity Catalog**: For data governance and access
- **Lakebase**: For low-latency serving when needed

---

## Code Quality Standards

### Naming Conventions
- **Files**: snake_case for Python, PascalCase for React components
- **Functions**: snake_case (Python), camelCase (TypeScript)
- **Components**: PascalCase
- **Constants**: SCREAMING_SNAKE_CASE

### Code Style
- **Python**: Follow PEP 8, use type hints
- **TypeScript**: Strict mode, explicit types for props
- **Comments**: Only when logic isn't self-evident
- **No dead code**: Delete unused code, don't comment it out

### Error Handling
- **Backend**: Return proper HTTP status codes with error messages
- **Frontend**: Show user-friendly error states, log details to console
- **APIs**: Validate inputs with Pydantic, return structured errors

---

## Project Structure

### Monorepo Layout
```
project/
├── app/
│   ├── backend/           # FastAPI application
│   └── frontend/          # React application
├── src/
│   ├── ingestion/         # Data generators
│   └── ml/                # ML models and predictions
├── tests/                 # Python tests
├── docs/                  # Documentation
├── databricks.yml         # DABs configuration
└── CLAUDE.md              # AI assistant instructions
```

### Key Files
- `CLAUDE.md`: Instructions for AI assistants
- `dev.sh`: Local development script
- `app.yaml`: Databricks App configuration
- `databricks.yml`: Asset bundle definition

---

## Decision Log Template

When making architectural decisions, document:

```markdown
## Decision: [Title]
**Date:** YYYY-MM-DD
**Status:** Accepted/Superseded/Deprecated

### Context
What is the issue that we're seeing that is motivating this decision?

### Decision
What is the change that we're proposing and/or doing?

### Consequences
What becomes easier or more difficult because of this change?
```

---

## TODO / Future Best Practices to Define

- [ ] Error boundary patterns for React
- [ ] Caching strategies (React Query vs. manual)
- [ ] Performance optimization guidelines
- [ ] Security best practices (input validation, auth)
- [ ] Monitoring and observability patterns
- [ ] CI/CD pipeline standards
- [ ] Code review checklist
- [ ] Accessibility (a11y) requirements

---

*This document is a living artifact - update it as practices evolve.*
