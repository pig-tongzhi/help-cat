const test = require("node:test");
const assert = require("node:assert/strict");

const leadForm = require("../../app/welcome/lead-form.js");

test("a trimmed contact becomes the submitted payload", () => {
  assert.deepEqual(
    leadForm.buildLeadPayload({ name: "  小张 ", contactType: "phone", contact: " 13800000000 ", message: " 想帮忙 " }),
    { name: "小张", contact_type: "PHONE", contact: "13800000000", message: "想帮忙", source: "" }
  );
});

test("a blank or single-character contact is rejected before any request", () => {
  assert.throws(() => leadForm.buildLeadPayload({ contact: "" }), /contact_required/);
  assert.throws(() => leadForm.buildLeadPayload({ contact: "   " }), /contact_required/);
  assert.throws(() => leadForm.buildLeadPayload({ contact: "x" }), /contact_required/);
});

test("an unknown contact type falls back to WeChat", () => {
  assert.equal(leadForm.buildLeadPayload({ contact: "abc", contactType: "telegram" }).contact_type, "WECHAT");
  assert.equal(leadForm.buildLeadPayload({ contact: "abc" }).contact_type, "WECHAT");
});

test("over-long text is truncated to the column limits instead of failing", () => {
  const payload = leadForm.buildLeadPayload({
    contact: "abc", name: "n".repeat(120), message: "m".repeat(2000), source: "s".repeat(120),
  });
  assert.equal(payload.name.length, 80);
  assert.equal(payload.message.length, 1000);
  assert.equal(payload.source.length, 80);
});

test("the promotion channel is read from the query string first, then the referrer", () => {
  assert.equal(leadForm.sourceFromLocation("?from=xiaohongshu", "https://www.douyin.com/video/1"), "xiaohongshu");
  assert.equal(leadForm.sourceFromLocation("?utm_source=group-chat", ""), "group-chat");
  assert.equal(leadForm.sourceFromLocation("", "https://www.douyin.com/video/1"), "www.douyin.com");
  assert.equal(leadForm.sourceFromLocation("", ""), "");
});

test("operator channels fall back to the values baked into the page", () => {
  assert.deepEqual(
    leadForm.operatorChannels({ wechat: "mantaooo1", wechat_note: "帮帮小猫", qr_image: "/x.png" }, { wechat: "fallback" }),
    { wechat: "mantaooo1", wechatNote: "帮帮小猫", qrImage: "/x.png", phone: "", footnote: "" }
  );
  const offline = leadForm.operatorChannels(null, { wechat: "mantaooo1", wechatNote: "帮帮小猫" });
  assert.equal(offline.wechat, "mantaooo1");
  assert.equal(offline.qrImage, "");
});

test("error text is friendly for both local and API failure codes", () => {
  assert.match(leadForm.errorText(new Error("contact_required")), /微信号或手机号/);
  assert.match(leadForm.errorText(new Error("contact_too_long")), /太长/);
  assert.match(leadForm.errorText({ code: "too_many_messages" }), /稍后再试/);
  assert.match(leadForm.errorText({ code: "network_error" }), /网络连接失败/);
  assert.match(leadForm.errorText(null), /重试/);
});
