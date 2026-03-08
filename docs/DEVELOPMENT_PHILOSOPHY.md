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

## Security Best Practices

### OWASP Top 10 Awareness

| Vulnerability | Prevention | Status |
|---------------|------------|--------|
| **SQL Injection** | Parameterized queries (`:param` syntax) | Implemented |
| **XSS** | React auto-escapes, no `dangerouslySetInnerHTML` | Implemented |
| **CSRF** | Restrict CORS origins in production | TODO |
| **Broken Auth** | Implement OAuth2/API keys | TODO |
| **Sensitive Data** | Use Databricks Secrets, not env vars | TODO |
| **Security Misconfig** | Remove debug endpoints in prod | TODO |
| **Injection** | Validate all inputs with Pydantic | Implemented |

### Backend Security (FastAPI)

**1. SQL Injection Prevention**
```python
# NEVER do this:
query = f"SELECT * FROM table WHERE id = '{user_input}'"

# ALWAYS do this:
query = "SELECT * FROM table WHERE id = :id"
cursor.execute(query, {"id": user_input})
```

**2. Input Validation**
```python
from fastapi import Path, Query
from pydantic import BaseModel, Field, validator

# Path parameters - use regex constraints
@router.get("/flights/{icao24}")
async def get_flight(
    icao24: str = Path(..., regex="^[a-f0-9]{6}$", description="ICAO24 hex address")
):
    ...

# Query parameters - use bounds
@router.get("/flights")
async def get_flights(
    limit: int = Query(default=100, ge=1, le=1000),
    minutes: int = Query(default=60, ge=1, le=1440)
):
    ...

# Request body - use Pydantic with validators
class FlightRequest(BaseModel):
    callsign: str = Field(..., min_length=1, max_length=8)
    altitude: float = Field(..., ge=-1000, le=60000)

    @validator('callsign')
    def callsign_alphanumeric(cls, v):
        if not v.replace(' ', '').isalnum():
            raise ValueError('Callsign must be alphanumeric')
        return v.upper().strip()
```

**3. CORS Configuration**
```python
# Development (permissive)
allow_origins=["*"]  # OK for local dev only

# Production (restrictive)
allow_origins=[
    "https://your-app.databricksapps.com",
    "https://your-domain.com"
]
allow_credentials=True  # Only with specific origins, NEVER with "*"
```

**4. Authentication Patterns**
```python
from fastapi.security import HTTPBearer, OAuth2PasswordBearer
from fastapi import Depends, HTTPException, status

# Option 1: API Key (simple)
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid API key")

# Option 2: OAuth2 Bearer Token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    # Validate token with your auth provider
    ...

# Apply to routes
@router.get("/protected", dependencies=[Depends(verify_api_key)])
async def protected_route():
    ...
```

**5. Rate Limiting**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/flights")
@limiter.limit("100/minute")
async def get_flights(request: Request):
    ...
```

### Frontend Security (React)

**1. XSS Prevention**
```typescript
// React auto-escapes by default - this is safe:
<div>{userInput}</div>

// NEVER do this unless content is trusted:
<div dangerouslySetInnerHTML={{__html: userInput}} />

// If you must render HTML, sanitize first:
import DOMPurify from 'dompurify';
<div dangerouslySetInnerHTML={{__html: DOMPurify.sanitize(userInput)}} />
```

**2. URL Handling**
```typescript
// Validate URLs before using
const isValidUrl = (url: string): boolean => {
  try {
    const parsed = new URL(url);
    return ['http:', 'https:'].includes(parsed.protocol);
  } catch {
    return false;
  }
};

// Never construct URLs from user input without validation
const safeNavigate = (path: string) => {
  if (path.startsWith('/') && !path.includes('//')) {
    navigate(path);
  }
};
```

**3. Sensitive Data Handling**
```typescript
// Never log sensitive data
console.log('User:', user.name);  // OK
console.log('Token:', token);     // NEVER

// Clear sensitive data when unmounting
useEffect(() => {
  return () => {
    setAuthToken(null);
  };
}, []);
```

**4. Content Security Policy**
```html
<!-- In index.html or via headers -->
<meta http-equiv="Content-Security-Policy"
      content="default-src 'self';
               script-src 'self';
               style-src 'self' 'unsafe-inline';
               img-src 'self' data: https:;
               connect-src 'self' https://api.example.com;">
```

### Secrets Management

**1. Never Commit Secrets**
```gitignore
# .gitignore
.env
.env.local
.env.*.local
*.pem
*.key
credentials.json
```

**2. Use Databricks Secrets**
```python
# Instead of environment variables:
token = os.getenv("API_TOKEN")  # Visible in process list

# Use Databricks Secrets:
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
token = w.dbutils.secrets.get("scope-name", "api-token")
```

**3. Rotate Credentials Regularly**
- API keys: Every 90 days
- Service accounts: Every 180 days
- After any security incident: Immediately

### Security Checklist (Pre-Deployment)

```markdown
## Security Review Checklist

### Authentication & Authorization
- [ ] All sensitive endpoints require authentication
- [ ] CORS configured for specific origins (not "*" in prod)
- [ ] API keys/tokens not hardcoded
- [ ] Debug endpoints disabled or protected

### Input Validation
- [ ] All user inputs validated with Pydantic
- [ ] SQL queries use parameterized statements
- [ ] File paths validated (no path traversal)
- [ ] URL parameters have type/range constraints

### Data Protection
- [ ] Secrets stored in Databricks Secrets (not env vars)
- [ ] No sensitive data in logs
- [ ] HTTPS enforced (handled by Databricks Apps)
- [ ] Sensitive data encrypted at rest

### Frontend
- [ ] No `dangerouslySetInnerHTML` with user content
- [ ] No sensitive data in localStorage
- [ ] CSP headers configured
- [ ] Dependencies audited (`npm audit`)

### Infrastructure
- [ ] Rate limiting enabled
- [ ] WebSocket connection limits set
- [ ] Error messages don't leak internal details
- [ ] Health check endpoints don't expose sensitive info
```

### Security Audit Process

Run periodic security audits:

```bash
# Python dependencies
uv pip audit

# JavaScript dependencies
cd app/frontend && npm audit

# Check for secrets in git history
git secrets --scan-history

# Static analysis
bandit -r app/backend/
```

**Reference:** See `SECURITY_AUDIT.md` for detailed vulnerability assessment.

---

## TODO / Future Best Practices to Define

- [ ] Error boundary patterns for React
- [ ] Caching strategies (React Query vs. manual)
- [ ] Performance optimization guidelines
- [x] Security best practices (input validation, auth) - **Added**
- [ ] Monitoring and observability patterns
- [ ] CI/CD pipeline standards
- [ ] Code review checklist
- [ ] Accessibility (a11y) requirements

---

*This document is a living artifact - update it as practices evolve.*
