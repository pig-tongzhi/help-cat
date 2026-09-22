(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.HelpCatLeadForm = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var CONTACT_TYPES = ["WECHAT", "PHONE", "QQ", "OTHER"];
  var MAX_CONTACT = 120;
  var MAX_NAME = 80;
  var MAX_MESSAGE = 1000;
  var MAX_SOURCE = 80;

  var ERROR_TEXT = {
    contact_required: "请填写微信号或手机号，方便我们联系你。",
    contact_too_long: "联系方式太长了，请检查一下。",
    too_many_messages: "短时间提交太多次了，请稍后再试，或直接加微信。",
    network_error: "网络连接失败，请稍后重试，或直接加微信联系。",
    request_failed: "提交失败，请稍后重试，或直接加微信联系。"
  };

  function text(value) {
    return String(value == null ? "" : value).trim();
  }

  function normalizeContactType(value) {
    var type = text(value).toUpperCase();
    return CONTACT_TYPES.indexOf(type) >= 0 ? type : "WECHAT";
  }

  function normalizeSource(value) {
    return text(value).slice(0, MAX_SOURCE);
  }

  /**
   * Build the public API payload for a lead.
   * Throws `Error("contact_required")` when the contact is unusable, so the
   * caller can show a field-level message without touching the network.
   */
  function buildLeadPayload(fields) {
    var source = fields || {};
    var contact = text(source.contact);
    if (contact.length < 2) throw new Error("contact_required");
    if (contact.length > MAX_CONTACT) throw new Error("contact_too_long");
    return {
      name: text(source.name).slice(0, MAX_NAME),
      contact_type: normalizeContactType(source.contactType),
      contact: contact,
      message: text(source.message).slice(0, MAX_MESSAGE),
      source: normalizeSource(source.source)
    };
  }

  /**
   * Attribute a lead to the channel that produced it, so promotion can be
   * measured without asking the visitor an extra question.
   */
  function sourceFromLocation(search, referrer) {
    var explicit = "";
    try {
      var params = new URLSearchParams(search || "");
      explicit = text(params.get("from") || params.get("utm_source"));
    } catch (error) {
      explicit = "";
    }
    if (explicit) return normalizeSource(explicit);
    try {
      return normalizeSource(referrer ? new URL(referrer).hostname : "");
    } catch (error) {
      return "";
    }
  }

  /**
   * Read the operator channels from the API response, falling back to the
   * values baked into the page so the call to action works even offline.
   */
  function operatorChannels(payload, fallback) {
    var body = payload || {};
    var spare = fallback || {};
    return {
      wechat: text(body.wechat) || text(spare.wechat),
      wechatNote: text(body.wechat_note) || text(spare.wechatNote),
      qrImage: text(body.qr_image),
      phone: text(body.phone),
      footnote: text(body.note)
    };
  }

  /** Accepts both a locally thrown Error (message is the code) and the request layer's `{ code }`. */
  function errorText(error) {
    if (!error) return "提交失败，请稍后重试。";
    var key = text(error.code) || text(error.message);
    return ERROR_TEXT[key] || text(error.message) || "提交失败，请稍后重试。";
  }

  return {
    CONTACT_TYPES: CONTACT_TYPES,
    buildLeadPayload: buildLeadPayload,
    normalizeContactType: normalizeContactType,
    sourceFromLocation: sourceFromLocation,
    operatorChannels: operatorChannels,
    errorText: errorText
  };
}));
