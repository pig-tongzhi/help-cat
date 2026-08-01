# 杭州银湖街道流浪猫救助 H5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a mobile-first H5 rescue ledger for Fuyang District Yinhu Subdistrict with auditable feeding points, cat records, reports, TNR, tasks, supplies, privacy masking, logs and exports.

**Architecture:** Keep the existing Python standard-library project dependency-free. Add a focused rescue domain module with an in-memory repository for the MVP, an optional SQLite-compatible boundary, and a map-provider adapter that degrades to manual area selection. Add a standalone H5 route under `app/rescue` without changing the existing content-service page.

**Tech Stack:** Python 3.9 standard library, `unittest`, HTML/CSS/vanilla JavaScript, localStorage for H5 demo persistence, JSON/CSV export.

## Global Constraints

- Pilot scope is Hangzhou / Fuyang District / Yinhu Subdistrict.
- Public views must not expose exact coordinates, full addresses, or private contact data.
- No real map key is required for the first runnable demo.
- No donation, payment, smart hardware, AI identification, or real-time chat in this iteration.
- Frozen artifacts under `features/hangzhou-stray-cat-rescue` must not be modified after development starts.

### Task 1: Rescue domain model and validation

**Files:**
- Create: `sop/rescue_models.py`
- Create: `sop/rescue_validation.py`
- Test: `tests/test_rescue_models.py`

**Interfaces:**
- `ReportType`, `ReportStatus`, `TaskStatus`, `TnrStatus` string enums.
- `FeedingPoint`, `CatProfile`, `RescueReport`, `RescueTask`, `SupplyShortage`, `AuditLog` dataclasses.
- `validate_positive_quantity(value)`, `validate_report_payload(payload)` and explicit state-transition helpers.

- [ ] Write tests for valid objects, invalid quantity, invalid blank title, and illegal task/TNR transitions.
- [ ] Run `python3 -m unittest tests.test_rescue_models -v`; expect failures because the module is absent.
- [ ] Implement the enums, dataclasses and validation with no persistence concerns.
- [ ] Re-run the focused test; expect all pass.

### Task 2: Repository and service workflows

**Files:**
- Create: `sop/rescue_service.py`
- Create: `tests/test_rescue_service.py`

**Interfaces:**
- `RescueService.create_report(payload, idempotency_key)`
- `RescueService.review_report(report_id, approved, actor_id)`
- `RescueService.claim_task(task_id, actor_id)`
- `RescueService.complete_task(task_id, actor_id, evidence)`
- `RescueService.create_feeding_point(...)`, `create_cat(...)`, `update_tnr(...)`, `create_supply_shortage(...)`.
- `RescueService.public_snapshot()` and `export(format_name)`.

- [ ] Write failing tests for report-to-task flow, duplicate idempotency key, failed review rollback, and concurrent task claim.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement repository storage and service transactions with conditional claim.
- [ ] Add audit-log writes for each successful mutation and export.
- [ ] Re-run focused tests, then full existing tests.

### Task 3: Map adapter and location privacy

**Files:**
- Create: `sop/rescue_map.py`
- Create: `tests/test_rescue_map.py`

- [ ] Write tests for manual fallback with no key, provider timeout fallback, and public coordinate masking.
- [ ] Implement `MapProvider`, `FallbackMapProvider`, `AmapMapProvider` configuration-only adapter, and fixed-grid masking.
- [ ] Verify no key or secret appears in browser assets.

### Task 4: H5 pilot interface

**Files:**
- Create: `app/rescue/index.html`
- Create: `app/rescue/styles.css`
- Create: `app/rescue/app.js`
- Modify: `app/index.html` with a link to the pilot
- Test: `tests/test_rescue_h5_contract.py`

- [ ] Write a contract test for required labels, public privacy copy, and report form fields.
- [ ] Implement mobile-first dashboard, feeding-point cards, cat cards, report form, task panel, supply form and JSON/CSV download.
- [ ] Use localStorage demo seed data and clearly label map as “地图服务未配置时可手工选择”。
- [ ] Run contract tests and inspect at 375px viewport.

### Task 5: SOP self-test and independent acceptance

**Files:**
- Create: `features/hangzhou-stray-cat-rescue/aa/change-list.md`
- Create: `features/hangzhou-stray-cat-rescue/aa/self-test.json`
- Create: `features/hangzhou-stray-cat-rescue/reports/acceptance.json`
- Test: `tests/test_rescue_acceptance.py`

- [ ] Map every acceptance ID to an executable test or browser contract assertion.
- [ ] Run compile, unit, repository, integration, static and coverage checks.
- [ ] Write self-test evidence only from actual command output.
- [ ] Run independent acceptance from a clean process and write its evidence.
- [ ] Advance the SOP state only after all gates pass.

## Rollback

Keep the rescue route and domain modules isolated. If the H5 fails, remove only the rescue navigation link and leave the existing content-service and SOP engine untouched. Never modify frozen artifacts to make tests pass.
