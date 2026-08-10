(function () {
  "use strict";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[character];
    });
  }

  var PROFILE_KEY = "story-77";

  var chapters = Object.freeze([
    Object.freeze({ title: "初见 77", marker: "2025 年 6 月 2 日", copy: "2025 年 6 月 2 日，我们第一次遇见了 77。一次相遇，让它被认真记住。", image: "assets/77/rescue-day.webp", alt: "77 幼猫期的近照", width: 620, height: 460 }),
    Object.freeze({ title: "名字的由来", marker: "农历五月初七", copy: "那天是农历五月初七。77 的名字，来自这一份最初的记录。" }),
    Object.freeze({ title: "从脆弱到安心", marker: "幼猫期", copy: "从幼猫期的照料和适应开始，77 的故事被一点点记录下来。公开叙事不对未确认的医疗或健康信息作推断。" }),
    Object.freeze({ title: "77 长大了", marker: "成长记录", copy: "从幼年到长大，日常的相处让这段陪伴有了连续的记录。", image: "assets/77/grown-up.webp", alt: "长大后的 77 正面近照", width: 720, height: 650 }),
    Object.freeze({ title: "为什么有帮帮小猫", marker: "一起接力", copy: "一次个人相遇，也让我们看到：让信息可查、行动可接力，才能让社区救助走得更远。" }),
    Object.freeze({ title: "从 77 到每一只小猫", marker: "新的开始", copy: "77 的故事是一个开始。帮帮小猫希望让更多被遇见的猫咪，有机会被认真记录、被持续关注。", image: "assets/77/resting.webp", alt: "77 安静休息的近照", width: 670, height: 750 })
  ]);

  function renderChapter(chapter, index) {
    var visual = chapter.image
      ? '<figure class="story-visual story-visual-' + (index + 1) + '" style="position:relative">' +
        '<img src="' + escapeHtml(chapter.image) + '" alt="' + escapeHtml(chapter.alt) + '" width="' + chapter.width + '" height="' + chapter.height + '"' + (index === 0 ? '' : ' loading="lazy"') + ' style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover">' +
        '<span>' + escapeHtml(chapter.marker) + '</span></figure>'
      : '<figure class="story-visual story-visual-' + (index + 1) + '" aria-hidden="true"><span>' + escapeHtml(chapter.marker) + '</span></figure>';
    return '<article class="story-chapter">' +
      visual +
      '<div class="story-chapter-copy"><span class="story-index">0' + (index + 1) + '</span><h2>' + escapeHtml(chapter.title) + '</h2><p>' + escapeHtml(chapter.copy) + '</p>' +
      (index === chapters.length - 1 ? '<div class="story-actions"><a class="button secondary" href="#cats?profile=' + PROFILE_KEY + '" data-story-action="profile" data-story-profile-link hidden>正在读取 77 公开档案…</a><button class="button primary" type="button" data-story-action="cats">看看正在等待帮助的小猫</button><button class="button secondary" type="button" data-story-action="create-cat">为遇见的小猫建立档案</button></div>' : '') +
      '</div></article>';
  }

  function renderToString() {
    return '<div class="story-page">' +
      '<div class="story-topbar"><span class="story-wordmark">HELP CAT · 77</span><button class="story-back" type="button" data-story-action="back-home">返回首页</button></div>' +
      '<header class="story-intro"><p>一只猫咪的故事，也是一份持续记录的开始。</p><h1>77 的故事</h1></header>' +
      '<div class="story-timeline">' + chapters.map(renderChapter).join("") + '</div>' +
      '<footer class="story-signoff">安得广厦千万间，大庇天下小猫俱欢颜</footer>' +
      '</div>';
  }

  function render(container, actions) {
    if (!container) return;
    var handlers = actions || {};
    var loadedProfile = null;
    container.innerHTML = renderToString();
    Array.prototype.forEach.call(container.querySelectorAll("[data-story-action]"), function (button) {
      button.addEventListener("click", function (event) {
        var action = button.dataset.storyAction;
        if (action === "profile") {
          if (event && typeof event.preventDefault === "function") event.preventDefault();
          if (loadedProfile && typeof handlers.openProfile === "function") handlers.openProfile(loadedProfile);
        }
        if (action === "cats" && typeof handlers.openCats === "function") handlers.openCats();
        if (action === "create-cat" && typeof handlers.openCreateCat === "function") handlers.openCreateCat();
        if (action === "back-home" && typeof handlers.backHome === "function") handlers.backHome();
      });
    });
    var profileLink = typeof container.querySelector === "function" ? container.querySelector("[data-story-profile-link]") : null;
    if (profileLink && typeof handlers.loadProfile === "function") {
      Promise.resolve(handlers.loadProfile(PROFILE_KEY)).then(function (profile) {
        if (!profile || profile.profile_key !== PROFILE_KEY) throw new Error("invalid public profile");
        loadedProfile = profile;
        profileLink.hidden = false;
        profileLink.textContent = "查看 " + (profile.nickname || "77") + " 的公开档案";
        profileLink.setAttribute("href", "#cats?profile=" + PROFILE_KEY);
        profileLink.removeAttribute("aria-disabled");
      }).catch(function () {
        profileLink.hidden = false;
        profileLink.textContent = "77 公开档案暂时无法载入";
        profileLink.setAttribute("aria-disabled", "true");
      });
    }
  }

  window.HelpCatStory77 = Object.freeze({ render: render, renderToString: renderToString });
}());
