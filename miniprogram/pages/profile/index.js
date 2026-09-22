const api = require('../../utils/api');

// 角色枚举不直接展示给用户
const ROLE_LABELS = {USER: '志愿者', ADMIN: '管理员', SUPER_ADMIN: '超级管理员'};

function roleLabel(user) {
  if (!user) return '';
  return ROLE_LABELS[user.role] || '志愿者';
}

Page({
  data: {loading: false, error: '', empty: false, user: null, role_label: ''},
  onShow() {
    const user = getApp().globalData.user || null;
    this.setData({user, role_label: roleLabel(user), empty: !user});
  },
  login() {
    this.setData({loading: true, error: ''});
    api.wechatLogin().then(payload => {
      getApp().setSession(payload);
      this.setData({user: payload.user, role_label: roleLabel(payload.user), empty: false, loading: false});
    }).catch(err => this.setData({
      error: err.message === 'wechat_not_configured' ? '微信登录等待管理员配置 AppID' : '登录失败，请稍后重试',
      loading: false
    }));
  },
  logout() {
    getApp().clearSession();
    this.setData({user: null, role_label: '', empty: true, error: ''});
  }
});
