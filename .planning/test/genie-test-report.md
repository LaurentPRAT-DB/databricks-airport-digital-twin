# Genie Chat — Test Report

**Date:** 2026-03-24
**Version:** v0.1.0, Build #349
**Tester:** Claude Code (automated + manual)
**Environment:** Local dev (localhost:3004 + localhost:8000) + Deployed Databricks App

---

## 1. Unit Test Results

### GenieChat Component Tests — 27/27 PASSED

| # | Test | Suite | Status |
|---|------|-------|--------|
| 1 | Renders the floating action button | FAB Button | PASS |
| 2 | FAB has correct title | FAB Button | PASS |
| 3 | Opens chat panel when FAB is clicked | Panel toggle | PASS |
| 4 | Hides FAB when panel is open | Panel toggle | PASS |
| 5 | Closes panel when close button is clicked | Panel toggle | PASS |
| 6 | Shows sample questions when no messages | Empty state | PASS |
| 7 | Shows prompt text | Empty state | PASS |
| 8 | Renders input field | Input | PASS |
| 9 | Input accepts text | Input | PASS |
| 10 | Send button is disabled when input is empty | Input | PASS |
| 11 | Send button is enabled when input has text | Input | PASS |
| 12 | Displays user message after send | Sending messages | PASS |
| 13 | Displays assistant response | Sending messages | PASS |
| 14 | Sends to followup endpoint on second message | Sending messages | PASS |
| 15 | Shows error message when fetch fails | Error handling | PASS |
| 16 | Sends message when sample question is clicked | Sample questions | PASS |
| 17 | Shows link to Databricks Genie UI | Header actions | PASS |
| 18 | Shows result count when COMPLETED with data but no text_response | Response hardening | PASS |
| 19 | Shows no-results message when COMPLETED with SQL but 0 rows | Response hardening | PASS |
| 20 | Shows error message when FAILED with error field | Response hardening | PASS |
| 21 | Shows fallback when FAILED with no error and no text | Response hardening | PASS |
| 22 | Shows timeout message for TIMEOUT status | Response hardening | PASS |
| 23 | Shows permission denied for HTTP 403 | Response hardening | PASS |
| 24 | Shows service unavailable for HTTP 503 | Response hardening | PASS |
| 25 | Shows retry button on error and re-sends last question | Retry | PASS |
| 26 | Closes panel when Escape key is pressed | Keyboard shortcuts | PASS |
| 27 | Shows relative timestamps on messages | Timestamps | PASS |

### Full Frontend Suite — 806/806 PASSED

```
Test Files  33 passed (33)
Tests       806 passed (806)
Duration    26.38s
```

**Note:** The known flaky test ("switch to 3D and back to 2D", 750ms threshold) passed this run.

---

## 2. UI Feature Verification (Local Dev)

These were verified visually via Chrome DevTools screenshots.

| # | Feature | Expected | Actual | Status | Screenshot |
|---|---------|----------|--------|--------|------------|
| 1 | FAB button visible | Blue chat bubble, bottom-right | Visible at bottom-right | PASS | `01-fab-button.png` |
| 2 | Panel opens on FAB click | Slide-in from right with animation | Panel opens with slide-in transition | PASS | `02-panel-empty-state.png` |
| 3 | Empty state shows sample questions | 4 clickable sample questions + prompt text | All 4 shown with "Ask me anything" text | PASS | `02-panel-empty-state.png` |
| 4 | Error message with Retry button | Red bubble, user-friendly text, Retry link | "Access denied..." in red, Retry button present | PASS | `03-error-with-retry.png` |
| 5 | Message timestamps | "just now" on fresh messages | Both user and assistant show "just now" | PASS | `03-error-with-retry.png` |
| 6 | New conversation button | Appears after first message | "New conversation" (+) button visible in header | PASS | `03-error-with-retry.png` |
| 7 | Mobile responsive panel | Full-width on small screens | Panel uses full viewport width at 375px | PASS | `04-mobile-chat-panel.png` |
| 8 | Light mode styling | All elements respect light theme | White backgrounds, dark text, blue accents | PASS | `05-light-mode-chat.png` |
| 9 | Dark mode styling | All elements respect dark theme | Slate backgrounds, light text, blue accents | PASS | `03-error-with-retry.png` |
| 10 | Escape key closes panel | Panel closes on Escape keypress | Verified via unit test #26 | PASS | — |
| 11 | "Thinking" indicator | Shows "Thinking" text + bounce dots while loading | Verified via code review (visible during API call) | PASS | — |
| 12 | External Genie link | Opens Databricks Genie UI in new tab | Link present in header, correct URL | PASS | `02-panel-empty-state.png` |

---

## 3. Live Genie API Tests (Requires Databricks)

These tests require the **deployed Databricks App** with authenticated OBO token.
**App URL:** `https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com`
**Genie Space ID:** `01f12612fa6314ae943d0526f5ae3a00`

### Prerequisites
- User must be logged in via Databricks SSO
- User must have `CAN_RUN` permission on the Genie Space
- SQL warehouse must be running

### Test Matrix

| # | Question | Expected Behavior | Verify |
|---|----------|-------------------|--------|
| T1 | "How many flights are approaching KJFK right now?" | SQL + data table with flight count | Response shows number, SQL expandable, data table present |
| T2 | "Which gates are most used in the last 6 hours?" | SQL + data table with gate list | Multiple rows, gate names and counts visible |
| T3 | "Show me all flights at KSFO by phase" | SQL + data table grouped by phase | Phase names (approach, taxi, parked, etc.) in results |
| T4 | "Average turnaround time by aircraft type today" | SQL + data table with averages | Aircraft types and numeric averages |
| T5 | "What is the meaning of life?" | Graceful text response or polite decline | NOT "Status: FAILED" — should show text explanation |
| T6 | "asdfghjkl" (gibberish) | Graceful failure with helpful message | NOT "Status: FAILED" — user-friendly message |
| T7 | Follow-up: Ask T1, then "break that down by airline" | Uses `/followup` endpoint, shows follow-up result | Second message uses existing conversation_id |
| T8 | Disconnect network, then ask | "Failed to connect to the assistant..." + Retry button | Retry button re-sends after reconnect |

### Response Handling Verification

For each successful Genie response, verify:

| Check | What to verify |
|-------|---------------|
| **Text response** | Assistant message shows Genie's natural language answer |
| **SQL block** | "SQL Query" expandable link appears; clicking shows formatted SQL |
| **Data table** | Column headers match query; data rows are populated |
| **Row count badge** | Shows "N rows" above the table |
| **"Showing X of Y"** | If >10 rows, truncation message + "View all in Genie" link |
| **Timestamp** | "just now" appears below the message |
| **Follow-up routing** | First message → `/api/genie/ask`; subsequent → `/api/genie/followup` |

### Error Scenario Verification

| Scenario | How to reproduce | Expected message |
|----------|-----------------|------------------|
| No auth (local dev) | Run locally without Databricks token | "Access denied. You may not have permission..." |
| 403 Forbidden | User without `CAN_RUN` permission | "Access denied. You may not have permission..." |
| 503 Service unavailable | Backend cannot reach Databricks | "The assistant service is not available..." |
| Network error | Disable network/block API calls | "Failed to connect to the assistant..." + Retry |
| Timeout | Very complex query exceeding 120s | "The query took too long..." |
| Empty result | "Show flights to Antarctica" | "The query ran successfully but returned no results..." |

---

## 4. Files Modified

| File | Changes |
|------|---------|
| `app/backend/api/genie.py` | Hardened `followup_genie` to catch exceptions and return `GenieResponse` instead of raising HTTPException; added fallback `text_response` for FAILED/CANCELLED/TIMEOUT statuses |
| `app/frontend/src/components/GenieChat/GenieChat.tsx` | Added `getAssistantContent()` for status-specific fallbacks; `getHttpErrorContent()` for HTTP errors; `formatRelativeTime()` for timestamps; Escape key handler; Retry button; "Thinking" loading text; mobile responsive `w-full sm:w-[400px]`; slide-in animation; row count badge; no-results blue styling |
| `app/frontend/src/components/GenieChat/GenieChat.test.tsx` | Added 10 new test cases for response hardening, retry, Escape key, timestamps |

---

## 5. Screenshots Index

| File | Description |
|------|-------------|
| `01-fab-button.png` | Main app with FAB chat button visible (bottom-right) |
| `02-panel-empty-state.png` | Chat panel open, showing sample questions and empty state |
| `03-error-with-retry.png` | Error response with "Access denied" message, Retry button, timestamps |
| `04-mobile-chat-panel.png` | Mobile viewport (375px) — panel uses full width |
| `05-light-mode-chat.png` | Light mode theme — all elements styled correctly |

---

## 6. Known Issues / Notes

1. **Local dev cannot test live Genie**: The Genie API requires Databricks OBO authentication, which is only available when running as a Databricks App. Local dev correctly shows "Access denied" error.
2. **Code reverted to pre-hardening state**: The user's linter/editor reverted `GenieChat.tsx`, `GenieChat.test.tsx`, and `genie.py` to their original versions (before the hardening changes). The hardened code needs to be re-applied before deploying.
3. **Known flaky test**: `App.e2e.test.tsx` > "switch to 3D and back to 2D" has a 750ms timing threshold that occasionally fails. Not related to Genie.

---

## 7. Recommendation

- **Deploy the hardened code** to the Databricks App and run tests T1-T8 from the live test matrix above
- **Grant `CAN_RUN`** permission on the Genie Space to all target users before testing
- **Verify SQL warehouse** is running before live tests (auto-starts but may take 1-2 min)
