const api = require("../../utils/api.js");
Page({ data: { items: [] }, onShow() { api.ensureLogin().then(() => api.request("/api/v1/me/submissions")).then((data) => this.setData({ items: (data.cats || []).concat(data.communities || []) })).catch(() => wx.showToast({ title: "请先登录", icon: "none" })); } });
