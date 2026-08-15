# Help Cat Premium Pet Community and Linked Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade H5 and admin to a premium pet-community design, support atomic cat plus community-candidate submission and linked governance, add the admin home-return link and shared footer motto, then test and deploy safely.

**Architecture:** Keep candidates in the existing `communities` table so every cat retains a non-null `community_id`. Add deterministic name normalization, atomic creation, explicit review/merge transitions and a derived community blocker. Preserve the current FastAPI/SQLAlchemy and vanilla HTML/CSS/JavaScript stack and remain backward compatible with `community_id` submissions.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLAlchemy 2, Alembic, SQLite, vanilla JavaScript, HTML5, CSS variables, Python `unittest`, Node 22 test runner, Nginx.

## Global Constraints

- Visual direction: Apple-style hierarchy/whitespace plus premium pet-community warmth; do not copy Apple assets or components.
- Exact shared footer: `安得广厦千万间，大庇天下小猫俱欢颜`.
- Admin brand target: `/help-cat/rescue/index.html#home`; tokens never enter URLs.
- Candidate statuses: `PENDING_REVIEW`, `NEEDS_CHANGES`, `ACTIVE`, `MERGED`, `REJECTED`, `ARCHIVED`.
- Every cat keeps a non-null `community_id` and cannot be public unless its community is `ACTIVE`.
- Candidate and cat creation commit in one transaction; edits, reviews, merges and reassignments are audited.
- Stale writes return HTTP 409 instead of overwriting newer state.
- Existing `community_id` clients remain supported.
- Public cat, community and admin-review collections use stable cursor pagination with a default page of 24 and a hard maximum of 100; no new endpoint may return an unbounded collection.
- Cover 360, 390, 430, 768, 820, 1024 and 1280+ widths and reduced-motion preferences.
- UI scalability does not replace the separate PostgreSQL/Redis/object-storage/multi-instance roadmap.

---

### Task 1: Candidate persistence and normalization

**Files:**
- Create: `server/helpcat/community_rules.py`
- Create: `server/helpcat/migrations/versions/002_community_candidates.py`
- Create: `server/tests/test_community_rules.py`
- Modify: `server/helpcat/models.py`
- Modify: `server/helpcat/db.py`
- Modify: `server/helpcat/app.py`
- Modify: `tests/test_commercial_migrations.py`

**Interfaces:**
- Produces `normalize_community_name(value: str) -> str`.
- Produces Community fields `normalized_name`, `review_note`, `merged_into_id`, `version`.

- [ ] **Step 1: Write failing normalization and migration tests**

```python
from server.helpcat.community_rules import normalize_community_name

def test_normalize_community_name():
    assert normalize_community_name("  星河　家园！ ") == "星河家园"
    assert normalize_community_name("XING He") == "xinghe"
```

Extend the migration contract to require revision `002_community_candidates` and all four columns.

- [ ] **Step 2: Verify the red test**

Run: `python3 -m unittest server.tests.test_community_rules tests.test_commercial_migrations -v`

Expected: FAIL because helper and migration do not exist.

- [ ] **Step 3: Implement the normalizer**

```python
import re
import unicodedata

def normalize_community_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    return re.sub(r"[\s\-—_·，。！？、,.!?:：;；()（）]+", "", value)
```

- [ ] **Step 4: Extend model and SQLite bootstrap**

```python
normalized_name: Mapped[str] = mapped_column(String(120), default="", index=True)
review_note: Mapped[str] = mapped_column(Text, default="")
merged_into_id: Mapped[Optional[str]] = mapped_column(ForeignKey("communities.id"), nullable=True, index=True)
version: Mapped[int] = mapped_column(Integer, default=1)
```

`ensure_schema()` must add missing columns and backfill existing names/version in one engine transaction.

- [ ] **Step 5: Add Alembic revision and populate normalized names on every community write**

Revision `002_community_candidates` uses `down_revision = "001_initial"`, adds columns/indexes safely, backfills existing rows and defines reverse-order downgrade. Empty normalized names return `422 invalid_community_name`.

- [ ] **Step 6: Verify and commit**

Run: `python3 -m unittest server.tests.test_community_rules tests.test_commercial_migrations -v`

Expected: PASS.

Commit: `git commit -m "Add community candidate persistence"` with Task 1 files.

### Task 2: Atomic cat plus candidate creation

**Files:**
- Modify: `server/helpcat/schemas.py`
- Modify: `server/helpcat/app.py`
- Modify: `server/tests/test_commercial_api.py`

**Interfaces:**
- Produces `CommunityCandidateCreate(name, street, note)`.
- `CatCreate` accepts exactly one of `community_id` or `community_candidate`.
- Cat responses add `community_status` and `community_review_blocker`.

- [ ] **Step 1: Write failing API tests**

POST a cat with:

```python
{"community_candidate": {"name": "新湖家园", "street": "银湖街道", "note": "北门"},
 "nickname": "团团", "location_note": "北门绿化带"}
```

Assert one pending candidate, one pending cat, two audit entries and a shared `community_id`. Add 422 tests for neither/both community sources and a forbidden-photo rollback test proving no orphan candidate remains.

- [ ] **Step 2: Verify red**

Run: `python3 -m unittest server.tests.test_commercial_api.CommercialApiTests.test_user_creates_cat_with_pending_community_atomically -v`

Expected: FAIL because `community_candidate` is unsupported.

- [ ] **Step 3: Add exclusive Pydantic inputs**

```python
class CommunityCandidateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    street: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)

class CatCreate(BaseModel):
    community_id: Optional[str] = None
    community_candidate: Optional[CommunityCandidateCreate] = None
```

Use an `after` model validator to require exactly one source.

- [ ] **Step 4: Resolve/create the community without committing**

`resolve_cat_community(db, actor_id, role, payload)` reuses an exact ACTIVE/PENDING_REVIEW/NEEDS_CHANGES normalized candidate or creates a pending candidate for USER and ACTIVE community for ADMIN/SUPER_ADMIN. It flushes and audits but never commits.

- [ ] **Step 5: Keep quota, photo validation, candidate, cat and audits in one transaction**

Only the existing final `db.commit()` may persist the operation. On any error, rollback leaves neither a candidate nor cat.

- [ ] **Step 6: Add blocker payload and run backend regression**

```python
blocker = None if community.status == "ACTIVE" else "COMMUNITY_" + community.status
```

Run: `python3 -m unittest discover -s server/tests -v`

Expected: all backend tests PASS.

- [ ] **Step 7: Commit**

Commit: `git commit -m "Create cats with inline community candidates"` with Task 2 files.

### Task 3: Candidate edit, review, merge and publication guard

**Files:**
- Modify: `server/helpcat/schemas.py`
- Modify: `server/helpcat/app.py`
- Modify: `server/tests/test_commercial_api.py`

**Interfaces:**
- Produces `CommunityEdit(name, street, note, version)`.
- Produces review actions `approve`, `request_changes`, `reject`.
- Produces `POST /communities/{id}/merge` with `target_community_id` and `version`.
- Produces backward-compatible collection payloads with `items` plus `next_cursor`, accepting `cursor` and `limit` query parameters.

- [ ] **Step 1: Write failing permission/state tests**

Cover creator edit, another-user 403, stale-version 409, approve, request_changes with required reason, reject with required reason, merge/reassign all linked cats, ADMIN/SUPER_ADMIN parity and cat-approval guard. Add deterministic cursor tests proving no duplicates or omissions across pages and `limit > 100` validation.

- [ ] **Step 2: Verify red**

Run: `python3 -m unittest server.tests.test_commercial_api.CommercialApiTests.test_candidate_review_merge_and_cat_publication_guard -v`

Expected: FAIL because explicit actions and merge are missing.

- [ ] **Step 3: Add request schemas**

```python
class CommunityReview(BaseModel):
    action: Literal["approve", "request_changes", "reject"]
    note: str = Field(default="", max_length=500)
    version: int = Field(ge=1)

class CommunityMerge(BaseModel):
    target_community_id: str
    version: int = Field(ge=1)
```

- [ ] **Step 4: Implement ownership-aware edit and explicit transitions**

Creator can edit own PENDING_REVIEW/NEEDS_CHANGES row; admins can edit non-final candidates. Check version before changing. Require notes for request_changes/reject, increment version and audit full before/after state.

- [ ] **Step 5: Implement transactional merge**

Lock source and linked cats; require an ACTIVE target different from source; reassign every cat, set source `MERGED`, set `merged_into_id`, increment version and audit before one commit.

- [ ] **Step 6: Guard cat approval and public listing**

Approving a cat with non-ACTIVE community returns `409 community_not_active`. Public cats query must also filter joined Community status ACTIVE.

- [ ] **Step 7: Add bounded cursor pagination**

Apply stable `(created_at DESC, id DESC)` cursor pagination to public cats, community choices and admin community/cat review lists. Default to 24, cap at 100 and return `next_cursor = null` on the last page. Keep the existing top-level `items` key so current clients remain compatible.

- [ ] **Step 8: Verify and commit**

Run: `python3 -m unittest discover -s server/tests -v`

Expected: PASS.

Commit: `git commit -m "Add linked community governance"`.

### Task 4: H5 inline candidate and correction experience

**Files:**
- Create: `app/rescue/community-form.js`
- Create: `tests/js/rescue_community_runtime.test.js`
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/app.js`
- Modify: `app/rescue/styles.css`
- Modify: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Produces `HelpCatCommunityForm.buildCatCommunityPayload(mode, values)`.
- Consumes blocker/status/version fields from Tasks 2–3.

- [ ] **Step 1: Write failing HTML and runtime tests**

Require accessible mode controls and candidate name/street/note inputs. Runtime assertions:

```javascript
assert.deepEqual(build("existing", {communityId:"c1"}), {community_id:"c1"});
assert.deepEqual(build("new", {name:"新湖家园",street:"银湖街道",note:"北门"}),
  {community_candidate:{name:"新湖家园",street:"银湖街道",note:"北门"}});
```

- [ ] **Step 2: Verify red**

Run: `python3 -m unittest tests.test_rescue_h5_contract -v && node --test tests/js/rescue_community_runtime.test.js`

Expected: FAIL because controls/helper do not exist.

- [ ] **Step 3: Add two modes inside cat step 2**

Use real buttons with `aria-pressed`: “选择已有小区” and “填写新小区”. Keep both field groups in the DOM and preserve other cat fields when switching.

- [ ] **Step 4: Add the testable payload helper and integrate submit**

Load `community-form.js` after `api.js` and before `app.js`. Existing mode sends `community_id`; new mode sends `community_candidate`. Lock duplicate submit and preserve form on upload/network errors.

- [ ] **Step 5: Render candidate status and correction in My Submissions**

Show PENDING_REVIEW, NEEDS_CHANGES, MERGED, REJECTED and ACTIVE. Creator can edit own pending/needs-changes candidate with version; 409 refreshes latest state.

- [ ] **Step 6: Consume bounded pages**

Load 24 records initially, append via an accessible “加载更多” control only when `next_cursor` exists, and suppress duplicate IDs if a row changes between requests.

- [ ] **Step 7: Verify and commit**

Run: `python3 -m unittest tests.test_rescue_h5_contract -v && node --test tests/js/rescue_community_runtime.test.js tests/js/rescue_version_runtime.test.js && node --check app/rescue/community-form.js && node --check app/rescue/app.js`

Expected: PASS.

Commit: `git commit -m "Add inline community candidates to cat creation"`.

### Task 5: Admin home link and linked-review workbench

**Files:**
- Create: `admin/community-review.js`
- Create: `tests/js/admin_community_review_runtime.test.js`
- Modify: `admin/index.html`
- Modify: `admin/app.js`
- Modify: `admin/styles.css`
- Modify: `tests/test_commercial_frontends.py`

**Interfaces:**
- Produces UI actions approve, merge, request_changes, reject and cat reassignment.

- [ ] **Step 1: Write failing navigation and action tests**

Assert `.side-brand` target/accessible name, separate overview button and no token in URL. Runtime tests map actions to endpoint/body and reject blank reasons before network calls.

- [ ] **Step 2: Verify red**

Run: `python3 -m unittest tests.test_commercial_frontends -v && node --test tests/js/admin_community_review_runtime.test.js`

Expected: FAIL because brand points to `#overview` and linked actions do not exist.

- [ ] **Step 3: Change the brand link**

```html
<a class="side-brand" href="/help-cat/rescue/index.html#home" aria-label="返回帮帮小猫首页" title="返回帮帮小猫首页">
```

- [ ] **Step 4: Render linked candidate cards**

Show candidate identity/history, similar ACTIVE choices, at most three linked-cat previews and stable `data-community-action` controls. Block cat approval while `community_review_blocker` exists and provide “先处理小区”.

- [ ] **Step 5: Implement review/merge requests**

Use `community-review.js` to build endpoint/body pairs. Require reason for request_changes/reject, ACTIVE target for merge, disable controls while busy and refresh with a clear message on 409.

- [ ] **Step 6: Consume bounded review pages**

Render the first 24 candidates/cats and append later pages through an accessible “加载更多” control; reset cursor and de-duplicate IDs after filters or mutations.

- [ ] **Step 7: Verify and commit**

Run: `python3 -m unittest tests.test_commercial_frontends -v && node --test tests/js/admin_community_review_runtime.test.js tests/js/admin_session_runtime.test.js && node --check admin/community-review.js && node --check admin/app.js`

Expected: PASS.

Commit: `git commit -m "Add linked community review workbench"`.

### Task 6: Premium visual system and shared footer

**Files:**
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/styles.css`
- Modify: `admin/index.html`
- Modify: `admin/styles.css`
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `tests/test_commercial_frontends.py`

**Interfaces:**
- Produces shared premium visual tokens and exact footer text without API changes.

- [ ] **Step 1: Write failing visual/footer contracts**

Require semantic `<footer>` with exact copy on both surfaces, `#F5F5F7`, `#1D1D1F`, responsive `clamp(` type, 44px targets, reduced-motion rules and responsive admin sidebar.

- [ ] **Step 2: Verify red**

Run: `python3 -m unittest tests.test_rescue_h5_contract tests.test_commercial_frontends -v`

Expected: FAIL on missing footer/premium markers.

- [ ] **Step 3: Refresh H5 hierarchy**

Keep existing JS IDs while implementing an image-led hero, lighter metrics, simplified surfaces, premium rounded cards, restrained badges, responsive typography and low-cost motion.

- [ ] **Step 4: Refresh admin hierarchy**

Keep section IDs while improving typography, summary metrics, linked-review hierarchy and tablet/mobile sidebar. Destructive actions remain visually distinct.

- [ ] **Step 5: Add the exact footer to both surfaces**

```html
<footer class="brand-footer"><small>安得广厦千万间，大庇天下小猫俱欢颜</small></footer>
```

H5 footer sits above fixed-nav safe area; admin footer ends main content and remains separate from service status.

- [ ] **Step 6: Verify responsive/accessibility contracts and commit**

Run contracts and inspect 360, 390, 430, 768, 820, 1024 and 1280 widths for overflow, focus, 44px targets, contrast and reduced motion.

Commit: `git commit -m "Refresh Help Cat premium pet community UI"`.

### Task 7: Documentation, migration rehearsal, deployment and final gate

**Files:**
- Modify: `docs/wiki/功能清单与状态.md`
- Modify: `docs/wiki/核心业务流程.md`
- Modify: `docs/wiki/数据模型与-API.md`
- Modify: `docs/wiki/测试与质量保障.md`
- Modify: `docs/wiki/变更记录.md`
- Update: Draft PR `pig-tongzhi/help-cat#1`

**Interfaces:**
- Produces timestamped production release/backup and synchronized GitHub Wiki.

- [ ] **Step 1: Update Wiki source**

Document candidate states, atomic creation, correction permissions, merge/reassignment, publication guard, API, visual rules, exact footer, tests and rollback.

- [ ] **Step 2: Run complete local gate**

Run Python test discovery for `tests` and `server/tests`, all `tests/js/*.test.js`, syntax checks for every H5/admin script and `git diff --check main...HEAD`.

Expected: zero failures/errors.

- [ ] **Step 3: Review for release blockers**

Reject secrets, token-in-URL logic, unbounded new list queries, missing audits, destructive migration behavior and unrelated changes. Resolve all Critical/Important issues.

- [ ] **Step 4: Back up and rehearse migration**

Create `/opt/help-cat/backups/<timestamp>-premium-community`, copy DB/backend/H5/admin/Nginx, record hashes, then run migration against a DB copy. Verify row counts, foreign keys, IDs, normalized names and versions before touching production.

- [ ] **Step 5: Stage and deploy backend first**

Upload to `/opt/help-cat/releases/<timestamp>-premium-community`, compare hashes, stop only Help Cat API, install/migrate/start, and verify health. On failure restore DB/backend before serving traffic.

- [ ] **Step 6: Deploy admin and H5**

Install versioned assets, preserve no-store HTML headers, run `nginx -t`, compare live hashes and verify required markers.

- [ ] **Step 7: Run production acceptance with disposable QA data**

Verify admin brand return/session, atomic user candidate+cat, linked review/merge/correction, publication guard, exact footer and phone/tablet/desktop layout. Remove QA data through manifest cleanup.

- [ ] **Step 8: Commit docs, push, sync Wiki and PR**

Commit Wiki source, push `agent/mobile-upload-admin-entry`, sync changed pages to the Wiki repository and update Draft PR #1 with tests, release/backup paths and scale limits.

- [ ] **Step 9: Run a fresh final verification**

Confirm local tests, production health/markers/hashes, clean worktree, branch HEAD equals remote, Wiki head and PR head before marking the goal complete.
