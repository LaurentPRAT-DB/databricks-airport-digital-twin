# Genie Chat — Response Hardening & UI Improvements

## Context

The Genie chat feature (FAB + panel) is live and working end-to-end. However, there are edge cases where the user gets unhelpful responses like "Status: FAILED" or "Query completed." with no additional context. The UI also lacks polish — no slide-in animation, no message timestamps, no retry capability, and no visual distinction between different response types (text-only, SQL+data, no-results, errors). This plan hardens the response handling and improves the chat UX.

---

## Analysis of Current Gaps

### Response Handling Gaps (line 109 of GenieChat.tsx)

```typescript
content: data.text_response || (data.status === 'COMPLETED' ? 'Query completed.' : `Status: ${data.status}`)
```

This fallback chain produces poor UX in these scenarios:

| Scenario | Current Output | Desired Output |
|----------|---------------|----------------|
| COMPLETED, no text, SQL+data returned | "Query completed." | "Here are the results:" (with table) |
| COMPLETED, no text, SQL but 0 rows | "Query completed." | "The query returned no results. Try rephrasing your question." |
| FAILED, no text, no error | "Status: FAILED" | "I couldn't answer that question. Try rephrasing or ask something else." |
| FAILED, error field set | "Status: FAILED" (error ignored!) | Show the error message with red styling |
| TIMEOUT | "Status: TIMEOUT" | "The query took too long. Try a simpler question." |
| CANCELLED | "Status: CANCELLED" | "The query was cancelled." |
| HTTP error (non-200 from backend) | "Failed to connect to Genie." | Distinguish 403 (permissions) vs 502 (Genie down) vs 503 (no auth) |
| text_response is null, status UNKNOWN | "Status: UNKNOWN" | "Something went wrong. Please try again." |

### Backend Gaps (`genie.py`)

- `_genie_api` raises HTTPException on 4xx/5xx — frontend catches as generic network error, loses the detail
- `_parse_message_response` doesn't set `text_response` when FAILED with no content
- No fallback `text_response` for any terminal status — relies entirely on frontend

### Missing UI Polish

- No slide-in animation when panel opens
- No message timestamps shown
- No retry button on failed messages
- No "Genie is thinking..." text alongside bounce dots
- No visual row count badge on data tables
- Sample questions disappear after first message (can't access later)
- No keyboard shortcut to open/close (Escape to close)
- Mobile: panel is 400px fixed width — overflows on small screens

---

## Files to Modify

### 1. `app/frontend/src/components/GenieChat/GenieChat.tsx`

**Response content hardening** — Replace the single-line fallback with a proper `getAssistantContent()` function:

```typescript
function getAssistantContent(data: GenieApiResponse): string {
  // 1. If Genie provided text, use it
  if (data.text_response) return data.text_response;

  // 2. Status-specific fallbacks
  switch (data.status) {
    case 'COMPLETED':
      if (data.data && data.data.length > 0) return `Found ${data.row_count} result${data.row_count !== 1 ? 's' : ''}:`;
      if (data.sql) return 'The query ran successfully but returned no results. Try broadening your question.';
      return 'Query completed.';
    case 'FAILED':
      return data.error || 'I couldn\'t answer that question. Try rephrasing or ask something else.';
    case 'TIMEOUT':
      return 'The query took too long to complete. Try a simpler question or try again later.';
    case 'CANCELLED':
      return 'The query was cancelled.';
    default:
      return data.error || 'Something unexpected happened. Please try again.';
  }
}
```

**HTTP error handling** — Check `res.ok` before parsing JSON; parse error detail from backend response:

```typescript
if (!res.ok) {
  const errorData = await res.json().catch(() => null);
  const detail = errorData?.detail || `Server error (${res.status})`;
  if (res.status === 403) content = 'Access denied. You may not have permission to use the assistant.';
  else if (res.status === 503) content = 'The assistant service is not available. Please try again later.';
  else content = `Error: ${detail}`;
}
```

**UI Improvements:**

- **Slide-in animation:** Add `translate-x-full` -> `translate-x-0` transition on panel mount (CSS transition with state)
- **Escape to close:** Add `useEffect` with keydown listener for Escape key
- **Retry button:** On error messages, add a small "Retry" button that re-sends the last user message
- **Thinking text:** Change bounce dots to include "Thinking..." label
- **Timestamps:** Show relative time (e.g., "just now", "2m ago") on messages
- **Mobile responsive:** Use `w-full sm:w-[400px]` instead of fixed `w-[400px]`
- **No-results state:** When SQL completes with 0 rows, show a distinct info-style message (blue bg, not grey)

### 2. `app/backend/api/genie.py`

**Ensure `text_response` is always set** — Add fallback in `_parse_message_response` and `_poll_message`:

```python
# In _parse_message_response, after parsing:
if not result.text_response:
    if status == "FAILED":
        result.text_response = "Genie could not process this question."
    elif status == "CANCELLED":
        result.text_response = "The query was cancelled."
```

**Don't raise HTTPException for Genie 4xx** — Instead, return a `GenieResponse` with error field set, so the frontend can display it properly:

```python
# In ask_genie and followup_genie, catch HTTPException from _genie_api
# and convert to GenieResponse with status=FAILED and error=detail
```

### 3. `app/frontend/src/components/GenieChat/GenieChat.test.tsx`

Add new test cases:

- COMPLETED with data but no text -> shows "Found N results:"
- COMPLETED with SQL but 0 rows -> shows no-results message
- FAILED status with error -> shows error in red bubble
- FAILED status without error -> shows fallback message
- TIMEOUT status -> shows timeout message
- HTTP 403 response -> shows permission denied message
- HTTP 503 response -> shows service unavailable message
- Retry button appears on error -> clicking retry re-sends last question
- Escape key closes panel
- Mobile width -> panel uses full width

---

## Verification

1. `cd app/frontend && npm test -- --run` — all existing + new tests pass
2. Manual test matrix against live Genie Space:

| # | Question | Expected Behavior |
|---|----------|-------------------|
| 1 | "How many flights are approaching KJFK right now?" | SQL + data table with count |
| 2 | "Which gates are most used in the last 6 hours?" | SQL + data table with gate list |
| 3 | "Show me all flights at KSFO by phase" | SQL + data table grouped by phase |
| 4 | "Average turnaround time by aircraft type today" | SQL + data table |
| 5 | "What is the meaning of life?" | Graceful failure — "I couldn't answer..." or clarification request |
| 6 | "asdfghjkl" | Graceful failure — not "Status: FAILED" |
| 7 | Follow-up: Ask Q1, then "break that down by airline" | Uses /followup endpoint, shows follow-up result |
| 8 | Network offline | "Failed to connect to Genie. Please try again." with retry button |

3. Verify mobile layout: resize browser to 375px width, panel should be full-width
4. Verify dark mode: toggle theme, all chat elements should respect `dark:` classes
5. Verify Escape key closes the panel
