# 帮帮小猫社区猫咪档案与任务权限 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing Yinhu rescue H5 into Help Cat with community search, user-owned pending cat profiles, a daily three-profile limit, and admin-only reporting/task management.

**Architecture:** Keep the current in-memory Python domain service and localStorage H5 pilot. Add explicit cat ownership/review state and task publication/claim rules in the service, while the H5 uses a replaceable local identity provider until formal login is added. Preserve the frozen original feature package and create a separate change package for this release.

**Tech Stack:** Python 3.9 `unittest`, dataclasses, JavaScript ES5-compatible browser code, static HTML/CSS, localStorage.

## Global Constraints

- Product name must be `帮帮小猫` and `Help Cat`.
- Initial scope is Hangzhou, Fuyang District, Yinhu Street.
- Ordinary users may create at most 3 cat profiles per Asia/Shanghai calendar day.
- New ordinary-user cat profiles are pending review and visible to their creator only until approved.
- Reporting, report review, task creation/management, point management, supplies, logs, and exports remain admin-only.
- Ordinary users may view and claim published open tasks.
- No production code may be written before a failing test is observed.
- Do not modify frozen files under `features/hangzhou-stray-cat-rescue/`.

## Task 1: Add the new change-package SOP artifacts

**Files:**
- Create: `features/help-cat-community-cats/input.md`
- Create: `features/help-cat-community-cats/requirements.md`
- Create: `features/help-cat-community-cats/research.md`
- Create: `features/help-cat-community-cats/spec.md`
- Create: `features/help-cat-community-cats/plan.md`
- Create: `features/help-cat-community-cats/tasks.md`
- Create: `features/help-cat-community-cats/acceptance.json`
- Create: `features/help-cat-community-cats/state.json`

- [ ] **Step 1: Record the approved goal and frozen scope.**
- [ ] **Step 2: Record the requirement and permission matrix.**
- [ ] **Step 3: Record machine-readable acceptance cases.**
- [ ] **Step 4: Validate that every requirement has at least one acceptance case.**

## Task 2: Extend the domain model and service with cat ownership/review

**Files:**
- Modify: `sop/rescue_models.py`
- Modify: `sop/rescue_service.py`
- Test: `tests/test_rescue_service.py`

**Interfaces:**
- Add `CatProfile.created_by`, `review_status`, `photo_url`, `living_status`, and `location_note`.
- Add `RescueService.create_cat(..., actor_id, nickname, notes, photo_url, living_status, location_note)`.
- Add `RescueService.review_cat(cat_id, approved, actor_id)`.
- Add `RescueService.list_cats(actor_id, query="", include_pending_for_owner=True)`.
- Add `RescueService.daily_cat_count(actor_id, day=None)`.
- Add `RescueService.create_task(title, description, actor_id, published=True)` and `RescueService.list_tasks(actor_id)`.

- [ ] **Step 1: Write failing tests for ordinary-user creation, ownership visibility, daily limit, admin bypass, approval, and task claim permissions.**
- [ ] **Step 2: Run `python3 -m unittest tests.test_rescue_service -v` and confirm failures are caused by missing behavior.**
- [ ] **Step 3: Implement the smallest dataclass and service changes.**
- [ ] **Step 4: Re-run the focused tests and then the complete Python suite.**
- [ ] **Step 5: Refactor only after all tests are green.**

## Task 3: Add H5 search, “my submissions”, cat creation, and task notice

**Files:**
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/app.js`
- Modify: `app/rescue/styles.css`
- Test: `tests/test_rescue_h5_contract.py`

- [ ] **Step 1: Write failing contract tests for Help Cat branding, search controls, pending submissions, daily limit copy, task notice, and admin-only report/task copy.**
- [ ] **Step 2: Run the focused contract test and confirm it fails.**
- [ ] **Step 3: Implement local demo identity, filtered rendering, cat form, own-submission list, and task claim UI.**
- [ ] **Step 4: Run the contract tests and `node --check app/rescue/app.js`.**
- [ ] **Step 5: Verify no-result search and duplicate-safe localStorage behavior in the browser.**

## Task 4: Add independent acceptance checks and evidence

**Files:**
- Create: `features/help-cat-community-cats/aa/change-list.md`
- Create: `features/help-cat-community-cats/aa/self-test.json`
- Create: `features/help-cat-community-cats/reports/acceptance.json`

- [ ] **Step 1: Run compile, full unit tests, H5 contract tests, and JavaScript syntax checks.**
- [ ] **Step 2: Run isolated service acceptance cases for permissions, quota, visibility, and concurrency.**
- [ ] **Step 3: Perform browser acceptance for search, add, own pending, task notice, and claim.**
- [ ] **Step 4: Record evidence and coverage in machine-readable files.**
- [ ] **Step 5: Mark this change package DONE only if every acceptance case passes.**
