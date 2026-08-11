# Help Cat Reference Homepage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production Help Cat homepage match the confirmed desktop/mobile reference while exposing four truthful, auditable impact totals.

**Architecture:** Add an append-only `impact_events` ledger with reversible admin mutations and extend the existing public metrics endpoint to aggregate four event kinds. Keep one semantic homepage DOM and use responsive CSS to reproduce the two confirmed compositions; existing public cats/tasks APIs remain the source of cards.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic/SQLite, vanilla ES5 JavaScript, HTML5/CSS3, Python `unittest`, Node `node:test`, Nginx/systemd.

## Global Constraints

- Design reference is `codex-clipboard-85611778-55d9-47b3-ae5d-dd00b018b740.png`.
- Never ship the reference's sample numbers or sample cats as production data.
- Missing impact data renders as numeric `0`; failed requests render a component-local error without a full-width hero banner.
- Exclude QA and reversed impact events from public totals.
- Preserve login, cat submission, task, community, admin, and story-77 behavior.
- Validate 1440×900 desktop and 390×844 mobile locally and on `https://helpcat.xyz/`.

---

### Task 1: Impact ledger schema and migration

**Files:**
- Modify: `server/helpcat/models.py`
- Modify: `server/helpcat/db.py`
- Create: `server/helpcat/migrations/versions/006_impact_events.py`
- Test: `tests/test_commercial_migrations.py`

**Interfaces:**
- Produces: `ImpactEvent` model with `kind`, `amount`, `note`, `occurred_at`, `created_by`, `reversed_at`, `reversed_by`, and `is_qa`.

- [ ] Write a migration contract test asserting revision `006_impact_events`, down revision `005_public_profiles`, the four-kind check constraint, positive amount check, QA index, and reversible fields.
- [ ] Run `python3 -m unittest tests.test_commercial_migrations.CommercialMigrationTests.test_impact_event_migration_declares_auditable_ledger -v`; expect failure because revision 006 is absent.
- [ ] Add `ImpactEvent` and revision 006; extend bootstrap schema for SQLite installations that start without Alembic.
- [ ] Run the focused migration test and an actual legacy-SQLite upgrade; expect pass and the `impact_events` table to exist.
- [ ] Commit with `feat: add auditable impact ledger`.

### Task 2: Admin mutations and public aggregation

**Files:**
- Modify: `server/helpcat/app.py`
- Modify: `server/helpcat/schemas.py`
- Test: `server/tests/test_commercial_api.py`

**Interfaces:**
- Produces: `POST /api/v1/admin/impact-events`, `GET /api/v1/admin/impact-events`, `POST /api/v1/admin/impact-events/{id}/reverse`.
- Produces: `GET /api/v1/public/metrics -> {rescued, adopted, medical, supporters}`.

- [ ] Add failing API tests proving admin-only creation, positive amount validation, cursor pagination, reversal idempotency, QA/reversed exclusion, and session-independent public totals.
- [ ] Run the focused tests; expect 404 or old metrics keys.
- [ ] Implement explicit allow-list validation for `RESCUED`, `ADOPTED`, `MEDICAL`, `SUPPORTER`; create audit-log entries for create/reverse.
- [ ] Aggregate `sum(amount)` for each kind with zero defaults and no authentication-dependent branches.
- [ ] Run `python3 -m unittest server.tests.test_commercial_api -v`; expect all tests pass.
- [ ] Commit with `feat: expose truthful impact metrics`.

### Task 3: Exact homepage semantic structure

**Files:**
- Modify: `app/rescue/index.html`
- Modify: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: four public metric keys from Task 2.
- Produces: `.reference-hero`, `.impact-strip`, `.reference-content-grid`, four-card `#home-cats`, one-card `#home-tasks`, and mobile reference nav labels.

- [ ] Add a failing contract test asserting four metric IDs/labels, desktop nav labels, four-card archive structure, single task panel, and exact mobile navigation copy.
- [ ] Run the focused contract test; expect failure on the old metrics and nav.
- [ ] Rewrite only the home/header/bottom-nav markup while preserving all existing IDs used by forms, routing, sheets, and account state.
- [ ] Bump asset version to `20260812-reference-home-r1` in HTML and `version.js`.
- [ ] Run `python3 -m unittest tests.test_rescue_h5_contract -v`; expect pass.
- [ ] Commit with `feat: align homepage structure to reference`.

### Task 4: Responsive rendering and data behavior

**Files:**
- Modify: `app/rescue/styles.css`
- Modify: `app/rescue/app.js`
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `tests/js/rescue_story_77_runtime.test.js` only if routing assertions require the new nav labels.

**Interfaces:**
- Consumes: `{rescued, adopted, medical, supporters}` and existing cat/task payloads.
- Produces: desktop 4-card + 1-task layout; mobile 2×2 cards + task + fixed nav.

- [ ] Add failing tests for the four metric mappings, `slice(0, 4)`, `slice(0, 1)`, 50/50 hero, desktop hidden bottom nav, and mobile safe-area layout.
- [ ] Run focused Python/Node tests; expect failures on old 3-metric rendering and three-card slice.
- [ ] Implement component-local metric errors, prioritise public profile `story-77` in the home four without changing archive order, and render one task.
- [ ] Replace layered legacy homepage overrides with one final reference block matching measured proportions; retain non-home page styles.
- [ ] Run all H5 contracts, Node runtime tests, and `node --check app/rescue/*.js`; expect pass.
- [ ] Commit with `fix: reproduce confirmed responsive homepage`.

### Task 5: Visual, full-suite, and migration verification

**Files:**
- Modify: `docs/wiki/测试与质量保障.md`
- Modify: `docs/wiki/变更记录.md`

**Interfaces:**
- Produces: reproducible screenshot and release evidence.

- [ ] Start a local stack with real API data; capture 1440×900 and 390×844 screenshots.
- [ ] Compare header height, hero split/crop, metric strip, card count, task panel, and mobile nav against the confirmed image; fix deviations before proceeding.
- [ ] Execute `python3 -m unittest discover -s server -v`, `python3 -m unittest discover -s tests -v`, `node --test tests/js/*.test.js`, all JS syntax checks, migration upgrade, and `git diff --check`.
- [ ] Document the commands, counts, screenshot sizes, and four-metric semantics.
- [ ] Commit with `docs: record reference homepage verification`.

### Task 6: Push, immutable release, and production acceptance

**Files:**
- No new source files; deploy the committed tree.

**Interfaces:**
- Consumes: verified commit from Tasks 1–5.
- Produces: new immutable `/opt/help-cat/releases/<release>` and atomic `/opt/help-cat/current` switch.

- [ ] Push through ClashX only for GitHub transport.
- [ ] Back up production database and current release pointer; upload the complete release, install declared dependencies, run migration 006, and start the API against the new release.
- [ ] Verify health and migrations before atomically switching Nginx/current; on failure keep the previous release active.
- [ ] From the real domain capture 1440×900 and 390×844 screenshots and verify the page contains no top-level error banner and shows real metrics/cards.
- [ ] Verify `story-77` still returns nickname `77` and community `银湖街道`, admin remains reachable, service is active, and local/remote hashes match.
- [ ] Mark the goal complete only after every acceptance item passes.

