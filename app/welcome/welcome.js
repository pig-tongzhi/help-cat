(function () {
  "use strict";

  var API_BASE = window.HELPCAT_API_BASE || "/help-cat-api";
  var leadForm = window.HelpCatLeadForm;
  var revealButton = document.getElementById("reveal-contact");
  var fallback = {
    wechat: revealButton ? revealButton.dataset.fallbackWechat || "" : "",
    wechatNote: revealButton ? revealButton.dataset.fallbackNote || "" : ""
  };
  var revealed = false;
  var submitting = false;

  function byId(id) { return document.getElementById(id); }

  function toast(message) {
    var target = byId("toast");
    if (!target) return;
    target.textContent = message;
    target.hidden = false;
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () { target.hidden = true; }, 2800);
  }

  function request(path, options) {
    var config = options || {};
    var headers = Object.assign({}, config.headers || {});
    if (config.body !== undefined) headers["Content-Type"] = "application/json";
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
      throw { status: 0, code: "network_error" };
    });
  }

  function renderContact(channels) {
    var card = byId("contact-card");
    var wechat = byId("contact-wechat");
    var note = byId("contact-note");
    var copyButton = byId("copy-wechat");
    var phoneLine = byId("contact-phone-line");
    var footnote = byId("contact-footnote");
    var qrFigure = byId("contact-qr-figure");
    var qr = byId("contact-qr");

    wechat.textContent = channels.wechat || "暂未配置，请稍后再试";
    note.textContent = channels.wechatNote || "帮帮小猫";
    copyButton.hidden = !channels.wechat;

    if (channels.phone) {
      byId("contact-phone").textContent = channels.phone;
      phoneLine.hidden = false;
    } else {
      phoneLine.hidden = true;
    }

    footnote.textContent = channels.footnote || "";

    if (channels.qrImage) {
      qr.src = channels.qrImage;
    }
    qrFigure.hidden = !qr.src;
    qr.onerror = function () { qrFigure.hidden = true; };

    card.hidden = false;
    revealed = true;
  }

  function revealContact() {
    var card = byId("contact-card");
    if (revealed) {
      card.hidden = !card.hidden;
      if (!card.hidden) card.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    revealButton.disabled = true;
    var label = revealButton.textContent;
    revealButton.textContent = "正在获取…";
    request("/api/v1/public/contact").then(function (body) {
      renderContact(leadForm.operatorChannels(body, fallback));
      card.scrollIntoView({ behavior: "smooth", block: "center" });
    }).catch(function () {
      // The page must still work when the API is unreachable, so fall back to
      // the operator channels baked into the markup.
      renderContact(leadForm.operatorChannels(null, fallback));
      byId("contact-footnote").textContent = byId("contact-footnote").textContent || "当前网络不稳定，如果加不上微信，请稍后再试。";
    }).finally(function () {
      revealButton.disabled = false;
      revealButton.textContent = label;
    });
  }

  function copyWechat() {
    var value = byId("contact-wechat").textContent;
    if (!value || value.indexOf("暂未配置") >= 0) return;
    function done() { toast("微信号已复制"); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(done).catch(fallbackCopy);
      return;
    }
    fallbackCopy();

    function fallbackCopy() {
      var field = document.createElement("textarea");
      field.value = value;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      try { document.execCommand("copy"); done(); } catch (error) { toast("请手动长按复制微信号"); }
      document.body.removeChild(field);
    }
  }

  function setStatus(message, tone) {
    var target = byId("lead-status");
    target.textContent = message || "";
    target.classList.toggle("error", tone === "error");
    target.classList.toggle("success", tone === "success");
  }

  function submitLead(event) {
    event.preventDefault();
    if (submitting) return;
    var contactField = byId("lead-contact");
    var payload;
    try {
      payload = leadForm.buildLeadPayload({
        name: byId("lead-name").value,
        contactType: byId("lead-contact-type").value,
        contact: contactField.value,
        message: byId("lead-message").value,
        source: leadForm.sourceFromLocation(window.location.search, document.referrer)
      });
    } catch (error) {
      contactField.classList.add("is-invalid");
      setStatus(leadForm.errorText(error), "error");
      contactField.focus();
      return;
    }

    submitting = true;
    contactField.classList.remove("is-invalid");
    var button = byId("lead-submit");
    button.disabled = true;
    button.textContent = "正在提交…";
    setStatus("正在提交，请稍候…", "");

    request("/api/v1/public/messages", { method: "POST", body: payload }).then(function () {
      byId("lead-form").reset();
      setStatus("已收到，管理员会尽快加你。也可以直接加上面的微信更快。", "success");
      toast("提交成功，谢谢你的加入");
      if (!revealed) revealContact();
    }).catch(function (error) {
      setStatus(leadForm.errorText(error), "error");
    }).finally(function () {
      submitting = false;
      button.disabled = false;
      button.textContent = "提交，等管理员联系我";
    });
  }

  revealButton.addEventListener("click", revealContact);
  byId("copy-wechat").addEventListener("click", copyWechat);
  byId("lead-form").addEventListener("submit", submitLead);
  byId("lead-contact").addEventListener("input", function (event) {
    event.target.classList.remove("is-invalid");
    setStatus("", "");
  });
  byId("jump-to-form").addEventListener("click", function () {
    var section = byId("leave");
    section.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(function () { byId("lead-contact").focus(); }, 320);
  });
}());
