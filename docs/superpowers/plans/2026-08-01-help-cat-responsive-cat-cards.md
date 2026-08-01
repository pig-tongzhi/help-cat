# Help Cat Responsive Cat Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix broken cat-card rendering and ship one automatically responsive card component for desktop, tablet, and mobile H5.

**Architecture:** Make the current `app.js` class names the single card-component contract, style those exact selectors, and add a capture-phase image error handler so broken media falls back to the same illustration as missing media. Use CSS breakpoints for three-column desktop, two-column tablet, and compact horizontal single-column mobile layouts.

**Tech Stack:** Vanilla JavaScript, HTML5, CSS3, Python `unittest`, in-app browser, Nginx static hosting.

## Global Constraints

- No UI framework or build dependency.
- Desktop, tablet, and mobile use the same HTML and JavaScript data model.
- Broken or absent images never show browser-native broken-image text.
- Mobile content remains readable at 360px and has no horizontal overflow.
- Bottom navigation retains safe-area spacing and never covers the last card.
- Existing API behavior and database schema remain unchanged.
- The project directory is not a Git repository; use snapshots and production backups instead of commits.

---

### Task 1: Card markup and image fallback contract

**Files:**
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `app/rescue/app.js`

**Interfaces:**
- Produces: `healthTone(value) -> "healthy" | "attention" | "unknown"`.
- Produces: card classes `cat-card-body`, `cat-title`, `cat-community`, `cat-placeholder`, `health-badge`.
- Produces: capture-phase `error` listener that adds `image-failed` and hides the failed image.

- [ ] **Step 1: Write failing contract tests**

Require `cat-placeholder` to be present for every card, `health-badge` to include a tone class, and the script to contain an image error listener, `image-failed`, and image hiding behavior.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python3 -m unittest tests.test_rescue_h5_contract`

Expected: fail because the current card includes no placeholder when an image URL exists and has no error listener.

- [ ] **Step 3: Implement minimal accessible card markup**

Render the placeholder below the optional image, add `data-cat-photo`, map health tone classes, keep descriptive alt text for valid images, and handle `error` once at document level in capture phase.

- [ ] **Step 4: Run JavaScript syntax and focused tests**

Run: `node --check app/rescue/app.js && python3 -m unittest tests.test_rescue_h5_contract`

Expected: syntax succeeds and focused tests pass.

---

### Task 2: Responsive card visual system

**Files:**
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `app/rescue/styles.css`
- Modify: `app/rescue/index.html`

**Interfaces:**
- Consumes: Task 1 card classes and `image-failed` state.
- Produces: desktop `3` columns, tablet `2` columns, mobile `1` compact horizontal column.

- [ ] **Step 1: Add failing selector and breakpoint tests**

Require CSS selectors for every Task 1 class, `image-failed`, line clamping, tablet breakpoint `1024px`, mobile breakpoint `720px`, and the horizontal mobile card grid.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: fail because the stylesheet still defines the old card selectors.

- [ ] **Step 3: Replace the stale card CSS block**

Define the new component selectors, layer photos over a permanent illustrated placeholder, style health variants, clamp long text, equalize desktop card bodies, show three recent cards on desktop and two on tablet/mobile, and implement the mobile horizontal card.

- [ ] **Step 4: Update cache-busting versions**

Change rescue CSS/JS query versions in `index.html` to `20260801-responsive` so production browsers do not retain the broken assets.

- [ ] **Step 5: Run focused tests and syntax checks**

Run: `node --check app/rescue/app.js && node --check app/rescue/api.js && python3 -m unittest tests.test_rescue_h5_contract`

Expected: all checks pass.

---

### Task 3: Valid QA card media

**Files:**
- Create: one temporary valid QA JPEG outside the repository.
- Replace on production: the media file referenced by `QA-20260801-manifest.json`.

- [ ] **Step 1: Locate and back up the current media**

Resolve the manifest `object_key`, assert it belongs to the QA media ID, and copy it into the timestamped production backup directory before replacement.

- [ ] **Step 2: Produce a valid test cat JPEG**

Generate or reuse a clearly non-sensitive test cat image, verify it with an image decoder, and keep reasonable dimensions and file size.

- [ ] **Step 3: Replace only the QA object file**

Upload to a release directory, verify SHA-256, atomically replace the same `object_key`, and leave the database media ID and cat relation unchanged.

- [ ] **Step 4: Verify HTTP image decode**

Fetch `/api/v1/media/{id}`, require HTTP 200, `image/jpeg`, and successful decoder inspection.

---

### Task 4: Automated and three-viewport browser regression

**Files:**
- Verify: `app/rescue/index.html`
- Verify: `app/rescue/styles.css`
- Verify: `app/rescue/app.js`
- Verify: `app/rescue/api.js`

- [ ] **Step 1: Run complete automated verification**

Run:

```bash
node --check app/rescue/app.js
node --check app/rescue/api.js
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest discover -s server/tests -p 'test_*.py'
```

Expected: zero failures.

- [ ] **Step 2: Start an isolated local preview**

Serve the production-shaped H5 and API data locally, including one valid image, one absent image, and one forced broken image.

- [ ] **Step 3: Verify desktop `1440×900`**

Require three columns, styled badges and body, no broken alt text, equal card alignment, and `scrollWidth <= clientWidth`.

- [ ] **Step 4: Verify tablet `820×1180`**

Require two columns, complete search/filter/navigation controls, readable cards, and no horizontal overflow.

- [ ] **Step 5: Verify mobile `390×844` and `360×800`**

Require a single horizontal-card column, compact media, visible placeholder, unobstructed last content, functional bottom navigation, and no horizontal overflow.

---

### Task 5: Production deployment and verification

**Files:**
- Deploy: `app/rescue/index.html`
- Deploy: `app/rescue/styles.css`
- Deploy: `app/rescue/app.js`

- [ ] **Step 1: Back up current production H5 and QA media**

Create `/opt/help-cat/backups/<timestamp>-responsive-cards/` containing the full current rescue static directory and original QA media.

- [ ] **Step 2: Upload release and verify SHA-256**

Upload all three files to `/opt/help-cat/releases/<timestamp>-responsive-cards/`, compare local and remote hashes, then copy them into the static directory only if every hash matches.

- [ ] **Step 3: Verify production resources and service health**

Check Nginx syntax, Help Cat service health, public no-proxy H5/CSS/JS responses, cache-busting version, media decode, and local/remote asset hashes.

- [ ] **Step 4: Run final production browser regression**

Repeat desktop, tablet, and mobile layout assertions against `http://175.178.41.19/help-cat/rescue/index.html`, verify no console errors, then leave the production page available to the user.
