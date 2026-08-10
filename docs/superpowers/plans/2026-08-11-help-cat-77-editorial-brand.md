# 帮帮小猫「77」高级公益编辑风 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将确认的 77 高级公益编辑风落地到帮帮小猫 H5，交付统一品牌图标、响应式首页、可分享的 77 故事页、真实 77 档案、质量门禁和可回滚上线版本。

**Architecture:** 保留现有无框架 H5 和 FastAPI/SQLAlchemy 架构，在现有 hash 视图路由中新增 `story-77`，把故事内容和路由行为拆到独立前端模块。品牌符号使用单一 SVG 源文件派生 favicon；77 的平台档案继续走现有媒体与猫咪 API，通过幂等脚本创建，不把私有信息写入静态页面。

**Tech Stack:** HTML5、CSS3、原生 JavaScript、Node `node:test`、Python `unittest`、FastAPI、SQLAlchemy、SQLite、SVG、WebP/AVIF、Nginx/HTTPS。

## Global Constraints

- 页面底色 `#F7F5F1`，主文字 `#171717`，品牌强调 `#D9683A`，鼻尖 `#D99386`。
- 浏览器可分享路由固定为 `#story-77`；不得使用弹窗或新窗口打开故事。
- 77 相遇日期固定为 `2025-06-02`，命名来源为农历五月初七。
- 77 的性别、绝育、疫苗、健康和所在地等未确认字段不得从照片推断。
- 所有公开图片必须移除 EXIF；远程资源使用 HTTPS；首屏不自动播放视频。
- 点击目标不小于 44×44 CSS 像素，并支持 `prefers-reduced-motion`。
- 首页指标只使用真实公开数据，不使用概念图中的演示数字或 QA 数据。
- 现有管理员、猫咪建档、小区审核、任务和登录流程不得回归。
- 每个任务遵循测试先行，测试失败后再写实现；每个任务独立提交。

---

## File Map

**Create**

- `app/rescue/assets/brand/helpcat-77-mark.svg`：唯一品牌矢量源文件。
- `app/rescue/assets/brand/favicon.svg`：favicon 入口，内容与品牌源文件同步。
- `app/rescue/assets/brand/apple-touch-icon.png`：iOS 主屏图标。
- `app/rescue/assets/brand/icon-192.png`、`icon-512.png`：PWA/未来小程序素材。
- `app/rescue/assets/77/hero-desktop.webp`、`hero-mobile.webp`、`rescue-day.webp`、`grown-up.webp`、`resting.webp`：移除元数据后的公开衍生图。
- `app/rescue/manifest.webmanifest`：浏览器图标、主题色和显示模式。
- `app/rescue/story-77.js`：故事内容模型、故事渲染和 CTA 行为。
- `tests/js/rescue_story_77_runtime.test.js`：故事模块运行时测试。
- `scripts/help_cat_77_seed.py`：幂等创建/更新 77 真实档案与媒体。
- `tests/test_help_cat_77_seed.py`：77 档案脚本测试。

**Modify**

- `app/rescue/index.html`：favicon/manifest、编辑式首页、故事视图和入口。
- `app/rescue/styles.css`：设计令牌、编辑式首页、故事页与响应式样式。
- `app/rescue/app.js`：支持 `story-77` 路由、浏览历史和滚动恢复。
- `app/rescue/version.js`：静态资源版本更新。
- `tests/test_rescue_h5_contract.py`：品牌、故事、可访问性和素材契约。
- `docs/wiki/功能清单与状态.md`：记录已实现范围。
- `docs/wiki/变更记录.md`：记录发布内容。
- `docs/wiki/测试与质量保障.md`：补充多设备与 favicon 验证。

---

### Task 1: 77 品牌符号与浏览器图标

**Files:**
- Create: `app/rescue/assets/brand/helpcat-77-mark.svg`
- Create: `app/rescue/assets/brand/favicon.svg`
- Create: `app/rescue/assets/brand/apple-touch-icon.png`
- Create: `app/rescue/assets/brand/icon-192.png`
- Create: `app/rescue/assets/brand/icon-512.png`
- Create: `app/rescue/manifest.webmanifest`
- Modify: `app/rescue/index.html`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Produces: stable asset URLs under `assets/brand/`; `<link rel="icon">`, `<link rel="apple-touch-icon">`, `<link rel="manifest">`.
- Consumes: confirmed 77 visual rule: white cat face, observer-right black eye patch, pink nose.

- [ ] **Step 1: Write the failing favicon contract test**

Add to `tests/test_rescue_h5_contract.py`:

```python
def test_77_brand_assets_and_manifest_are_wired(self):
    page = (ROOT / "app/rescue/index.html").read_text()
    for marker in (
        'rel="icon" href="assets/brand/favicon.svg"',
        'rel="apple-touch-icon" href="assets/brand/apple-touch-icon.png"',
        'rel="manifest" href="manifest.webmanifest"',
        'class="brand-logo brand-logo-77"',
    ):
        self.assertIn(marker, page)
    svg = (ROOT / "app/rescue/assets/brand/helpcat-77-mark.svg").read_text()
    self.assertIn('viewBox="0 0 64 64"', svg)
    self.assertIn('aria-labelledby="helpcat-77-title"', svg)
    manifest = json.loads((ROOT / "app/rescue/manifest.webmanifest").read_text())
    self.assertEqual(manifest["name"], "帮帮小猫")
    self.assertEqual({icon["sizes"] for icon in manifest["icons"]}, {"192x192", "512x512"})
```

Ensure the test file imports `json`.

- [ ] **Step 2: Run the test and verify failure**

Run: `python -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_77_brand_assets_and_manifest_are_wired -v`

Expected: FAIL because `helpcat-77-mark.svg` and manifest links do not exist.

- [ ] **Step 3: Create the accessible SVG source**

Create a 64×64 SVG with: rounded white face, two triangular ears, black patch over the viewer-right eye, two dark eyes, and a `#D99386` triangular nose. Use `stroke="#171717"`, `stroke-width="1.5"`, round joins, and title `77 极简黑眼斑猫咪标志`. Copy the same geometry to `favicon.svg`.

- [ ] **Step 4: Generate raster sizes and manifest**

Use the workspace image runtime or macOS `sips` to render exact 180, 192, and 512 PNG outputs. Create:

```json
{
  "name": "帮帮小猫",
  "short_name": "帮帮小猫",
  "start_url": "./index.html#home",
  "display": "standalone",
  "background_color": "#F7F5F1",
  "theme_color": "#F7F5F1",
  "icons": [
    {"src": "assets/brand/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "assets/brand/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

Wire the three `<link>` elements into `<head>` and replace CSS-only logo instances with `.brand-logo-77` elements using the SVG as their background image.

- [ ] **Step 5: Verify icon sizes and tests**

Run:

```bash
file app/rescue/assets/brand/*.png
python -m unittest tests.test_rescue_h5_contract -v
```

Expected: PNG files report 180×180, 192×192, 512×512 respectively; all H5 contract tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/rescue/assets/brand app/rescue/manifest.webmanifest app/rescue/index.html tests/test_rescue_h5_contract.py
git commit -m "feat: add 77 brand mark and browser icons"
```

---

### Task 2: 编辑式首页骨架与真实指标

**Files:**
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/styles.css`
- Modify: `app/rescue/app.js`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: existing `state.cats`, `state.tasks`, `state.communities` loaded by `loadPublicData()`.
- Produces: `renderMetrics(): void` using only public API collections; hero entry with `data-nav="story-77"`.

- [ ] **Step 1: Write failing homepage structure tests**

Add assertions requiring `editorial-hero`, exact headline `让每一只小猫，<br>都被认真看见`, `data-nav="story-77"`, `metric-communities`, `home-cats`, and `home-tasks`. Assert the old English region chip and CSS-only `hero-mark` no longer occur.

- [ ] **Step 2: Run the contract test and verify failure**

Run: `python -m unittest tests.test_rescue_h5_contract -v`

Expected: FAIL on missing editorial hero and story entry.

- [ ] **Step 3: Replace the home hero and metric markup**

Build semantic `<section class="editorial-hero">` with text, a `<picture>` for 77, and a real button/link carrying `data-nav="story-77"`. Keep existing IDs for cat/task lists so current rendering continues to work. Use metric IDs `metric-cats`, `metric-tasks`, and `metric-communities`; label them “公开猫咪”“开放任务”“覆盖小区”.

- [ ] **Step 4: Implement real metric rendering**

In `app.js`, make `renderMetrics()` set counts from deduplicated public collections and call it after each public data load. Do not introduce hard-coded counts. Use `Intl.NumberFormat("zh-CN")` with a plain-number fallback.

- [ ] **Step 5: Add editorial responsive styling**

Define CSS tokens from Global Constraints, create desktop two-column hero, tablet proportions, and phone stacked/overlaid composition. Preserve 44px targets, visible focus, reduced motion, existing sheets and admin entry behavior.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
python -m unittest tests.test_rescue_h5_contract -v
node --check app/rescue/app.js
```

Expected: PASS and no syntax output.

```bash
git add app/rescue/index.html app/rescue/styles.css app/rescue/app.js tests/test_rescue_h5_contract.py
git commit -m "feat: build editorial help cat homepage"
```

---

### Task 3: 可分享的 77 故事路由与浏览器返回

**Files:**
- Create: `app/rescue/story-77.js`
- Create: `tests/js/rescue_story_77_runtime.test.js`
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/app.js`
- Modify: `app/rescue/styles.css`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Produces: `window.HelpCatStory77.render(container, actions)` and route name `story-77`.
- `actions.openCats(): void`, `actions.openCreateCat(): void`, `actions.backHome(): void` are injected by `app.js`.
- Consumes: normal `data-nav` click delegation and existing cat sheet opening function.

- [ ] **Step 1: Write failing runtime tests**

Create a Node VM test that loads `story-77.js` and asserts:

```javascript
assert.equal(typeof sandbox.window.HelpCatStory77.render, "function");
const html = sandbox.window.HelpCatStory77.renderToString();
assert.match(html, /2025 年 6 月 2 日/);
assert.match(html, /农历五月初七/);
assert.match(html, /从 77 到每一只小猫/);
assert.match(html, /data-story-action="cats"/);
assert.match(html, /data-story-action="create-cat"/);
```

- [ ] **Step 2: Run and verify failure**

Run: `node --test tests/js/rescue_story_77_runtime.test.js`

Expected: FAIL with missing `story-77.js`.

- [ ] **Step 3: Implement the story content module**

Create an IIFE exposing `renderToString()` and `render(container, actions)`. Store the six approved chapter titles and copy in one immutable array. Escape dynamic strings; do not use user-provided HTML. Bind action buttons by `data-story-action`.

- [ ] **Step 4: Add the story view and route behavior**

Add `<section class="view story-view" data-view="story-77" hidden>` with a render root. Extend valid views to include `story-77`. Change navigation from `replaceState` to `pushState` for user-initiated route changes, listen to `hashchange`, and store `homeScrollY` before entering the story. `backHome()` restores the stored position without smooth scrolling when reduced motion is requested.

While `story-77` is active: hide bottom navigation and floating add button; show a 44px “返回首页” control. All other routes retain existing behavior.

- [ ] **Step 5: Add story styles and contract assertions**

Implement a restrained timeline, alternating image/text sections on desktop and a single column on phones. Add contract assertions for `story-77.js`, `#story-77`, “返回首页”, and the two CTAs.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
node --test tests/js/rescue_story_77_runtime.test.js
node --check app/rescue/app.js
python -m unittest tests.test_rescue_h5_contract -v
```

Expected: all PASS.

```bash
git add app/rescue/story-77.js app/rescue/index.html app/rescue/app.js app/rescue/styles.css tests/js/rescue_story_77_runtime.test.js tests/test_rescue_h5_contract.py
git commit -m "feat: add shareable 77 story experience"
```

---

### Task 4: 77 公开媒体处理与隐私门禁

**Files:**
- Create: `app/rescue/assets/77/hero-desktop.webp`
- Create: `app/rescue/assets/77/hero-mobile.webp`
- Create: `app/rescue/assets/77/rescue-day.webp`
- Create: `app/rescue/assets/77/grown-up.webp`
- Create: `app/rescue/assets/77/resting.webp`
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/story-77.js`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Produces: fixed public media names consumed by homepage and story module.
- Consumes: user-supplied 77 sources; source files remain outside Git, only sanitized derivatives are committed.

- [ ] **Step 1: Add failing media contracts**

Assert each expected derivative exists, is below 450 KiB, and that HTML/JS references all five paths. Assert hero `<img>` has explicit width, height, `alt="77，一只白底黑斑的猫咪"`, and story images use non-empty alt text.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_rescue_h5_contract -v`

Expected: FAIL because sanitized derivatives do not exist.

- [ ] **Step 3: Produce sanitized derivatives**

Use these supplied sources as candidates:

- Rescue day: `/var/folders/0r/7qxrq2wn1nj23d0f2yc_14dw0000gp/T/codex-clipboard-16d21af3-4984-4de4-88dd-6d3a149a4202.jpg`
- Adult portrait: `/var/folders/0r/7qxrq2wn1nj23d0f2yc_14dw0000gp/T/codex-clipboard-ae6b6eb7-7e44-4fe2-b785-fc2f385fe576.jpg`
- Resting portrait: `/var/folders/0r/7qxrq2wn1nj23d0f2yc_14dw0000gp/T/codex-clipboard-39078160-94b8-4da1-ad81-8b5c0a882c37.jpg`

Crop out identifiable people and private details. Export WebP with metadata stripped: desktop hero max 1920×1080, mobile hero max 960×1280, story images max 1280px long edge. Verify `exiftool` reports no GPS, camera serial, creator, or original timestamp fields.

- [ ] **Step 4: Wire responsive pictures**

Use `<picture>` and explicit dimensions in the homepage. Story images use `loading="lazy"` except the first story image. Do not autoplay or preload videos.

- [ ] **Step 5: Verify and commit**

Run:

```bash
du -h app/rescue/assets/77/*
exiftool -gps:all -serialnumber -creator app/rescue/assets/77/*
python -m unittest tests.test_rescue_h5_contract -v
```

Expected: every file under 450 KiB, EXIF command returns no sensitive values, tests PASS.

```bash
git add app/rescue/assets/77 app/rescue/index.html app/rescue/story-77.js tests/test_rescue_h5_contract.py
git commit -m "feat: add privacy-safe 77 story media"
```

---

### Task 5: 幂等写入 77 的真实平台档案

**Files:**
- Create: `scripts/help_cat_77_seed.py`
- Create: `tests/test_help_cat_77_seed.py`
- Modify: `docs/wiki/核心业务流程.md`

**Interfaces:**
- Produces CLI: `python scripts/help_cat_77_seed.py --base-url URL --username USER --password-env HELP_CAT_77_PASSWORD --community-id ID --photo PATH`.
- Returns exit code 0 and JSON containing `cat_id`, `media_id`, and `changed`.
- Consumes existing login, image upload, cat create, admin review, visibility and cat-list APIs.

- [ ] **Step 1: Write failing idempotency tests**

Build a fake HTTP client fixture and assert two invocations create one media asset and one cat. Expected create payload:

```python
{
    "community_id": "community-77",
    "nickname": "77",
    "living_status": "已进入家庭",
    "health_status": "UNKNOWN",
    "location_note": "公开位置已保护；2025-06-02 相遇",
    "photo_asset_id": "media-77",
}
```

Assert the script never supplies gender, vaccine, sterilization, exact address, latitude, or longitude.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_help_cat_77_seed -v`

Expected: FAIL because the module is missing.

- [ ] **Step 3: Implement the script**

Follow the HTTP and error-handling patterns in `scripts/help_cat_qa_seed.py`, but do not reuse the QA prefix or cleanup manifest. Authenticate using the named environment variable, upload one approved portrait, search public/admin cats for the stable marker `2025-06-02 相遇`, create only if absent, and require an ADMIN or SUPER_ADMIN account for review.

Do not place passwords or tokens in arguments, files, logs, Git history, or JSON output.

- [ ] **Step 4: Run tests and a dry production read**

Run:

```bash
python -m unittest tests.test_help_cat_77_seed -v
python scripts/help_cat_77_seed.py --help
```

Expected: tests PASS; help prints required options without accessing the network.

- [ ] **Step 5: Commit**

```bash
git add scripts/help_cat_77_seed.py tests/test_help_cat_77_seed.py docs/wiki/核心业务流程.md
git commit -m "feat: add idempotent 77 profile importer"
```

Production execution happens only in the release task after a backup and explicit verification of community ID and approved public image.

---

### Task 6: 手机、平板、可访问性与缓存版本

**Files:**
- Modify: `app/rescue/styles.css`
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/version.js`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: all visual components from Tasks 1–4.
- Produces: stable layouts at 360×800, 390×844, 768×1024, 1024×768, 1440×900; version key `20260811-77-editorial-r1`.

- [ ] **Step 1: Add failing responsive/accessibility contracts**

Assert the stylesheet contains `env(safe-area-inset-bottom)`, `prefers-reduced-motion`, story phone/tablet breakpoints, visible `:focus-visible`, and no `100vw` page containers. Assert every story control is a real `<button>` or `<a>`.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_rescue_h5_contract -v`

Expected: FAIL for missing story-specific responsive rules/version.

- [ ] **Step 3: Complete responsive and accessibility CSS**

At phone sizes use a single-column story and two-column cat cards; at tablet sizes use a three-column archive and two-column story where content permits; desktop uses constrained max-width. Ensure bottom safe area, no horizontal overflow, 44px controls, AA contrast, focus indicators and reduced-motion overrides.

- [ ] **Step 4: Bump asset version consistently**

Set `data-app-version`, CSS/JS query strings and `version.js` current value to `20260811-77-editorial-r1`. Include `story-77.js` with the same version query.

- [ ] **Step 5: Run gates and commit**

Run:

```bash
python -m unittest tests.test_rescue_h5_contract -v
node --check app/rescue/app.js
node --check app/rescue/story-77.js
git diff --check
```

Expected: all PASS/no output for syntax and diff checks.

```bash
git add app/rescue/index.html app/rescue/styles.css app/rescue/version.js tests/test_rescue_h5_contract.py
git commit -m "fix: harden 77 experience across devices"
```

---

### Task 7: 全量回归、文档与生产发布

**Files:**
- Modify: `docs/wiki/功能清单与状态.md`
- Modify: `docs/wiki/变更记录.md`
- Modify: `docs/wiki/测试与质量保障.md`

**Interfaces:**
- Consumes: completed feature branch and current production deployment procedure.
- Produces: pushed Git commit, backed-up deployment, live 77 route/favicon/profile, verification evidence and rollback path.

- [ ] **Step 1: Run the complete local quality gate**

Run:

```bash
python -m unittest discover -v
node --test tests/js/*.test.js
for file in app/rescue/*.js admin/*.js miniapp/**/*.js; do node --check "$file"; done
git diff --check
```

Expected: all Python and Node tests PASS; all syntax checks and diff check exit 0.

- [ ] **Step 2: Perform visual/device verification**

Serve the H5 only for the duration of verification. Capture and inspect screenshots at 390×844, 768×1024, 1024×768 and 1440×900. Verify:

- favicon shows the 77 black-eye-patch symbol after a cache-busting reload;
- hero never crops both eyes or the black patch;
- `#story-77` loads directly and browser Back returns correctly;
- story CTA opens cat archive and cat creation respectively;
- logged-in SUPER_ADMIN still sees “进入管理后台”;
- photo picker still opens the album and does not force camera capture;
- no horizontal scroll, clipped text or bottom-nav overlap.

Stop the local server immediately after screenshots so no unused Node process remains.

- [ ] **Step 3: Update the wiki**

Record the exact route, brand asset source, media privacy rules, responsive coverage, 77 seed command (without credentials), test commands and rollback method. Mark微信小程序正式发布 as not implemented.

- [ ] **Step 4: Commit and push the verified branch**

```bash
git add docs/wiki/功能清单与状态.md docs/wiki/变更记录.md docs/wiki/测试与质量保障.md
git commit -m "docs: record 77 editorial release"
git push origin agent/mobile-upload-admin-entry
```

Expected: push succeeds and remote branch contains all feature commits.

- [ ] **Step 5: Back up production and deploy code/media**

On the server, create a timestamped backup of the current H5, admin files, API code, database and uploaded-media metadata before replacing anything. Deploy to a new version directory, install only declared dependencies, run migrations, health check and tests, then atomically switch the active symlink or Nginx root. Do not overwrite the sole live copy in place.

- [ ] **Step 6: Create 77 profile after backup**

Resolve and print the target ACTIVE community name/ID with a read-only request. Then run the idempotent importer with the password supplied only through `HELP_CAT_77_PASSWORD`. Review the returned cat in the admin UI before making it public. Run the importer a second time and verify `changed` is false.

- [ ] **Step 7: Execute production smoke tests**

Verify with direct, no-proxy requests and a real browser:

```bash
curl -fsS https://helpcat.xyz/api/v1/health
curl -fsSI https://helpcat.xyz/assets/brand/favicon.svg
curl -fsSI https://helpcat.xyz/assets/77/hero-mobile.webp
curl -fsS https://helpcat.xyz/ | grep '20260811-77-editorial-r1'
```

Expected: health JSON has `"status":"ok"`; assets and homepage return 200; version marker is present. Then open `https://helpcat.xyz/#story-77` and verify the complete interaction checklist from Step 2.

- [ ] **Step 8: Roll back on any failed critical check**

If health, login, admin entry, cat creation, direct story route, favicon/media, or mobile layout fails, immediately restore the previous application symlink/root and database/media backup. Record the failed check and do not claim release completion until the full smoke suite passes.

---

## Final Self-Review Checklist

- Spec coverage: brand mark, favicon, editorial home, real metrics, story route/content, 77 archive, privacy, responsive behavior, accessibility, tests, documentation, release and rollback each map to a task above.
- Placeholder scan: no TBD/TODO or undefined “implement later” work remains.
- Type consistency: route is always `story-77`; story interface is always `window.HelpCatStory77`; version is always `20260811-77-editorial-r1`; importer output uses `cat_id`, `media_id`, `changed`.
- Scope: payment, donation, AI health inference and formal mini-program release remain explicitly excluded.

