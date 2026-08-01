const app = getApp();

function request(path, options) {
  const config = options || {};
  const token = app.globalData.token || wx.getStorageSync("help_cat_token");
  return new Promise((resolve, reject) => {
    wx.request({
      url: app.globalData.apiBase + path,
      method: config.method || "GET",
      data: config.data || {},
      header: Object.assign({ "content-type": "application/json" }, token ? { Authorization: "Bearer " + token } : {}, config.header || {}),
      success: (res) => res.statusCode >= 200 && res.statusCode < 300 ? resolve(res.data) : reject(res.data || res),
      fail: reject
    });
  });
}

function login() {
  return new Promise((resolve, reject) => {
    wx.login({
      success: (loginRes) => request("/api/v1/auth/wechat-login", { method: "POST", data: { code: loginRes.code } }).then((data) => {
        app.globalData.token = data.access_token;
        wx.setStorageSync("help_cat_token", data.access_token);
        resolve(data.user);
      }).catch(reject),
      fail: reject
    });
  });
}

function ensureLogin() {
  const token = app.globalData.token || wx.getStorageSync("help_cat_token");
  return token ? Promise.resolve() : login().then(() => undefined);
}

function uploadImage(filePath) {
  const token = app.globalData.token || wx.getStorageSync("help_cat_token");
  return new Promise((resolve, reject) => wx.uploadFile({ url: app.globalData.apiBase + "/api/v1/media/images", filePath, name: "file", header: { Authorization: "Bearer " + token }, success: (res) => res.statusCode === 201 ? resolve(JSON.parse(res.data)) : reject(res), fail: reject }));
}

module.exports = { request, login, ensureLogin, uploadImage };
