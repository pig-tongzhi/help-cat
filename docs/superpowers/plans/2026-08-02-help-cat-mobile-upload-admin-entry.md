# Help Cat Mobile Upload and Admin Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let mobile users choose an existing photo or take a new one, and let `ADMIN` and `SUPER_ADMIN` users enter the management console without signing in twice.

**Architecture:** Keep the native HTML file picker and remove the camera-forcing capture hint. Add a role-gated account action in the existing rescue H5; on click it copies the current same-origin bearer token into the admin console's existing session key before navigating to `/help-cat/admin/`. Backend authorization remains the security boundary.

**Tech Stack:** Static HTML/CSS/ES5 JavaScript, Python `unittest` contract tests, same-origin `sessionStorage`, Nginx static deployment.

## Global Constraints

- Preserve `type="file"` and `accept="image/*"`; the final input must not contain any `capture` attribute.
- Show the management action only for `ADMIN` and `SUPER_ADMIN`.
- Keep `zack` as the only `SUPER_ADMIN`; no backend role or API change is allowed.
- Store the handoff token only in same-origin `sessionStorage` under `help_cat_admin_token`; never put it in a URL, log, cookie, or persistent storage.
- If the admin token is expired or revoked, the existing admin console authentication check must return to its login view.
- Deploy only the three changed rescue assets after creating a production backup and verifying SHA-256 hashes.
- Access `175.178.41.19` directly without a proxy.

---

### Task 1: Restore the native mobile photo chooser

**Files:**
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `app/rescue/index.html`

**Interfaces:**
- Consumes: Browser-native `<input type="file">` behavior.
- Produces: `#cat-photo-file` with `accept="image/*"` and no `capture` attribute.

- [ ] **Step 1: Write the failing upload contract test**

Replace the upload assertions in `test_rescue_page_contains_auth_and_three_step_cat_flow` with:

```python
for text in ("登录", "注册", "cat-community", "cat-photo-file", 'accept="image/*"', "use-current-location", "location-fallback", "下一步", "上一步"):
    self.assertIn(text, html)
self.assertNotIn('capture=', html)
```

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/help-cat-pycache python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_rescue_page_contains_auth_and_three_step_cat_flow
```

Expected: FAIL because `capture="environment"` still exists in `app/rescue/index.html`.

- [ ] **Step 3: Remove the camera-forcing attribute**

Change the upload input to:

```html
<input id="cat-photo-file" type="file" accept="image/*">
```

Keep the visible copy “选择照片或拍摄” and the existing file type validation, preview, removal, and upload code unchanged.

- [ ] **Step 4: Run the focused test and verify it passes**

Run the Step 2 command again.

Expected: PASS.

- [ ] **Step 5: Commit the photo chooser fix**

```bash
git add tests/test_rescue_h5_contract.py app/rescue/index.html
git commit -m "Fix mobile photo selection"
```

---

### Task 2: Add a role-gated management console handoff

**Files:**
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/app.js`
- Modify: `app/rescue/styles.css`

**Interfaces:**
- Consumes: `HelpCatApi.token(): string`, `state.user.role`, admin console session key `help_cat_admin_token`.
- Produces: `isAdminRole(role): boolean`, hidden button `#admin-console-action`, navigation to `/help-cat/admin/`.

- [ ] **Step 1: Write the failing management entry contract test**

Add this method to `RescueH5ContractTests`:

```python
def test_admin_roles_get_same_session_management_entry(self):
    html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
    self.assertIn('id="admin-console-action"', html)
    self.assertIn('id="admin-console-action" type="button" hidden', html)
    for marker in (
        "function isAdminRole(role)",
        'role === "ADMIN" || role === "SUPER_ADMIN"',
        'byId("admin-console-action").hidden = !admin',
        'sessionStorage.setItem("help_cat_admin_token", api.token())',
        'window.location.assign("/help-cat/admin/")',
        'role === "SUPER_ADMIN" ? "超级管理员"',
        '"超级管理员账号 · 新建档案将直接公开"',
    ):
        self.assertIn(marker, script)
```

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/help-cat-pycache python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_admin_roles_get_same_session_management_entry
```

Expected: FAIL because the management button and role helper do not exist.

- [ ] **Step 3: Add the hidden management action markup**

Replace the account card's single action button with:

```html
<div class="account-actions">
  <button class="button secondary small" id="admin-console-action" type="button" hidden>进入管理后台</button>
  <button class="button primary small" id="account-action" type="button">登录 / 注册</button>
</div>
```

- [ ] **Step 4: Add role-aware rendering**

Add above `renderAccount`:

```javascript
function isAdminRole(role) {
  return role === "ADMIN" || role === "SUPER_ADMIN";
}
```

Replace the start of `renderAccount` through the account description assignment with:

```javascript
var signedIn = Boolean(state.user);
var role = signedIn ? state.user.role : "";
var admin = isAdminRole(role);
var fallbackName = role === "SUPER_ADMIN" ? "超级管理员" : (admin ? "管理员" : "志愿者");
var name = signedIn ? (state.user.username || fallbackName) : "志愿者账户";
var initial = name.slice(0, 1) || "志";
byId("profile-avatar").textContent = initial;
byId("profile-label").textContent = signedIn ? name : "登录";
byId("account-avatar").textContent = initial;
byId("account-name").textContent = name;
byId("account-description").textContent = !signedIn
  ? "登录后可以提交档案、查看审核状态和领取任务。"
  : role === "SUPER_ADMIN"
    ? "超级管理员账号 · 新建档案将直接公开"
    : role === "ADMIN"
      ? "管理员账号 · 新建档案将直接公开"
      : "志愿者账号 · 可提交档案并领取任务";
byId("admin-console-action").hidden = !admin;
```

Leave submission loading and logout button behavior unchanged.

- [ ] **Step 5: Add the same-session navigation handler**

Add beside the existing account action listener:

```javascript
byId("admin-console-action").addEventListener("click", function () {
  if (!state.user || !isAdminRole(state.user.role) || !api.token()) {
    openAuth();
    return;
  }
  sessionStorage.setItem("help_cat_admin_token", api.token());
  window.location.assign("/help-cat/admin/");
});
```

- [ ] **Step 6: Add responsive account action layout**

Add to the account card rules:

```css
.account-actions { display: grid; flex: 0 0 auto; gap: 8px; }
```

Inside `@media (max-width: 720px)`, replace the broad account button width rule with:

```css
.account-actions { width: 100%; }
.account-actions .button { width: 100%; }
```

- [ ] **Step 7: Run the focused and full H5 contract tests**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/help-cat-pycache python3 -m unittest tests.test_rescue_h5_contract
```

Expected: all H5 contract tests PASS.

- [ ] **Step 8: Commit the management entry**

```bash
git add tests/test_rescue_h5_contract.py app/rescue/index.html app/rescue/app.js app/rescue/styles.css
git commit -m "Add admin console entry"
```

---

### Task 3: Version assets, regress, publish, and deploy

**Files:**
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `app/rescue/index.html`
- Deploy: `/data/purchase-system/frontend/dist/help-cat/rescue/index.html`
- Deploy: `/data/purchase-system/frontend/dist/help-cat/rescue/styles.css`
- Deploy: `/data/purchase-system/frontend/dist/help-cat/rescue/app.js`

**Interfaces:**
- Consumes: Tasks 1 and 2 verified static assets.
- Produces: GitHub draft PR and updated production H5 at `http://175.178.41.19/help-cat/rescue/index.html`.

- [ ] **Step 1: Write the failing asset version contract**

Change `test_rescue_assets_are_versioned_in_dependency_order` to require:

```python
self.assertIn('styles.css?v=20260802-mobile-admin', html)
api_index = html.index('api.js?v=20260802-mobile-admin')
app_index = html.index('app.js?v=20260802-mobile-admin')
self.assertLess(api_index, app_index)
```

- [ ] **Step 2: Run the version test and verify the expected failure**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/help-cat-pycache python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_rescue_assets_are_versioned_in_dependency_order
```

Expected: FAIL because the page still uses `20260801-responsive`.

- [ ] **Step 3: Bump all rescue asset query versions**

In `app/rescue/index.html`, use `20260802-mobile-admin` for `styles.css`, `api.js`, and `app.js`.

- [ ] **Step 4: Run static syntax and all Help Cat tests**

Run:

```bash
node --check app/rescue/api.js
node --check app/rescue/app.js
node --check admin/app.js
PYTHONPYCACHEPREFIX=/tmp/help-cat-pycache python3 -m unittest server.tests.test_commercial_api tests.test_commercial_frontends tests.test_commercial_migrations tests.test_help_cat_qa_seed tests.test_help_cat_qa_cleanup tests.test_rescue_h5_contract
git diff --check
```

Expected: JavaScript syntax checks succeed, all Help Cat tests PASS, and `git diff --check` has no output.

- [ ] **Step 5: Commit and push the implementation branch**

```bash
git add tests/test_rescue_h5_contract.py app/rescue/index.html
git commit -m "Version mobile admin assets"
git push -u origin agent/mobile-upload-admin-entry
```

- [ ] **Step 6: Open a draft pull request**

Create a draft PR from `agent/mobile-upload-admin-entry` to `main` titled `Fix mobile upload and add admin entry`. Its body must state the capture root cause, role-gated token handoff, test commands, and production deployment status.

- [ ] **Step 7: Create a production backup and upload a staged release**

Run with the existing SSH configuration:

```bash
release_stamp=$(date +%Y%m%d-%H%M%S)-mobile-admin
ssh 175.178.41.19 "mkdir -p /opt/help-cat/backups/$release_stamp/rescue /opt/help-cat/releases/$release_stamp/rescue && cp -a /data/purchase-system/frontend/dist/help-cat/rescue/. /opt/help-cat/backups/$release_stamp/rescue/"
scp app/rescue/index.html app/rescue/styles.css app/rescue/app.js "175.178.41.19:/opt/help-cat/releases/$release_stamp/rescue/"
shasum -a 256 app/rescue/index.html app/rescue/styles.css app/rescue/app.js
ssh 175.178.41.19 "sha256sum /opt/help-cat/releases/$release_stamp/rescue/index.html /opt/help-cat/releases/$release_stamp/rescue/styles.css /opt/help-cat/releases/$release_stamp/rescue/app.js"
```

Expected: local and remote hashes match for every file. Do not copy staged files into production if any hash differs.

- [ ] **Step 8: Activate the staged static files and validate Nginx**

```bash
ssh 175.178.41.19 "cp /opt/help-cat/releases/$release_stamp/rescue/index.html /opt/help-cat/releases/$release_stamp/rescue/styles.css /opt/help-cat/releases/$release_stamp/rescue/app.js /data/purchase-system/frontend/dist/help-cat/rescue/ && sudo nginx -t"
```

Expected: Nginx configuration syntax is successful.

- [ ] **Step 9: Verify direct production responses and contracts**

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY curl -fsS http://175.178.41.19/help-cat/rescue/index.html | rg '20260802-mobile-admin|admin-console-action|accept="image/\*"'
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY curl -fsS http://175.178.41.19/help-cat/rescue/index.html | rg 'capture=' && exit 1 || true
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY curl -fsS http://175.178.41.19/help-cat-api/api/v1/health
```

Expected: the first command finds all new markers, the second finds no `capture`, and the health endpoint returns `status: ok`.

- [ ] **Step 10: Run production browser regression and close local services**

At desktop, tablet, and 390×844 mobile viewport sizes, verify no horizontal overflow, the guest account has no visible management action, the upload input has no `capture` attribute, and there are no console errors. Use automated contract coverage for admin role visibility and same-session token handoff. Stop every temporary local HTTP/API process immediately after validation.

- [ ] **Step 11: Roll back on any failed production check**

If Step 8, 9, or 10 fails, run:

```bash
ssh 175.178.41.19 "cp -a /opt/help-cat/backups/$release_stamp/rescue/. /data/purchase-system/frontend/dist/help-cat/rescue/ && sudo nginx -t"
```

Expected: previous static files are restored and Nginx syntax remains valid.
