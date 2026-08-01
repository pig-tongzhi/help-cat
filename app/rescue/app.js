(function () {
  "use strict";

  var api = window.HelpCatApi;
  var state = {
    user: null,
    communities: [],
    cats: [],
    tasks: [],
    submissions: { cats: [], communities: [] },
    view: "home",
    authMode: "login",
    catStep: 1,
    location: null,
    submitting: false
  };

  var errorMessages = {
    invalid_credentials: "账号或密码不正确，请重新输入。",
    username_exists: "这个账号已经注册，请直接登录。",
    user_disabled: "账号已停用，请联系管理员。",
    daily_cat_limit_reached: "今天已达到 3 条建档上限，请明天再提交。",
    task_already_claimed: "这个任务刚刚已被其他志愿者领取。",
    community_exists: "这个小区已经存在或正在审核。",
    community_not_found: "所选小区不存在或尚未审核通过。",
    unsupported_image_type: "仅支持 JPEG、PNG 或 WebP 图片。",
    image_too_large: "图片过大，请压缩后重新选择。",
    image_content_mismatch: "图片内容无法识别，请重新选择。",
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
  function communityName(id) {
    var item = state.communities.find(function (community) { return community.id === id; });
    return item ? item.name : "社区范围内";
  }
  function photoUrl(cat) {
    return cat.photo_asset_id ? api.API_BASE + "/api/v1/media/" + encodeURIComponent(cat.photo_asset_id) : "";
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
    return { APPROVED: "已通过", PENDING_REVIEW: "待审核", REJECTED: "未通过" }[value] || value;
  }
  function reviewTone(value) {
    return { APPROVED: "approved", ACTIVE: "approved", PENDING_REVIEW: "pending", REJECTED: "rejected" }[value] || "pending";
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

  function loadPublicData() {
    showStatus("正在同步社区救助数据…", false);
    return Promise.all([
      api.request("/api/v1/communities"),
      api.request("/api/v1/cats"),
      api.request("/api/v1/tasks")
    ]).then(function (results) {
      state.communities = results[0].items || [];
      state.cats = results[1].items || [];
      state.tasks = results[2].items || [];
      showStatus("", false);
      renderApp();
    }).catch(function (error) {
      showStatus(errorText(error), true);
      renderApp();
    });
  }

  function loadSubmissions() {
    if (!state.user) return Promise.resolve();
    return api.request("/api/v1/me/submissions").then(function (payload) {
      state.submissions = { cats: payload.cats || [], communities: payload.communities || [] };
      renderSubmissions();
    }).catch(function (error) {
      if (error.status === 401) state.user = null;
      toast(errorText(error));
      renderAccount();
    });
  }

  function catCard(cat) {
    var image = photoUrl(cat);
    return '<article class="cat-card">' +
      '<div class="cat-photo ' + (image ? "has-photo" : "") + '">' +
      '<span class="cat-placeholder" aria-hidden="true"><i></i><small>暂无照片</small></span>' +
      (image ? '<img data-cat-photo src="' + escapeHtml(image) + '" alt="' + escapeHtml(cat.nickname) + '的照片" loading="lazy">' : '') +
      '<span class="health-badge ' + healthTone(cat.health_status) + '">' + escapeHtml(healthLabel(cat.health_status)) + '</span></div>' +
      '<div class="cat-card-body"><div class="cat-title"><h3>' + escapeHtml(cat.nickname) + '</h3><span>' + escapeHtml(cat.code) + '</span></div>' +
      '<p class="cat-community">' + escapeHtml(communityName(cat.community_id)) + '</p>' +
      '<p class="cat-meta">' + escapeHtml(cat.living_status || "居住情况待观察") + ' · ' + escapeHtml(cat.location_note || "位置已保护") + '</p></div></article>';
  }

  function taskCard(task) {
    return '<article class="task-card"><span class="task-priority">待领取</span><div class="task-copy"><h3>' + escapeHtml(task.title) + '</h3>' +
      '<p>' + escapeHtml(task.description || "管理员发布的社区救助任务") + '</p><span>' + escapeHtml(communityName(task.community_id)) + '</span></div>' +
      '<button class="button secondary compact claim-task" type="button" data-task-id="' + escapeHtml(task.id) + '">领取任务</button></article>';
  }

  function emptyCard(title, description) {
    return '<div class="empty-state"><strong>' + escapeHtml(title) + '</strong><p>' + escapeHtml(description) + '</p></div>';
  }

  function filteredCats() {
    var query = byId("cat-search").value.trim().toLowerCase();
    var communityId = byId("community-filter").value;
    return state.cats.filter(function (cat) {
      var haystack = [cat.nickname, cat.code, communityName(cat.community_id)].join(" ").toLowerCase();
      return (!query || haystack.indexOf(query) >= 0) && (!communityId || cat.community_id === communityId);
    });
  }

  function renderCats() {
    var cats = filteredCats();
    byId("metric-cats").textContent = String(state.cats.length);
    byId("cat-result-count").textContent = "共 " + cats.length + " 只已审核猫咪";
    byId("home-cats").innerHTML = state.cats.length ? state.cats.slice(0, 3).map(catCard).join("") : emptyCard("还没有公开档案", "登录后可以提交第一只社区猫咪。");
    byId("cat-list").innerHTML = cats.length ? cats.map(catCard).join("") : emptyCard("没有找到匹配档案", "试试更换名称或小区筛选条件。");
  }

  function renderTasks() {
    byId("metric-tasks").textContent = String(state.tasks.length);
    byId("open-task-count").textContent = String(state.tasks.length);
    var content = state.tasks.length ? state.tasks.map(taskCard).join("") : emptyCard("暂时没有开放任务", "有新的救助行动时会在这里及时发布。");
    byId("task-list").innerHTML = content;
    byId("home-tasks").innerHTML = state.tasks.length ? state.tasks.slice(0, 2).map(taskCard).join("") : content;
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
  }

  function renderAccount() {
    var signedIn = Boolean(state.user);
    var name = signedIn ? (state.user.username || (state.user.role === "ADMIN" ? "管理员" : "志愿者")) : "志愿者账户";
    var initial = name.slice(0, 1) || "志";
    byId("profile-avatar").textContent = initial;
    byId("profile-label").textContent = signedIn ? name : "登录";
    byId("account-avatar").textContent = initial;
    byId("account-name").textContent = name;
    byId("account-description").textContent = signedIn ? (state.user.role === "ADMIN" ? "管理员账号 · 新建档案将直接公开" : "志愿者账号 · 可提交档案并领取任务") : "登录后可以提交档案、查看审核状态和领取任务。";
    byId("account-action").textContent = signedIn ? "退出登录" : "登录 / 注册";
    byId("account-card").classList.toggle("guest-state", !signedIn);
    byId("signed-in-content").hidden = !signedIn;
    if (signedIn) renderSubmissions();
  }

  function renderSubmissions() {
    if (!state.user) return;
    var items = [];
    state.submissions.communities.forEach(function (community) {
      var review = community.status === "ACTIVE" ? "APPROVED" : community.status;
      items.push('<article class="submission-item"><span class="submission-type">小区建议</span><div><strong>' + escapeHtml(community.name) + '</strong><p>' + escapeHtml(community.street) + '</p></div><span class="review-status ' + reviewTone(review) + '">' + escapeHtml(reviewLabel(review)) + '</span></article>');
    });
    state.submissions.cats.forEach(function (cat) {
      items.push('<article class="submission-item"><span class="submission-type">猫咪档案</span><div><strong>' + escapeHtml(cat.nickname) + '</strong><p>' + escapeHtml(communityName(cat.community_id)) + ' · ' + escapeHtml(cat.code) + '</p></div><span class="review-status ' + reviewTone(cat.review_status) + '">' + escapeHtml(reviewLabel(cat.review_status)) + '</span></article>');
    });
    byId("submission-list").innerHTML = items.length ? items.join("") : emptyCard("还没有提交记录", "完成猫咪建档或小区建议后会显示在这里。");
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
    byId("floating-add-cat").hidden = state.view === "profile";
  }

  function renderApp() {
    renderCommunityOptions();
    renderCats();
    renderTasks();
    renderAccount();
    renderView();
  }

  function navigate(view) {
    state.view = ["home", "cats", "tasks", "profile"].indexOf(view) >= 0 ? view : "home";
    renderView();
    window.history.replaceState(null, "", "#" + state.view);
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (state.view === "profile" && state.user) loadSubmissions();
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
    state.location = null;
    byId("cat-message").textContent = "";
    updateCatStep();
    openSheet("cat-sheet");
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
      if (!byId("cat-community").value) {
        byId("cat-message").textContent = "请选择已经审核通过的小区。";
        byId("cat-community").focus();
        return false;
      }
      if (!byId("cat-location").value.trim()) {
        byId("cat-message").textContent = "请填写猫咪在小区内的模糊活动位置。";
        byId("cat-location").focus();
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
      return Promise.all([loadPublicData(), loadSubmissions()]);
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
      toast(state.user.role === "ADMIN" ? "小区已创建并开放" : "小区建议已提交，等待管理员审核");
      return Promise.all([loadPublicData(), loadSubmissions()]);
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
    byId("cat-submit").disabled = true;
    byId("cat-message").textContent = "正在提交档案…";
    var file = byId("cat-photo-file").files && byId("cat-photo-file").files[0];
    var upload = file ? api.uploadImage(file) : Promise.resolve(null);
    upload.then(function (asset) {
      var locationNote = byId("cat-location").value.trim();
      var notes = byId("cat-notes").value.trim();
      if (notes) locationNote = (locationNote + "；" + notes).slice(0, 240);
      return api.request("/api/v1/cats", {
        method: "POST",
        body: {
          community_id: byId("cat-community").value,
          nickname: byId("cat-name").value.trim(),
          living_status: byId("cat-living").value,
          health_status: byId("cat-health").value,
          location_note: locationNote,
          photo_asset_id: asset ? asset.id : null,
          latitude: state.location ? state.location.latitude : null,
          longitude: state.location ? state.location.longitude : null
        }
      });
    }).then(function (cat) {
      var approved = cat.review_status === "APPROVED";
      byId("cat-form").reset();
      byId("photo-preview").hidden = true;
      state.location = null;
      closeSheets();
      toast(approved ? "档案已创建并公开" : "档案已提交，等待管理员审核");
      return Promise.all([loadPublicData(), loadSubmissions()]);
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
      toast("任务领取成功，请按说明完成救助");
    }).catch(function (error) {
      toast(errorText(error));
      return loadPublicData();
    }).finally(function () {
      state.submitting = false;
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
    target.hidden = true;
    var media = target.closest(".cat-photo");
    if (media) media.classList.add("image-failed");
  }, true);

  document.addEventListener("click", function (event) {
    var nav = event.target.closest("[data-nav]");
    if (nav) { navigate(nav.dataset.nav); return; }
    if (event.target.closest("[data-close-sheet]") || event.target === byId("sheet-backdrop")) { closeSheets(); return; }
    var authMode = event.target.closest("[data-auth-mode]");
    if (authMode) { setAuthMode(authMode.dataset.authMode); return; }
    var claim = event.target.closest(".claim-task");
    if (claim) { claimTask(claim.dataset.taskId, claim); return; }
    if (event.target.closest("#home-add-cat") || event.target.closest("#floating-add-cat")) { openCatSheet(); return; }
    if (event.target.closest("#remove-photo")) {
      byId("cat-photo-file").value = "";
      byId("photo-preview").hidden = true;
      byId("photo-preview").innerHTML = "";
    }
  });

  byId("profile-button").addEventListener("click", function () { navigate("profile"); });
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
  byId("account-action").addEventListener("click", function () {
    if (!state.user) { openAuth(); return; }
    api.logout().then(function () {
      state.user = null;
      state.submissions = { cats: [], communities: [] };
      renderAccount();
      toast("已安全退出登录");
    });
  });
  byId("refresh-submissions").addEventListener("click", loadSubmissions);
  byId("cat-search").addEventListener("input", renderCats);
  byId("community-filter").addEventListener("change", renderCats);
  byId("cat-community-search").addEventListener("input", function (event) {
    var query = event.target.value.trim().toLowerCase();
    Array.prototype.forEach.call(byId("cat-community").options, function (option, index) {
      option.hidden = index > 0 && query && option.textContent.toLowerCase().indexOf(query) < 0;
    });
  });
  byId("use-current-location").addEventListener("click", useCurrentLocation);
  byId("cat-photo-file").addEventListener("change", previewPhoto);
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") closeSheets(); });

  var initialView = window.location.hash.replace("#", "");
  if (["home", "cats", "tasks", "profile"].indexOf(initialView) >= 0) state.view = initialView;
  renderApp();
  api.restoreSession().then(function (user) {
    state.user = user;
    renderAccount();
    return Promise.all([loadPublicData(), user ? loadSubmissions() : Promise.resolve()]);
  }).catch(function (error) {
    showStatus(errorText(error), true);
    return loadPublicData();
  });
}());
