(function () {
  "use strict";

  var API_BASE = window.HELPCAT_API_BASE || "/help-cat-api";
  var TOKEN_KEY = "help_cat_admin_token";
  var H5_TOKEN_KEY = "help_cat_token";
  var communityReview = window.HelpCatCommunityReview;
  // 令牌优先读 localStorage：勾了"记住这台设备"就存在那里，关掉浏览器也还在；
  // 没勾的临时登录放在 sessionStorage（关标签页即失效）。
  function readToken() {
    try { return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || ""; }
    catch (error) { return sessionStorage.getItem(TOKEN_KEY) || ""; }
  }
  function writeToken(value, remember) {
    clearToken();
    try { (remember ? localStorage : sessionStorage).setItem(TOKEN_KEY, value); }
    catch (error) { sessionStorage.setItem(TOKEN_KEY, value); }
  }
  function clearToken() {
    try { localStorage.removeItem(TOKEN_KEY); } catch (error) {}
    sessionStorage.removeItem(TOKEN_KEY);
  }
  var token = readToken();
  var profile = null;
  var state = { cats: [], communities: [], users: [], messages: [], feeding: [], tasks: [], impact: [], newMessageCount: 0, messageFilter: "", taskFilter: "", counts: { tasks: 0 }, cursors: { cats: null, communities: null, users: null, messages: null, feeding: null, tasks: null, impact: null }, section: "overview", busy: false, selectedCats: {}, selectedCommunities: {} };

  function byId(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[character];
    });
  }
  function request(path, options) {
    var config = options || {};
    var headers = Object.assign({}, config.headers || {});
    var body;
    if (config.form) {
      // FormData 由浏览器自己带 multipart boundary，不能手动设置 Content-Type
      body = config.form;
    } else if (config.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(config.body);
    }
    if (token) headers.Authorization = "Bearer " + token;
    return fetch(API_BASE + path, {
      method: config.method || "GET",
      headers: headers,
      body: body
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
      too_many_login_attempts: "密码错误次数太多，请稍后再试。",
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
      version_conflict: "猫咪档案刚刚已被其他管理员更新，请刷新后重试",
      media_not_found: "这张图片已失效，请重新选择上传",
      lead_message_not_found: "这条留言已被删除或不存在",
      too_many_messages: "该访客提交过于频繁，请稍后再试",
      feeding_point_not_found: "投喂点不存在或已被删除",
      task_already_closed: "任务已完成或已取消，不能再操作",
      task_not_claimed: "任务还没有被领取",
      task_not_yours: "只能操作自己领取的任务",
      target_user_not_found: "指定的志愿者不存在或已停用",
      evidence_asset_forbidden: "不能使用这张凭证图片",
      cat_not_found: "猫咪档案不存在或已归档",
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
    clearToken();
    if (clearSharedToken) {
      try { localStorage.removeItem(H5_TOKEN_KEY); } catch (error) {}
      sessionStorage.removeItem(H5_TOKEN_KEY);
    }
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
  function authenticate(username, password, remember) {
    return request("/api/v1/auth/login", { method: "POST", body: { username: username, password: password, remember: !!remember } }).then(function (body) {
      token = body.access_token;
      writeToken(token, remember);
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
  function capturePage(path) {
    return request(path).then(function (body) {
      return body;
    }).catch(function (error) {
      return { items: [], next_cursor: null, pageError: error };
    });
  }
  function applyPage(type, body) {
    state[type] = (body && body.items) || [];
    state.cursors[type] = (body && body.next_cursor) || null;
  }
  function showPageError(messageId, page) {
    var target = byId(messageId);
    if (target) target.textContent = page && page.pageError ? errorText(page.pageError) : "";
  }
  function adminTasksPath(cursor) {
    var params = ["limit=24"];
    if (state.taskFilter) params.push("status=" + encodeURIComponent(state.taskFilter));
    if (cursor) params.push("cursor=" + encodeURIComponent(cursor));
    return "/api/v1/admin/tasks?" + params.join("&");
  }
  function activeTaskCount(items) {
    return (items || []).filter(function (task) {
      return task.status === "OPEN" || task.status === "CLAIMED";
    }).length;
  }
  function loadAll() {
    showGlobal("正在同步管理数据…", false);
    var requests = [
      request("/api/v1/cats?limit=24"),
      request("/api/v1/admin/communities?limit=24"),
      request("/api/v1/admin/messages?limit=24" + (state.messageFilter ? "&status=" + encodeURIComponent(state.messageFilter) : "")),
      capturePage("/api/v1/admin/feeding-points?limit=24"),
      capturePage(adminTasksPath()),
      capturePage("/api/v1/admin/impact-events?limit=24")
    ];
    if (profile.role === "SUPER_ADMIN") requests.push(request("/api/v1/admin/users?limit=24"));
    return Promise.all(requests).then(function (results) {
      state.cats = results[0].items || [];
      state.communities = results[1].items || [];
      state.cursors.cats = results[0].next_cursor || null;
      state.cursors.communities = results[1].next_cursor || null;
      state.messages = results[2].items || [];
      state.cursors.messages = results[2].next_cursor || null;
      state.newMessageCount = Number(results[2].new_count || 0);
      state.users = results[6] ? results[6].items || [] : [];
      state.cursors.users = results[6] ? results[6].next_cursor || null : null;
      applyPage("feeding", results[3]);
      applyPage("tasks", results[4]);
      applyPage("impact", results[5]);
      showPageError("feeding-panel-message", results[3]);
      showPageError("task-panel-message", results[4]);
      showPageError("impact-panel-message", results[5]);
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
    var route = type === "cats" ? "/api/v1/cats" : type === "users" ? "/api/v1/admin/users" : type === "messages" ? "/api/v1/admin/messages" : type === "feeding" ? "/api/v1/admin/feeding-points" : type === "tasks" ? "/api/v1/admin/tasks" : type === "impact" ? "/api/v1/admin/impact-events" : "/api/v1/admin/communities";
    var params = ["limit=24", "cursor=" + encodeURIComponent(cursor)];
    if (type === "cats" && byId("cat-search").value.trim()) params.push("q=" + encodeURIComponent(byId("cat-search").value.trim()));
    if (type === "messages" && state.messageFilter) params.push("status=" + encodeURIComponent(state.messageFilter));
    if (type === "tasks" && state.taskFilter) params.push("status=" + encodeURIComponent(state.taskFilter));
    request(route + "?" + params.join("&")).then(function (body) {
      state[type] = communityReview.appendUnique(state[type], body.items || []);
      state.cursors[type] = body.next_cursor || null;
      render();
    }).catch(function (error) {
      showGlobal(errorText(error), true);
    }).finally(function () {
      state.busy = false;
      button.disabled = false;
      button.textContent = type === "cats" ? "加载更多猫咪" : type === "users" ? "加载更多用户" : type === "messages" ? "加载更多留言" : type === "feeding" ? "加载更多投喂点" : type === "tasks" ? "加载更多任务" : type === "impact" ? "加载更多记录" : "加载更多小区";
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
  function catEventKindOptions() {
    return [["RESCUE", "相遇"], ["FEED", "投喂"], ["MEDICAL", "就医"], ["CHECKUP", "检查"], ["ADOPTED", "领养"], ["NOTE", "备注"]].map(function (pair) {
      return '<option value="' + pair[0] + '">' + pair[1] + '</option>';
    }).join("");
  }
  // ---- 批量审核 ----------------------------------------------------------
  // 单人管理员最费时间的就是一条条点"审核通过"。这里把勾选状态存在 state 里，
  // 重渲染后仍然保留；提交时带上 version，避免用过期页面覆盖别人的改动。

  function batchSelection(kind) {
    return kind === "cats" ? state.selectedCats : state.selectedCommunities;
  }

  function selectedItems(kind) {
    var selection = batchSelection(kind);
    var source = kind === "cats" ? state.cats : state.communities;
    return source.filter(function (item) { return selection[item.id]; })
      .map(function (item) { return { id: item.id, version: item.version }; });
  }

  function renderBatchBar(kind) {
    var items = selectedItems(kind);
    var pending = (kind === "cats" ? state.cats : state.communities).filter(function (item) {
      return kind === "cats" ? item.review_status === "PENDING_REVIEW" : ["PENDING_REVIEW", "NEEDS_CHANGES"].indexOf(item.status) >= 0;
    });
    var bar = byId(kind + "-batch-bar");
    if (!bar) return;
    bar.hidden = pending.length === 0;
    var count = byId(kind + "-batch-count");
    if (count) count.textContent = "已选 " + items.length + " / 待审 " + pending.length + " 条";
    var selectAll = byId(kind + "-select-all");
    if (selectAll) {
      selectAll.checked = pending.length > 0 && items.length === pending.length;
      selectAll.indeterminate = items.length > 0 && items.length < pending.length;
    }
    var button = byId(kind + "-batch-approve");
    if (button) button.disabled = items.length === 0 || state.busy;
  }

  function toggleAllPending(kind, checked) {
    var selection = batchSelection(kind);
    (kind === "cats" ? state.cats : state.communities).forEach(function (item) {
      var pending = kind === "cats"
        ? item.review_status === "PENDING_REVIEW"
        : ["PENDING_REVIEW", "NEEDS_CHANGES"].indexOf(item.status) >= 0;
      if (!pending) return;
      if (checked) selection[item.id] = true;
      else delete selection[item.id];
    });
    kind === "cats" ? renderCats() : renderCommunities();
  }

  function submitBatchApproval(kind) {
    var items = selectedItems(kind);
    if (!items.length || state.busy) return;
    var label = kind === "cats" ? "猫咪档案" : "待审小区";
    var extra = kind === "cats" ? "；如果它们挂在新提交的小区下，那些小区会一起开放" : "";
    if (!window.confirm("将通过 " + items.length + " 条" + label + extra + "。确认？")) return;
    state.busy = true;
    renderBatchBar(kind);
    // 注意：request() 内部会 JSON.stringify，这里必须传对象，不能传字符串
    // （传字符串会双重编码，后端拿到一个 JSON 字符串 → 422）。
    var payload = kind === "cats" ? { cats: items } : { communities: items };
    request("/api/v1/admin/reviews/approve", { method: "POST", body: payload })
      .then(function (result) {
        var opened = (result.opened_communities || []).length;
        var message = "已通过 " + result.approved_count + " 条";
        if (opened) message += "，同时开放了 " + opened + " 个待审小区";
        if (result.skipped_count) {
          var skipped = (result.cats || []).concat(result.communities || []).filter(function (item) { return item.status !== "approved"; });
          message += "；" + result.skipped_count + " 条没通过（" + skipped.map(function (item) { return errorText({ code: item.code, message: item.code }); }).join("、") + "）";
        }
        state.selectedCats = {};
        state.selectedCommunities = {};
        toast(message);
        return loadAll();
      })
      .catch(function (error) { showGlobal(errorText(error), true); })
      .finally(function () { state.busy = false; renderBatchBar(kind); });
  }

  function renderCats() {
    var query = byId("cat-search").value.trim().toLowerCase();
    var cats = state.cats.filter(function (cat) {
      return !query || [cat.nickname, cat.code, cat.location_note, cat.community_name].join(" ").toLowerCase().indexOf(query) >= 0;
    });
    byId("cats").innerHTML = cats.length ? cats.map(function (cat) {
      var blocker = cat.community_review_blocker;
      var targetId = "cat-target-" + cat.id;
      var hasPhoto = Boolean(cat.photo_asset_id);
      var photoBadge = '<span class="photo-badge">' + (hasPhoto ? "已有照片" : "暂无照片") + '</span>';
      var photoButton = '<button data-cat-action="photo" data-id="' + esc(cat.id) + '" data-version="' + esc(cat.version) + '" data-has-photo="' + (hasPhoto ? "true" : "false") + '">' + (hasPhoto ? "换图" : "补图") + '</button>';
      var recovery = blocker ? '<div class="reassign-workbench"><label>改挂到已开放小区<input type="search" data-target-search data-target-select="' + esc(targetId) + '" placeholder="输入小区名称搜索全部结果"><select id="' + esc(targetId) + '" data-cat-reassign-target="' + esc(cat.id) + '"><option value="">请选择目标小区</option>' + activeTargetOptions(cat.community_id) + '</select></label><button data-cat-action="reassign" data-id="' + esc(cat.id) + '" data-version="' + esc(cat.version) + '">确认改挂</button></div>' : '';
      var timeline = '<form class="cat-event-workbench" data-cat-event-form="' + esc(cat.id) + '" hidden>' +
        '<label>时间线类型<select data-cat-event-kind="' + esc(cat.id) + '">' + catEventKindOptions() + '</select></label>' +
        '<label>标题<input data-cat-event-title="' + esc(cat.id) + '" maxlength="120" required placeholder="例如：送到银湖宠物医院"></label>' +
        '<label>详情<textarea data-cat-event-detail="' + esc(cat.id) + '" maxlength="2000" placeholder="补充经过、结果或后续安排"></textarea></label>' +
        '<button class="button secondary" type="submit">保存时间线</button></form>';
      // 待审的档案前面给个勾选框，配合"批量审核通过"一次清掉队列。
      var picker = cat.review_status === "PENDING_REVIEW"
        ? '<label class="row-pick" title="选中后可批量通过"><input type="checkbox" data-cat-select="' + esc(cat.id) + '" data-version="' + esc(cat.version) + '"' + (state.selectedCats[cat.id] ? " checked" : "") + '><span class="sr-only">选择 ' + esc(cat.nickname) + '</span></label>'
        : '<span class="row-pick empty" aria-hidden="true"></span>';
      return '<article class="list-item"><div class="entity-icon cat-entity">猫</div>' + picker + '<div class="entity-copy"><strong>' + esc(cat.nickname) + '<small>' + esc(cat.code) + '</small></strong><p>' + esc(cat.community_name) + ' · ' + esc(cat.location_note) + '</p><div class="badges"><span>' + esc(statusLabel(cat.review_status)) + '</span><span>' + esc(statusLabel(cat.visibility_status)) + '</span>' + photoBadge + (blocker ? '<span class="blocker-badge">小区待处理</span>' : '') + '</div></div><div class="actions">' +
        (cat.review_status === "PENDING_REVIEW" ? (blocker ? '<button data-section-link="communities">查看小区状态</button>' : '<button data-cat-action="review" data-id="' + esc(cat.id) + '">审核通过</button>') : '') +
        (cat.visibility_status !== "ARCHIVED" ? '<button data-cat-action="visibility" data-id="' + esc(cat.id) + '" data-visible="' + String(cat.visibility_status === "HIDDEN") + '">' + (cat.visibility_status === "HIDDEN" ? "公开" : "隐藏") + '</button>' : '') +
        photoButton +
        '<button data-cat-action="event" data-id="' + esc(cat.id) + '">记录时间线</button>' +
        '<button class="danger" data-cat-action="archive" data-id="' + esc(cat.id) + '" ' + (cat.visibility_status === "ARCHIVED" ? "disabled" : "") + '>归档</button></div>' + recovery + timeline + '</article>';
    }).join("") : '<div class="empty-state"><strong>没有匹配的猫咪档案</strong><p>调整搜索条件或等待新的居民提交。</p></div>';
    renderBatchBar("cats");
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
      var picker = reviewable
        ? '<label class="row-pick" title="选中后可批量核准"><input type="checkbox" data-community-select="' + esc(community.id) + '" data-version="' + esc(community.version) + '"' + (state.selectedCommunities[community.id] ? " checked" : "") + '><span class="sr-only">选择 ' + esc(community.name) + '</span></label>'
        : '<span class="row-pick empty" aria-hidden="true"></span>';
      return '<article class="list-item community-review-item"><div class="entity-icon community-entity">区</div>' + picker + '<div class="entity-copy"><strong>' + esc(community.name) + '</strong><p>' + esc(community.street) + (community.review_note ? ' · ' + esc(community.review_note) : '') + merged + '</p><div class="badges"><span>' + esc(statusLabel(community.status)) + '</span><span>v' + esc(community.version) + '</span></div></div>' +
        (!reviewable ? '<div class="actions"><button class="danger" data-community-action="archive" data-id="' + esc(community.id) + '" data-version="' + esc(community.version) + '" ' + (["ARCHIVED", "MERGED"].indexOf(community.status) >= 0 ? "disabled" : "") + '>归档</button></div>' : '') + workbench + '</article>';
    }).join("") : '<div class="empty-state"><strong>暂无小区</strong><p>可以使用上方表单新增首个小区。</p></div>';
    renderBatchBar("communities");
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
  function syncCommunitySelect(selectId, placeholder) {
    var select = byId(selectId);
    if (!select) return;
    var current = select.value;
    var options = ['<option value="">' + esc(placeholder) + '</option>'];
    state.communities.forEach(function (community) {
      if (community.status !== "ACTIVE") return;
      options.push('<option value="' + esc(community.id) + '">' + esc(community.name) + ' · ' + esc(community.street) + '</option>');
    });
    var html = options.join("");
    if (select.getAttribute("data-options") !== html) {
      select.setAttribute("data-options", html);
      select.innerHTML = html;
    }
    if (Array.prototype.some.call(select.options, function (option) { return option.value === current; })) select.value = current;
  }

  /* ---------- 投喂点管理 ---------- */
  function feedingStatusLabel(value) {
    return { ACTIVE: "投喂中", PAUSED: "已暂停", ARCHIVED: "已归档" }[value] || value;
  }
  function feedingStatusTone(value) {
    return { ACTIVE: "active", PAUSED: "paused", ARCHIVED: "archived" }[value] || "paused";
  }
  function renderFeedingPoints() {
    byId("feeding-points").innerHTML = state.feeding.length ? state.feeding.map(function (point) {
      var community = point.community_name ? esc(point.community_name) : "未指定小区";
      var schedule = point.feeding_time ? ' · ' + esc(point.feeding_time) : '';
      var location = point.location_note ? '<p>位置：' + esc(point.location_note) + '</p>' : '';
      var caretaker = point.caretaker_note ? '<p>照看说明：' + esc(point.caretaker_note) + '</p>' : '';
      var archived = point.status === "ARCHIVED";
      var hasCoords = point.latitude !== null && point.latitude !== undefined && point.longitude !== null && point.longitude !== undefined;
      var coordsBadge = '<span>' + (hasCoords ? "已设坐标" : "未设坐标") + '</span>';
      var toggle = point.status === "ACTIVE"
        ? '<button data-feeding-action="pause" data-id="' + esc(point.id) + '">暂停投喂</button>'
        : '<button data-feeding-action="activate" data-id="' + esc(point.id) + '">恢复投喂</button>';
      // 没有坐标的点在居民端无法参与「按距离排序」，这里给一个就地补录入口
      var coordsButton = hasCoords ? "" : '<button data-feeding-action="coords" data-id="' + esc(point.id) + '">补坐标</button>';
      var coordsForm = hasCoords ? "" :
        '<form class="feeding-coords-form" data-feeding-coords-form="' + esc(point.id) + '" hidden>' +
        '<label>纬度<input data-feeding-lat="' + esc(point.id) + '" type="number" step="0.000001" min="-90" max="90" required placeholder="30.052000"></label>' +
        '<label>经度<input data-feeding-lng="' + esc(point.id) + '" type="number" step="0.000001" min="-180" max="180" required placeholder="119.962000"></label>' +
        '<button class="button secondary" type="submit">保存坐标</button></form>';
      return '<article class="list-item feeding-item"><div class="entity-icon feeding-entity">喂</div><div class="entity-copy"><strong>' + esc(point.name) + '<small>' + community + schedule + '</small></strong>' + location + caretaker + '<div class="badges"><span class="feeding-status ' + esc(feedingStatusTone(point.status)) + '">' + esc(feedingStatusLabel(point.status)) + '</span>' + coordsBadge + '<span>今日已喂 ' + esc(point.fed_today || 0) + ' 次</span>' + (point.fed_by_me ? '<span>我今天喂过</span>' : '') + '</div></div><div class="actions">' + coordsButton + toggle + '<button class="danger" data-feeding-action="archive" data-id="' + esc(point.id) + '" ' + (archived ? "disabled" : "") + '>归档</button></div>' + coordsForm + '</article>';
    }).join("") : '<div class="empty-state"><strong>暂无投喂点</strong><p>可以使用上方表单新增第一个投喂点。</p></div>';
    byId("load-more-admin-feeding").hidden = !state.cursors.feeding;
  }
  function loadFeedingPoints() {
    return request("/api/v1/admin/feeding-points?limit=24").then(function (body) {
      applyPage("feeding", body);
      byId("feeding-panel-message").textContent = "";
      renderSummary();
      renderFeedingPoints();
    }).catch(function (error) {
      byId("feeding-panel-message").textContent = errorText(error);
    });
  }
  function actOnFeeding(button) {
    if (button.dataset.feedingAction === "coords") {
      var form = document.querySelector('[data-feeding-coords-form="' + button.dataset.id + '"]');
      if (!form) return;
      form.hidden = !form.hidden;
      button.textContent = form.hidden ? "补坐标" : "收起坐标";
      return;
    }
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    var next = { pause: "PAUSED", activate: "ACTIVE", archive: "ARCHIVED" }[button.dataset.feedingAction];
    byId("feeding-panel-message").textContent = "正在更新投喂点…";
    request("/api/v1/admin/feeding-points/" + encodeURIComponent(button.dataset.id), { method: "PATCH", body: { status: next } }).then(function () {
      byId("feeding-panel-message").textContent = "";
      toast(next === "PAUSED" ? "投喂点已暂停" : next === "ARCHIVED" ? "投喂点已归档" : "投喂点已恢复投喂");
      return loadFeedingPoints();
    }).catch(function (error) {
      byId("feeding-panel-message").textContent = errorText(error);
      button.disabled = false;
    }).finally(function () { state.busy = false; });
  }

  /* ---------- 救助任务 ---------- */
  function taskStatusLabel(value) {
    return { OPEN: "待领取", CLAIMED: "进行中", COMPLETED: "已完成", CANCELLED: "已取消" }[value] || value;
  }
  function taskStatusTone(value) {
    return { OPEN: "open", CLAIMED: "claimed", COMPLETED: "completed", CANCELLED: "cancelled" }[value] || "open";
  }
  function renderTasks() {
    byId("admin-tasks").innerHTML = state.tasks.length ? state.tasks.map(function (task) {
      var community = task.community_name ? task.community_name : "未指定小区";
      var description = task.description ? '<p>' + esc(task.description) + '</p>' : '';
      var claim = task.claimed_by_username ? '<span>领取人：' + esc(task.claimed_by_username) + '</span>' : "";
      var completion = task.completion_note ? '<p class="lead-note">完成说明：' + esc(task.completion_note) + '</p>' : '';
      var reason = task.cancel_reason ? '<p class="lead-note">取消原因：' + esc(task.cancel_reason) + '</p>' : '';
      var cancellable = task.status === "OPEN" || task.status === "CLAIMED";
      var actions = (cancellable ? '<button data-task-action="cancel" data-id="' + esc(task.id) + '">取消任务</button>' : '') +
        (task.status === "CLAIMED" ? '<button data-task-action="reassign" data-id="' + esc(task.id) + '">释放回待领取</button>' : '');
      var reasonInput = cancellable ? '<label class="task-note">取消原因（选填）<input data-task-reason="' + esc(task.id) + '" maxlength="500" placeholder="会展示给领取人"></label>' : '';
      return '<article class="list-item task-item"><div class="entity-icon task-entity">任</div><div class="entity-copy"><strong>' + esc(task.title) + '<small>' + esc(community) + '</small></strong>' + description + completion + reason + '<div class="badges"><span class="task-status ' + esc(taskStatusTone(task.status)) + '">' + esc(taskStatusLabel(task.status)) + '</span>' + claim + '</div></div><div class="actions">' + actions + '</div>' + reasonInput + '</article>';
    }).join("") : '<div class="empty-state"><strong>暂无救助任务</strong><p>调整状态筛选，或用上方表单发布第一条任务。</p></div>';
    byId("load-more-admin-tasks").hidden = !state.cursors.tasks;
  }
  function loadTasks() {
    return request(adminTasksPath()).then(function (body) {
      applyPage("tasks", body);
      byId("task-panel-message").textContent = "";
      renderSummary();
      renderTasks();
    }).catch(function (error) {
      byId("task-panel-message").textContent = errorText(error);
    });
  }
  function setTaskFilter(filter) {
    state.taskFilter = filter || "";
    document.querySelectorAll("[data-task-filter]").forEach(function (button) {
      button.classList.toggle("active", (button.dataset.taskFilter || "") === state.taskFilter);
    });
    return loadTasks();
  }
  function refreshTaskCount() {
    return request("/api/v1/admin/tasks?limit=24").then(function (body) {
      state.counts.tasks = activeTaskCount(body.items || []);
      byId("admin-task-count").textContent = String(state.counts.tasks);
    }).catch(function () {});
  }
  function actOnTask(button) {
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    var id = button.dataset.id;
    var action = button.dataset.taskAction;
    var route;
    var options;
    if (action === "cancel") {
      var reason = document.querySelector('[data-task-reason="' + id + '"]');
      route = "/api/v1/tasks/" + encodeURIComponent(id) + "/cancel";
      options = { method: "POST", body: { reason: reason ? reason.value.trim() : "" } };
    } else {
      route = "/api/v1/tasks/" + encodeURIComponent(id) + "/reassign";
      options = { method: "POST", body: { target_user_id: null } };
    }
    byId("task-panel-message").textContent = "正在更新任务…";
    request(route, options).then(function () {
      byId("task-panel-message").textContent = "";
      toast(action === "cancel" ? "任务已取消" : "任务已释放回待领取");
      return loadTasks();
    }).catch(function (error) {
      byId("task-panel-message").textContent = errorText(error);
      button.disabled = false;
      if (error.status === 409) return loadTasks();
    }).finally(function () {
      state.busy = false;
      if (state.taskFilter) refreshTaskCount();
    });
  }

  /* ---------- 救助记录 ---------- */
  function impactKindLabel(value) {
    return { RESCUED: "已救助", ADOPTED: "找到新家", MEDICAL: "医疗救助", SUPPORTER: "爱心支持" }[value] || value;
  }
  function formatRecordTime(value) {
    if (!value) return "";
    var date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    try {
      return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
    } catch (error) {
      return String(value);
    }
  }
  function renderImpactEvents() {
    byId("impact-events").innerHTML = state.impact.length ? state.impact.map(function (item) {
      var reversed = Boolean(item.reversed_at);
      var note = item.note ? '<p>' + esc(item.note) + '</p>' : "";
      var occurred = '<span>' + esc(formatRecordTime(item.occurred_at)) + '</span>';
      var action = reversed ? '<span class="reversed-badge">已撤销</span>' : '<button class="danger" data-impact-action="reverse" data-id="' + esc(item.id) + '">撤销这一笔</button>';
      return '<article class="list-item impact-item' + (reversed ? " reversed" : "") + '"><div class="entity-icon impact-entity">记</div><div class="entity-copy"><strong>' + esc(impactKindLabel(item.kind)) + '<small class="impact-amount">× ' + esc(item.amount) + '</small></strong>' + note + '<div class="badges">' + occurred + (item.is_qa ? '<span>测试数据</span>' : '') + (reversed ? '<span>已撤销</span>' : '') + '</div></div><div class="actions">' + action + '</div></article>';
    }).join("") : '<div class="empty-state"><strong>暂无救助记录</strong><p>记录一笔之后，首页的公开计数会同步更新。</p></div>';
    byId("load-more-admin-impact").hidden = !state.cursors.impact;
  }
  function loadImpactEvents() {
    return request("/api/v1/admin/impact-events?limit=24").then(function (body) {
      applyPage("impact", body);
      byId("impact-panel-message").textContent = "";
      renderSummary();
      renderImpactEvents();
    }).catch(function (error) {
      byId("impact-panel-message").textContent = errorText(error);
    });
  }
  function actOnImpact(button) {
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    byId("impact-panel-message").textContent = "正在撤销这一笔…";
    request("/api/v1/admin/impact-events/" + encodeURIComponent(button.dataset.id) + "/reverse", { method: "POST" }).then(function () {
      byId("impact-panel-message").textContent = "";
      toast("已撤销，首页计数会同步更新");
      return loadImpactEvents();
    }).catch(function (error) {
      byId("impact-panel-message").textContent = errorText(error);
      button.disabled = false;
    }).finally(function () { state.busy = false; });
  }

  /* ---------- 猫咪时间线 ---------- */
  function toggleCatEventForm(button) {
    var form = document.querySelector('[data-cat-event-form="' + button.dataset.id + '"]');
    if (!form) return;
    form.hidden = !form.hidden;
    button.textContent = form.hidden ? "记录时间线" : "收起时间线";
  }
  function submitFeedingCoords(form) {
    if (state.busy) return;
    var pointId = form.getAttribute("data-feeding-coords-form");
    var latInput = form.querySelector("[data-feeding-lat]");
    var lngInput = form.querySelector("[data-feeding-lng]");
    var latitude = latInput ? Number(latInput.value) : NaN;
    var longitude = lngInput ? Number(lngInput.value) : NaN;
    if (!isFinite(latitude) || latitude < -90 || latitude > 90 || !isFinite(longitude) || longitude < -180 || longitude > 180) {
      byId("feeding-panel-message").textContent = "坐标不合法：纬度需在 -90~90，经度需在 -180~180";
      return;
    }
    state.busy = true;
    byId("feeding-panel-message").textContent = "正在保存坐标…";
    request("/api/v1/admin/feeding-points/" + encodeURIComponent(pointId), {
      method: "PATCH", body: { latitude: latitude, longitude: longitude }
    }).then(function () {
      byId("feeding-panel-message").textContent = "";
      toast("坐标已保存，居民端可按距离排序");
      return loadFeedingPoints();
    }).catch(function (error) {
      byId("feeding-panel-message").textContent = errorText(error);
    }).finally(function () { state.busy = false; });
  }

  function submitCatEvent(form) {
    if (state.busy) return;
    var catId = form.getAttribute("data-cat-event-form");
    var kind = form.querySelector("[data-cat-event-kind]");
    var title = form.querySelector("[data-cat-event-title]");
    var detail = form.querySelector("[data-cat-event-detail]");
    var value = title ? title.value.trim() : "";
    var button = form.querySelector('button[type="submit"]');
    if (!value) {
      showGlobal("请填写时间线标题", true);
      if (title) title.focus();
      return;
    }
    state.busy = true;
    if (button) button.disabled = true;
    request("/api/v1/admin/cats/" + encodeURIComponent(catId) + "/events", { method: "POST", body: {
      kind: kind ? kind.value : "NOTE", title: value, detail: detail ? detail.value.trim() : ""
    } }).then(function () {
      toast("时间线已记录");
      return loadAll();
    }).catch(function (error) {
      showGlobal(errorText(error), true);
    }).finally(function () {
      state.busy = false;
      if (button) button.disabled = false;
    });
  }

  /* ---------- 猫咪照片 ---------- */
  var photoTarget = null;
  function uploadCatPhoto(file) {
    var form = new FormData();
    form.append("file", file);
    return request("/api/v1/media/images", { method: "POST", form: form });
  }
  function pickCatPhoto(button) {
    if (state.busy) return;
    var input = byId("cat-photo-input");
    if (!input) return;
    photoTarget = {
      id: button.dataset.id,
      version: Number(button.dataset.version),
      hadPhoto: button.dataset.hasPhoto === "true",
      button: button
    };
    input.value = "";
    input.click();
  }
  function submitCatPhoto() {
    var input = byId("cat-photo-input");
    if (!input || !input.files || !input.files.length) return;
    var target = photoTarget;
    if (!target || state.busy) {
      input.value = "";
      photoTarget = null;
      return;
    }
    var file = input.files[0];
    var button = target.button && document.body.contains(target.button) ? target.button : document.querySelector('[data-cat-action="photo"][data-id="' + target.id + '"]');
    state.busy = true;
    if (button) button.disabled = true;
    byId("cats-panel-message").textContent = target.hadPhoto ? "正在替换照片…" : "正在上传照片…";
    uploadCatPhoto(file).then(function (asset) {
      var body = { photo_asset_id: asset.id };
      if (isFinite(target.version)) body.version = target.version;
      return request("/api/v1/admin/cats/" + encodeURIComponent(target.id), { method: "PATCH", body: body });
    }).then(function () {
      byId("cats-panel-message").textContent = "";
      toast(target.hadPhoto ? "猫咪照片已替换" : "猫咪照片已补齐");
      return loadAll();
    }).catch(function (error) {
      byId("cats-panel-message").textContent = errorText(error);
      // 版本过期说明列表里的 version 已经落后，刷新一次拿最新版本，用户可以直接重试
      if (error.status === 409) return loadAll();
    }).finally(function () {
      state.busy = false;
      photoTarget = null;
      input.value = "";
      if (button) button.disabled = false;
    });
  }

  function messageStatusLabel(value) {
    return { NEW: "待联系", CONTACTED: "已联系", CLOSED: "已关闭" }[value] || value;
  }
  function messageStatusTone(value) {
    return { NEW: "pending", CONTACTED: "approved", CLOSED: "muted" }[value] || "pending";
  }
  function contactTypeLabel(value) {
    return { WECHAT: "微信", PHONE: "手机号", QQ: "QQ", OTHER: "其他" }[value] || value;
  }
  function formatMessageTime(value) {
    if (!value) return "";
    var date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    try {
      return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
    } catch (error) {
      return String(value);
    }
  }
  function renderMessages() {
    byId("messages").innerHTML = state.messages.length ? state.messages.map(function (item) {
      var wanted = item.message ? '<p>' + esc(item.message) + '</p>' : '<p class="lead-empty">访客没有留下留言内容</p>';
      var note = item.admin_note ? '<p class="lead-note">处理备注：' + esc(item.admin_note) + '</p>' : '';
      var source = item.source ? '<p class="lead-source">来源：' + esc(item.source) + '</p>' : '';
      var actions = item.status === "CLOSED"
        ? '<button data-message-action="reopen" data-id="' + esc(item.id) + '">重新打开</button>'
        : '<button data-message-action="contacted" data-id="' + esc(item.id) + '">标记已联系</button><button class="danger" data-message-action="closed" data-id="' + esc(item.id) + '">关闭</button>';
      return '<article class="list-item lead-item"><div class="entity-icon lead-entity">言</div><div class="entity-copy"><strong>' + esc(item.name || "未留称呼") + '<small>' + esc(contactTypeLabel(item.contact_type)) + ' · ' + esc(formatMessageTime(item.created_at)) + '</small></strong><p class="lead-contact">' + esc(item.contact) + '</p>' + wanted + note + source + '<div class="badges"><span class="lead-status ' + esc(messageStatusTone(item.status)) + '">' + esc(messageStatusLabel(item.status)) + '</span></div></div><div class="actions">' + actions + '</div></article>';
    }).join("") : '<div class="empty-state"><strong>暂无留言</strong><p>把欢迎页链接发出去后，访客留下的联系方式会出现在这里。</p></div>';
    byId("load-more-admin-messages").hidden = !state.cursors.messages;
  }
  function syncMessageBadge() {
    byId("message-count").textContent = String(state.newMessageCount);
    var badge = byId("message-nav-badge");
    badge.textContent = String(state.newMessageCount);
    badge.hidden = !state.newMessageCount;
  }
  function loadMessages() {
    var query = "limit=24" + (state.messageFilter ? "&status=" + encodeURIComponent(state.messageFilter) : "");
    return request("/api/v1/admin/messages?" + query).then(function (body) {
      state.messages = body.items || [];
      state.cursors.messages = body.next_cursor || null;
      state.newMessageCount = Number(body.new_count || 0);
      byId("message-panel-message").textContent = "";
      renderMessages();
      syncMessageBadge();
    }).catch(function (error) {
      byId("message-panel-message").textContent = errorText(error);
    });
  }
  function actOnMessage(button) {
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    var next = { contacted: "CONTACTED", closed: "CLOSED", reopen: "NEW" }[button.dataset.messageAction];
    request("/api/v1/admin/messages/" + encodeURIComponent(button.dataset.id) + "/status", { method: "POST", body: { status: next } })
      .then(function () {
        toast(next === "CONTACTED" ? "已标记为已联系" : next === "CLOSED" ? "已关闭这条留言" : "已重新打开");
        return loadMessages();
      })
      .catch(function (error) { showGlobal(errorText(error), true); button.disabled = false; })
      .finally(function () { state.busy = false; });
  }
  function setMessageFilter(filter) {
    state.messageFilter = filter || "";
    document.querySelectorAll("[data-message-filter]").forEach(function (button) {
      button.classList.toggle("active", (button.dataset.messageFilter || "") === state.messageFilter);
    });
    return loadMessages();
  }
  function renderSummary() {
    byId("cat-count").textContent = String(state.cats.length);
    byId("community-count").textContent = String(state.communities.length);
    byId("pending-count").textContent = String(state.cats.filter(function (cat) { return cat.review_status === "PENDING_REVIEW"; }).length + state.communities.filter(function (item) { return ["PENDING_REVIEW", "NEEDS_CHANGES"].indexOf(item.status) >= 0; }).length);
    byId("user-count").textContent = String(state.users.length);
    byId("feeding-count").textContent = String(state.feeding.length);
    if (!state.taskFilter) state.counts.tasks = activeTaskCount(state.tasks);
    byId("admin-task-count").textContent = String(state.counts.tasks);
    byId("impact-count").textContent = String(state.impact.filter(function (item) { return !item.reversed_at; }).length);
    syncMessageBadge();
  }
  function render() {
    renderSummary();
    renderMessages();
    renderCats();
    renderCommunities();
    renderUsers();
    syncCommunitySelect("feeding-community", "不指定小区");
    syncCommunitySelect("task-community", "不指定小区");
    renderFeedingPoints();
    renderTasks();
    renderImpactEvents();
  }
  function switchSection(section) {
    if (section === "users" && (!profile || profile.role !== "SUPER_ADMIN")) return;
    state.section = section;
    var titles = { overview: "管理总览", cats: "猫咪档案", communities: "小区管理", feeding: "投喂点管理", tasks: "救助任务", messages: "留言板", impact: "救助记录", users: "用户与权限", devices: "登录的设备" };
    byId("page-title").textContent = titles[section] || "管理总览";
    document.querySelectorAll("[data-admin-section]").forEach(function (panel) {
      var active = panel.dataset.adminSection === section;
      panel.hidden = !active;
      panel.classList.toggle("active", active);
    });
    document.querySelectorAll(".side-nav").forEach(function (button) { button.classList.toggle("active", button.dataset.section === section); });
    window.location.hash = section;
    if (section === "devices") loadDevices();
  }

  // ---- 登录的设备：长期免登录的安全兜底（手机丢了要能一键切断）------------
  function deviceLine(label, value) {
    var wrap = document.createElement("span");
    wrap.className = "device-line";
    var strong = document.createElement("strong");
    strong.textContent = label;
    var span = document.createElement("span");
    span.textContent = value;
    wrap.appendChild(strong);
    wrap.appendChild(span);
    return wrap;
  }
  function renderDevices(items) {
    var list = byId("device-list");
    list.innerHTML = "";
    byId("device-message").textContent = items.length ? "" : "没有其它设备在登录。";
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.className = "device-item";
      li.appendChild(deviceLine(item.device, item.ip || "IP 未知"));
      li.appendChild(deviceLine("登录时间", String(item.created_at || "").replace("T", " ").slice(0, 16)));
      li.appendChild(deviceLine("有效期到", String(item.expires_at || "").replace("T", " ").slice(0, 16)));
      if (item.remember) {
        var tag = document.createElement("span");
        tag.className = "device-tag";
        tag.textContent = "记住设备";
        li.appendChild(tag);
      }
      if (item.current) {
        var current = document.createElement("span");
        current.className = "device-tag current";
        current.textContent = "本机";
        li.appendChild(current);
      } else {
        var button = document.createElement("button");
        button.className = "button secondary";
        button.type = "button";
        button.dataset.revokeSession = item.id;
        button.textContent = "踢出这台设备";
        li.appendChild(button);
      }
      list.appendChild(li);
    });
  }
  function loadDevices() {
    byId("device-message").textContent = "正在读取…";
    return request("/api/v1/auth/sessions").then(function (body) {
      renderDevices((body && body.items) || []);
      return body;
    }).catch(function (error) {
      byId("device-message").textContent = errorText(error);
      throw error;
    });
  }
  function revokeDevice(button) {
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    byId("device-message").textContent = "正在踢出…";
    request("/api/v1/auth/sessions/revoke", { method: "POST", body: { id: button.dataset.revokeSession } })
      .then(function () { byId("device-message").textContent = "那台设备已经被踢下线。"; return loadDevices(); })
      .catch(function (error) { byId("device-message").textContent = errorText(error); })
      .then(function () { state.busy = false; });
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

  byId("device-list").addEventListener("click", function (event) {
    var button = event.target.closest("[data-revoke-session]");
    if (button) revokeDevice(button);
  });
  byId("login-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    byId("login-submit").disabled = true;
    byId("login-message").textContent = "正在验证账号…";
    authenticate(byId("login-username").value.trim(), byId("login-password").value, byId("login-remember").checked).then(function () {
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
  byId("load-more-admin-messages").addEventListener("click", function (event) { loadMore("messages", event.currentTarget); });
  byId("load-more-admin-feeding").addEventListener("click", function (event) { loadMore("feeding", event.currentTarget); });
  byId("load-more-admin-tasks").addEventListener("click", function (event) { loadMore("tasks", event.currentTarget); });
  byId("load-more-admin-impact").addEventListener("click", function (event) { loadMore("impact", event.currentTarget); });
  byId("refresh-messages").addEventListener("click", loadMessages);
  byId("refresh-feeding").addEventListener("click", loadFeedingPoints);
  byId("refresh-tasks").addEventListener("click", loadTasks);
  byId("refresh-impact").addEventListener("click", loadImpactEvents);
  byId("cat-search").addEventListener("input", scheduleAdminCatSearch);
  byId("cat-photo-input").addEventListener("change", submitCatPhoto);
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
  byId("feeding-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    var button = event.target.querySelector("button[type=submit]");
    button.disabled = true;
    var communityId = byId("feeding-community").value;
    var latitude = byId("feeding-latitude").value.trim();
    var longitude = byId("feeding-longitude").value.trim();
    byId("feeding-panel-message").textContent = "";
    request("/api/v1/admin/feeding-points", { method: "POST", body: {
      name: byId("feeding-name").value.trim(),
      community_id: communityId || null,
      location_note: byId("feeding-location").value.trim(),
      feeding_time: byId("feeding-time").value.trim(),
      caretaker_note: byId("feeding-note").value.trim(),
      latitude: latitude ? Number(latitude) : null,
      longitude: longitude ? Number(longitude) : null
    } }).then(function () {
      event.target.reset();
      toast(latitude && longitude ? "投喂点已创建，居民端可按距离排序" : "投喂点已创建");
      return loadFeedingPoints();
    }).catch(function (error) { byId("feeding-panel-message").textContent = errorText(error); }).finally(function () { state.busy = false; button.disabled = false; });
  });
  byId("task-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    var button = event.target.querySelector("button[type=submit]");
    button.disabled = true;
    var communityId = byId("task-community").value;
    byId("task-panel-message").textContent = "";
    request("/api/v1/tasks", { method: "POST", body: {
      title: byId("task-title").value.trim(),
      description: byId("task-description").value.trim(),
      community_id: communityId || null
    } }).then(function () {
      event.target.reset();
      toast("任务已发布");
      return setTaskFilter("");
    }).catch(function (error) { byId("task-panel-message").textContent = errorText(error); }).finally(function () { state.busy = false; button.disabled = false; });
  });
  byId("impact-form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (state.busy) return;
    var amount = parseInt(byId("impact-amount").value, 10);
    if (!amount || amount < 1) {
      byId("impact-panel-message").textContent = "数量必须是不小于 1 的整数";
      return;
    }
    state.busy = true;
    var button = event.target.querySelector("button[type=submit]");
    button.disabled = true;
    byId("impact-panel-message").textContent = "";
    request("/api/v1/admin/impact-events", { method: "POST", body: {
      kind: byId("impact-kind").value,
      amount: amount,
      note: byId("impact-note").value.trim()
    } }).then(function () {
      event.target.reset();
      byId("impact-amount").value = "1";
      toast("已记录一笔，首页计数会同步更新");
      return loadImpactEvents();
    }).catch(function (error) { byId("impact-panel-message").textContent = errorText(error); }).finally(function () { state.busy = false; button.disabled = false; });
  });
  document.addEventListener("change", function (event) {
    var catPick = event.target.closest("[data-cat-select]");
    if (catPick) {
      if (catPick.checked) state.selectedCats[catPick.dataset.catSelect] = true;
      else delete state.selectedCats[catPick.dataset.catSelect];
      renderBatchBar("cats");
      return;
    }
    var communityPick = event.target.closest("[data-community-select]");
    if (communityPick) {
      if (communityPick.checked) state.selectedCommunities[communityPick.dataset.communitySelect] = true;
      else delete state.selectedCommunities[communityPick.dataset.communitySelect];
      renderBatchBar("communities");
    }
  });

  byId("cats-select-all").addEventListener("change", function (event) { toggleAllPending("cats", event.target.checked); });
  byId("communities-select-all").addEventListener("change", function (event) { toggleAllPending("communities", event.target.checked); });
  byId("cats-batch-approve").addEventListener("click", function () { submitBatchApproval("cats"); });
  byId("communities-batch-approve").addEventListener("click", function () { submitBatchApproval("communities"); });

  document.addEventListener("click", function (event) {
    var sectionButton = event.target.closest("[data-section], [data-section-link]");
    if (sectionButton) { switchSection(sectionButton.dataset.section || sectionButton.dataset.sectionLink); return; }
    var roleButton = event.target.closest("[data-user-id]");
    if (roleButton) { changeRole(roleButton); return; }
    var filterChip = event.target.closest("[data-message-filter]");
    if (filterChip) { setMessageFilter(filterChip.dataset.messageFilter); return; }
    var taskFilterChip = event.target.closest("[data-task-filter]");
    if (taskFilterChip) { setTaskFilter(taskFilterChip.dataset.taskFilter); return; }
    var messageButton = event.target.closest("[data-message-action]");
    if (messageButton) { actOnMessage(messageButton); return; }
    var feedingButton = event.target.closest("[data-feeding-action]");
    if (feedingButton) { actOnFeeding(feedingButton); return; }
    var taskButton = event.target.closest("[data-task-action]");
    if (taskButton) { actOnTask(taskButton); return; }
    var impactButton = event.target.closest("[data-impact-action]");
    if (impactButton) { actOnImpact(impactButton); return; }
    var catEventButton = event.target.closest('[data-cat-action="event"]');
    if (catEventButton) { toggleCatEventForm(catEventButton); return; }
    var catPhotoButton = event.target.closest('[data-cat-action="photo"]');
    if (catPhotoButton) { pickCatPhoto(catPhotoButton); return; }
    var catButton = event.target.closest("[data-cat-action]");
    if (catButton) { actOnCat(catButton); return; }
    var communityButton = event.target.closest("[data-community-action]");
    if (communityButton) actOnCommunity(communityButton);
  });
  document.addEventListener("submit", function (event) {
    var catEventForm = event.target.closest("[data-cat-event-form]");
    if (catEventForm) {
      event.preventDefault();
      submitCatEvent(catEventForm);
      return;
    }
    var coordsForm = event.target.closest("[data-feeding-coords-form]");
    if (coordsForm) {
      event.preventDefault();
      submitFeedingCoords(coordsForm);
    }
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
  if (["overview", "cats", "communities", "feeding", "tasks", "messages", "impact", "users"].indexOf(initialSection) >= 0) state.section = initialSection;
  // 总是先问服务端，不要因为"本机没有令牌"就直接弹登录框：
  // 会话也可能来自 HttpOnly Cookie（H5 登录后同一个 host 共享），
  // 而且后台强制 HTTPS、H5 走 HTTP 时两者是**不同源**，localStorage 根本不共享。
  // 这里和 app/rescue/api.js 的 restoreSession 是同一个坑，别再改回去。
  restoreSession().then(function () { switchSection(state.section); }).catch(function () {});
}());
