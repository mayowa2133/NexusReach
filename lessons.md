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

### SQLAlchemy async requires `selectinload` for relationships
- Lazy loading doesn't work with async sessions.
- Always use `.options(selectinload(Model.relationship))` when you need related data.
- Forgetting this causes `greenlet` errors at runtime.

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
