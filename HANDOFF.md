# NexusReach Handoff

## Completed in this pass
- Added safe batch email drafting from a People shortlist.
  - People page now supports multi-select with a max of 10 contacts.
  - Selected contacts navigate into Messages via `mode=batch`, `person_ids`, and optional `job_id`.
- Added backend batch APIs.
  - `POST /api/messages/batch-draft`
  - `POST /api/email/stage-drafts`
- Batch drafting now:
  - deduplicates selections
  - skips recent contacts by default
  - allows verified and best-guess emails
  - skips contacts with no usable email
  - returns per-item `ready`, `skipped`, or `failed` results with reasons
- Batch staging now:
  - stages drafts sequentially through Gmail or Outlook
  - continues after partial failures
  - sets `Message.status = "staged"`
  - creates outreach logs only for successfully staged drafts
- Messages page now has a batch review mode.
  - shows one review card per contact
  - supports per-row edit, regenerate, deselect
  - supports recent-contact override from the review queue
  - stages only the drafts the user explicitly selects
- Added route/UI/tests coverage for the new batch flow.
- Updated `lessons.md`.

## Files changed in this pass
- `backend/app/routers/email.py`
- `backend/app/routers/messages.py`
- `backend/app/schemas/email.py`
- `backend/app/schemas/messages.py`
- `backend/app/services/draft_staging_service.py`
- `backend/app/services/message_service.py`
- `backend/tests/test_email_api.py`
- `backend/tests/test_messages_api.py`
- `frontend/src/hooks/useEmail.ts`
- `frontend/src/hooks/useMessages.ts`
- `frontend/src/pages/MessagesPage.tsx`
- `frontend/src/pages/PeoplePage.tsx`
- `frontend/src/pages/__tests__/MessagesPage.test.tsx`
- `frontend/src/pages/__tests__/PeoplePage.test.tsx`
- `frontend/src/types/index.ts`
- `HANDOFF.md`
- `lessons.md`

## Verification completed
- `cd backend && ruff check app tests conftest.py`
- `cd backend && pytest`
  - result: `485 passed`
- `cd frontend && npx eslint .`
- `cd frontend && npx tsc -b`
- `cd frontend && npm run test`
  - result: `96 passed`
- `cd frontend && npm run build`

## Remaining caveats
- Batch mode is email-only in v1. LinkedIn note/message batching is still not implemented.
- The batch review queue is driven by query-param handoff from People. There is no persisted “campaign” object yet.
- Deselecting a contact inside batch mode updates the local queue only; it does not rewrite the URL query string.
- Shared or deployed environments do not need a migration for this pass, but they do need the updated backend/frontend code together because both new endpoints are used by the new UI flow.

## Suggested next manual check
- In People, select 3-5 contacts with mixed email states.
- Start batch drafts and confirm:
  - ready rows show individualized drafts
  - no-email and recent-contact rows show explicit skip reasons
  - `Include Anyway` only affects the targeted recent-contact row
  - staging selected drafts marks them `staged` and creates outreach entries only for the staged subset
