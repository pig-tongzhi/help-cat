App({
  globalData: { apiBase: "https://api.example.com", token: "" },
  onLaunch: function () {
    this.globalData.token = wx.getStorageSync("help_cat_token") || "";
  }
});
