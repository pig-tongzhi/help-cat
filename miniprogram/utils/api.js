const BASE_URL = 'https://helpcat.xyz/api/v1';

function request(path, options = {}) {
  const token = getApp().globalData.token;
  return new Promise((resolve, reject) => {
    wx.request({
      url: BASE_URL + path,
      method: options.method || 'GET',
      data: options.data,
      header: Object.assign(
        {'Content-Type': 'application/json'},
        token ? {Authorization: 'Bearer ' + token} : {},
        options.header || {}
      ),
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) resolve(response.data);
        else reject(new Error((response.data && response.data.detail && response.data.detail.code) || 'request_failed'));
      },
      fail: reject
    });
  });
}

function wechatLogin() {
  return new Promise((resolve, reject) => wx.login({success: resolve, fail: reject}))
    .then(result => request('/auth/wechat-login', {method: 'POST', data: {code: result.code}}));
}

function mediaUrl(assetId) {
  return assetId ? BASE_URL + '/media/' + encodeURIComponent(assetId) : '';
}

module.exports = { request, wechatLogin, mediaUrl, BASE_URL };
