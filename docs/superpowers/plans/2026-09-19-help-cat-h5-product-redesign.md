# Help Cat H5 Product Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the H5 home and core user path into a polished, large-product-style public experience while preserving the existing Help Cat business model and backend contracts.

**Architecture:** Keep the current static H5 architecture under `app/rescue/`: semantic HTML in `index.html`, presentational styling in `styles.css`, and runtime rendering in `app.js`. This iteration does not change database tables or API schemas; it tightens UI contracts, component states, responsive layout, and documentation.

**Tech Stack:** Static HTML/CSS/JavaScript, existing `window.HelpCatApi`, Python `unittest` H5 contract tests, Node runtime tests, existing image assets under `app/rescue/assets`.

## Global Constraints

- Do not rewrite the backend or change database schema in this round.
- Do not introduce a large frontend framework or build step.
- Preserve existing flows: login, cat profile creation, upload, community selection/candidate entry, public cat archive, rescue tasks, submissions, admin entry.
- Use real data only; do not hard-code public fake metrics or fake rescue counts.
- Module-level API failures must not create a persistent full-width top error strip on the home page.
- H5 structure should be reusable for the WeChat Mini Program information architecture.
- Every implementation round must update Markdown docs and commit to Git.
- Preserve user-owned untracked `.superpowers/brainstorm/`.

---

## File Structure

- Modify `tests/test_rescue_h5_contract.py`: add product-redesign contracts before implementation.
- Modify `app/rescue/index.html`: refine home semantic sections, CTAs, trust band, and stable module containers.
- Modify `app/rescue/styles.css`: add the final large-product visual system, responsive layout, stable image/card dimensions, and polished fallbacks.
- Modify `app/rescue/app.js`: render module-level failure states, richer task/card metadata, role-aware profile copy, and home CTAs without changing API contracts.
- Modify `app/rescue/version.js` only if cache version wiring requires a new release token.
- Modify `docs/wiki/变更记录.md`: record the H5 product redesign implementation.
- Modify `docs/wiki/功能清单与状态.md` only when Task 4 changes a listed feature status or known limitation.

---

### Task 1: Product Redesign Contracts

**Files:**
- Modify: `tests/test_rescue_h5_contract.py`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: existing static files under `app/rescue/`.
- Produces: failing contracts that later tasks satisfy.

- [ ] **Step 1: Add failing contract tests**

Append these tests to `RescueH5ContractTests` in `tests/test_rescue_h5_contract.py`:

```python
    def test_h5_redesign_has_public_product_path(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for marker in (
            'data-product-section="home-hero"',
            'data-product-section="primary-actions"',
            'data-product-section="cat-preview"',
            'data-product-section="task-preview"',
            'data-product-section="trust"',
            'id="home-create-cat"',
            'id="home-view-tasks"',
            'id="home-view-cats"',
            "让每一只小猫，",
            "为猫咪建档",
            "查看救助任务",
            "隐私保护",
            "社区审核",
        ):
            self.assertIn(marker, html)
        self.assertIn(".product-shell", styles)
        self.assertIn(".primary-action-grid", styles)
        self.assertIn("renderHomeModuleState", script)

    def test_h5_redesign_uses_module_level_fallbacks(self):
        html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
        for marker in (
            'id="home-cats-status"',
            'id="home-tasks-status"',
            'id="home-metrics-status"',
            "state.publicDataStatus",
            "cats: \"loading\"",
            "tasks: \"loading\"",
            "communities: \"loading\"",
            "renderHomeModuleState(\"cats\"",
            "renderHomeModuleState(\"tasks\"",
        ):
            self.assertIn(marker, html + script)
        self.assertNotIn('showStatus(errorText(error), true)', script)

    def test_h5_redesign_responsive_contracts_for_mobile_and_tablet(self):
        styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
        for marker in (
            "@media (max-width: 1024px)",
            "@media (max-width: 720px)",
            "@media (max-width: 360px)",
            "grid-template-columns: repeat(4, minmax(0, 1fr))",
            "aspect-ratio: 4 / 3",
            "padding-bottom: calc(112px + env(safe-area-inset-bottom))",
            "overflow-wrap: anywhere",
        ):
            self.assertIn(marker, styles)
        self.assertNotIn("font-size: 12vw", styles)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests -v
```

Expected: FAIL, with missing markers such as `data-product-section="primary-actions"` or `renderHomeModuleState`.

- [ ] **Step 3: Commit the red contracts**

```bash
git add tests/test_rescue_h5_contract.py
git commit -m "test: define h5 product redesign contracts"
```

---

### Task 2: Home Structure and Visual System

**Files:**
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/styles.css`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: existing `data-nav` navigation handlers in `app/rescue/app.js`.
- Produces: `#home-create-cat`, `#home-view-tasks`, `#home-view-cats`, `#home-cats-status`, `#home-tasks-status`, `#home-metrics-status`.

- [ ] **Step 1: Update the home HTML shell**

In `app/rescue/index.html`, keep the existing `data-view="home"` section but change the inner home structure to include these stable regions:

```html
<section class="reference-hero editorial-hero product-shell" data-product-section="home-hero">
  <div class="editorial-hero-copy">
    <h1 id="home-title">让每一只小猫，<br>都被认真看见</h1>
    <p class="editorial-deck">一份可信档案，连接社区里的每一次发现、照料与救助。</p>
    <div class="editorial-hero-actions">
      <button class="button primary" id="home-create-cat" type="button">为猫咪建档</button>
      <button class="button secondary" id="home-view-tasks" type="button" data-nav="tasks">查看救助任务</button>
      <button class="editorial-story-link" type="button" data-nav="story-77">77 的故事</button>
    </div>
  </div>
  <picture class="editorial-hero-visual">
    <source media="(max-width: 720px)" srcset="assets/77/hero-mobile.webp?v=20260816-image-cache-r2">
    <img src="assets/77/hero-desktop.webp?v=20260816-image-cache-r2" alt="77，一只白底黑斑的猫咪" width="960" height="720" decoding="async">
  </picture>
</section>

<section class="primary-action-grid" data-product-section="primary-actions" aria-label="快速开始">
  <button class="action-tile" type="button" id="home-view-cats" data-nav="cats">
    <span>猫咪档案</span><strong>查看已公开猫咪</strong>
  </button>
  <button class="action-tile" type="button" data-nav="tasks">
    <span>救助任务</span><strong>认领可帮助事项</strong>
  </button>
  <button class="action-tile" type="button" data-nav="profile">
    <span>我的提交</span><strong>查看审核进度</strong>
  </button>
</section>
```

Add `id="home-metrics-status"` near the metrics strip and `id="home-cats-status"` / `id="home-tasks-status"` near the corresponding home preview containers.

- [ ] **Step 2: Add trust section HTML**

After the home preview grid, add:

```html
<section class="trust-band" data-product-section="trust" aria-label="项目信任机制">
  <article><strong>隐私保护</strong><p>公开页面只展示模糊位置，精确位置默认不公开。</p></article>
  <article><strong>社区审核</strong><p>猫咪档案和新小区由管理员审核后再公开。</p></article>
  <article><strong>救助协作</strong><p>任务领取、档案更新和后台审核保留清晰状态。</p></article>
</section>
```

- [ ] **Step 3: Add visual CSS**

Append a final scoped block near the end of `app/rescue/styles.css`:

```css
/* Product redesign cascade: keep after legacy home rules. */
.product-shell {
  border-radius: 0;
  background: var(--hero-backdrop, #F5F1EB);
}
.product-shell .editorial-deck {
  max-width: 560px;
  color: rgba(23, 23, 23, .68);
  font-size: 17px;
  line-height: 1.8;
}
.primary-action-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 22px 0 34px;
}
.action-tile {
  display: grid;
  gap: 6px;
  min-height: 108px;
  padding: 20px;
  border: 1px solid rgba(29,29,31,.12);
  border-radius: 8px;
  background: #fff;
  color: var(--editorial-ink);
  text-align: left;
  cursor: pointer;
}
.action-tile span {
  color: var(--brand-dark);
  font-size: 12px;
  font-weight: 800;
}
.action-tile strong {
  font-size: 20px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.home-module-status {
  min-height: 22px;
  color: var(--muted);
  font-size: 12px;
}
.trust-band {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin: 28px 0 10px;
  border: 1px solid rgba(29,29,31,.1);
  background: rgba(29,29,31,.1);
}
.trust-band article {
  min-height: 128px;
  padding: 24px;
  background: #fff;
}
.trust-band strong {
  display: block;
  margin-bottom: 8px;
  color: var(--editorial-ink);
  font-size: 16px;
}
.trust-band p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
}
.cat-photo {
  aspect-ratio: 4 / 3;
}
@media (max-width: 1024px) {
  .primary-action-grid,
  .trust-band {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 720px) {
  .primary-action-grid,
  .trust-band {
    grid-template-columns: 1fr;
  }
  .product-shell .editorial-deck {
    font-size: 14px;
  }
  .action-tile {
    min-height: 84px;
  }
}
```

- [ ] **Step 4: Run contracts**

Run:

```bash
python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_h5_redesign_has_public_product_path -v
python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_h5_redesign_responsive_contracts_for_mobile_and_tablet -v
```

Expected: PASS after the HTML and CSS changes.

- [ ] **Step 5: Commit**

```bash
git add app/rescue/index.html app/rescue/styles.css
git commit -m "feat: reshape h5 public home experience"
```

---

### Task 3: Runtime State, CTAs, and Role Copy

**Files:**
- Modify: `app/rescue/app.js`
- Modify: `app/rescue/index.html` if hook IDs need adjustment
- Test: `tests/test_rescue_h5_contract.py`
- Test: `tests/js/*.test.js`

**Interfaces:**
- Consumes: DOM IDs from Task 2.
- Produces: `state.publicDataStatus`, `renderHomeModuleState(name, status, message)`, click handlers for `#home-create-cat`, `#home-view-tasks`, `#home-view-cats`.

- [ ] **Step 1: Add public data status state**

In the top-level `state` object in `app/rescue/app.js`, add:

```javascript
    publicDataStatus: {
      communities: "loading",
      cats: "loading",
      tasks: "loading"
    },
```

- [ ] **Step 2: Add module state renderer**

Add this helper after `renderMetrics()`:

```javascript
  function renderHomeModuleState(name, status, message) {
    var target = byId("home-" + name + "-status");
    if (!target) return;
    target.textContent = message || "";
    target.dataset.state = status || "ready";
    target.hidden = !message;
  }
```

When metrics fail in `renderMetrics()`, set `home-metrics-status` to `公开指标暂时无法获取，其他内容可继续查看。`.

- [ ] **Step 3: Make public data loading independent**

Replace the `Promise.all` logic in `loadPublicData()` with independent requests:

```javascript
  function loadPublicData() {
    showStatus("", false);
    state.publicDataStatus = { communities: "loading", cats: "loading", tasks: "loading" };
    renderHomeModuleState("cats", "loading", "正在加载猫咪档案…");
    renderHomeModuleState("tasks", "loading", "正在加载救助任务…");

    var communities = api.request("/api/v1/communities?limit=24").then(function (payload) {
      state.communities = payload.items || [];
      state.cursors.communities = payload.next_cursor || null;
      state.publicDataStatus.communities = "ready";
      renderCommunityOptions();
    }).catch(function (error) {
      state.publicDataStatus.communities = "error";
      toast(errorText(error));
    });

    var cats = api.request("/api/v1/cats?limit=24").then(function (payload) {
      state.cats = payload.items || [];
      state.cursors.cats = payload.next_cursor || null;
      state.publicDataStatus.cats = "ready";
      renderHomeModuleState("cats", "ready", "");
      renderCats();
    }).catch(function () {
      state.publicDataStatus.cats = "error";
      renderHomeModuleState("cats", "error", "猫咪档案暂时无法获取，请稍后重试。");
      renderCats();
    });

    var tasks = api.request("/api/v1/tasks?limit=24").then(function (payload) {
      state.tasks = payload.items || [];
      state.cursors.tasks = payload.next_cursor || null;
      state.publicDataStatus.tasks = "ready";
      renderHomeModuleState("tasks", "ready", "");
      renderTasks();
    }).catch(function () {
      state.publicDataStatus.tasks = "error";
      renderHomeModuleState("tasks", "error", "救助任务暂时无法获取，请稍后重试。");
      renderTasks();
    });

    return Promise.all([communities, cats, tasks]).then(function () {
      renderApp();
    });
  }
```

- [ ] **Step 4: Wire home CTAs**

In the existing event binding setup, add handlers:

```javascript
    var createCat = byId("home-create-cat");
    if (createCat) createCat.addEventListener("click", function () { openCatSheet(); });
    var viewTasks = byId("home-view-tasks");
    if (viewTasks) viewTasks.addEventListener("click", function () { navigate("tasks"); });
    var viewCats = byId("home-view-cats");
    if (viewCats) viewCats.addEventListener("click", function () { navigate("cats"); });
```

Use the existing `openCatSheet()` and `navigate(view)` functions already defined in `app/rescue/app.js`; do not add a duplicate create-cat flow.

- [ ] **Step 5: Improve role-aware account copy**

Keep existing role detection but ensure the rendered text distinguishes:

```javascript
// USER: "可提交档案、查看审核状态和领取任务。"
// ADMIN: "管理员账号，可审核猫咪、小区和救助任务。"
// SUPER_ADMIN: "超级管理员账号，可进入后台管理用户权限和审核流程。"
```

- [ ] **Step 6: Run runtime and contract tests**

Run:

```bash
python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_h5_redesign_uses_module_level_fallbacks -v
node --test tests/js/*.test.js
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/rescue/app.js app/rescue/index.html tests/test_rescue_h5_contract.py
git commit -m "feat: add resilient h5 home runtime states"
```

---

### Task 4: Full Verification, Docs, and Release Token

**Files:**
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/version.js`
- Modify: `app/rescue/manifest.webmanifest`
- Modify: `docs/wiki/变更记录.md`
- Modify: `docs/wiki/功能清单与状态.md` when a listed feature status or known limitation changes
- Test: Python and Node suites

**Interfaces:**
- Consumes: completed UI/runtime changes.
- Produces: release-ready static H5 with a new cache token.

- [ ] **Step 1: Set release token**

Use release token:

```text
20260919-h5-product-redesign-r1
```

Update every `20260816-image-cache-r2` static asset query in:

```text
app/rescue/index.html
app/rescue/version.js
app/rescue/manifest.webmanifest
```

Keep the HTML root:

```html
<html lang="zh-CN" data-app-version="20260919-h5-product-redesign-r1">
```

- [ ] **Step 2: Update changelog**

Append this entry to `docs/wiki/变更记录.md`:

```markdown
## 2026-09-19 H5 产品体验重构第一轮

- 重构 H5 首页信息架构，强化 77 故事、猫咪建档、猫咪档案和救助任务四条主路径。
- 新增首页快速行动区和项目信任区，保持普通用户与管理员入口分层。
- 将首页公开数据加载调整为模块级降级，避免单个接口失败破坏首屏。
- 更新响应式合同，覆盖手机、平板和桌面基础布局要求。
```

- [ ] **Step 3: Run full local gates**

Run:

```bash
git diff --check
python3 -m unittest discover -s server/tests -v
python3 -m unittest discover -s tests -v
node --test tests/js/*.test.js
node --check app/rescue/app.js
node --check app/rescue/api.js
node --check app/rescue/community-form.js
node --check app/rescue/story-77.js
node --check app/rescue/version.js
```

Expected: all pass, except the known Alembic environment skip if it still appears in the general suite.

- [ ] **Step 4: Run H5 release gate**

Run:

```bash
python3 /Users/mac_1/.codex/skills/help-cat-production-deploy/scripts/check_h5_release.py \
  --root /Users/mac_1/Documents/Codex/2026-07-25/sop/.worktrees/mobile-upload-admin-entry/app/rescue \
  --version 20260919-h5-product-redesign-r1
```

Expected: `H5 release gate passed`.

- [ ] **Step 5: Capture local responsive screenshots**

Serve the page locally from the repo root:

```bash
python3 -m http.server 8765 --directory /Users/mac_1/Documents/Codex/2026-07-25/sop/.worktrees/mobile-upload-admin-entry
```

Use Playwright or the in-app browser to capture:

```text
1440x900: http://127.0.0.1:8765/app/rescue/index.html
390x844:  http://127.0.0.1:8765/app/rescue/index.html
```

Expected visual checks:

- Desktop: no top error strip, brand visible, hero and CTAs visible, next section visible.
- Mobile: no horizontal scroll, bottom nav does not cover CTAs, 77 image and headline do not overlap.
- Cat cards: stable image dimensions and no broken image icon.
- Task preview: readable title, location, and action.

- [ ] **Step 6: Commit documentation and release token**

```bash
git add app/rescue/index.html app/rescue/version.js app/rescue/manifest.webmanifest docs/wiki/变更记录.md docs/wiki/功能清单与状态.md tests/test_rescue_h5_contract.py
git commit -m "chore: prepare h5 product redesign release"
```

- [ ] **Step 7: Push and deploy only after all gates pass**

Push through the GitHub proxy only:

```bash
GIT_TERMINAL_PROMPT=0 git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 push --verbose origin agent/mobile-upload-admin-entry
```

Deploy with `help-cat-production-deploy` using release:

```text
20260919-h5-product-redesign-r1
```

Expected public result:

- IP entry returns HTTP 200 and includes `data-app-version="20260919-h5-product-redesign-r1"`.
- API health path remains OK through the public IP entry.
- If `https://helpcat.xyz/` still resets, report it as domain/ICP/edge blocker rather than code failure.

---

## Self-Review

- Spec coverage: Tasks cover H5 home structure, CTAs, cat/task preview, module failures, profile role copy, responsive requirements, docs, Git, and release token. Backend rewrite, database migration, CDN, donation, and Mini Program publishing are intentionally excluded per spec.
- Placeholder scan: No `TBD`, `TODO`, or unspecified implementation steps remain.
- Type consistency: The plan consistently uses `state.publicDataStatus`, `renderHomeModuleState(name, status, message)`, `#home-create-cat`, `#home-view-tasks`, and `#home-view-cats`.
