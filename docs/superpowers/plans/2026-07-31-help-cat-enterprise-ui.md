# 帮帮小猫大厂公益风改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将帮帮小猫用户端升级为真实 API 驱动的大厂公益风 H5，修复管理员建档审核、登录验证、位置降级和权限隔离问题，回归后部署到现有服务器。

**Architecture:** 保留 FastAPI + SQLAlchemy 服务与独立管理端，用户 H5 使用 `/help-cat-api/api/v1` 作为唯一数据源。用户端拆分为 API 客户端、状态/渲染控制器和设计系统 CSS；服务器继续使用 SQLite，部署采用静态资源和 API 服务的可回滚覆盖。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy、Pydantic、原生 HTML/CSS/JavaScript、`unittest`、Nginx、systemd。

## Global Constraints

- 用户端不再使用 localStorage 保存猫咪、任务或审核业务数据。
- 未登录用户可浏览公开数据，提交和领取必须登录。
- 管理员建档直接 `APPROVED`，普通用户建档进入 `PENDING_REVIEW`。
- 普通用户端不显示管理入口，管理能力只保留在 `/help-cat/admin/`。
- HTTP IP 下定位失败必须降级为小区搜索与手工位置描述。
- 不引入重型 UI 库，不增加第三方地图、支付或微信真实登录。
- 所有外网连接默认走 ClashX，但 `175.178.41.19` 按用户要求直连。
- 项目无 Git；每个任务修改前复制相关文件到 `/tmp/help-cat-enterprise-ui-backup/`。

---

### Task 1: 锁定账号验证与管理员建档规则

**Files:**
- Modify: `server/helpcat/app.py`
- Test: `server/tests/test_commercial_api.py`

**Interfaces:**
- Produces: `GET /api/v1/auth/me -> {id, username, role}`。
- Produces: `POST /api/v1/cats` 对管理员返回 `review_status=APPROVED`，对普通用户返回 `PENDING_REVIEW`。

- [ ] **Step 1: 写失败测试**

```python
def test_authenticated_user_can_restore_session_and_admin_cat_is_approved(self):
    admin = self.register("admin", "password-123")
    me = self.client.get("/api/v1/auth/me", headers=self.auth(admin))
    self.assertEqual(me.status_code, 200)
    self.assertEqual(me.json()["role"], "ADMIN")
    community = self.create_community(admin, "银湖测试小区")
    cat = self.client.post("/api/v1/cats", headers=self.auth(admin), json={
        "community_id": community["id"], "nickname": "免审猫",
        "location_note": "北门附近", "living_status": "常住",
        "health_status": "HEALTHY"
    })
    self.assertEqual(cat.status_code, 201)
    self.assertEqual(cat.json()["review_status"], "APPROVED")
```

- [ ] **Step 2: 运行并确认失败**

Run: `PYTHONPYCACHEPREFIX=/tmp/help-cat-pycache python3 -m unittest server.tests.test_commercial_api.CommercialApiTests.test_authenticated_user_can_restore_session_and_admin_cat_is_approved -v`

Expected: FAIL；`/auth/me` 为 404 或管理员猫咪仍为 `PENDING_REVIEW`。

- [ ] **Step 3: 实现会话恢复和角色审核分支**

```python
@app.get("/api/v1/auth/me")
def auth_me(actor=Depends(current_user), db: DbSession = Depends(db_session)):
    user = db.get(User, actor[0])
    return {"id": user.id, "username": user.username, "role": user.role}

review_status = "APPROVED" if role == "ADMIN" else "PENDING_REVIEW"
```

将 `review_status` 传入 `Cat(...)`，保留普通用户配额逻辑不变。

- [ ] **Step 4: 运行 API 测试**

Run: `PYTHONPYCACHEPREFIX=/tmp/help-cat-pycache python3 -m unittest server.tests.test_commercial_api -v`

Expected: 全部 PASS。

### Task 2: 建立用户端 API 客户端与错误契约

**Files:**
- Create: `app/rescue/api.js`
- Modify: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Produces: `HelpCatApi.request(path, options)`、`register(username,password)`、`login(username,password)`、`restoreSession()`、`logout()`、`uploadImage(file)`。
- Produces: 标准错误 `{status, code, message}`。

- [ ] **Step 1: 写失败契约测试**

```python
def test_rescue_client_uses_real_api_and_session_token(self):
    script = (ROOT / "app/rescue/api.js").read_text()
    self.assertIn('API_BASE = "/help-cat-api"', script)
    self.assertIn('sessionStorage.getItem("help_cat_token")', script)
    self.assertIn('/api/v1/auth/me', script)
    self.assertNotIn('help-cat-demo-v2', script)
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_rescue_client_uses_real_api_and_session_token -v`

Expected: FAIL，`api.js` 不存在。

- [ ] **Step 3: 实现 API 客户端**

```javascript
(function (global) {
  "use strict";
  var API_BASE = "/help-cat-api";
  var TOKEN_KEY = "help_cat_token";
  function token() { return sessionStorage.getItem(TOKEN_KEY) || ""; }
  function request(path, options) {
    var config = options || {};
    var headers = Object.assign({}, config.headers || {});
    if (!config.form) headers["Content-Type"] = "application/json";
    if (token()) headers.Authorization = "Bearer " + token();
    return fetch(API_BASE + path, {
      method: config.method || "GET", headers: headers,
      body: config.form || (config.body ? JSON.stringify(config.body) : undefined)
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) throw { status: response.status, code: body.code || "network_error", message: body.message || "请求失败" };
        return body;
      });
    });
  }
  global.HelpCatApi = { request: request, token: token };
}(window));
```

补齐登录、注册、恢复、退出和图片上传封装；401 时删除 `help_cat_token`。

- [ ] **Step 4: 运行契约和语法检查**

Run: `python3 -m unittest tests.test_rescue_h5_contract -v && node --check app/rescue/api.js`

Expected: 全部 PASS。

### Task 3: 重建大厂公益风用户端结构

**Files:**
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/styles.css`
- Modify: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: `window.HelpCatApi`。
- Produces: `data-view` 四视图、`#auth-sheet`、`#cat-sheet`、`#toast`、`#app-status` 和 44px 触控导航。

- [ ] **Step 1: 写失败 UI 契约测试**

```python
def test_rescue_page_has_enterprise_mobile_shell(self):
    html = (ROOT / "app/rescue/index.html").read_text()
    css = (ROOT / "app/rescue/styles.css").read_text()
    for marker in ('data-view="home"', 'data-view="cats"', 'data-view="tasks"', 'data-view="profile"', 'id="auth-sheet"', 'id="cat-sheet"'):
        self.assertIn(marker, html)
    self.assertIn("position: fixed", css)
    self.assertIn("min-height: 44px", css)
    self.assertNotIn("演示身份", html)
    self.assertNotIn("重置演示", html)
    self.assertNotIn("体验版", html)
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_rescue_page_has_enterprise_mobile_shell -v`

Expected: FAIL，旧页面仍为演示单页。

- [ ] **Step 3: 重写 HTML 信息架构**

建立品牌头、首页数据卡、猫咪列表、任务列表、个人中心、底部导航、登录/注册面板和三步建档面板。脚本顺序必须为：

```html
<script src="api.js?v=20260731-enterprise"></script>
<script src="app.js?v=20260731-enterprise"></script>
```

- [ ] **Step 4: 实现视觉系统**

CSS 变量使用：

```css
:root {
  --brand: #e66b3d; --brand-dark: #bc4b25; --ink: #18352d;
  --muted: #708078; --canvas: #f6f7f3; --surface: #ffffff;
  --line: #e7ebe5; --success: #2f8f68; --warning: #d98b27;
  --danger: #c84f4f; --radius-sm: 12px; --radius-md: 18px;
  --radius-lg: 24px; --shadow: 0 14px 36px rgba(24,53,45,.08);
}
```

在 `@media (max-width: 640px)` 下保证单列卡片、固定底部导航、表单面板全宽且无横向溢出。

- [ ] **Step 5: 运行 UI 契约**

Run: `python3 -m unittest tests.test_rescue_h5_contract -v`

Expected: 全部 PASS。

### Task 4: 实现真实数据、登录和建档交互

**Files:**
- Modify: `app/rescue/app.js`
- Modify: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: Task 1 的 `/auth/me`、管理员免审规则和 Task 2 的 `HelpCatApi`。
- Produces: `loadPublicData()`、`requireLogin()`、`submitCat()`、`claimTask()`、`renderApp()`。

- [ ] **Step 1: 写失败交互契约测试**

```python
def test_rescue_app_has_real_auth_data_and_location_fallback(self):
    script = (ROOT / "app/rescue/app.js").read_text()
    for marker in ("loadPublicData", "requireLogin", "/api/v1/communities", "/api/v1/cats", "/api/v1/tasks", "/api/v1/me/submissions", "navigator.geolocation", "location-fallback"):
        self.assertIn(marker, script)
    self.assertNotIn("help-cat-demo-v2", script)
    self.assertNotIn("role-select", script)
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_rescue_app_has_real_auth_data_and_location_fallback -v`

Expected: FAIL，旧脚本仍使用本地演示数据。

- [ ] **Step 3: 实现应用状态与公开数据加载**

```javascript
var state = { user: null, communities: [], cats: [], tasks: [], submissions: { cats: [], communities: [] }, view: "home", loading: false };
function loadPublicData() {
  return Promise.all([
    HelpCatApi.request("/api/v1/communities"),
    HelpCatApi.request("/api/v1/cats"),
    HelpCatApi.request("/api/v1/tasks")
  ]).then(function (results) {
    state.communities = results[0].items || [];
    state.cats = results[1].items || [];
    state.tasks = results[2].items || [];
    renderApp();
  });
}
```

- [ ] **Step 4: 实现登录、注册、会话恢复和权限跳转**

登录成功后保存令牌和用户信息；刷新时调用 `/auth/me`；401 清理会话；未登录提交或领取时打开登录面板，不显示管理入口。

- [ ] **Step 5: 实现三步建档与位置降级**

小区字段使用搜索过滤后的 `community_id`。`window.isSecureContext && navigator.geolocation` 为真时尝试定位；否则给 `#location-fallback` 添加可见状态并聚焦位置描述。上传图片成功后再提交猫咪；失败时保留表单。

- [ ] **Step 6: 实现任务领取和错误映射**

409 显示“任务已被其他志愿者领取”，429 显示“今天已达到 3 条建档上限”，401 打开登录面板，其余错误显示可重试提示。

- [ ] **Step 7: 运行契约和语法检查**

Run: `python3 -m unittest tests.test_rescue_h5_contract -v && node --check app/rescue/app.js`

Expected: 全部 PASS。

### Task 5: 完整回归与本地浏览器验收

**Files:**
- Modify when defects are found: `app/rescue/index.html`, `app/rescue/styles.css`, `app/rescue/api.js`, `app/rescue/app.js`, `server/helpcat/app.py`
- Test: `tests/test_rescue_h5_contract.py`, `server/tests/test_commercial_api.py`

**Interfaces:**
- Produces: 可部署的静态资源和服务端代码。

- [ ] **Step 1: 运行全量自动化**

Run: `PYTHONPYCACHEPREFIX=/tmp/help-cat-full-pycache python3 -m unittest discover -s tests -v`

Run: `PYTHONPYCACHEPREFIX=/tmp/help-cat-full-pycache python3 -m unittest server.tests.test_commercial_api -v`

Run: `node --check app/rescue/api.js && node --check app/rescue/app.js && node --check admin/app.js`

Expected: 全部 PASS，无 warning/error。

- [ ] **Step 2: 启动隔离测试服务**

Run: `HELPCAT_DATABASE_URL=sqlite:////tmp/help-cat-enterprise-test.db HELPCAT_STORAGE_ROOT=/tmp/help-cat-enterprise-uploads PYTHONPATH=. python3 -m uvicorn server.helpcat.app:app --host 127.0.0.1 --port 18765`

静态资源通过 `python3 -m http.server 18766 --directory app` 提供。

- [ ] **Step 3: 浏览器验收**

在 390×844 和桌面宽度检查：首页、猫咪搜索空状态、登录失败/注册/登录、会话刷新、三步建档、HTTP 定位降级、我的提交、任务领取、无管理入口、控制台无错误及 `scrollWidth == innerWidth`。

- [ ] **Step 4: 修复缺陷并重复步骤 1–3**

每个缺陷先增加最小失败测试，再只修复根因；浏览器和自动化全部通过才进入部署。

### Task 6: 可回滚部署与公网验收

**Files:**
- Deploy: `/opt/help-cat/release/server/helpcat/app.py`
- Deploy: `/data/purchase-system/frontend/dist/help-cat/rescue/index.html`
- Deploy: `/data/purchase-system/frontend/dist/help-cat/rescue/styles.css`
- Deploy: `/data/purchase-system/frontend/dist/help-cat/rescue/api.js`
- Deploy: `/data/purchase-system/frontend/dist/help-cat/rescue/app.js`

**Interfaces:**
- Consumes: Task 5 已验证产物。
- Produces: `http://175.178.41.19/help-cat/rescue/index.html` 可访问的新版本。

- [ ] **Step 1: 备份线上资源和数据库**

在服务器创建 `/opt/help-cat/backups/20260731-enterprise-ui/`，复制当前静态资源、`server/helpcat/app.py`、systemd unit、Nginx 配置和 `/opt/help-cat/data/help-cat.db`。

- [ ] **Step 2: 上传到临时发布目录并校验哈希**

上传到 `/opt/help-cat/releases/20260731-enterprise-ui/`，比较本地与远端 SHA-256；哈希不一致不得覆盖。

- [ ] **Step 3: 覆盖服务端和静态资源**

将服务端文件复制到 `/opt/help-cat/release/server/helpcat/`，静态资源复制到 `/data/purchase-system/frontend/dist/help-cat/rescue/`；执行 `systemctl restart help-cat.service`。

- [ ] **Step 4: 服务端与 Nginx 验收**

Run remotely: `systemctl is-active help-cat.service && nginx -t && curl -fsS http://127.0.0.1:18000/api/v1/health && curl -fsSI http://127.0.0.1/help-cat/rescue/index.html`

Expected: `active`、Nginx syntax successful、API `status=ok`、页面 HTTP 200。

- [ ] **Step 5: 公网验收**

直连检查页面、CSS、`api.js`、`app.js` 均为 200；浏览器验证新品牌文案、登录、公开列表、移动端无溢出和控制台无错误。

- [ ] **Step 6: 回滚条件**

任一服务、API、静态资源或关键浏览器用例失败时，使用步骤 1 的备份恢复全部对应文件并重启 `help-cat.service`；恢复后再次执行步骤 4。
