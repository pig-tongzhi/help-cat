(function () {
  "use strict";

  var api = window.HelpCatApi;
  var communityForm = window.HelpCatCommunityForm;
  var state = {
    user: null,
    communities: [],
    cats: [],
    tasks: [],
    metrics: { status: "loading", values: null },
    publicDataStatus: { cats: "loading", tasks: "loading", communities: "loading", metrics: "loading" },
    feedingPoints: [],
    homeFeeding: [],
    myFeedingSummary: null,
    nearby: null,
    feedingStats: null,
    myFeedingLogs: [],
    contact: null,
    activeTask: null,
    myTasks: [],
    submissions: { cats: [], communities: [] },
    view: "home",
    homeScrollY: 0,
    authMode: "login",
    catStep: 1,
    catCommunityMode: "existing",
    cursors: { communities: null, cats: null, tasks: null, feedingPoints: null, feedingLogs: null, submissionCats: null, submissionCommunities: null },
    location: null,
    catIdempotencyKey: null,
    submitting: false
  };

  var errorMessages = {
    invalid_credentials: "账号或密码不正确，请重新输入。",
    username_exists: "这个账号已经注册，请直接登录。",
    user_disabled: "账号已停用，请联系管理员。",
    daily_cat_limit_reached: "今天已达到 3 条建档上限，请明天再提交。",
    task_already_claimed: "这个任务刚刚已被其他志愿者领取。",
    task_already_closed: "这个任务已经结束，不能再操作。",
    task_not_claimed: "这个任务还没有被领取，无法上报完成。",
    task_not_yours: "只有领取任务的志愿者或管理员可以上报完成。",
    task_not_found: "这个任务不存在或已被删除。",
    target_user_not_found: "要转派的账号不存在或已停用。",
    evidence_asset_forbidden: "只能使用自己刚上传的照片作为凭证。",
    community_exists: "这个小区已经存在或正在审核。",
    community_not_found: "所选小区不存在或尚未审核通过。",
    stale_community_version: "小区信息刚刚已更新，已为你刷新最新内容，请重新确认。",
    community_not_editable: "当前小区状态不能再修改。",
    community_edit_forbidden: "只能修改自己提交的小区建议。",
    community_review_state_invalid: "当前小区状态不能执行这个审核动作。",
    invalid_community_name: "小区名称无效，请重新填写。",
    cat_not_found: "这只猫咪的档案不存在或尚未公开。",
    feeding_point_not_found: "这个喂食点不存在或已暂停。",
    photo_asset_forbidden: "只能关联自己刚上传的照片。",
    unsupported_image_type: "仅支持 JPEG、PNG 或 WebP 图片。",
    image_too_large: "图片过大，请压缩后重新选择。",
    image_too_many_pixels: "图片像素过大，请压缩后重新选择。",
    image_content_mismatch: "图片内容无法识别，请重新选择。",
    thumbnail_generation_failed: "缩略图生成失败，请重试。",
    media_not_found: "图片不存在或已删除。",
    too_many_messages: "提交太频繁了，请稍后再试，或直接加微信。",
    invalid_idempotency_key: "提交标识无效，请刷新页面后重试。",
    invalid_cursor: "翻页参数已失效，已为你重新加载。",
    unauthorized: "登录已失效，请重新登录。",
    session_expired: "登录已过期，请重新登录。",
    forbidden: "当前账号没有这个权限。",
    super_admin_required: "只有唯一超级管理员可以管理用户权限。",
    network_error: "网络连接失败，请检查后重试。"
  };

  function byId(id) { return document.getElementById(id); }
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[character];
    });
  }
  function errorText(error) {
    return errorMessages[error && error.code] || (error && error.message) || "操作失败，请稍后重试。";
  }
  function communityName(id, fallback) {
    var all = state.communities.concat(state.submissions.communities || []);
    var item = all.find(function (community) { return community.id === id; });
    return item ? item.name : (fallback || "社区范围内");
  }
  function photoUrl(cat, variant) {
    if (!cat.photo_asset_id) return "";
    var source = api.API_BASE + "/api/v1/media/" + encodeURIComponent(cat.photo_asset_id);
    return variant === "thumb" ? source + "?variant=thumb" : source;
  }
  function healthLabel(value) {
    return { HEALTHY: "状态良好", NEEDS_HELP: "需要关注", UNKNOWN: "待观察" }[value] || value || "待观察";
  }
  function healthTone(value) {
    return {
      HEALTHY: "healthy", "良好": "healthy", "状态良好": "healthy", "看起来健康": "healthy",
      NEEDS_HELP: "attention", "需要观察": "attention", "需要帮助": "attention", "需要关注": "attention", "可能需要帮助": "attention",
      UNKNOWN: "unknown", "待观察": "unknown"
    }[value] || "unknown";
  }
  function reviewLabel(value) {
    return { APPROVED: "已通过", ACTIVE: "已开放", PENDING_REVIEW: "待审核", NEEDS_CHANGES: "待补充", MERGED: "已合并", REJECTED: "未通过", HIDDEN: "未开放", ARCHIVED: "已归档" }[value] || value;
  }
  function reviewTone(value) {
    return { APPROVED: "approved", ACTIVE: "approved", PENDING_REVIEW: "pending", NEEDS_CHANGES: "attention", MERGED: "merged", REJECTED: "rejected", HIDDEN: "rejected", ARCHIVED: "muted" }[value] || "pending";
  }
  function showStatus(message, isError) {
    var target = byId("app-status");
    target.textContent = message || "";
    target.classList.toggle("error", Boolean(isError));
    target.hidden = !message;
  }
  function toast(message) {
    var target = byId("toast");
    target.textContent = message;
    target.hidden = false;
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () { target.hidden = true; }, 2800);
  }

  function uniqueCollectionCount(collection) {
    var seen = Object.create(null);
    return (Array.isArray(collection) ? collection : []).reduce(function (count, item, index) {
      var key = item && item.id != null ? "id:" + String(item.id) : "item:" + String(index);
      if (seen[key]) return count;
      seen[key] = true;
      return count + 1;
    }, 0);
  }

  function formatMetric(value) {
    try {
      return new Intl.NumberFormat("zh-CN").format(value);
    } catch (error) {
      return String(value);
    }
  }

  function moduleMessage(status) {
    return { loading: "正在加载…", error: "加载失败，稍后会自动重试。", empty: "暂时还没有内容。" }[status] || "";
  }

  function renderHomeModuleState(module, status, message) {
    state.publicDataStatus[module] = status;
    if (module === "metrics") {
      var strip = byId("home-metrics-status");
      if (strip) strip.dataset.moduleState = status;
      return;
    }
    var target = byId("home-" + module + "-status");
    if (!target) return;
    var text = message || moduleMessage(status);
    target.textContent = status === "ready" ? "" : text;
    target.hidden = status === "ready" || !text;
    target.classList.toggle("error", status === "error");
  }

  function renderMetrics() {
    var definitions = [
      { key: "rescued", label: "已救助" },
      { key: "adopted", label: "找到新家" },
      { key: "medical", label: "医疗救助" },
      { key: "supporters", label: "爱心支持" }
    ];
    var total = 0;
    definitions.forEach(function (definition) {
      var value = byId("metric-" + definition.key);
      var label = byId("metric-" + definition.key + "-label");
      value.closest(".metric-card").dataset.metricState = state.metrics.status;
      label.textContent = definition.label;
      if (state.metrics.status === "ready") {
        var amount = state.metrics.values[definition.key];
        total += amount;
        value.textContent = amount === 0 ? "正在积累" : formatMetric(amount);
        // 占位文案用小字样式，避免和真实数字一样抢眼
        value.classList.toggle("is-placeholder", amount === 0);
        value.setAttribute("aria-label", definition.label + " " + formatMetric(amount));
      } else {
        value.textContent = "—";
        value.classList.toggle("is-placeholder", true);
        if (state.metrics.status === "error") value.setAttribute("aria-label", definition.label + "暂时无法获取");
        else value.setAttribute("aria-label", definition.label + "正在加载");
      }
    });
    renderHomeModuleState("metrics", state.metrics.status);
    var note = byId("home-metrics-note");
    if (!note) return;
    if (state.metrics.status === "error") {
      note.textContent = "救助数据暂时无法获取，稍后会自动重试。";
      note.hidden = false;
      note.classList.add("error");
    } else if (state.metrics.status === "ready" && total === 0) {
      note.textContent = "这些数字来自管理员录入的真实救助记录，目前还没有录入，所以先显示「正在积累」。";
      note.hidden = false;
      note.classList.remove("error");
    } else {
      note.textContent = "";
      note.hidden = true;
      note.classList.remove("error");
    }
  }

  function loadPublicMetrics() {
    state.metrics.status = "loading";
    renderMetrics();
    return api.request("/api/v1/public/metrics").then(function (metrics) {
      if (["rescued", "adopted", "medical", "supporters"].some(function (key) { return typeof metrics[key] !== "number"; })) {
        throw { code: "invalid_metrics", message: "公开指标响应无效" };
      }
      state.metrics.values = metrics;
      state.metrics.status = "ready";
      renderMetrics();
      return metrics;
    }).catch(function () {
      state.metrics.values = null;
      state.metrics.status = "error";
      renderMetrics();
      return null;
    });
  }

  function checkForUpdate() {
    var current = document.documentElement.dataset.appVersion || "";
    return window.HelpCatVersion.checkForUpdate(fetch, window.location.pathname, current, function () {
      byId("version-update").hidden = false;
    });
  }

  function loadPublicData() {
    ["cats", "tasks", "communities"].forEach(function (module) { renderHomeModuleState(module, "loading"); });
    loadHomeFeeding();
    return Promise.all([
      api.request("/api/v1/communities?limit=24"),
      api.request("/api/v1/cats?limit=24"),
      api.request("/api/v1/tasks?limit=24")
    ]).then(function (results) {
      state.communities = results[0].items || [];
      state.cats = results[1].items || [];
      state.cursors.communities = results[0].next_cursor || null;
      state.cursors.cats = results[1].next_cursor || null;
      state.tasks = results[2].items || [];
      state.cursors.tasks = results[2].next_cursor || null;
      renderHomeModuleState("cats", state.cats.length ? "ready" : "empty");
      renderHomeModuleState("tasks", state.tasks.length ? "ready" : "empty");
      renderHomeModuleState("communities", "ready");
      renderApp();
    }).catch(function (error) {
      ["cats", "tasks", "communities"].forEach(function (module) { renderHomeModuleState(module, "error"); });
      toast(errorText(error));
      renderApp();
    });
  }

  function loadMoreCollection(type, button) {
    var cursor = state.cursors[type];
    if (!cursor || state.submitting) return Promise.resolve();
    state.submitting = true;
    button.disabled = true;
    button.textContent = "正在加载…";
    var path = type === "cats" ? "/api/v1/cats" : type === "tasks" ? "/api/v1/tasks" : "/api/v1/communities";
    var params = ["limit=24", "cursor=" + encodeURIComponent(cursor)];
    if (type === "cats") {
      var query = byId("cat-search").value.trim();
      var communityId = byId("community-filter").value;
      if (query) params.push("q=" + encodeURIComponent(query));
      if (communityId) params.push("community_id=" + encodeURIComponent(communityId));
    }
    return api.request(path + "?" + params.join("&")).then(function (payload) {
      state[type] = communityForm.appendUnique(state[type], payload.items || []);
      state.cursors[type] = payload.next_cursor || null;
      if (type === "cats") renderCats();
      else if (type === "tasks") renderTasks();
      else renderCommunityOptions();
    }).catch(function (error) {
      toast(errorText(error));
    }).finally(function () {
      state.submitting = false;
      button.disabled = false;
      button.textContent = type === "cats" ? "加载更多猫咪" : type === "tasks" ? "加载更多任务" : "加载更多已审核小区";
    });
  }

  function loadSubmissions(append) {
    if (!state.user) return Promise.resolve();
    var query = communityForm.buildSubmissionQuery(append, {
      cats: state.cursors.submissionCats,
      communities: state.cursors.submissionCommunities
    }, 24);
    return api.request("/api/v1/me/submissions?" + query).then(function (payload) {
      state.submissions = {
        cats: append ? communityForm.appendUnique(state.submissions.cats, payload.cats || []) : payload.cats || [],
        communities: append ? communityForm.appendUnique(state.submissions.communities, payload.communities || []) : payload.communities || []
      };
      var next = payload.next_cursor || {};
      state.cursors.submissionCats = next.cats || null;
      state.cursors.submissionCommunities = next.communities || null;
      renderSubmissions();
    }).catch(function (error) {
      if (error.status === 401) state.user = null;
      toast(errorText(error));
      renderAccount();
    });
  }

  function catCard(cat) {
    var image = photoUrl(cat, "thumb");
    var originalImage = photoUrl(cat);
    return '<article class="cat-card" data-cat-open="' + escapeHtml(cat.id) + '" tabindex="0" role="button" aria-label="查看 ' + escapeHtml(cat.nickname) + ' 的档案">' +
      '<div class="cat-photo ' + (image ? "has-photo" : "") + '">' +
      '<span class="cat-placeholder" aria-hidden="true"><i></i><small>暂无照片</small></span>' +
      (image ? '<img data-cat-photo data-original-src="' + escapeHtml(originalImage) + '" src="' + escapeHtml(image) + '" alt="' + escapeHtml(cat.nickname) + '的照片" width="640" height="480" loading="lazy" decoding="async">' : '') +
      '<span class="health-badge ' + healthTone(cat.health_status) + '">' + escapeHtml(healthLabel(cat.health_status)) + '</span></div>' +
      '<div class="cat-card-body"><div class="cat-title"><h3>' + escapeHtml(cat.nickname) + '</h3><span>' + escapeHtml(cat.code) + '</span></div>' +
      '<p class="cat-community">' + escapeHtml(communityName(cat.community_id, cat.community_name)) + '</p>' +
      '<p class="cat-meta">' + escapeHtml(cat.living_status || "居住情况待观察") + ' · ' + escapeHtml(cat.location_note || "位置已保护") + '</p>' +
      '<span class="cat-card-more">查看档案与时间线 →</span></div></article>';
  }

  function taskCard(task) {
    return '<article class="task-card"><span class="task-priority">待领取</span><div class="task-copy"><h3>' + escapeHtml(task.title) + '</h3>' +
      '<p>' + escapeHtml(task.description || "管理员发布的社区救助任务") + '</p><span>' + escapeHtml(communityName(task.community_id, task.community_name)) + '</span></div>' +
      '<button class="button secondary compact claim-task" type="button" data-task-id="' + escapeHtml(task.id) + '">领取任务</button></article>';
  }

  function taskEmptyCard() {
    return '<div class="empty-state"><strong>暂时没有开放任务</strong><p>有新的救助行动时会在这里及时发布。你现在也可以先留下联系方式，需要人手时管理员会来找你。</p>' +
      '<button class="button secondary compact" type="button" data-contact-open="1">我想帮忙，留下联系方式</button></div>';
  }

  function emptyCard(title, description) {
    return '<div class="empty-state"><strong>' + escapeHtml(title) + '</strong><p>' + escapeHtml(description) + '</p></div>';
  }

  function filteredCats() {
    var query = byId("cat-search").value.trim().toLowerCase();
    var communityId = byId("community-filter").value;
    return state.cats.filter(function (cat) {
      var haystack = [cat.nickname, cat.code, communityName(cat.community_id, cat.community_name), cat.community_name].join(" ").toLowerCase();
      return (!query || haystack.indexOf(query) >= 0) && (!communityId || cat.community_id === communityId);
    });
  }

  function searchCatsFromServer() {
    var query = byId("cat-search").value.trim();
    var communityId = byId("community-filter").value;
    var sequence = (searchCatsFromServer.sequence || 0) + 1;
    searchCatsFromServer.sequence = sequence;
    var params = ["limit=24"];
    if (query) params.push("q=" + encodeURIComponent(query));
    if (communityId) params.push("community_id=" + encodeURIComponent(communityId));
    api.request("/api/v1/cats?" + params.join("&")).then(function (payload) {
      if (sequence !== searchCatsFromServer.sequence) return;
      state.cats = payload.items || [];
      state.cursors.cats = payload.next_cursor || null;
      renderCats();
    }).catch(function (error) { toast(errorText(error)); });
  }

  function scheduleCatSearch() {
    window.clearTimeout(scheduleCatSearch.timer);
    scheduleCatSearch.timer = window.setTimeout(searchCatsFromServer, 240);
  }

  function renderCats() {
    var cats = filteredCats();
    var homeCats = state.cats.slice(0, 4);
    var storyIndex = state.cats.findIndex(function (cat) { return cat.profile_key === "story-77"; });
    if (storyIndex > 0) {
      homeCats = [state.cats[storyIndex]].concat(state.cats.filter(function (_, index) { return index !== storyIndex; })).slice(0, 4);
    }
    // 服务端只返回一页，因此这里说"已显示"而不是伪造总数。
    byId("cat-result-count").textContent = "已显示 " + cats.length + " 只已审核猫咪" + (state.cursors.cats ? "（还有更多，可加载下一页）" : "");
    byId("home-cats").innerHTML = homeCats.length ? homeCats.map(catCard).join("") : emptyCard("还没有公开档案", "登录后可以提交第一只社区猫咪。");
    byId("cat-list").innerHTML = cats.length ? cats.map(catCard).join("") : emptyCard("没有找到匹配档案", "试试更换名称或小区筛选条件。");
    byId("load-more-cats").hidden = !state.cursors.cats;
  }

  function renderTasks() {
    byId("open-task-count").textContent = formatMetric(uniqueCollectionCount(state.tasks));
    var content = state.tasks.length ? state.tasks.map(taskCard).join("") : taskEmptyCard();
    byId("task-list").innerHTML = content;
    byId("home-tasks").innerHTML = state.tasks.length ? state.tasks.slice(0, 1).map(taskCard).join("") : taskEmptyCard();
    byId("load-more-tasks").hidden = !state.cursors.tasks;
    renderMyTasks();
  }

  function renderMyTasks() {
    var section = byId("my-tasks-section");
    var list = byId("my-task-list");
    if (!section || !list) return;
    var mine = state.myTasks || [];
    section.hidden = !state.user || !mine.length;
    list.innerHTML = mine.map(myTaskCard).join("");
  }

  function renderCommunityOptions() {
    var filterValue = byId("community-filter").value;
    var catValue = byId("cat-community").value;
    var filterOptions = '<option value="">全部小区</option>';
    var catOptions = '<option value="">请选择已审核小区</option>';
    state.communities.forEach(function (community) {
      var option = '<option value="' + escapeHtml(community.id) + '">' + escapeHtml(community.street + " · " + community.name) + '</option>';
      filterOptions += option;
      catOptions += option;
    });
    byId("community-filter").innerHTML = filterOptions;
    byId("cat-community").innerHTML = catOptions;
    if (state.communities.some(function (item) { return item.id === filterValue; })) byId("community-filter").value = filterValue;
    if (state.communities.some(function (item) { return item.id === catValue; })) byId("cat-community").value = catValue;
    byId("load-more-communities").hidden = !state.cursors.communities;
  }

  function normalizedRole(role) {
    var value = String(role || "USER").toUpperCase();
    return ["ADMIN", "SUPER_ADMIN"].indexOf(value) >= 0 ? value : "USER";
  }

  function isAdminRole(role) {
    var value = normalizedRole(role);
    return value === "ADMIN" || value === "SUPER_ADMIN";
  }

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

  function renderAccount() {
    var signedIn = Boolean(state.user);
    var role = normalizedRole(signedIn ? state.user.role : "USER");
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
    byId("account-action").textContent = signedIn ? "退出登录" : "登录 / 注册";
    byId("account-card").classList.toggle("guest-state", !signedIn);
    byId("signed-in-content").hidden = !signedIn;
    renderCommunityEntry();
    if (signedIn) renderSubmissions();
  }

  function renderSubmissions() {
    if (!state.user) return;
    var items = [];
    state.submissions.communities.forEach(function (community) {
      var review = community.status === "ACTIVE" ? "APPROVED" : community.status;
      var editable = ["PENDING_REVIEW", "NEEDS_CHANGES"].indexOf(community.status) >= 0;
      var meta = communityForm.statusMeta(community.status);
      var mergedTarget = community.status === "MERGED" && community.merged_into_name ? ' · 已合并至' + escapeHtml(community.merged_into_name) : '';
      items.push('<article class="submission-item community-submission"><span class="submission-type">小区建议</span><div class="submission-main"><strong>' + escapeHtml(community.name) + '</strong><p>' + escapeHtml(community.street) + (community.review_note ? ' · ' + escapeHtml(community.review_note) : '') + mergedTarget + '</p>' +
        (editable ? '<button class="inline-link correction-toggle" type="button" data-edit-community="' + escapeHtml(community.id) + '">修改并重新提交</button>' : '') +
        '</div><span class="review-status ' + escapeHtml(meta.tone) + '">' + escapeHtml(meta.label) + '</span>' +
        (editable ? '<form class="community-correction" data-community-correction-form="' + escapeHtml(community.id) + '" hidden>' +
          '<label>小区名称<input name="name" maxlength="120" required value="' + escapeHtml(community.name) + '"></label>' +
          '<label>所属街道<input name="street" maxlength="80" required value="' + escapeHtml(community.street) + '"></label>' +
          '<label>补充说明<textarea name="note" maxlength="500">' + escapeHtml(community.review_note || '') + '</textarea></label>' +
          '<input name="version" type="hidden" value="' + escapeHtml(community.version) + '">' +
          '<button class="button secondary compact" type="submit">保存并重新提交</button></form>' : '') + '</article>');
    });
    state.submissions.cats.forEach(function (cat) {
      var blocker = cat.community_review_blocker ? '<small class="submission-blocker">小区信息待审核或修正，猫咪档案暂不会公开</small>' : '';
      items.push('<article class="submission-item"><span class="submission-type">猫咪档案</span><div><strong>' + escapeHtml(cat.nickname) + '</strong><p>' + escapeHtml(communityName(cat.community_id, cat.community_name)) + ' · ' + escapeHtml(cat.code) + '</p>' + blocker + '</div><span class="review-status ' + reviewTone(cat.review_status) + '">' + escapeHtml(reviewLabel(cat.review_status)) + '</span></article>');
    });
    byId("submission-list").innerHTML = items.length ? items.join("") : emptyCard("还没有提交记录", "完成猫咪建档或小区建议后会显示在这里。");
    byId("load-more-submissions").hidden = !(state.cursors.submissionCats || state.cursors.submissionCommunities);
  }

  // ---- 加入我们：联系方式与留言 ---------------------------------------

  function sourceFromLocation() {
    var match = /(?:^|&)(?:from|utm_source)=([^&]+)/.exec(window.location.search.replace(/^\?/, ""));
    if (match) {
      try { return decodeURIComponent(match[1]).slice(0, 80); } catch (error) { return ""; }
    }
    return String(document.referrer || "").replace(/^https?:\/\//, "").split("/")[0].slice(0, 80);
  }

  function loadContact() {
    if (state.contact) return Promise.resolve(state.contact);
    return api.request("/api/v1/public/contact").then(function (payload) {
      state.contact = payload;
      return payload;
    }).catch(function () {
      state.contact = { wechat: "", wechat_note: "帮帮小猫", qr_image: "", phone: "", note: "" };
      return state.contact;
    });
  }

  function openContactSheet() {
    openSheet("contact-sheet");
    byId("contact-wechat").textContent = "正在获取…";
    loadContact().then(function (payload) {
      byId("contact-wechat").textContent = payload.wechat || "请先留言，管理员会来加你";
      byId("contact-note").textContent = payload.wechat_note || "帮帮小猫";
      byId("contact-footnote").textContent = payload.note || "";
    });
  }

  function submitContact(event) {
    event.preventDefault();
    if (state.submitting) return;
    var field = byId("contact-value");
    var value = field.value.trim();
    if (value.length < 2) {
      byId("contact-status").textContent = "请填写微信号或手机号，方便我们联系你。";
      field.focus();
      return;
    }
    state.submitting = true;
    var button = byId("contact-submit");
    button.disabled = true;
    byId("contact-status").textContent = "正在提交…";
    api.request("/api/v1/public/messages", {
      method: "POST",
      body: {
        name: byId("contact-name").value.trim(),
        contact_type: byId("contact-type").value,
        contact: value,
        message: byId("contact-message").value.trim(),
        source: sourceFromLocation()
      }
    }).then(function () {
      byId("contact-form").reset();
      byId("contact-status").textContent = "已收到，管理员会尽快加你。也可以直接加上面的微信。";
      toast("提交成功，谢谢你的加入");
    }).catch(function (error) {
      byId("contact-status").textContent = errorText(error);
    }).finally(function () {
      state.submitting = false;
      button.disabled = false;
    });
  }

  // ---- 猫咪详情与时间线 -----------------------------------------------

  var CAT_EVENT_LABELS = { RESCUE: "相遇", FEED: "投喂", MEDICAL: "就医", CHECKUP: "检查", ADOPTED: "领养", NOTE: "记录" };

  function openCatDetail(catId) {
    var cat = state.cats.find(function (item) { return item.id === catId; });
    if (!cat) return;
    openSheet("cat-detail-sheet");
    var image = photoUrl(cat);
    byId("cat-detail-body").innerHTML =
      '<span class="section-kicker">CAT PROFILE</span>' +
      '<h2 id="cat-detail-title">' + escapeHtml(cat.nickname) + '</h2>' +
      '<p class="sheet-intro">' + escapeHtml(cat.code) + ' · ' + escapeHtml(communityName(cat.community_id, cat.community_name)) + '</p>' +
      (image ? '<div class="cat-detail-photo"><img src="' + escapeHtml(image) + '" alt="' + escapeHtml(cat.nickname) + '的照片" loading="lazy" decoding="async"></div>' : '') +
      '<dl class="cat-detail-facts">' +
      '<div><dt>健康</dt><dd>' + escapeHtml(healthLabel(cat.health_status)) + '</dd></div>' +
      '<div><dt>居住</dt><dd>' + escapeHtml(cat.living_status || "待观察") + '</dd></div>' +
      '<div><dt>活动范围</dt><dd>' + escapeHtml(cat.location_note || "位置已保护") + '</dd></div>' +
      '</dl>' +
      '<p class="privacy-label">精确坐标、联系方式和未经确认的医疗信息不会公开。</p>' +
      '<div class="cat-timeline" id="cat-timeline"><p class="module-status">正在加载时间线…</p></div>' +
      '<button class="button secondary full" type="button" data-contact-open="1">我见过它，想帮忙</button>';
    api.request("/api/v1/cats/" + encodeURIComponent(catId) + "/events").then(function (payload) {
      var items = payload.items || [];
      byId("cat-timeline").innerHTML = items.length
        ? '<div class="section-title"><div><h3>时间线</h3></div></div>' + items.map(function (item) {
            return '<article class="timeline-item"><span class="timeline-kind">' + escapeHtml(CAT_EVENT_LABELS[item.kind] || item.kind) + '</span>' +
              '<div><strong>' + escapeHtml(item.title) + '</strong>' +
              (item.detail ? '<p>' + escapeHtml(item.detail) + '</p>' : '') +
              '<small>' + escapeHtml(String(item.occurred_at || "").slice(0, 10)) + '</small></div></article>';
          }).join("")
        : '<p class="module-status">还没有公开的时间线记录。</p>';
    }).catch(function () {
      byId("cat-timeline").innerHTML = '<p class="module-status error">时间线加载失败，稍后会自动重试。</p>';
    });
  }

  // ---- 定点投喂 -------------------------------------------------------

  function loadFeedingStats() {
    return api.request("/api/v1/public/feeding-stats").then(function (payload) {
      state.feedingStats = payload;
      renderFeedingStats();
    }).catch(function () {
      state.feedingStats = null;
      renderFeedingStats();
    });
  }

  function renderFeedingStats() {
    var target = byId("feeding-stats");
    if (!target) return;
    var stats = state.feedingStats;
    if (!stats) { target.innerHTML = ""; return; }
    var cards = [
      { label: "喂食点", value: stats.points_active },
      { label: "今日打卡", value: stats.feeds_today },
      { label: "近 7 天打卡", value: stats.feeds_week },
      { label: "参与志愿者", value: stats.volunteers_week }
    ];
    target.innerHTML = cards.map(function (card) {
      return '<article class="feeding-stat"><strong>' + (card.value ? formatMetric(card.value) : "正在积累") + '</strong><small>' + card.label + '</small></article>';
    }).join("");
  }

  function feedingPointCard(point) {
    var meta = [point.feeding_time, point.location_note].filter(Boolean).join(" · ");
    return '<article class="feeding-card' + (point.needs_feed ? " needs-feed" : "") + '"><div class="feeding-copy">' +
      '<strong>' + escapeHtml(point.name) + '</strong>' +
      '<p>' + escapeHtml(meta || "投喂时间待补充") + '</p>' +
      '<span class="feeding-tags">' +
      (point.needs_feed ? '<span class="feeding-badge">今天还没人喂</span>' : "") +
      (point.community_name ? '<span class="feeding-community">' + escapeHtml(point.community_name) + '</span>' : "") +
      (point.distance_m != null ? '<span class="feeding-distance">约 ' + escapeHtml(formatDistance(point.distance_m)) + '</span>' : "") +
      '</span>' +
      (point.caretaker_note ? '<p class="feeding-note">' + escapeHtml(point.caretaker_note) + '</p>' : '') +
      '<small class="feeding-today">今天已有 ' + point.fed_today + ' 人打卡</small></div>' +
      (point.fed_by_me
        ? '<span class="feeding-done">今天已打卡 ✓</span>'
        : '<span class="feeding-actions">' +
          '<button class="button primary compact" type="button" data-feeding-checkin="' + escapeHtml(point.id) + '">打卡投喂</button>' +
          '<button class="text-button" type="button" data-feeding-detail="' + escapeHtml(point.id) + '">打卡并记录</button>' +
          '</span>') +
      '</article>';
  }

  function formatDistance(metres) {
    if (metres == null) return "";
    return metres < 1000 ? metres + " 米" : (metres / 1000).toFixed(1) + " 公里";
  }

  function pad2(value) {
    return (value < 10 ? "0" : "") + value;
  }

  function loadFeedingPoints(append) {
    if (append && (!state.cursors.feedingPoints || state.nearby)) return Promise.resolve();
    var params = ["limit=24"];
    if (state.nearby) {
      // 定位成功时按距离排序；服务端在这种模式下不分页，next_cursor 固定为 null
      params.push("lat=" + state.nearby.latitude);
      params.push("lng=" + state.nearby.longitude);
    } else {
      // 默认「今天还没人喂」优先，形成每日打卡的秩序感
      params.push("sort=today");
      if (append) params.push("cursor=" + encodeURIComponent(state.cursors.feedingPoints));
    }
    return api.request("/api/v1/feeding-points?" + params.join("&")).then(function (payload) {
      state.feedingPoints = append
        ? communityForm.appendUnique(state.feedingPoints, payload.items || [])
        : (payload.items || []);
      state.cursors.feedingPoints = payload.next_cursor || null;
      renderFeeding();
    }).catch(function (error) {
      renderHomeModuleState("feeding", "error");
      toast(errorText(error));
    });
  }

  function renderFeeding() {
    var target = byId("feeding-list");
    if (!target) return;
    target.innerHTML = state.feedingPoints.length
      ? state.feedingPoints.map(feedingPointCard).join("")
      : emptyCard("还没有喂食点", "管理员发布喂食点后，这里就能打卡记录投喂。");
    byId("load-more-feeding").hidden = !state.cursors.feedingPoints || Boolean(state.nearby);
    var line = byId("feeding-today-line");
    if (line) {
      var pending = state.feedingPoints.filter(function (point) { return point.needs_feed; }).length;
      line.textContent = !state.feedingPoints.length ? ""
        : pending ? "今天还有 " + pending + " 个喂食点没人喂" : "今天的喂食点都有人喂过了，谢谢大家";
    }
  }

  // ---- 每日打卡进度（连续天数 / 近 7 天 / 里程碑） ---------------------

  function loadFeedingSummary() {
    if (!state.user) { state.myFeedingSummary = null; renderStreak(); return Promise.resolve(); }
    return api.request("/api/v1/feeding-logs/mine/summary").then(function (payload) {
      state.myFeedingSummary = payload;
      renderStreak();
    }).catch(function () {
      state.myFeedingSummary = null;
      renderStreak();
    });
  }

  function renderStreak() {
    var card = byId("streak-card");
    if (!card) return;
    var days = byId("streak-days");
    var line = byId("streak-line");
    var next = byId("streak-next");
    if (!state.user) {
      days.textContent = "—";
      line.textContent = "登录后可以记录投喂打卡，并累计连续天数。";
      byId("streak-week").innerHTML = "";
      next.hidden = true;
      return;
    }
    var summary = state.myFeedingSummary;
    if (!summary) {
      days.textContent = "…";
      line.textContent = "正在读取打卡记录…";
      return;
    }
    days.textContent = formatMetric(summary.streak_days);
    line.textContent = summary.checked_in_today
      ? "今天已打卡" + (summary.points_checked_today > 1 ? "（" + summary.points_checked_today + " 个喂食点）" : "") +
        "，本周 " + summary.days_this_week + " 天，累计 " + summary.total_days + " 天"
      : "今天还没打卡，今天打一次就能续上连续记录。";
    renderStreakWeek();
    if (summary.next_milestone) {
      next.textContent = "再坚持 " + (summary.next_milestone - summary.streak_days) + " 天，达成「连续 " + summary.next_milestone + " 天」";
      next.hidden = false;
    } else {
      next.hidden = true;
    }
  }

  function renderStreakWeek() {
    var target = byId("streak-week");
    if (!target) return;
    var fed = {};
    (state.myFeedingLogs || []).forEach(function (log) { fed[log.fed_on] = true; });
    // 以 Asia/Shanghai 的今天为基准，避免客户端时区导致日期错位
    var todayKey = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
    var base = new Date(todayKey + "T00:00:00");
    var labels = ["日", "一", "二", "三", "四", "五", "六"];
    var cells = [];
    for (var offset = 6; offset >= 0; offset--) {
      var day = new Date(base.getTime() - offset * 86400000);
      var key = day.getFullYear() + "-" + pad2(day.getMonth() + 1) + "-" + pad2(day.getDate());
      cells.push('<span class="streak-day' + (fed[key] ? " is-fed" : "") + (offset === 0 ? " is-today" : "") + '">' +
        (offset === 0 ? "今" : labels[day.getDay()]) + "</span>");
    }
    target.innerHTML = cells.join("");
  }

  function sortNearby(button) {
    if (!navigator.geolocation) {
      toast("当前浏览器不支持定位，已按待喂情况排列");
      return;
    }
    button.disabled = true;
    button.textContent = "定位中…";
    navigator.geolocation.getCurrentPosition(function (position) {
      state.nearby = {
        latitude: Number(position.coords.latitude.toFixed(6)),
        longitude: Number(position.coords.longitude.toFixed(6))
      };
      button.disabled = false;
      button.textContent = "已按距离排序";
      loadFeedingPoints(false);
    }, function () {
      button.disabled = false;
      button.textContent = "按距离排序";
      toast("没拿到定位权限，已按待喂情况排列");
    }, { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 });
  }

  function checkIn(pointId, button, details) {
    if (!requireLogin() || state.submitting) return Promise.resolve(false);
    state.submitting = true;
    if (button) {
      button.disabled = true;
      button.textContent = "打卡中…";
    }
    return api.request("/api/v1/feeding-points/" + encodeURIComponent(pointId) + "/logs", {
      method: "POST", body: details || {}
    }).then(function () {
      toast("打卡成功，谢谢你的投喂");
      return Promise.all([
        loadFeedingPoints(false), loadFeedingStats(), loadMyFeedingLogs(), loadHomeFeeding(), loadFeedingSummary()
      ]);
    }).then(function () { return true; }).catch(function (error) {
      toast(errorText(error));
      if (button) {
        button.disabled = false;
        button.textContent = "打卡投喂";
      }
      return false;
    }).finally(function () { state.submitting = false; });
  }

  // 快速打卡只发空 body；想记录「喂了什么 / 现场照片」就走这个弹层。
  // 注意：后端对同一人同一点同一天只保留首次记录，所以详情必须在首次打卡时提交。
  function openFeedSheet(pointId) {
    if (!requireLogin()) return;
    var point = (state.feedingPoints || []).find(function (item) { return item.id === pointId; }) ||
                (state.homeFeeding || []).find(function (item) { return item.id === pointId; });
    if (!point) return;
    state.activePoint = point;
    byId("feed-sheet-intro").textContent = point.name;
    byId("feed-form").reset();
    byId("feed-status").textContent = "";
    openSheet("feed-sheet");
  }

  function submitFeed(event) {
    event.preventDefault();
    var point = state.activePoint;
    if (!point || state.submitting) return;
    var button = byId("feed-submit");
    button.disabled = true;
    byId("feed-status").textContent = "正在提交…";
    var file = byId("feed-photo").files && byId("feed-photo").files[0];
    var upload = file ? api.uploadImage(file) : Promise.resolve(null);
    upload.then(function (asset) {
      return checkIn(point.id, null, {
        food_note: byId("feed-food").value.trim(),
        note: byId("feed-note").value.trim(),
        photo_asset_id: asset ? asset.id : null
      });
    }).then(function (ok) {
      if (ok) {
        closeSheets();
        toast("已记录这次投喂，谢谢");
      } else {
        byId("feed-status").textContent = "提交失败，请稍后重试";
      }
    }).finally(function () { button.disabled = false; });
  }

  function loadMyFeedingLogs() {
    if (!state.user) { state.myFeedingLogs = []; renderMyFeedingLogs(); renderStreak(); return Promise.resolve(); }
    return api.request("/api/v1/feeding-logs/mine?limit=24").then(function (payload) {
      state.myFeedingLogs = payload.items || [];
      renderMyFeedingLogs();
      renderStreak();
    }).catch(function () {
      state.myFeedingLogs = [];
      renderMyFeedingLogs();
      renderStreak();
    });
  }

  function renderMyFeedingLogs() {
    var target = byId("my-feeding-logs");
    if (!target) return;
    if (!state.user) {
      target.innerHTML = '<p class="module-status">登录后可以记录并查看自己的投喂打卡。</p>';
      return;
    }
    target.innerHTML = state.myFeedingLogs.length
      ? state.myFeedingLogs.map(function (log) {
          return '<article class="feeding-log"><strong>' + escapeHtml(log.point_name || "喂食点") + '</strong>' +
            '<span>' + escapeHtml(log.fed_on) + '</span>' +
            (log.food_note ? '<small>' + escapeHtml(log.food_note) + '</small>' : '') + '</article>';
        }).join("")
      : '<p class="module-status">还没有打卡记录，选一个喂食点开始吧。</p>';
  }

  function ensureFeeding() {
    loadFeedingStats();
    loadMyFeedingLogs();
    loadFeedingSummary();
    if (!state.feedingPoints.length) return loadFeedingPoints(false);
    return Promise.resolve();
  }

  // 首页的喂食点速览：单独一份数据，避免与投喂页的分页列表互相覆盖
  function loadHomeFeeding() {
    // 与投喂页保持一致：今天还没人喂的排前面
    return api.request("/api/v1/feeding-points?limit=3&sort=today").then(function (payload) {
      state.homeFeeding = payload.items || [];
      renderHomeFeeding();
      renderHomeModuleState("feeding", state.homeFeeding.length ? "ready" : "empty");
    }).catch(function () {
      state.homeFeeding = [];
      renderHomeFeeding();
      renderHomeModuleState("feeding", "error");
    });
  }

  function renderHomeFeeding() {
    var target = byId("home-feeding");
    if (!target) return;
    target.innerHTML = state.homeFeeding.length
      ? state.homeFeeding.slice(0, 3).map(feedingPointCard).join("")
      : emptyCard("还没有喂食点", "管理员发布喂食点后，这里就能打卡记录投喂。");
  }

  // ---- 任务闭环 -------------------------------------------------------

  function loadMyTasks() {
    if (!state.user) { state.myTasks = []; renderMyTasks(); return Promise.resolve(); }
    return api.request("/api/v1/tasks/mine?limit=24").then(function (payload) {
      state.myTasks = payload.items || [];
      renderMyTasks();
    }).catch(function () {
      state.myTasks = [];
      renderMyTasks();
    });
  }

  function myTaskCard(task) {
    var label = { OPEN: "待领取", CLAIMED: "进行中", COMPLETED: "已完成", CANCELLED: "已取消" }[task.status] || task.status;
    var action = task.status === "CLAIMED"
      ? '<button class="button primary compact" type="button" data-task-report="' + escapeHtml(task.id) + '">上报完成</button>'
      : '<span class="task-status-chip">' + escapeHtml(label) + '</span>';
    return '<article class="task-card"><span class="task-priority">' + escapeHtml(label) + '</span>' +
      '<div class="task-copy"><h3>' + escapeHtml(task.title) + '</h3>' +
      '<p>' + escapeHtml(task.description || "管理员发布的社区救助任务") + '</p>' +
      '<span>' + escapeHtml(communityName(task.community_id, task.community_name)) + '</span>' +
      (task.completion_note ? '<small>完成说明：' + escapeHtml(task.completion_note) + '</small>' : '') +
      '</div>' + action + '</article>';
  }

  function openTaskSheet(taskId) {
    var task = (state.myTasks || []).find(function (item) { return item.id === taskId; });
    if (!task) return;
    state.activeTask = task;
    byId("task-sheet-intro").textContent = task.title;
    byId("task-note").value = "";
    byId("task-status").textContent = "";
    openSheet("task-sheet");
  }

  function submitTaskReport(event) {
    event.preventDefault();
    var task = state.activeTask;
    if (!task || state.submitting) return;
    state.submitting = true;
    var button = byId("task-submit");
    button.disabled = true;
    byId("task-status").textContent = "正在提交…";
    var file = byId("task-evidence").files && byId("task-evidence").files[0];
    var upload = file ? api.uploadImage(file) : Promise.resolve(null);
    upload.then(function (asset) {
      return api.request("/api/v1/tasks/" + encodeURIComponent(task.id) + "/complete", {
        method: "POST",
        body: { note: byId("task-note").value.trim(), evidence_asset_id: asset ? asset.id : null }
      });
    }).then(function () {
      byId("task-form").reset();
      closeSheets();
      toast("已上报完成，谢谢你的付出");
      return Promise.all([loadMyTasks(), loadPublicData(), loadPublicMetrics()]);
    }).catch(function (error) {
      byId("task-status").textContent = errorText(error);
    }).finally(function () {
      state.submitting = false;
      button.disabled = false;
    });
  }

  function releaseTask() {
    var task = state.activeTask;
    if (!task || state.submitting) return;
    state.submitting = true;
    api.request("/api/v1/tasks/" + encodeURIComponent(task.id) + "/reassign", { method: "POST", body: { target_user_id: null } })
      .then(function () {
        closeSheets();
        toast("已退回任务池，谢谢你的时间");
        return Promise.all([loadMyTasks(), loadPublicData()]);
      })
      .catch(function (error) { byId("task-status").textContent = errorText(error); })
      .finally(function () { state.submitting = false; });
  }

  function renderView() {
    document.querySelectorAll("[data-view]").forEach(function (view) {
      var active = view.dataset.view === state.view;
      view.classList.toggle("active", active);
      view.hidden = !active;
    });
    document.querySelectorAll(".nav-item").forEach(function (button) {
      button.classList.toggle("active", button.dataset.nav === state.view);
    });
    var storyActive = state.view === "story-77";
    byId("floating-add-cat").hidden = storyActive || state.view === "profile";
    byId("bottom-nav").hidden = storyActive;
    if (state.view === "feeding") ensureFeeding();
    if (state.view === "tasks") loadMyTasks();
  }

  function renderApp() {
    renderMetrics();
    renderCommunityOptions();
    renderCats();
    renderTasks();
    renderAccount();
    renderView();
  }

  var validViews = ["home", "cats", "tasks", "feeding", "profile", "story-77"];

  function normalizedView(view) {
    var route = String(view || "").split("?")[0];
    return validViews.indexOf(route) >= 0 ? route : "home";
  }

  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" });
  }

  function restoreHomeScroll() {
    window.scrollTo({ top: state.homeScrollY || 0, behavior: "auto" });
  }

  function navigate(view, options) {
    var target = normalizedView(view);
    var previous = state.view;
    if (target === "story-77" && previous === "home") {
      state.homeScrollY = window.scrollY || window.pageYOffset || 0;
    }
    state.view = target;
    renderView();
    if (options && options.replace) window.history.replaceState(null, "", "#" + state.view);
    else window.history.pushState(null, "", "#" + state.view);
    if (options && options.restoreHomeScroll && target === "home") restoreHomeScroll();
    else if (target !== previous) scrollToTop();
    if (state.view === "profile" && state.user) loadSubmissions();
  }

  function syncRouteFromHash() {
    var target = normalizedView(window.location.hash.replace("#", ""));
    var previous = state.view;
    if (target === "story-77" && previous === "home") {
      state.homeScrollY = window.scrollY || window.pageYOffset || 0;
    }
    state.view = target;
    renderView();
    if (target === "home" && previous === "story-77") restoreHomeScroll();
    else if (target !== previous) scrollToTop();
    if (target === "profile" && state.user) loadSubmissions();
  }

  function renderStory() {
    if (!window.HelpCatStory77) return;
    window.HelpCatStory77.render(byId("story-77-root"), {
      openCats: function () { navigate("cats"); },
      loadProfile: function (profileKey) {
        return api.request("/api/v1/public/profiles/" + encodeURIComponent(profileKey));
      },
      openProfile: function (profile) {
        state.cats = [profile];
        state.cursors.cats = null;
        byId("cat-search").value = profile.nickname || "77";
        byId("community-filter").value = "";
        navigate("cats");
        window.history.replaceState(null, "", "#cats?profile=" + encodeURIComponent(profile.profile_key));
        renderCats();
      },
      openCreateCat: openCatSheet,
      backHome: function () { navigate("home", { replace: true, restoreHomeScroll: true }); }
    });
  }

  function openSheet(id) {
    byId("sheet-backdrop").hidden = false;
    byId(id).hidden = false;
    document.body.classList.add("sheet-open");
    window.setTimeout(function () {
      var input = byId(id).querySelector("input:not([type=file])");
      if (input) input.focus();
    }, 30);
  }
  function closeSheets() {
    byId("sheet-backdrop").hidden = true;
    document.querySelectorAll(".sheet").forEach(function (sheet) { sheet.hidden = true; });
    document.body.classList.remove("sheet-open");
  }
  function openAuth() {
    setAuthMode("login");
    openSheet("auth-sheet");
  }
  function requireLogin() {
    if (state.user) return true;
    openAuth();
    toast("请先登录后继续操作");
    return false;
  }

  function setAuthMode(mode) {
    state.authMode = mode === "register" ? "register" : "login";
    var register = state.authMode === "register";
    byId("auth-title").textContent = register ? "创建志愿者账户" : "欢迎回来";
    byId("auth-subtitle").textContent = register ? "注册后即可提交猫咪档案和领取任务。" : "登录后继续帮助社区里的小猫。";
    byId("auth-submit").textContent = register ? "注册并登录" : "登录";
    byId("auth-password").autocomplete = register ? "new-password" : "current-password";
    byId("auth-message").textContent = "";
    document.querySelectorAll("[data-auth-mode]").forEach(function (button) {
      var active = button.dataset.authMode === state.authMode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
  }

  function openCatSheet() {
    if (!requireLogin()) return;
    state.catStep = 1;
    setCatCommunityMode(state.catCommunityMode || "existing");
    state.location = null;
    byId("cat-message").textContent = "";
    updateCatStep();
    openSheet("cat-sheet");
  }

  function setCatCommunityMode(mode) {
    state.catCommunityMode = mode === "new" ? "new" : "existing";
    document.querySelectorAll("[data-community-mode]").forEach(function (button) {
      var active = button.dataset.communityMode === state.catCommunityMode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("[data-community-panel]").forEach(function (panel) {
      panel.hidden = panel.dataset.communityPanel !== state.catCommunityMode;
    });
    byId("cat-message").textContent = "";
  }

  function currentCatCommunityPayload() {
    return communityForm.buildCatCommunityPayload(state.catCommunityMode, {
      communityId: byId("cat-community").value,
      name: byId("cat-community-candidate-name").value,
      street: byId("cat-community-candidate-street").value,
      note: byId("cat-community-candidate-note").value
    });
  }

  function updateCatStep() {
    document.querySelectorAll("[data-form-step]").forEach(function (step) {
      step.hidden = Number(step.dataset.formStep) !== state.catStep;
    });
    document.querySelectorAll("[data-step-indicator]").forEach(function (indicator) {
      indicator.classList.toggle("active", Number(indicator.dataset.stepIndicator) <= state.catStep);
    });
    byId("cat-prev").hidden = state.catStep === 1;
    byId("cat-next").hidden = state.catStep === 3;
    byId("cat-submit").hidden = state.catStep !== 3;
  }

  function validateCatStep() {
    if (state.catStep === 1 && !byId("cat-name").value.trim()) {
      byId("cat-message").textContent = "请填写猫咪名称。";
      byId("cat-name").focus();
      return false;
    }
    if (state.catStep === 2) {
      try {
        currentCatCommunityPayload();
      } catch (error) {
        var newMode = state.catCommunityMode === "new";
        byId("cat-message").textContent = newMode ? "请填写小区名称和所属街道。" : "请选择已经审核通过的小区。";
        byId(newMode ? "cat-community-candidate-name" : "cat-community").focus();
        return false;
      }
      if (!byId("cat-location").value.trim()) {
        byId("cat-message").textContent = "请填写猫咪在小区内的模糊活动位置。";
        byId("cat-location").focus();
        return false;
      }
    }
    if (state.catStep === 3) {
      // 档案没有单独的备注字段，补充说明会并入位置说明；超长时明确报错，不静默截断。
      var combined = byId("cat-location").value.trim() + "；" + byId("cat-notes").value.trim();
      if (combined.length > 240) {
        byId("cat-message").textContent = "活动位置加补充说明最多 240 字，请精简后再提交。";
        byId("cat-notes").focus();
        return false;
      }
    }
    byId("cat-message").textContent = "";
    return true;
  }

  function handleAuth(event) {
    event.preventDefault();
    if (state.submitting) return;
    var username = byId("auth-username").value.trim();
    var password = byId("auth-password").value;
    state.submitting = true;
    byId("auth-submit").disabled = true;
    byId("auth-message").textContent = state.authMode === "register" ? "正在创建账户…" : "正在登录…";
    var action = state.authMode === "register" ? api.register(username, password) : api.login(username, password);
    action.then(function (user) {
      state.user = user;
      byId("auth-form").reset();
      closeSheets();
      renderAccount();
      return Promise.all([loadPublicData(), loadPublicMetrics(), loadSubmissions()]);
    }).then(function () {
      toast(state.authMode === "register" ? "注册成功，欢迎加入" : "登录成功");
    }).catch(function (error) {
      byId("auth-message").textContent = errorText(error);
    }).finally(function () {
      state.submitting = false;
      byId("auth-submit").disabled = false;
    });
  }

  function handleCommunity(event) {
    event.preventDefault();
    if (!requireLogin() || state.submitting) return;
    state.submitting = true;
    var button = event.target.querySelector("button[type=submit]");
    button.disabled = true;
    api.request("/api/v1/communities", {
      method: "POST",
      body: { name: byId("community-name").value.trim(), street: byId("community-street").value.trim() }
    }).then(function () {
      event.target.reset();
      byId("community-street").value = "银湖街道";
      toast(isAdminRole(state.user && state.user.role) ? "小区已创建并开放" : "小区建议已提交，等待管理员审核");
      return Promise.all([loadPublicData(), loadPublicMetrics(), loadSubmissions()]);
    }).catch(function (error) {
      toast(errorText(error));
    }).finally(function () {
      state.submitting = false;
      button.disabled = false;
    });
  }

  function submitCat(event) {
    event.preventDefault();
    if (!requireLogin() || state.submitting || !validateCatStep()) return;
    state.submitting = true;
    if (!state.catIdempotencyKey) {
      state.catIdempotencyKey = window.crypto && window.crypto.randomUUID
        ? window.crypto.randomUUID()
        : "cat-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
    }
    byId("cat-submit").disabled = true;
    byId("cat-message").textContent = "正在提交档案…";
    var file = byId("cat-photo-file").files && byId("cat-photo-file").files[0];
    var upload = file ? api.uploadImage(file) : Promise.resolve(null);
    upload.then(function (asset) {
      var locationNote = byId("cat-location").value.trim();
      var notes = byId("cat-notes").value.trim();
      if (notes) locationNote = locationNote + "；" + notes;
      var communityPayload = currentCatCommunityPayload();
      return api.request("/api/v1/cats", {
        method: "POST",
        headers: { "Idempotency-Key": state.catIdempotencyKey },
        body: Object.assign({
          nickname: byId("cat-name").value.trim(),
          living_status: byId("cat-living").value,
          health_status: byId("cat-health").value,
          location_note: locationNote,
          photo_asset_id: asset ? asset.id : null,
          latitude: state.location ? state.location.latitude : null,
          longitude: state.location ? state.location.longitude : null
        }, communityPayload)
      });
    }).then(function (cat) {
      var approved = cat.review_status === "APPROVED";
      byId("cat-form").reset();
      setCatCommunityMode("existing");
      byId("photo-preview").hidden = true;
      state.location = null;
      state.catIdempotencyKey = null;
      closeSheets();
      toast(approved ? "档案已创建并公开" : "档案已提交，等待管理员审核");
      return Promise.all([loadPublicData(), loadPublicMetrics(), loadSubmissions()]);
    }).catch(function (error) {
      byId("cat-message").textContent = errorText(error);
    }).finally(function () {
      state.submitting = false;
      byId("cat-submit").disabled = false;
    });
  }

  function claimTask(taskId, button) {
    if (!requireLogin() || state.submitting) return;
    state.submitting = true;
    button.disabled = true;
    button.textContent = "领取中…";
    api.request("/api/v1/tasks/" + encodeURIComponent(taskId) + "/claim", { method: "POST" }).then(function () {
      state.tasks = state.tasks.filter(function (task) { return task.id !== taskId; });
      renderTasks();
      // 领取后必须重新拉取我的任务，否则「我领取的任务」不会出现刚领的这一条。
      return Promise.all([loadMyTasks(), loadPublicMetrics()]);
    }).then(function () {
      toast("任务领取成功，请按说明完成救助");
    }).catch(function (error) {
      toast(errorText(error));
      return loadPublicData();
    }).finally(function () {
      state.submitting = false;
    });
  }

  function submitCommunityCorrection(form) {
    if (state.submitting) return;
    state.submitting = true;
    var button = form.querySelector("button[type=submit]");
    button.disabled = true;
    var payload;
    try {
      payload = communityForm.buildCommunityEditPayload({
        name: form.elements.name.value,
        street: form.elements.street.value,
        note: form.elements.note.value,
        version: form.elements.version.value
      });
    } catch (error) {
      state.submitting = false;
      button.disabled = false;
      toast("请完整填写小区名称和所属街道");
      return;
    }
    api.request("/api/v1/communities/" + encodeURIComponent(form.dataset.communityCorrectionForm), {
      method: "PATCH",
      body: payload
    }).then(function () {
      toast("小区信息已重新提交审核");
      return Promise.all([loadPublicData(), loadSubmissions()]);
    }).catch(function (error) {
      toast(errorText(error));
      if (error.status === 409) return loadSubmissions();
    }).finally(function () {
      state.submitting = false;
      button.disabled = false;
    });
  }

  function useCurrentLocation() {
    var fallback = byId("location-fallback");
    if (!window.isSecureContext || !navigator.geolocation) {
      fallback.textContent = "当前页面无法安全调用浏览器定位，请手动填写小区内的模糊位置。";
      fallback.classList.add("visible");
      byId("cat-location").focus();
      return;
    }
    byId("use-current-location").disabled = true;
    fallback.textContent = "正在获取当前位置，请允许浏览器使用定位权限…";
    fallback.classList.add("visible");
    navigator.geolocation.getCurrentPosition(function (position) {
      state.location = {
        latitude: Number(position.coords.latitude.toFixed(6)),
        longitude: Number(position.coords.longitude.toFixed(6))
      };
      if (!byId("cat-location").value.trim()) byId("cat-location").value = "已获取坐标，请补充附近楼栋或明显标志";
      fallback.textContent = "位置已获取；公开页面只展示你填写的模糊位置。";
      byId("use-current-location").disabled = false;
    }, function () {
      state.location = null;
      fallback.textContent = "定位权限未开启或获取失败，请直接填写小区内的模糊位置。";
      byId("use-current-location").disabled = false;
      byId("cat-location").focus();
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  }

  function previewPhoto(event) {
    var file = event.target.files && event.target.files[0];
    var preview = byId("photo-preview");
    if (!file) {
      preview.hidden = true;
      preview.innerHTML = "";
      return;
    }
    if (["image/jpeg", "image/png", "image/webp"].indexOf(file.type) < 0) {
      byId("cat-message").textContent = "仅支持 JPEG、PNG 或 WebP 图片。";
      event.target.value = "";
      return;
    }
    var url = URL.createObjectURL(file);
    preview.innerHTML = '<img src="' + url + '" alt="待上传的猫咪照片"><button class="button secondary compact" id="remove-photo" type="button">移除照片</button>';
    preview.hidden = false;
  }

  document.addEventListener("error", function (event) {
    var target = event.target;
    if (!target || !target.matches || !target.matches("[data-cat-photo]")) return;
    if (target.dataset.photoRetry !== "original" && target.dataset.originalSrc) {
      target.dataset.photoRetry = "original";
      target.src = target.dataset.originalSrc;
      return;
    }
    target.hidden = true;
    var media = target.closest(".cat-photo");
    if (media) media.classList.add("image-failed");
  }, true);

  document.addEventListener("click", function (event) {
    var nav = event.target.closest("[data-nav]");
    if (nav) {
      if (nav.tagName === "A") event.preventDefault();
      navigate(nav.dataset.nav);
      return;
    }
    if (event.target.closest("[data-close-sheet]") || event.target === byId("sheet-backdrop")) { closeSheets(); return; }
    var authMode = event.target.closest("[data-auth-mode]");
    if (authMode) { setAuthMode(authMode.dataset.authMode); return; }
    var communityMode = event.target.closest("[data-community-mode]");
    if (communityMode) { setCatCommunityMode(communityMode.dataset.communityMode); return; }
    var editCommunity = event.target.closest("[data-edit-community]");
    if (editCommunity) {
      var correction = document.querySelector('[data-community-correction-form="' + editCommunity.dataset.editCommunity + '"]');
      if (correction) {
        correction.hidden = !correction.hidden;
        editCommunity.textContent = correction.hidden ? "修改并重新提交" : "收起修改";
      }
      return;
    }
    var catOpen = event.target.closest("[data-cat-open]");
    if (catOpen) { openCatDetail(catOpen.dataset.catOpen); return; }
    var contactOpen = event.target.closest("[data-contact-open]");
    if (contactOpen) { openContactSheet(); return; }
    var checkInButton = event.target.closest("[data-feeding-checkin]");
    if (checkInButton) { checkIn(checkInButton.dataset.feedingCheckin, checkInButton); return; }
    var feedDetailButton = event.target.closest("[data-feeding-detail]");
    if (feedDetailButton) { openFeedSheet(feedDetailButton.dataset.feedingDetail); return; }
    var reportButton = event.target.closest("[data-task-report]");
    if (reportButton) { openTaskSheet(reportButton.dataset.taskReport); return; }
    var claim = event.target.closest(".claim-task");
    if (claim) { claimTask(claim.dataset.taskId, claim); return; }
    if (event.target.closest("#home-add-cat") || event.target.closest("#floating-add-cat")) { openCatSheet(); return; }
    if (event.target.closest("#remove-photo")) {
      byId("cat-photo-file").value = "";
      byId("photo-preview").hidden = true;
      byId("photo-preview").innerHTML = "";
    }
  });

  document.addEventListener("submit", function (event) {
    var correction = event.target.closest("[data-community-correction-form]");
    if (!correction) return;
    event.preventDefault();
    submitCommunityCorrection(correction);
  });

  // #profile-button 自带 data-nav="profile"，交给上面的委托统一处理，避免重复 pushState。
  byId("home-create-cat").addEventListener("click", openCatSheet);
  byId("home-contact").addEventListener("click", openContactSheet);
  byId("contact-form").addEventListener("submit", submitContact);
  byId("task-form").addEventListener("submit", submitTaskReport);
  byId("task-release").addEventListener("click", releaseTask);
  byId("load-more-feeding").addEventListener("click", function () { loadFeedingPoints(true); });
  byId("sort-nearby").addEventListener("click", function (event) { sortNearby(event.currentTarget); });
  byId("feed-form").addEventListener("submit", submitFeed);
  byId("refresh-my-feeding").addEventListener("click", function () { loadFeedingStats(); loadMyFeedingLogs(); });
  byId("auth-form").addEventListener("submit", handleAuth);
  byId("community-form").addEventListener("submit", handleCommunity);
  byId("cat-form").addEventListener("submit", submitCat);
  byId("cat-next").addEventListener("click", function () {
    if (!validateCatStep()) return;
    state.catStep = Math.min(3, state.catStep + 1);
    updateCatStep();
  });
  byId("cat-prev").addEventListener("click", function () {
    state.catStep = Math.max(1, state.catStep - 1);
    byId("cat-message").textContent = "";
    updateCatStep();
  });
  byId("open-community-form").addEventListener("click", function () {
    closeSheets();
    navigate("profile");
    window.setTimeout(function () { byId("community-name").focus(); }, 30);
  });
  byId("admin-console-action").addEventListener("click", function () {
    if (!state.user || !isAdminRole(state.user.role) || !api.token()) {
      openAuth();
      return;
    }
    sessionStorage.setItem("help_cat_admin_token", api.token());
    window.location.assign("/help-cat/admin/");
  });
  byId("account-action").addEventListener("click", function () {
    if (!state.user) { openAuth(); return; }
    api.logout().then(function () {
      state.user = null;
      state.submissions = { cats: [], communities: [] };
      renderAccount();
      toast("已安全退出登录");
    });
  });
  byId("refresh-submissions").addEventListener("click", function () { loadSubmissions(false); });
  byId("load-more-submissions").addEventListener("click", function () { loadSubmissions(true); });
  byId("load-more-cats").addEventListener("click", function (event) { loadMoreCollection("cats", event.currentTarget); });
  byId("load-more-tasks").addEventListener("click", function (event) { loadMoreCollection("tasks", event.currentTarget); });
  byId("load-more-communities").addEventListener("click", function (event) { loadMoreCollection("communities", event.currentTarget); });
  byId("cat-search").addEventListener("input", scheduleCatSearch);
  byId("community-filter").addEventListener("change", searchCatsFromServer);
  byId("cat-community-search").addEventListener("input", function (event) {
    var query = event.target.value.trim().toLowerCase();
    Array.prototype.forEach.call(byId("cat-community").options, function (option, index) {
      option.hidden = index > 0 && query && option.textContent.toLowerCase().indexOf(query) < 0;
    });
    window.clearTimeout(event.currentTarget.searchTimer);
    event.currentTarget.searchTimer = window.setTimeout(function () {
      if (!query) return;
      api.request("/api/v1/communities?limit=24&q=" + encodeURIComponent(query)).then(function (payload) {
        state.communities = communityForm.appendUnique(state.communities, payload.items || []);
        renderCommunityOptions();
      }).catch(function (error) { toast(errorText(error)); });
    }, 240);
  });
  byId("use-current-location").addEventListener("click", useCurrentLocation);
  byId("cat-photo-file").addEventListener("change", previewPhoto);
  byId("reload-version").addEventListener("click", function () { window.location.reload(); });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") checkForUpdate();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") { closeSheets(); return; }
    if (event.key !== "Enter" && event.key !== " ") return;
    var card = event.target && event.target.closest ? event.target.closest("[data-cat-open]") : null;
    if (!card) return;
    event.preventDefault();
    openCatDetail(card.dataset.catOpen);
  });
  window.addEventListener("hashchange", syncRouteFromHash);

  var initialView = window.location.hash.replace("#", "");
  if (validViews.indexOf(initialView) >= 0) state.view = initialView;
  renderStory();
  renderApp();
  checkForUpdate();
  var initialMetrics = loadPublicMetrics();
  api.restoreSession().then(function (user) {
    state.user = user;
    renderAccount();
    return Promise.all([loadPublicData(), initialMetrics, user ? loadSubmissions() : Promise.resolve()]);
  }).catch(function (error) {
    showStatus("", false);
    return Promise.all([loadPublicData(), initialMetrics]);
  });
}());
