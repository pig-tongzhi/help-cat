# Help Cat Production QA Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and verify one reversible `[QA-20260801]` production dataset that exercises every currently implemented Help Cat workflow.

**Architecture:** A standard-library Python seed runner calls the live API for all business actions. It inserts only one temporary zack session directly into SQLite, revokes it in `finally`, writes an exact-ID manifest, and pairs with a manifest-driven cleanup utility that defaults to dry-run.

**Tech Stack:** Python 3.11, `urllib`, SQLite, FastAPI production API, `unittest`, Nginx, systemd.

## Global Constraints

- Every visible test entity name starts with `[QA-20260801]` and every test username ends with `_20260801`.
- Never read, reset, print, or store zack's password.
- `zack` remains the only `SUPER_ADMIN` before and after the run.
- Business mutations use the production API; the only direct bootstrap mutation is a short-lived zack session.
- Back up the production SQLite database before seeding.
- Cleanup deletes exact manifest IDs only and defaults to dry-run.
- The project directory is not a Git repository, so commit steps do not apply.

---

### Task 1: Seed and manifest contracts

**Files:**
- Create: `scripts/help_cat_qa_seed.py`
- Create: `tests/test_help_cat_qa_seed.py`

**Interfaces:**
- Produces: `BATCH`, `PREFIX`, `qa_accounts()`, `expected_entities()`, `validate_manifest(manifest)`.
- Produces: CLI arguments `--base-url`, `--database`, `--storage-root`, `--manifest`, `--credentials`.

- [ ] **Step 1: Write failing contract tests**

Assert that the three usernames are unique and end in `_20260801`, all entity names start with `[QA-20260801]`, and manifest validation rejects a different batch, missing IDs, or a non-zack unique super administrator.

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests.test_help_cat_qa_seed`

Expected: import failure because `scripts.help_cat_qa_seed` does not exist.

- [ ] **Step 3: Implement constants, HTTP client, safety checks, and manifest validation**

The HTTP client must support JSON requests and multipart JPEG upload, require exact expected status codes, and omit bearer tokens and passwords from exception text. The preflight must reject an existing manifest, existing QA usernames, or any existing `[QA-20260801]` entity.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python3 -m unittest tests.test_help_cat_qa_seed`

Expected: all seed contract tests pass.

---

### Task 2: Full API seed workflow

**Files:**
- Modify: `scripts/help_cat_qa_seed.py`
- Modify: `tests/test_help_cat_qa_seed.py`

**Interfaces:**
- Produces: `seed_full_flow(config, passwords) -> dict`.
- Consumes: `/auth/register`, `/admin/users/{id}/role`, `/communities`, `/communities/{id}/review`, `/communities/{id}/archive`, `/media/images`, `/cats`, `/cats/{id}/review`, `/cats/{id}/visibility`, `/cats/{id}/archive`, `/tasks`, and `/tasks/{id}/claim`.

- [ ] **Step 1: Add a failing expected-coverage test**

Assert that the declared seed plan contains community states `ACTIVE`, `PENDING_REVIEW`, `HIDDEN`, `ARCHIVED`; cat combinations `PENDING_REVIEW/ACTIVE`, `APPROVED/ACTIVE`, `REJECTED/ACTIVE`, `APPROVED/HIDDEN`, `APPROVED/ARCHIVED`; and task states `OPEN`, `CLAIMED`.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: failure because the workflow plan and runner are missing.

- [ ] **Step 3: Implement the minimal workflow**

Register the three accounts, insert a 15-minute zack session, promote the test admin through the API, create every entity from the design, upload and read a minimal JPEG, collect exact IDs, and revoke the zack session in `finally`. Write the manifest atomically with mode `0600`; write a separate root-only credentials file.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python3 -m unittest tests.test_help_cat_qa_seed`

Expected: all seed tests pass.

---

### Task 3: Exact-ID cleanup

**Files:**
- Create: `scripts/help_cat_qa_cleanup.py`
- Create: `tests/test_help_cat_qa_cleanup.py`

**Interfaces:**
- Produces: `build_cleanup_preview(connection, storage_root, manifest) -> dict` and `cleanup(connection, storage_root, manifest, execute=False) -> dict`.
- Consumes: the exact-ID seed manifest.

- [ ] **Step 1: Write failing cleanup tests**

Build a temporary database containing one QA dataset plus unrelated rows. Assert dry-run changes nothing, execute removes only manifest-linked sessions, quota, audit, tasks, cats, media, communities and QA users, and unrelated rows remain.

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests.test_help_cat_qa_cleanup`

Expected: import failure because the cleanup module does not exist.

- [ ] **Step 3: Implement dry-run and explicit execution**

Require `--execute` for deletion, validate the batch and exact usernames, make a database backup before deletion, delete inside one transaction, and remove only manifest-listed media files after commit.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python3 -m unittest tests.test_help_cat_qa_cleanup`

Expected: all cleanup tests pass.

---

### Task 4: Isolated integration verification

**Files:**
- Verify: `scripts/help_cat_qa_seed.py`
- Verify: `scripts/help_cat_qa_cleanup.py`
- Verify: `server/helpcat/*`

- [ ] **Step 1: Run syntax and complete automated tests**

Run:

```bash
python3 -m py_compile scripts/help_cat_qa_seed.py scripts/help_cat_qa_cleanup.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest discover -s server/tests -p 'test_*.py'
```

Expected: zero failures.

- [ ] **Step 2: Seed an isolated database through a local API**

Start the production app against a temporary database and upload directory, seed once, verify the manifest and every public/admin state, verify a second seed refuses duplication, run cleanup dry-run, then execute cleanup and verify the original zack row is the only remaining business user.

---

### Task 5: Production seed and verification

**Files:**
- Deploy: `scripts/help_cat_qa_seed.py` to `/opt/help-cat/tools/help_cat_qa_seed.py`
- Deploy: `scripts/help_cat_qa_cleanup.py` to `/opt/help-cat/tools/help_cat_qa_cleanup.py`
- Create: `/opt/help-cat/data/qa/QA-20260801-manifest.json`
- Create: `/opt/help-cat/data/qa/QA-20260801-credentials.txt`

- [ ] **Step 1: Back up and preflight production**

Copy `/opt/help-cat/data/help-cat.db` to `/opt/help-cat/backups/<timestamp>-before-QA-20260801/help-cat.db`, assert the service is healthy, zack is the sole `SUPER_ADMIN`, and the QA namespace is unused.

- [ ] **Step 2: Upload scripts and compare SHA-256**

Upload both scripts and require local/remote hashes to match before execution.

- [ ] **Step 3: Execute the seed once**

Generate independent strong passwords, pass them without printing, run the seed on the server, and retain the root-only credentials file.

- [ ] **Step 4: Verify complete production coverage**

Check exact row counts and status groups from the manifest; verify public endpoints expose only active/approved/open QA entities; verify all audit actions; verify media read; verify temporary zack session is revoked; verify `SUPER_ADMIN = [('zack', 'ACTIVE')]`.

- [ ] **Step 5: Verify operational health and cleanup preview**

Run `systemctl is-active help-cat.service`, `nginx -t`, public health check with no proxy, and the cleanup script without `--execute`. The preview must enumerate only the new QA dataset and make zero database changes.
