# NexusReach — Lessons Learned

A living document of patterns, gotchas, and decisions encountered while building NexusReach. Updated as new lessons are discovered.

---

## Architecture

### PostgreSQL-specific types require careful test strategy
- Models use `UUID(as_uuid=True)`, `ARRAY(String)`, and `JSONB` — all PostgreSQL-only.
- **Lesson:** Can't use SQLite in-memory for integration tests without type adaptation.
- **Decision:** Mock the service layer for API tests, test pure functions directly.

### Dependency injection via FastAPI `Depends` makes testing clean
- Auth, DB sessions, and other dependencies are injected via `Depends()`.
- Override them in tests with `app.dependency_overrides[dep] = mock_fn`.
- This pattern lets us bypass JWT validation, mock DB, etc.

### Service layer separation pays off
- Routers call services, services call clients. Three clear layers.
- Makes it easy to mock at the right boundary (mock services for API tests, mock clients for service tests).

---

## Testing

### Mock at the right boundary
- **API tests:** Mock service functions (e.g., `search_jobs`, `draft_message`). This tests route handling, request parsing, response formatting.
- **Unit tests:** Call pure functions directly with constructed inputs. No mocking needed.
- **Don't mock too deeply** — mocking the DB session for every test is fragile. Mock the service return value instead.

### pytest-asyncio `auto` mode simplifies async tests
- Setting `asyncio_mode = auto` in `pytest.ini` means you just write `async def test_*` without the `@pytest.mark.asyncio` decorator on every function.
- Still need `pytestmark = pytest.mark.asyncio` at module level for test files that use `client` fixture.

### Frontend tests need careful mock layering
- Components use hooks → hooks use `api.ts` → `api.ts` reads from Zustand store.
- Mock from the outside in: mock hooks for page-level tests, mock fetch for API client tests.
- Always mock `@supabase/supabase-js` to avoid initialization side effects.

### Vitest `globals: true` + setup file = clean test files
- With `globals: true` in vitest config, `describe`, `it`, `expect` are available without imports.
- Setup file (`src/test/setup.ts`) imports `@testing-library/jest-dom/vitest` for DOM matchers.

---

## External APIs

### Graceful degradation when API keys are missing
- All clients check for their API key first and return `[]` if missing (e.g., `jsearch_client`).
- **Pattern:** `if not settings.api_key: return []` — never crash on missing config.

### Email finding waterfall handles partial data
- The waterfall (`Hunter → Proxycurl → Domain Search`) needs to handle cases where:
  - Person has no company domain (skip Hunter)
  - Person has no LinkedIn URL (skip Proxycurl)
  - Name can't be split into first/last (skip name-based lookups)
- **Lesson:** Each step must independently check its prerequisites.

### ATS board APIs are inconsistent
- Greenhouse returns JSON with `location.name`, Lever puts location at top-level.
- Ashby uses a GraphQL-like API with different field names.
- **Pattern:** Normalize to a common dict format in each client before returning.

---

## Frontend

### React 19 + TanStack Query works well for data fetching
- Mutations for writes (search, update), queries for reads (list, get).
- `invalidateQueries` on mutation success keeps UI in sync without manual refetching.

### Zustand for auth, TanStack Query for server state
- Auth state (user, session, tokens) belongs in Zustand — it's client-side state.
- Server data (jobs, people, messages) belongs in TanStack Query — it's cached server state.
- **Don't mix them** — putting server state in Zustand leads to stale data.

### shadcn/ui components need careful variant typing
- Badge `variant` only accepts specific values (`default`, `secondary`, `outline`, `destructive`).
- Use `Record<string, VariantType>` maps for dynamic variant selection.

---

## Backend

### Pydantic v2 `model_config = {"from_attributes": True}` replaces `orm_mode`
- In Pydantic v2, use `from_attributes = True` instead of the old `orm_mode = True`.
- Enables direct serialization from SQLAlchemy model instances.

### UUID-backed ORM fields should stay typed as `uuid.UUID` in response models
- If a SQLAlchemy model exposes `UUID(as_uuid=True)`, typing the Pydantic response field as `str` can trigger FastAPI `ResponseValidationError` when returning ORM objects directly.
- **Lesson:** Keep the schema field typed as `uuid.UUID` and let FastAPI serialize it to a JSON string on the wire.

### SQLAlchemy async requires `selectinload` for relationships
- Lazy loading doesn't work with async sessions.
- Always use `.options(selectinload(Model.relationship))` when you need related data.
- Forgetting this causes `greenlet` errors at runtime.

### Async service code should never rely on lazy relationship access
- In a live email-finding run, `person.company.domain` inside `email_finder_service.py` crashed with `sqlalchemy.exc.MissingGreenlet` because `company` was not eagerly loaded.
- **Lesson:** If an async service will touch related ORM data, load it in the original query rather than trusting implicit lazy loads.

### `exclude_unset=True` for partial updates
- `data.model_dump(exclude_unset=True)` only includes fields the client actually sent.
- Prevents overwriting existing values with `None` on partial updates.

---

## General

### Build in layers, test in layers
- Each phase builds on the previous one. Profile feeds into scoring, scoring feeds into jobs.
- Test each layer independently: pure functions first, then API endpoints with mocked services.

### Commit and push after every phase
- Small, atomic commits make rollback easier and code review clearer.
- Pattern: `Phase N: Feature Name — component 1, component 2, component 3`.

### Fingerprint-based deduplication is simple and effective
- MD5 hash of `company|title|location` (lowercased, stripped) catches duplicates across sources.
- Fast, deterministic, and handles the 90% case without fuzzy matching overhead.

### Alembic needs a real base revision for empty-database bootstrap
- A migration chain cannot start with `ALTER TABLE` operations against tables that have never been created.
- **Lesson:** Keep an explicit initial-schema revision in version control, and make extension requirements like `pgcrypto` idempotent inside the migration that uses them.

### ATS board clients should not silently truncate results by default
- Greenhouse, Lever, and Ashby public board endpoints already return full board payloads.
- **Lesson:** Default client behavior should preserve the full board and only apply limits when a caller asks for them explicitly, otherwise exact job handoff flows can fail before the UI ever sees the posting.

---

## Phase 7 Testing Insights

### `getByText` collisions in component pages with dropdowns + cards
- When a page renders both a dropdown (e.g., status filter, channel selector) and cards/badges with the same text values (e.g., "Sent", "Email", "LinkedIn Message"), `screen.getByText('Sent')` will fail with "multiple elements found."
- **Fix:** Use `screen.getAllByText('Sent').length` with `toBeGreaterThanOrEqual()` instead of `getByText`.
- **Alternative:** Use `within(container).getByText(...)` to scope queries to a specific DOM subtree.

### Test data values must be unique across the rendered page
- Stats card values like "12" can collide with computed totals (sum of `by_status` values). If `total_contacts = 12` and `sum(by_status) = 12`, `getByText('12')` finds two elements.
- **Fix:** Use distinct values (e.g., 42) that won't accidentally match other computed outputs.

### Mock state variables must be resettable between tests
- Module-level `let` variables for mock hook return values (e.g., `mockLogs`, `mockStats`) allow per-test overrides.
- **Pattern:** `beforeEach(() => { mockLogs = { data: undefined, isLoading: false }; })` resets to clean state.
- This avoids test coupling where one test's mock data leaks into the next.

### Response enrichment (_to_response) needs dedicated tests
- Router helpers that enrich API responses by joining related data (person name, company, job title) are easy to miss in tests.
- **Lesson:** Test with and without relationships (nulls, full data) to catch `getattr` / `None` access patterns.

### Partial update testing with `exclude_unset=True`
- When using `body.model_dump(exclude_unset=True)`, only fields the client sent are included.
- Test that sending `{"channel": "email"}` only passes `channel` to the service — no `status`, `notes`, etc.
- This prevents accidental overwriting of existing values with `None`.

### Node.js heap limits with heavy component tests
- ProfilePage (or components importing large libraries like Supabase) can OOM during vitest runs.
- **Workaround:** `NODE_OPTIONS="--max-old-space-size=4096"` or run heavy test files separately.
- Consider using `--pool=forks` to isolate worker memory.

---

## CI/CD & Linting (Phase 10)

### Always run linters locally before committing
- The CI pipeline runs `ruff check .` (backend) and `eslint .` + `tsc -b` + `vitest run` (frontend).
- **Lesson:** Running lint + build + tests locally before every push prevents CI failures. Added a `.githooks/pre-commit` hook to automate this.
- **Setup:** `git config core.hooksPath .githooks` to activate the shared hooks.

### ruff catches unused imports that Python silently ignores
- Python doesn't error on unused imports, but ruff (and CI) will.
- **Common offenders:** `uuid`, `AsyncMock`, `patch` — imported "just in case" during development.
- **Fix:** Run `ruff check --fix` to auto-remove unused imports before committing.
- **Also:** `conftest.py` is checked too — don't forget it's outside the `tests/` directory.

### SQLAlchemy forward references need `# noqa: F821`
- SQLAlchemy `relationship()` uses string forward references like `Mapped["Person"]` to avoid circular imports.
- ruff flags these as `F821 Undefined name` since the class isn't imported in that file.
- **Fix:** Add `# noqa: F821` to each relationship line. Don't use `from __future__ import annotations` — it can break SQLAlchemy's runtime type resolution.

### shadcn/ui v2 uses `@base-ui/react`, NOT Radix — different API
- The latest shadcn CLI generates components using `@base-ui/react` instead of `@radix-ui`.
- **Key API differences:**
  - **No `asChild` prop.** Use `render={<Component />}` instead. E.g., `<SheetTrigger render={<Button />}>` not `<SheetTrigger asChild>`.
  - **No `onInteractOutside` or `onEscapeKeyDown`** on DialogContent/Popup. Control dismissal via `onOpenChange` on the Dialog root, or use `showCloseButton` prop.
  - **No `onPointerDownOutside`** either. These are all Radix-specific props.
- **Lesson:** Always check the actual component types in `src/components/ui/*.tsx` before using props from Radix documentation or examples.

### shadcn/ui components legitimately export non-components
- Files like `badge.tsx`, `button.tsx`, `tabs.tsx` export both components and variant functions (e.g., `buttonVariants`).
- This triggers `react-refresh/only-export-components` lint errors.
- **Fix:** Add an eslint config override for `src/components/ui/**/*.{ts,tsx}` to disable this rule. These are generated files with an intentional pattern.

### TypeScript's `tsc -b` (build mode) catches errors that `eslint` and `vitest` don't
- The CI runs `tsc -b && vite build` as a separate step from lint and test.
- Type errors in component props (wrong prop names, missing types) only surface during `tsc` build, not during test runs (vitest uses esbuild which skips type checking).
- **Lesson:** Always run `npx tsc -b` locally before pushing, not just lint + test.

### Recharts Tooltip `formatter` type is strict
- `Tooltip formatter` expects `(value: ValueType | undefined) => ...`, not `(value: number) => ...`.
- **Fix:** Remove the explicit type annotation: `formatter={(value) => \`${value}%\`}` — let TypeScript infer the correct type.

### `getByText` and `getByRole` fail on multiple matches
- `screen.getByText(/profile/i)` fails if "Profile" appears in both `<h1>` and `<p>` text.
- `screen.getByRole('button', { name: /save/i })` fails if both "Save" and "Save & Continue" buttons exist.
- **Fixes:**
  - Use `getByRole('heading', { name: /profile/i })` to target specific element types.
  - Use exact regex `/^save$/i` to avoid partial matches like "Save & Continue".
  - Use `getAllByText(...)` with `.length` checks when duplicates are expected.

### Vitest `beforeEach` must be imported when `globals: true` isn't set
- If vitest config has `globals: true`, test globals are auto-available.
- If not (or in CI with strict TS), `beforeEach` must be explicitly imported: `import { beforeEach } from 'vitest'`.
- **Lesson:** Always import all vitest utilities explicitly for portability.

### Ambiguous variable names fail E741
- Single-letter variables like `l` in list comprehensions trigger ruff's `E741` (ambiguous variable name).
- **Fix:** Use descriptive names: `[line.strip() for line in text.split("\n")]` instead of `[l.strip() for l in ...]`.

### Global error handler changes response format for ALL endpoints
- Adding a global `HTTPException` handler that returns `{"error": {"code", "message"}}` instead of FastAPI's default `{"detail": "..."}` breaks existing tests.
- **Lesson:** After adding middleware that changes response format, grep all tests for the old format (e.g., `resp.json()["detail"]`) and update them.

### First-login bootstrap must not create duplicate placeholder users
- `get_or_create_user()` currently inserts new users with `email=""`, which means only the first auto-created user succeeds because `users.email` is unique.
- **Lesson:** When bootstrapping auth-backed users, populate unique fields from the token payload or make them nullable until real profile data exists.

### Greenhouse embed links should key off `token`, not `jr_id`
- Greenhouse embed URLs like `.../embed/job_app?...for=affirm&jr_id=<opaque>&token=7550577003` can carry two job identifiers, but the canonical public job ID is the numeric `token`.
- **Lesson:** Normalize Greenhouse embed links into canonical board URLs using `for` + `token`, then match on the same external ID shape used by stored ATS jobs.

### Best-effort email guesses must not short-circuit verified lookups
- It is tempting to return a high-confidence pattern suggestion as soon as it is generated, but that prevents later Apollo/Hunter/Proxycurl steps from finding a verified or stronger address.
- **Lesson:** Collect pattern suggestions as fallback candidates first, exhaust the verified waterfall, and only then surface the best guess. Persist low-confidence guesses only if you explicitly want them to become durable contact data.

### Weighted job-context scoring should not double-count the lead section
- If the first paragraph is scored once as the lead and again as part of the full body, weak mentions like “not frontend” can outrank the real domain keywords in a role such as backend credit decisioning.
- **Lesson:** Split description scoring into non-overlapping sections so title and lead signals stay strong without inflating stray body mentions.

### Optional response fields break mocked API tests unless mocks set them explicitly
- Adding `match_quality` and `match_reason` to `PersonResponse` caused FastAPI response validation failures because `MagicMock` auto-creates nested mocks for missing attributes.
- **Lesson:** When extending Pydantic response models, update API test doubles to set new optional attributes to concrete values like `None`, not leave them implicit on `MagicMock`.
