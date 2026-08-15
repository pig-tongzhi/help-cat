# Final Image Cache Review Fix Report

## Upload submission race

- Added `test_miniapp_submit_blocks_pending_or_failed_selected_photo_and_snapshots_asset` to the commercial frontend contracts.
- RED: the focused test failed because `submit()` could proceed while the selected photo was uploading or failed, and it read live `photoAssetId` after asynchronous community lookup.
- GREEN: `submit()` now returns with a clear toast when a selected photo is uploading or has failed, snapshots the accepted asset ID before asynchronous work, and uses that value in the create payload. The submit button is also disabled for upload-pending and upload-error states; the JavaScript guard remains authoritative.

## Release checklist

- The image release check now requires `Cache-Control: public, max-age=31536000, immutable` for both thumbnail and original responses.

## Verification

- `python3 -m unittest tests.test_commercial_frontends.CommercialFrontendContractTests.test_miniapp_submit_blocks_pending_or_failed_selected_photo_and_snapshots_asset -v` — passed after implementation.
- `python3 -m unittest tests.test_commercial_frontends -v` — 9 passed.
- `node --check miniapp/pages/cats/new.js` — passed.
- `git diff --check` — passed.
