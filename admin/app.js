(function () {
  "use strict";

  var API_BASE = window.HELPCAT_API_BASE || "/help-cat-api";
  var TOKEN_KEY = "help_cat_admin_token";
  var H5_TOKEN_KEY = "help_cat_token";
  var communityReview = window.HelpCatCommunityReview;
  var token = sessionStorage.getItem(TOKEN_KEY) || "";
  var profile = null;
  var state = { cats: [], communities: [], users: [], cursors: { cats: null, communities: null, users: null }, section: "overview", busy: false };

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
      stale_community_version: "该小区刚刚已被其他管理员更新，已刷新最新内容",
      community_not_active: "请先处理关联小区，再审核通过猫咪档案",
      review_note_required: "退回修改或驳回时必须填写原因",
      community_merge_target_invalid: "请选择另一个已开放小区作为合并目标",
      community_reassign_target_invalid: "只能把猫咪改挂到已开放小区",
      stale_cat_version: "猫咪档案刚刚已更新，已刷新最新内容",
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
    var requests = [request("/api/v1/cats?limit=24"), request("/api/v1/admin/communities?limit=24")];
    if (profile.role === "SUPER_ADMIN") requests.push(request("/api/v1/admin/users?limit=24"));
    return Promise.all(requests).then(function (results) {
      state.cats = results[0].items || [];
      state.communities = results[1].items || [];
      state.cursors.cats = results[0].next_cursor || null;
      state.cursors.communities = results[1].next_cursor || null;
      state.users = results[2] ? results[2].items || [] : [];
      state.cursors.users = results[2] ? results[2].next_cursor || null : null;
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
  function loadMore(type, button) {
    var cursor = state.cursors[type];
    if (!cursor || state.busy) return;
    state.busy = true;
    button.disabled = true;
    button.textContent = "正在加载…";
    var route = type === "cats" ? "/api/v1/cats" : type === "users" ? "/api/v1/admin/users" : "/api/v1/admin/communities";
    var params = ["limit=24", "cursor=" + encodeURIComponent(cursor)];
    if (type === "cats" && byId("cat-search").value.trim()) params.push("q=" + encodeURIComponent(byId("cat-search").value.trim()));
    request(route + "?" + params.join("&")).then(function (body) {
      state[type] = communityReview.appendUnique(state[type], body.items || []);
      state.cursors[type] = body.next_cursor || null;
      render();
    }).catch(function (error) {
      showGlobal(errorText(error), true);
    }).finally(function () {
      state.busy = false;
      button.disabled = false;
      button.textContent = type === "cats" ? "加载更多猫咪" : type === "users" ? "加载更多用户" : "加载更多小区";
    });
  }
  function loadUsers() {
    if (!profile || profile.role !== "SUPER_ADMIN") return Promise.resolve();
    return request("/api/v1/admin/users?limit=24").then(function (body) {
      state.users = body.items || [];
      state.cursors.users = body.next_cursor || null;
      renderUsers();
      byId("user-count").textContent = String(state.users.length);
    });
  }
  function statusLabel(value) {
    return { APPROVED: "已通过", PENDING_REVIEW: "待审核", NEEDS_CHANGES: "待补充", MERGED: "已合并", REJECTED: "未通过", ACTIVE: "公开", HIDDEN: "隐藏", ARCHIVED: "已归档" }[value] || value;
  }
  function activeTargetOptions(excludeId) {
    return state.communities.filter(function (item) {
      return item.status === "ACTIVE" && item.id !== excludeId;
    }).map(function (item) {
      return '<option value="' + esc(item.id) + '">' + esc(item.name) + ' · ' + esc(item.street) + '</option>';
    }).join("");
  }
  function renderCats() {
    var query = byId("cat-search").value.trim().toLowerCase();
    var cats = state.cats.filter(function (cat) {
      return !query || [cat.nickname, cat.code, cat.location_note].join(" ").toLowerCase().indexOf(query) >= 0;
    });
    byId("cats").innerHTML = cats.length ? cats.map(function (cat) {
      var blocker = cat.community_review_blocker;
      var targetId = "cat-target-" + cat.id;
      var recovery = blocker ? '<div class="reassign-workbench"><label>改挂到已开放小区<input type="search" data-target-search data-target-select="' + esc(targetId) + '" placeholder="输入小区名称搜索全部结果"><select id="' + esc(targetId) + '" data-cat-reassign-target="' + esc(cat.id) + '"><option value="">请选择目标小区</option>' + activeTargetOptions(cat.community_id) + '</select></label><button data-cat-action="reassign" data-id="' + esc(cat.id) + '" data-version="' + esc(cat.version) + '">确认改挂</button></div>' : '';
      return '<article class="list-item"><div class="entity-icon cat-entity">猫</div><div class="entity-copy"><strong>' + esc(cat.nickname) + '<small>' + esc(cat.code) + '</small></strong><p>' + esc(cat.community_name) + ' · ' + esc(cat.location_note) + '</p><div class="badges"><span>' + esc(statusLabel(cat.review_status)) + '</span><span>' + esc(statusLabel(cat.visibility_status)) + '</span>' + (blocker ? '<span class="blocker-badge">小区待处理</span>' : '') + '</div></div><div class="actions">' +
        (cat.review_status === "PENDING_REVIEW" ? (blocker ? '<button data-section-link="communities">查看小区状态</button>' : '<button data-cat-action="review" data-id="' + esc(cat.id) + '">审核通过</button>') : '') +
        (cat.visibility_status !== "ARCHIVED" ? '<button data-cat-action="visibility" data-id="' + esc(cat.id) + '" data-visible="' + String(cat.visibility_status === "HIDDEN") + '">' + (cat.visibility_status === "HIDDEN" ? "公开" : "隐藏") + '</button>' : '') +
        '<button class="danger" data-cat-action="archive" data-id="' + esc(cat.id) + '" ' + (cat.visibility_status === "ARCHIVED" ? "disabled" : "") + '>归档</button></div>' + recovery + '</article>';
    }).join("") : '<div class="empty-state"><strong>没有匹配的猫咪档案</strong><p>调整搜索条件或等待新的居民提交。</p></div>';
    byId("load-more-admin-cats").hidden = !state.cursors.cats;
  }
  function searchAdminCats() {
    var query = byId("cat-search").value.trim();
    var sequence = (searchAdminCats.sequence || 0) + 1;
    searchAdminCats.sequence = sequence;
    request("/api/v1/cats?limit=24&q=" + encodeURIComponent(query)).then(function (body) {
      if (sequence !== searchAdminCats.sequence) return;
      state.cats = body.items || [];
      state.cursors.cats = body.next_cursor || null;
      renderCats();
    }).catch(function (error) { showGlobal(errorText(error), true); });
  }

  function scheduleAdminCatSearch() {
    window.clearTimeout(scheduleAdminCatSearch.timer);
    scheduleAdminCatSearch.timer = window.setTimeout(searchAdminCats, 240);
  }
  function renderCommunities() {
    byId("communities").innerHTML = state.communities.length ? state.communities.map(function (community) {
      var linked = community.linked_cats || [];
      var reviewable = ["PENDING_REVIEW", "NEEDS_CHANGES"].indexOf(community.status) >= 0;
      var previews = linked.slice(0, 3).map(function (cat) {
        return '<span class="linked-cat" data-linked-cat="' + esc(cat.id) + '">' + esc(cat.nickname) + ' · ' + esc(cat.code) + '</span>';
      }).join("");
      var mergeTargetId = "merge-target-" + community.id;
      var workbench = reviewable ? '<div class="review-workbench"><div class="linked-cats"><strong>关联猫咪共 ' + esc(community.linked_cat_count || 0) + ' 只</strong>' + (previews || '<span class="linked-cat empty">暂无关联档案</span>') + '</div>' +
        '<label>审核说明<textarea data-review-note="' + esc(community.id) + '" maxlength="500" placeholder="退回修改或驳回时必填"></textarea></label>' +
        '<label>合并到已开放小区<input type="search" data-target-search data-target-select="' + esc(mergeTargetId) + '" placeholder="输入名称搜索全部开放小区"><select id="' + esc(mergeTargetId) + '" data-merge-target="' + esc(community.id) + '"><option value="">请选择目标小区</option>' + activeTargetOptions(community.id) + '</select></label>' +
        '<div class="review-actions"><button data-community-action="approve" data-id="' + esc(community.id) + '" data-version="' + esc(community.version) + '">核准开放</button>' +
        '<button data-community-action="request_changes" data-id="' + esc(community.id) + '" data-version="' + esc(community.version) + '">退回补充</button>' +
        '<button data-community-action="merge" data-id="' + esc(community.id) + '" data-version="' + esc(community.version) + '">合并小区</button>' +
        '<button class="danger" data-community-action="reject" data-id="' + esc(community.id) + '" data-version="' + esc(community.version) + '">驳回无效内容</button></div></div>' : '';
      var merged = community.merged_into_name ? ' · 已合并至 ' + esc(community.merged_into_name) : '';
      return '<article class="list-item community-review-item"><div class="entity-icon community-entity">区</div><div class="entity-copy"><strong>' + esc(community.name) + '</strong><p>' + esc(community.street) + (community.review_note ? ' · ' + esc(community.review_note) : '') + merged + '</p><div class="badges"><span>' + esc(statusLabel(community.status)) + '</span><span>v' + esc(community.version) + '</span></div></div>' +
        (!reviewable ? '<div class="actions"><button class="danger" data-community-action="archive" data-id="' + esc(community.id) + '" data-version="' + esc(community.version) + '" ' + (["ARCHIVED", "MERGED"].indexOf(community.status) >= 0 ? "disabled" : "") + '>归档</button></div>' : '') + workbench + '</article>';
    }).join("") : '<div class="empty-state"><strong>暂无小区</strong><p>可以使用上方表单新增首个小区。</p></div>';
    byId("load-more-admin-communities").hidden = !state.cursors.communities;
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
    byId("load-more-admin-users").hidden = !state.cursors.users;
  }
  function render() {
    byId("cat-count").textContent = String(state.cats.length);
    byId("community-count").textContent = String(state.communities.length);
    byId("pending-count").textContent = String(state.cats.filter(function (cat) { return cat.review_status === "PENDING_REVIEW"; }).length + state.communities.filter(function (item) { return ["PENDING_REVIEW", "NEEDS_CHANGES"].indexOf(item.status) >= 0; }).length);
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
    var route;
    var options;
    try {
      if (action === "reassign") {
        var target = document.querySelector('[data-cat-reassign-target="' + button.dataset.id + '"]');
        var built = communityReview.buildCatReassignRequest(button.dataset.id, target ? target.value : "", button.dataset.version);
        route = built.path;
        options = built.options;
      } else {
        route = action === "review" ? "/api/v1/cats/" + id + "/review" : action === "visibility" ? "/api/v1/cats/" + id + "/visibility" : "/api/v1/cats/" + id + "/archive";
        var body = action === "review" ? { approved: true } : action === "visibility" ? { visible: button.dataset.visible === "true" } : undefined;
        options = { method: "POST", body: body };
      }
    } catch (error) {
      state.busy = false;
      button.disabled = false;
      showGlobal("请选择要改挂到的已开放小区", true);
      return;
    }
    request(route, options).then(function () { toast(action === "reassign" ? "猫咪已改挂到新小区" : "档案状态已更新"); return loadAll(); }).catch(function (error) { showGlobal(errorText(error), true); if (error.status === 409) return loadAll(); }).finally(function () { state.busy = false; });
  }
  function actOnCommunity(button) {
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    var id = button.dataset.id;
    var action = button.dataset.communityAction;
    var route;
    var options;
    try {
      if (action === "archive") {
        var archive = communityReview.buildArchiveRequest(id, button.dataset.version);
        route = archive.path;
        options = archive.options;
      } else {
        var note = document.querySelector('[data-review-note="' + id + '"]');
        var target = document.querySelector('[data-merge-target="' + id + '"]');
        var built = communityReview.buildActionRequest(action, id, {
          version: button.dataset.version,
          note: note ? note.value : "",
          targetCommunityId: target ? target.value : ""
        });
        route = built.path;
        options = built.options;
      }
    } catch (error) {
      state.busy = false;
      button.disabled = false;
      showGlobal(error.message === "review_note_required" ? "退回修改或驳回时必须填写审核原因" : error.message === "merge_target_required" ? "请选择要合并到的已开放小区" : "审核参数无效", true);
      return;
    }
    request(route, options).then(function () {
      toast(action === "merge" ? "小区已合并，关联猫咪已自动改挂" : "小区状态已更新");
      return loadAll();
    }).catch(function (error) {
      showGlobal(errorText(error), true);
      if (error.status === 409) return loadAll();
    }).finally(function () { state.busy = false; });
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
  byId("load-more-admin-cats").addEventListener("click", function (event) { loadMore("cats", event.currentTarget); });
  byId("load-more-admin-communities").addEventListener("click", function (event) { loadMore("communities", event.currentTarget); });
  byId("load-more-admin-users").addEventListener("click", function (event) { loadMore("users", event.currentTarget); });
  byId("cat-search").addEventListener("input", scheduleAdminCatSearch);
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
  document.addEventListener("input", function (event) {
    var input = event.target.closest("[data-target-search]");
    if (!input) return;
    window.clearTimeout(input.searchTimer);
    input.searchTimer = window.setTimeout(function () {
      request("/api/v1/communities?limit=24&q=" + encodeURIComponent(input.value.trim())).then(function (body) {
        var selectTarget = byId(input.dataset.targetSelect);
        if (!selectTarget) return;
        var current = selectTarget.value;
        selectTarget.innerHTML = '<option value="">请选择目标小区</option>' + (body.items || []).map(function (item) {
          return '<option value="' + esc(item.id) + '">' + esc(item.name) + ' · ' + esc(item.street) + '</option>';
        }).join("");
        if (Array.prototype.some.call(selectTarget.options, function (option) { return option.value === current; })) selectTarget.value = current;
      }).catch(function (error) { showGlobal(errorText(error), true); });
    }, 260);
  });

  var initialSection = window.location.hash.replace("#", "");
  if (["overview", "cats", "communities", "users"].indexOf(initialSection) >= 0) state.section = initialSection;
  if (token) restoreSession().then(function () { switchSection(state.section); }).catch(function () {});
  else showLogin("");
}());
