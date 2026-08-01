# Help Cat Role and Community Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 H5 稳定识别管理员角色、清晰开放小区新增与审核流程，并提示长时间打开页面的版本更新。

**Architecture:** 保留现有 FastAPI 权限和社区状态机，把缺口限制在 H5 的角色感知渲染、小区入口与版本检测。权限仍由后端校验；前端只负责正确展示和导航。HTML 携带应用版本，运行中的页面只提示刷新而不强制丢弃表单。

**Tech Stack:** 原生 HTML/CSS/JavaScript、FastAPI、SQLAlchemy、Python `unittest`、Nginx。

## Global Constraints

- `USER` 新增小区必须为 `PENDING_REVIEW`。
- `ADMIN` 和 `SUPER_ADMIN` 新增小区必须立即为 `ACTIVE`。
- 未知角色按 `USER` 最小权限展示。
- 页面检测到新版本只提示刷新，不自动清空表单。
- 普通用户不能看到管理后台入口。
- 生产发布必须先备份，再比较本地、release 和生产 SHA-256。

---

### Task 1: 锁定角色与小区交互合同

**Files:**
- Modify: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: 现有 `app/rescue/index.html`、`app/rescue/app.js`、`app/rescue/styles.css`。
- Produces: H5 角色、小区快捷入口和版本提示的静态合同。

- [ ] **Step 1: 写入失败测试**

新增以下断言：

```python
def test_role_aware_community_entry_and_version_notice(self):
    html = (ROOT / "app" / "rescue" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "rescue" / "styles.css").read_text(encoding="utf-8")
    for marker in (
        'data-app-version="20260802-community-quality"',
        'id="open-community-form"',
        'id="community-section-title"',
        'id="community-section-description"',
        'id="community-submit"',
        'id="version-update"',
        'id="reload-version"',
    ):
        self.assertIn(marker, html)
    for marker in (
        "function normalizedRole(role)",
        "function renderCommunityEntry()",
        "function checkForUpdate()",
        'fetch(window.location.pathname, { cache: "no-store" })',
        'document.addEventListener("visibilitychange"',
    ):
        self.assertIn(marker, script)
    self.assertIn(".version-update", styles)
```

扩充现有管理员合同，要求 `ADMIN` 与 `SUPER_ADMIN` 都通过统一角色函数显示后台入口。

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/help-cat-role-community-pycache python3 -m unittest tests.test_rescue_h5_contract -v
```

Expected: 新测试因版本标记、小区快捷入口或更新提示不存在而失败。

- [ ] **Step 3: 提交测试红灯**

```bash
git add tests/test_rescue_h5_contract.py
git commit -m "Test role-aware community flow"
```

---

### Task 2: 实现角色规范化与小区快捷入口

**Files:**
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/app.js`
- Modify: `app/rescue/styles.css`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: `HelpCatApi.request()`、`navigate(view)`、`closeSheets()`、`loadPublicData()`。
- Produces: `normalizedRole(role) -> "USER" | "ADMIN" | "SUPER_ADMIN"`、`renderCommunityEntry()`。

- [ ] **Step 1: 在猫咪第二步增加入口并给小区卡片加可更新节点**

在 `#cat-community` 后加入：

```html
<button class="inline-link" id="open-community-form" type="button">没有找到小区？提交小区建议</button>
```

把小区卡片标题、说明和按钮分别增加稳定 ID：

```html
<h2 id="community-section-title">没有找到小区？</h2>
<p id="community-section-description">提交建议后由管理员审核...</p>
<button class="button secondary" id="community-submit" type="submit">提交小区建议</button>
```

- [ ] **Step 2: 统一角色判断**

在 `app.js` 中实现：

```javascript
function normalizedRole(role) {
  var value = String(role || "USER").toUpperCase();
  return ["ADMIN", "SUPER_ADMIN"].indexOf(value) >= 0 ? value : "USER";
}

function isAdminRole(role) {
  return ["ADMIN", "SUPER_ADMIN"].indexOf(normalizedRole(role)) >= 0;
}
```

所有账号文案、后台入口、小区提示统一使用 `normalizedRole()`。

- [ ] **Step 3: 实现角色感知小区文案**

```javascript
function renderCommunityEntry() {
  var admin = Boolean(state.user && isAdminRole(state.user.role));
  byId("community-section-title").textContent = admin ? "新增小区" : "没有找到小区？";
  byId("community-section-description").textContent = admin
    ? "新增后立即开放，可直接用于猫咪档案。"
    : "提交建议后由管理员审核，审核通过后可用于猫咪档案。";
  byId("community-submit").textContent = admin ? "新增并开放" : "提交小区建议";
  byId("open-community-form").textContent = admin
    ? "没有找到小区？新增并开放小区"
    : "没有找到小区？提交小区建议";
}
```

从 `renderAccount()` 调用该函数。

- [ ] **Step 4: 实现快捷跳转和正确成功提示**

点击 `#open-community-form` 时保留猫咪表单字段，关闭弹层、导航到 `profile`，并聚焦 `#community-name`。提交成功后：

```javascript
var admin = isAdminRole(state.user && state.user.role);
toast(admin ? "小区已创建并开放" : "小区建议已提交，等待管理员审核");
return loadPublicData();
```

- [ ] **Step 5: 增加移动端样式并运行聚焦测试**

Run:

```bash
node --check app/rescue/app.js
PYTHONPYCACHEPREFIX=/tmp/help-cat-role-community-pycache python3 -m unittest tests.test_rescue_h5_contract -v
```

Expected: JavaScript 语法通过，H5 合同测试通过。

- [ ] **Step 6: 提交角色与小区交互**

```bash
git add app/rescue/index.html app/rescue/app.js app/rescue/styles.css tests/test_rescue_h5_contract.py
git commit -m "Clarify role-aware community creation"
```

---

### Task 3: 增加非破坏性的版本更新提示

**Files:**
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/app.js`
- Modify: `app/rescue/styles.css`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: `<html data-app-version>`、`window.fetch`、页面 `visibilitychange`。
- Produces: `checkForUpdate() -> Promise<void>`、`#version-update`。

- [ ] **Step 1: 增加版本标记与提示组件**

```html
<html lang="zh-CN" data-app-version="20260802-community-quality">
...
<aside class="version-update" id="version-update" role="status" hidden>
  <span>发现新版本，刷新后可使用最新功能。</span>
  <button id="reload-version" type="button">立即刷新</button>
</aside>
```

- [ ] **Step 2: 实现版本比较**

```javascript
function checkForUpdate() {
  var current = document.documentElement.dataset.appVersion || "";
  return fetch(window.location.pathname, { cache: "no-store" })
    .then(function (response) { return response.text(); })
    .then(function (html) {
      var match = html.match(/data-app-version="([^"]+)"/);
      byId("version-update").hidden = !match || match[1] === current;
    })
    .catch(function () { return null; });
}
```

页面加载后调用一次；重新可见时再次调用。`#reload-version` 点击后执行 `window.location.reload()`。

- [ ] **Step 3: 增加安全区和移动端样式**

提示位于底部导航之上，不遮挡表单和按钮；手机宽度使用 `calc(100vw - 24px)`。

- [ ] **Step 4: 更新所有静态资源版本并运行测试**

把 `styles.css`、`api.js`、`app.js` 的查询参数统一改为 `20260802-community-quality`。

Run:

```bash
node --check app/rescue/api.js
node --check app/rescue/app.js
PYTHONPYCACHEPREFIX=/tmp/help-cat-role-community-pycache python3 -m unittest tests.test_rescue_h5_contract -v
```

Expected: 全部通过。

- [ ] **Step 5: 提交版本提示**

```bash
git add app/rescue/index.html app/rescue/app.js app/rescue/styles.css tests/test_rescue_h5_contract.py
git commit -m "Notify users when Help Cat updates"
```

---

### Task 4: 回归、审查与生产发布

**Files:**
- Verify: `app/rescue/*`
- Verify: `admin/*`
- Verify: `server/helpcat/*`

**Interfaces:**
- Consumes: Task 1-3 的实现。
- Produces: 可回滚生产版本与验收记录。

- [ ] **Step 1: 运行完整测试**

```bash
node --check app/rescue/api.js
node --check app/rescue/app.js
node --check admin/app.js
PYTHONPYCACHEPREFIX=/tmp/help-cat-final-pycache python3 -m unittest \
  server.tests.test_commercial_api \
  tests.test_commercial_frontends \
  tests.test_commercial_migrations \
  tests.test_help_cat_qa_seed \
  tests.test_help_cat_qa_cleanup \
  tests.test_rescue_h5_contract
git diff --check main...HEAD
```

Expected: 0 failures，JavaScript 和 diff 检查通过。

- [ ] **Step 2: 进行代码自审**

核对未知角色最小权限、SUPER_ADMIN 文案、小区状态、表单保留、版本提示不自动刷新和普通用户不可见后台入口。

- [ ] **Step 3: 推送功能分支并更新 PR #1**

通过 ClashX 推送，PR 写入测试结果和新增功能说明，不在未验证时合并主分支。

- [ ] **Step 4: 备份并部署静态文件**

创建 `/opt/help-cat/backups/<timestamp>-community-quality/` 与 `/opt/help-cat/releases/<timestamp>-community-quality/`，上传四个 H5 文件，比较 SHA-256 后覆盖生产目录。

- [ ] **Step 5: 配置 HTML 重新验证**

先备份 `/etc/nginx/conf.d/purchase-system.conf`。在现有 `server` 中为 H5 入口增加精确 location，继承现有静态根目录和回退规则，并设置：

```nginx
location = /help-cat/rescue/index.html {
    add_header Cache-Control "no-cache, no-store, must-revalidate" always;
    try_files $uri =404;
}
```

执行 `nginx -t` 后只 reload Nginx；若配置测试失败，立即恢复备份且不 reload。

- [ ] **Step 6: 生产验收**

直连验证健康接口、静态版本、小区角色文案、后台入口、版本提示标记、Nginx 配置和生产哈希。使用已有 QA 数据完成 USER 待审与 ADMIN/SUPER_ADMIN 立即开放的 API 回归，不向生产写入无清理计划的数据。
