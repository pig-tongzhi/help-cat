const api = require("../../utils/api.js");
Page({
  data: { communities: [], cats: [], query: "", taskCount: 0 },
  onShow() { this.load(); },
  load() { Promise.all([api.request("/api/v1/communities?q=" + encodeURIComponent(this.data.query)), api.request("/api/v1/cats?q=" + encodeURIComponent(this.data.query))]).then(([communities, cats]) => this.setData({ communities: communities.items || [], cats: cats.items || [] })).catch(() => wx.showToast({ title: "加载失败", icon: "none" })); },
  onSearch(e) { this.setData({ query: e.detail.value }); this.load(); },
  newCat() { wx.navigateTo({ url: "/pages/cats/new" }); },
  openTasks() { wx.navigateTo({ url: "/pages/tasks/tasks" }); }
});
