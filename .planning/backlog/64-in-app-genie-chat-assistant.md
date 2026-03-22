# In-App Genie Chat Assistant

## Context

The Airport Operations Genie Space (`01f12612fa6314ae943d0526f5ae3a00`) was just created with 7 tables. The user wants an in-app chat UI so airport operators can ask natural language questions without leaving the app. Currently the "Platform > Airport Ops Genie" link opens the Databricks workspace in a new tab — we want a native chat experience inside the app.

## Architecture

```
Frontend (React)               Backend (FastAPI)              Databricks
┌─────────────────┐           ┌─────────────────┐           ┌─────────────┐
│ GenieChat.tsx    │──POST──→ │ /api/genie/ask   │──REST──→  │ Genie API   │
│ (floating FAB + │           │ /api/genie/      │           │ Conversation│
│  chat panel)    │←──JSON──  │  followup        │←──JSON──  │ API         │
└─────────────────┘           └─────────────────┘           └─────────────┘
```

---

## Files to Create/Modify

### Backend (2 files)

**1. NEW: `app/backend/api/genie.py`** — Genie proxy router

- `POST /api/genie/ask` — Start new conversation (proxies to `POST /api/2.0/genie/spaces/{space_id}/start-conversation`)
- `POST /api/genie/followup` — Follow-up in existing conversation (proxies to `POST /api/2.0/genie/spaces/{space_id}/conversations/{conv_id}/messages`)
- Uses `_make_workspace_client` pattern from `simulation.py` (OBO auth with user's Bearer token)
- Polls for completion (Genie API is async — returns statement, need to poll get-message)
- Returns: `{ question, conversation_id, message_id, status, sql, columns, data, row_count, text_response, error }`
- Space ID from env var `GENIE_SPACE_ID` (default: `01f12612fa6314ae943d0526f5ae3a00`)

**2. MODIFY: `app/backend/main.py`** — Register the genie router

- Add `from app.backend.api.genie import genie_router`
- Add `app.include_router(genie_router)`

### Frontend (3 files)

**3. NEW: `app/frontend/src/components/GenieChat/GenieChat.tsx`** — Chat component

- Floating action button (bottom-right) with assistant icon
- Click toggles a chat panel (400px wide, full height minus header)
- Chat messages: user bubbles (right) + assistant bubbles (left)
- Input bar with send button at bottom
- Shows: text response, SQL query (collapsible), data table (if rows returned)
- Maintains `conversation_id` for follow-ups within same session
- Loading state with typing indicator while waiting for Genie
- Sample questions shown as clickable chips when chat is empty
- Dark/light mode via Tailwind `dark:` classes (uses ThemeContext)
- "New conversation" button to reset

**4. NEW: `app/frontend/src/components/GenieChat/GenieChat.test.tsx`** — Tests

- Renders FAB button
- Opens/closes chat panel
- Sends message and displays response
- Shows sample questions on empty state
- Handles error states

**5. MODIFY: `app/frontend/src/App.tsx`** — Add GenieChat to the layout

- Import and render `<GenieChat />` after the main layout (it's `position:fixed`, so placement doesn't matter structurally)

### Config

**6. MODIFY: `app.yaml`** — Add `GENIE_SPACE_ID` env var (for deployed app)

---

## Backend API Detail

### POST /api/genie/ask

```
Request:  { "question": "How many flights landing at KJFK?" }
Response: {
  "conversation_id": "...", "message_id": "...",
  "status": "COMPLETED",
  "sql": "SELECT ...",
  "columns": ["count"], "data": [[42]], "row_count": 1,
  "text_response": null
}
```

### POST /api/genie/followup

```
Request:  { "conversation_id": "...", "question": "Break that down by terminal" }
Response: { same shape as above }
```

### Genie REST API flow (what the backend does)

1. `POST /api/2.0/genie/spaces/{space_id}/start-conversation` with `{"content": "..."}` → returns `conversation_id` + `message_id`
2. Poll `GET /api/2.0/genie/spaces/{space_id}/conversations/{conv_id}/messages/{msg_id}` until status != `EXECUTING`
3. Parse attachments for SQL query and result data
4. Return normalized response to frontend

For follow-ups: `POST /api/2.0/genie/spaces/{space_id}/conversations/{conv_id}/messages` with `{"content": "..."}`

---

## Frontend Chat UI Detail

- **FAB:** 48px circle, bottom-right corner (16px margin), blue-600 bg, chat bubble SVG icon
- **Panel:** Fixed position, right-0, top-[header-height] to bottom-0, 400px wide, slide-in animation
- **Messages:** Scrollable area, auto-scroll to bottom on new messages
- **Data display:** When Genie returns data, show as a compact table (max 10 rows, "show more" link to full Genie UI)
- **SQL display:** Collapsible code block with syntax highlighting (monospace)
- **Sample questions:** 4 chips from the Genie Space config, clickable to send

---

## Verification

1. `cd app/frontend && npm test -- --run` — all tests pass including new GenieChat tests
2. `uv run pytest tests/ -v -k genie` — backend genie route tests pass
3. Manual: `./dev.sh` → click FAB → type question → see response with SQL + data
4. Manual: verify follow-up questions work (conversation context maintained)
5. Manual: verify dark/light mode styling
