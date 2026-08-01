(function () {
  "use strict";

  var API_BASE = window.HELPCAT_API_BASE || "/help-cat-api";
  var TOKEN_KEY = "help_cat_admin_token";
  var H5_TOKEN_KEY = "help_cat_token";
  var token = sessionStorage.getItem(TOKEN_KEY) || "";
  var profile = null;
  var state = { cats: [], communities: [], users: [], section: "overview", busy: false };

  function byId(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[character];
    });
  }
  function request(path, options) {
    var config = options || {};
    var headers = Object.assign({}, config.headers || {});
    if (config.body !== undefined) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = "Bearer " + token;
    return fetch(API_BASE + path, {
      method: config.method || "GET",
      headers: headers,
      body: config.body !== undefined ? JSON.stringify(config.body) : undefined
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) throw { status: response.status, code: body.code || "request_failed", message: body.message };
        return body;
      });
    }).catch(function (error) {
      if (error && error.code) throw error;
      throw { status: 0, code: "network_error", message: "网络连接失败" };
    });
  }
  function errorText(error) {
    return {
      invalid_credentials: "账号或密码错误",
      unauthorized: "登录已失效，请重新登录",
      session_expired: "登录已过期，请重新登录",
      forbidden: "当前账号没有管理权限",
      super_admin_required: "只有唯一超级管理员可以管理用户权限",
      super_admin_immutable: "唯一超级管理员的角色不能修改",
      user_not_found: "用户不存在",
      network_error: "网络连接失败，请稍后重试"
    }[error && error.code] || (error && error.message) || "操作失败，请稍后重试";
  }
  function toast(message) {
    var target = byId("toast");
    target.textContent = message;
    target.hidden = false;
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () { target.hidden = true; }, 2600);
  }
  function showGlobal(message, isError) {
    var target = byId("global-message");
    target.textContent = message || "";
    target.classList.toggle("error", Boolean(isError));
    target.hidden = !message;
  }
  function clearSession(clearSharedToken) {
    token = "";
    profile = null;
    sessionStorage.removeItem(TOKEN_KEY);
    if (clearSharedToken) sessionStorage.removeItem(H5_TOKEN_KEY);
  }
  function showLogin(message) {
    document.title = "帮帮小猫 · 管理员登录";
    byId("admin-shell").hidden = true;
    byId("login-view").hidden = false;
    byId("login-password").value = "";
    byId("login-message").textContent = message || "";
  }
  function showAdmin() {
    document.title = "帮帮小猫 · 管理后台";
    byId("login-view").hidden = true;
    byId("admin-shell").hidden = false;
    var name = profile.username || profile.nickname || "管理员";
    byId("account-name").textContent = name;
    byId("account-avatar").textContent = name.slice(0, 1);
    byId("account-role").textContent = profile.role === "SUPER_ADMIN" ? "唯一超级管理员" : "管理员";
    var isSuper = profile.role === "SUPER_ADMIN";
    byId("users-nav").hidden = !isSuper;
    byId("user-summary").hidden = !isSuper;
    if (!isSuper && state.section === "users") switchSection("overview");
  }
  function authenticate(username, password) {
    return request("/api/v1/auth/login", { method: "POST", body: { username: username, password: password } }).then(function (body) {
      token = body.access_token;
      sessionStorage.setItem(TOKEN_KEY, token);
      return restoreSession();
    });
  }
  function restoreSession() {
    return request("/api/v1/auth/me").then(function (body) {
      if (["ADMIN", "SUPER_ADMIN"].indexOf(body.role) < 0) throw { status: 403, code: "forbidden" };
      profile = body;
      showAdmin();
      return loadAll();
    }).catch(function (error) {
      clearSession();
      showLogin(errorText(error));
      throw error;
    });
  }
  function loadAll() {
    showGlobal("正在同步管理数据…", false);
    var requests = [request("/api/v1/cats"), request("/api/v1/admin/communities")];
    if (profile.role === "SUPER_ADMIN") requests.push(request("/api/v1/admin/users"));
    return Promise.all(requests).then(function (results) {
      state.cats = results[0].items || [];
      state.communities = results[1].items || [];
      state.users = results[2] ? results[2].items || [] : [];
      showGlobal("", false);
      render();
    }).catch(function (error) {
      if (error.status === 401 || error.status === 403) {
        clearSession();
        showLogin(errorText(error));
        return;
      }
      showGlobal(errorText(error), true);
    });
  }
  function loadUsers() {
    if (!profile || profile.role !== "SUPER_ADMIN") return Promise.resolve();
    return request("/api/v1/admin/users").then(function (body) {
      state.users = body.items || [];
      renderUsers();
      byId("user-count").textContent = String(state.users.length);
    });
  }
  function statusLabel(value) {
    return { APPROVED: "已通过", PENDING_REVIEW: "待审核", REJECTED: "未通过", ACTIVE: "公开", HIDDEN: "隐藏", ARCHIVED: "已归档" }[value] || value;
  }
  function renderCats() {
    var query = byId("cat-search").value.trim().toLowerCase();
    var cats = state.cats.filter(function (cat) {
      return !query || [cat.nickname, cat.code, cat.location_note].join(" ").toLowerCase().indexOf(query) >= 0;
    });
    byId("cats").innerHTML = cats.length ? cats.map(function (cat) {
      return '<article class="list-item"><div class="entity-icon cat-entity">猫</div><div class="entity-copy"><strong>' + esc(cat.nickname) + '<small>' + esc(cat.code) + '</small></strong><p>' + esc(cat.location_note) + '</p><div class="badges"><span>' + esc(statusLabel(cat.review_status)) + '</span><span>' + esc(statusLabel(cat.visibility_status)) + '</span></div></div><div class="actions">' +
        (cat.review_status === "PENDING_REVIEW" ? '<button data-cat-action="review" data-id="' + esc(cat.id) + '">审核通过</button>' : '') +
        (cat.visibility_status !== "ARCHIVED" ? '<button data-cat-action="visibility" data-id="' + esc(cat.id) + '" data-visible="' + String(cat.visibility_status === "HIDDEN") + '">' + (cat.visibility_status === "HIDDEN" ? "公开" : "隐藏") + '</button>' : '') +
        '<button class="danger" data-cat-action="archive" data-id="' + esc(cat.id) + '" ' + (cat.visibility_status === "ARCHIVED" ? "disabled" : "") + '>归档</button></div></article>';
    }).join("") : '<div class="empty-state"><strong>没有匹配的猫咪档案</strong><p>调整搜索条件或等待新的居民提交。</p></div>';
  }
  function renderCommunities() {
    byId("communities").innerHTML = state.communities.length ? state.communities.map(function (community) {
      return '<article class="list-item"><div class="entity-icon community-entity">区</div><div class="entity-copy"><strong>' + esc(community.name) + '</strong><p>' + esc(community.street) + '</p><div class="badges"><span>' + esc(statusLabel(community.status)) + '</span></div></div><div class="actions">' +
        (community.status === "PENDING_REVIEW" ? '<button data-community-action="review" data-id="' + esc(community.id) + '">审核通过</button>' : '') +
        '<button class="danger" data-community-action="archive" data-id="' + esc(community.id) + '" ' + (community.status === "ARCHIVED" ? "disabled" : "") + '>归档</button></div></article>';
    }).join("") : '<div class="empty-state"><strong>暂无小区</strong><p>可以使用上方表单新增首个小区。</p></div>';
  }
  function renderUsers() {
    if (!profile || profile.role !== "SUPER_ADMIN") return;
    var query = byId("user-search").value.trim().toLowerCase();
    var users = state.users.filter(function (user) {
      return !query || [user.username, user.nickname, user.role].join(" ").toLowerCase().indexOf(query) >= 0;
    });
    byId("users").innerHTML = users.length ? users.map(function (user) {
      var name = user.username || user.nickname || "微信用户";
      var control;
      if (user.role === "SUPER_ADMIN") {
        control = '<span class="role-badge super">唯一超级管理员</span>';
      } else {
        var nextRole = user.role === "ADMIN" ? "USER" : "ADMIN";
        control = '<button class="role-action" data-user-id="' + esc(user.id) + '" data-next-role="' + nextRole + '">' + (user.role === "ADMIN" ? "撤销管理员" : "设为管理员") + '</button>';
      }
      return '<article class="list-item user-item"><div class="user-avatar">' + esc(name.slice(0, 1)) + '</div><div class="entity-copy"><strong>' + esc(name) + '</strong><p>账号状态：' + esc(user.status === "ACTIVE" ? "正常" : user.status) + '</p><div class="badges"><span class="role-badge ' + esc(user.role.toLowerCase()) + '">' + esc(user.role) + '</span></div></div><div class="actions">' + control + '</div></article>';
    }).join("") : '<div class="empty-state"><strong>没有匹配用户</strong><p>请检查用户名或昵称。</p></div>';
  }
  function render() {
    byId("cat-count").textContent = String(state.cats.length);
    byId("community-count").textContent = String(state.communities.length);
    byId("pending-count").textContent = String(state.cats.filter(function (cat) { return cat.review_status === "PENDING_REVIEW"; }).length + state.communities.filter(function (item) { return item.status === "PENDING_REVIEW"; }).length);
    byId("user-count").textContent = String(state.users.length);
    renderCats();
    renderCommunities();
    renderUsers();
  }
  function switchSection(section) {
    if (section === "users" && (!profile || profile.role !== "SUPER_ADMIN")) return;
    state.section = section;
    var titles = { overview: "管理总览", cats: "猫咪档案", communities: "小区管理", users: "用户与权限" };
    byId("page-title").textContent = titles[section] || "管理总览";
    document.querySelectorAll("[data-admin-section]").forEach(function (panel) {
      var active = panel.dataset.adminSection === section;
      panel.hidden = !active;
      panel.classList.toggle("active", active);
    });
    document.querySelectorAll(".side-nav").forEach(function (button) { button.classList.toggle("active", button.dataset.section === section); });
    window.location.hash = section;
  }
  function changeRole(button) {
    if (state.busy || !profile || profile.role !== "SUPER_ADMIN") return;
    state.busy = true;
    button.disabled = true;
    byId("user-message").textContent = "正在更新用户权限…";
    request("/api/v1/admin/users/" + encodeURIComponent(button.dataset.userId) + "/role", { method: "POST", body: { role: button.dataset.nextRole } }).then(function (user) {
      byId("user-message").textContent = user.role === "ADMIN" ? "已授予管理员权限" : "已撤销管理员权限";
      toast(byId("user-message").textContent);
      return loadUsers();
    }).catch(function (error) {
      byId("user-message").textContent = errorText(error);
      button.disabled = false;
    }).finally(function () { state.busy = false; });
  }
  function actOnCat(button) {
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    var id = encodeURIComponent(button.dataset.id);
    var action = button.dataset.catAction;
    var route = action === "review" ? "/api/v1/cats/" + id + "/review" : action === "visibility" ? "/api/v1/cats/" + id + "/visibility" : "/api/v1/cats/" + id + "/archive";
    var body = action === "review" ? { approved: true } : action === "visibility" ? { visible: button.dataset.visible === "true" } : undefined;
    request(route, { method: "POST", body: body }).then(function () { toast("档案状态已更新"); return loadAll(); }).catch(function (error) { showGlobal(errorText(error), true); }).finally(function () { state.busy = false; });
  }
  function actOnCommunity(button) {
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    var id = encodeURIComponent(button.dataset.id);
    var review = button.dataset.communityAction === "review";
    var route = review ? "/api/v1/communities/" + id + "/review" : "/api/v1/communities/" + id + "/archive";
    request(route, { method: "POST", body: review ? { approved: true } : undefined }).then(function () { toast("小区状态已更新"); return loadAll(); }).catch(function (error) { showGlobal(errorText(error), true); }).finally(function () { state.busy = false; });
  }

  function logout() {
    return window.HelpCatAdminSession.logout(request, clearSession, showLogin, state);
  }

  byId("login-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    byId("login-submit").disabled = true;
    byId("login-message").textContent = "正在验证账号…";
    authenticate(byId("login-username").value.trim(), byId("login-password").value).then(function () {
      byId("login-form").reset();
      byId("login-message").textContent = "";
    }).catch(function () {}).finally(function () {
      state.busy = false;
      byId("login-submit").disabled = false;
    });
  });
  byId("logout").addEventListener("click", logout);
  byId("refresh").addEventListener("click", loadAll);
  byId("cat-search").addEventListener("input", renderCats);
  byId("user-search").addEventListener("input", renderUsers);
  byId("community-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    var button = event.target.querySelector("button[type=submit]");
    button.disabled = true;
    request("/api/v1/communities", { method: "POST", body: { name: byId("community-name").value.trim(), street: byId("community-street").value.trim() } }).then(function () {
      event.target.reset();
      byId("community-street").value = "银湖街道";
      toast("小区已创建并开放");
      return loadAll();
    }).catch(function (error) { showGlobal(errorText(error), true); }).finally(function () { state.busy = false; button.disabled = false; });
  });
  document.addEventListener("click", function (event) {
    var sectionButton = event.target.closest("[data-section], [data-section-link]");
    if (sectionButton) { switchSection(sectionButton.dataset.section || sectionButton.dataset.sectionLink); return; }
    var roleButton = event.target.closest("[data-user-id]");
    if (roleButton) { changeRole(roleButton); return; }
    var catButton = event.target.closest("[data-cat-action]");
    if (catButton) { actOnCat(catButton); return; }
    var communityButton = event.target.closest("[data-community-action]");
    if (communityButton) actOnCommunity(communityButton);
  });

  var initialSection = window.location.hash.replace("#", "");
  if (["overview", "cats", "communities", "users"].indexOf(initialSection) >= 0) state.section = initialSection;
  if (token) restoreSession().then(function () { switchSection(state.section); }).catch(function () {});
  else showLogin("");
}());
