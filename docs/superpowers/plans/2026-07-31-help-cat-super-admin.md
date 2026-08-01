# Help Cat Super Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `zack` the only `SUPER_ADMIN` and let that account grant or revoke ordinary administrator access from the Help Cat admin console.

**Architecture:** Extend the existing string role model with `SUPER_ADMIN`, keep content-governance authorization shared by `ADMIN` and `SUPER_ADMIN`, and add a separate super-admin guard for user-role APIs. The existing admin SPA gains a role-aware user panel; production promotion of `zack` is a guarded one-time database transaction.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, SQLite, vanilla JavaScript, HTML/CSS, `unittest`, Nginx, systemd.

## Global Constraints

- `zack` is the only `SUPER_ADMIN`.
- Role-management APIs accept only `USER` and `ADMIN`; they never create another `SUPER_ADMIN`.
- `ADMIN` can govern content but cannot list users or modify roles.
- Role changes are recorded in `audit_logs` with action `ROLE_CHANGE`.
- User responses never expose password hashes, openids, sessions, or tokens.
- No Git commit step is applicable because this project directory is not a Git repository.

---

### Task 1: Backend authorization and role-management API

**Files:**
- Modify: `server/helpcat/auth.py`
- Modify: `server/helpcat/schemas.py`
- Modify: `server/helpcat/app.py`
- Test: `server/tests/test_commercial_api.py`

**Interfaces:**
- Produces: `require_admin(actor)` accepting `ADMIN` and `SUPER_ADMIN`.
- Produces: `require_super_admin(actor)` accepting only `SUPER_ADMIN`.
- Produces: `RoleUpdate` with `role: Literal["USER", "ADMIN"]`.
- Produces: `GET /api/v1/admin/users` and `POST /api/v1/admin/users/{user_id}/role`.

- [ ] **Step 1: Write failing role tests**

Add test setup support for three actors and assertions equivalent to:

```python
self.super_token = self.register("zack", "password-1234")
with self.app.state.session_factory() as db:
    zack = db.scalar(select(User).where(User.username == "zack"))
    zack.role = "SUPER_ADMIN"
    db.commit()

def test_super_admin_can_list_users_without_sensitive_fields(self):
    status, body = self.request("GET", "/api/v1/admin/users", self.super_token)
    self.assertEqual(status, 200)
    self.assertNotIn("password_hash", body["items"][0])
    self.assertNotIn("openid", body["items"][0])

def test_super_admin_can_promote_and_demote_user_with_audit(self):
    status, body = self.request("POST", f"/api/v1/admin/users/{self.user_id}/role", self.super_token, {"role": "ADMIN"})
    self.assertEqual((status, body["role"]), (200, "ADMIN"))
    status, body = self.request("POST", f"/api/v1/admin/users/{self.user_id}/role", self.super_token, {"role": "USER"})
    self.assertEqual((status, body["role"]), (200, "USER"))

def test_admin_cannot_manage_roles_and_super_admin_is_immutable(self):
    self.assertEqual(self.request("GET", "/api/v1/admin/users", self.admin_token)[0], 403)
    self.assertEqual(self.request("POST", f"/api/v1/admin/users/{self.super_id}/role", self.super_token, {"role": "ADMIN"})[0], 409)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -m unittest server.tests.test_commercial_api`

Expected: failures because `/api/v1/admin/users` does not exist and `SUPER_ADMIN` fails current `require_admin`.

- [ ] **Step 3: Implement guards, schema, payload, and endpoints**

Implement in `auth.py`:

```python
def require_admin(current_user):
    if current_user[1] not in {"ADMIN", "SUPER_ADMIN"}:
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    return current_user

def require_super_admin(current_user):
    if current_user[1] != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail={"code": "super_admin_required"})
    return current_user
```

Implement in `schemas.py`:

```python
from typing import Literal

class RoleUpdate(BaseModel):
    role: Literal["USER", "ADMIN"]
```

Implement in `app.py`:

```python
def user_payload(user):
    return {"id": user.id, "username": user.username, "nickname": user.nickname,
            "role": user.role, "status": user.status, "created_at": user.created_at.isoformat()}

@app.get("/api/v1/admin/users")
def list_admin_users(actor=Depends(current_user), db: DbSession = Depends(db_session)):
    require_super_admin(actor)
    items = db.scalars(select(User).order_by(User.created_at)).all()
    return {"items": [user_payload(item) for item in items]}

@app.post("/api/v1/admin/users/{user_id}/role")
def update_user_role(user_id: str, payload: RoleUpdate, actor=Depends(current_user), db: DbSession = Depends(db_session)):
    require_super_admin(actor)
    user = db.get(User, user_id)
    if not user:
        error(404, "user_not_found")
    if user.role == "SUPER_ADMIN":
        error(409, "super_admin_immutable")
    if user.role != payload.role:
        before = {"role": user.role}
        user.role = payload.role
        audit(db, actor[0], "ROLE_CHANGE", "user", user.id, before, {"role": user.role})
        db.commit()
    return user_payload(user)
```

Remove username-based automatic administrator registration so new registrations always use `role="USER"`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python3 -m unittest server.tests.test_commercial_api`

Expected: all commercial API tests pass.

---

### Task 2: Admin-console user and permission panel

**Files:**
- Modify: `admin/index.html`
- Modify: `admin/styles.css`
- Modify: `admin/app.js`
- Test: `tests/test_commercial_frontends.py`

**Interfaces:**
- Consumes: `GET /api/v1/auth/me`.
- Consumes: `GET /api/v1/admin/users` returning `{items: UserPayload[]}`.
- Consumes: `POST /api/v1/admin/users/{id}/role` with `{role: "USER" | "ADMIN"}`.

- [ ] **Step 1: Write failing frontend contract tests**

Add assertions equivalent to:

```python
for text in ("用户与权限", "唯一超级管理员", "设为管理员", "撤销管理员"):
    self.assertIn(text, html + script)
for route in ("/api/v1/auth/me", "/api/v1/admin/users", "/role"):
    self.assertIn(route, script)
self.assertIn('profile.role === "SUPER_ADMIN"', script)
self.assertNotIn("API Token", html)
```

- [ ] **Step 2: Run frontend contract test and verify RED**

Run: `python3 -m unittest tests.test_commercial_frontends`

Expected: failure because the current admin page has no user panel and still exposes a token input.

- [ ] **Step 3: Implement the role-aware admin SPA**

Update the page to contain a login view, authenticated application view, content-governance panels, and:

```html
<section class="panel users-panel" id="users-panel" hidden>
  <div class="panel-head"><div><span>ACCESS CONTROL</span><h2>用户与权限</h2></div><span>仅唯一超级管理员可操作</span></div>
  <label class="search-box">搜索用户<input id="user-search" placeholder="用户名或昵称"></label>
  <div id="users" class="list"></div>
</section>
```

After password login, save the token in `sessionStorage`, call `/api/v1/auth/me`, reject `USER`, and load content data. Only when `profile.role === "SUPER_ADMIN"` load `/api/v1/admin/users` and reveal `#users-panel`.

Render roles with these controls:

```javascript
if (user.role === "SUPER_ADMIN") return '<span class="role-badge super">唯一超级管理员</span>';
return '<button class="role-action" data-user-id="' + esc(user.id) + '" data-next-role="' +
  (user.role === "ADMIN" ? "USER" : "ADMIN") + '">' +
  (user.role === "ADMIN" ? "撤销管理员" : "设为管理员") + '</button>';
```

On click, disable the button, POST the role, show an inline success/error status, and reload the user list.

- [ ] **Step 4: Run frontend test and verify GREEN**

Run: `node --check admin/app.js && python3 -m unittest tests.test_commercial_frontends`

Expected: JavaScript syntax succeeds and all frontend contract tests pass.

---

### Task 3: Full regression and browser verification

**Files:**
- Verify: `server/helpcat/*.py`
- Verify: `admin/*`
- Verify: `app/rescue/*`

- [ ] **Step 1: Run complete automated verification**

Run:

```bash
node --check admin/app.js
node --check app/rescue/api.js
node --check app/rescue/app.js
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest discover -s server/tests -p 'test_*.py'
```

Expected: zero syntax errors and zero test failures.

- [ ] **Step 2: Run browser regression against an isolated database**

Start the API/static preview at `127.0.0.1:18765`, then verify:

1. `zack` logs in as `SUPER_ADMIN` and sees “用户与权限”.
2. A normal test user can be promoted to `ADMIN` and demoted back to `USER`.
3. An `ADMIN` can access cat/community governance but cannot see user management.
4. A `USER` is denied access to the admin application.
5. There are no console errors and no horizontal overflow at 390×844 and 1440×900.

---

### Task 4: Guarded production promotion and deployment

**Files:**
- Deploy: `server/helpcat/auth.py`
- Deploy: `server/helpcat/schemas.py`
- Deploy: `server/helpcat/app.py`
- Deploy: `admin/index.html`
- Deploy: `admin/styles.css`
- Deploy: `admin/app.js`

- [ ] **Step 1: Back up production**

Create a timestamped directory under `/opt/help-cat/backups/` and copy the production database, full `server/helpcat` Python package, and `/data/purchase-system/frontend/dist/help-cat/admin/`.

- [ ] **Step 2: Upload release and verify SHA-256**

Upload to a timestamped `/opt/help-cat/releases/` directory and compare local/remote SHA-256 for every file. Do not replace production if any hash differs.

- [ ] **Step 3: Promote zack transactionally**

Run a Python/SQLite transaction that:

```python
rows = connection.execute("SELECT id FROM users WHERE username = ? AND status = 'ACTIVE'", ("zack",)).fetchall()
assert len(rows) == 1
connection.execute("UPDATE users SET role = 'USER' WHERE role = 'SUPER_ADMIN' AND id != ?", (rows[0][0],))
connection.execute("UPDATE users SET role = 'SUPER_ADMIN' WHERE id = ?", (rows[0][0],))
assert connection.execute("SELECT COUNT(*) FROM users WHERE role = 'SUPER_ADMIN'").fetchone()[0] == 1
```

Commit only after all assertions pass.

- [ ] **Step 4: Replace files, restart, and verify**

Restart `help-cat.service`, validate `nginx -t`, `/api/v1/health`, `/help-cat/admin/`, the role-management OpenAPI routes, and `zack` as the sole `SUPER_ADMIN`.

- [ ] **Step 5: Roll back on any failure**

Restore the backed-up database, Python package, and admin static directory; restart the service and rerun health checks.
