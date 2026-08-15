# Task 3 Report: Compressed, Retryable Miniapp Photo Uploads

## Status

Complete.

## Red → Green record

- RED: `python3 -m unittest tests.test_commercial_frontends.CommercialFrontendContractTests.test_miniapp_photo_upload_compresses_and_preserves_retryable_state -v` failed as expected because `miniapp/pages/cats/new.js` did not call `wx.compressImage`.
- GREEN: added `compressPhoto()` with quality 80 and original-path fallback, explicit upload/retry state, plus upload progress and retry controls. The full frontend contract suite then passed.

## Implementation

- New selections immediately retain their original preview path and reset stale asset/error state.
- `wx.compressImage({ src, quality: 80 })` provides the upload path; compression failures safely upload the original path.
- Successful uploads save the returned asset ID and clear progress/error state.
- Failed uploads retain `photoPath`, mark `uploadError`, and offer `retryPhoto()` to repeat compression and upload from that path.

## Verification

- `python3 -m unittest tests.test_commercial_frontends -v` — PASS (7 tests)
- `node --check miniapp/pages/cats/new.js` — PASS
- `git diff --check` — PASS

## Self-review and concerns

- Upload failure only changes `uploading` and `uploadError`; it deliberately does not clear the selected preview, satisfying retryability.
- `uploadPhoto()` handles both compression and upload failures through its single error path; cancelled media selection remains a no-op.
- No concerns. The pre-existing `.superpowers/brainstorm/` directory and concurrent miniprogram changes were left untouched.

## Critical review follow-up: stale upload completion guard

### Root cause

- `uploadPhoto()` previously let every compression/upload completion call `setData()` unconditionally. A completion for an earlier selection or retry could therefore replace the asset ID or error state belonging to the photo currently shown in `photoPath`.

### TDD evidence

- RED: added `test_miniapp_photo_upload_ignores_stale_selection_completions`, then ran `python3 -m unittest tests.test_commercial_frontends.CommercialFrontendContractTests.test_miniapp_photo_upload_ignores_stale_selection_completions -v`. It failed as expected: `photoUploadVersion` was absent from `miniapp/pages/cats/new.js`.
- GREEN: added a page-level `photoUploadVersion`, incremented it for every accepted selection and retry, passed the captured version into `uploadPhoto()`, and ignored both success and failure completions whose version no longer matches the current version. The same focused contract then passed.

### Preserved behavior

- A newly selected photo still updates the original preview immediately and resets its asset/error state.
- Retrying retains the current preview and starts a new compression/upload attempt.
- Obsolete uploads no longer change `photoAssetId`, `uploading`, `uploadError`, or show an outdated failure toast.

### Verification

- `python3 -m unittest tests.test_commercial_frontends -v` — PASS (8 tests).
- `node --check miniapp/pages/cats/new.js` — PASS.
- `git diff --check` — PASS.
