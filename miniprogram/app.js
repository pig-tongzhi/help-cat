App({
  globalData: { token: "", user: null },
  onLaunch() {
    this.globalData.token = wx.getStorageSync("help_cat_token") || "";
    this.globalData.user = wx.getStorageSync("help_cat_user") || null;
  },
  setSession(payload) {
    this.globalData.token = payload.access_token;
    this.globalData.user = payload.user;
    wx.setStorageSync("help_cat_token", payload.access_token);
    wx.setStorageSync("help_cat_user", payload.user);
  },
  clearSession() {
    this.globalData.token = "";
    this.globalData.user = null;
    wx.removeStorageSync("help_cat_token");
    wx.removeStorageSync("help_cat_user");
  }
});
