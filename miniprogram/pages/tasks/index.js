const api = require('../../utils/api');

Page({
  data: {loading: true, error: '', empty: false, items: []},
  onLoad() { this.load(); },
  onPullDownRefresh() { this.load().finally(wx.stopPullDownRefresh); },
  load() {
    this.setData({loading: true, error: ''});
    return api.request('/tasks?limit=24')
      .then(data => this.setData({items: data.items || [], empty: !(data.items || []).length, loading: false}))
      .catch(() => this.setData({error: '任务加载失败，请稍后重试', loading: false}));
  },
  claim(event) {
    // 领取任务需要登录：先在客户端拦住，只靠服务端 401 时用户只会看到一句笼统提示
    if (!getApp().globalData.token) {
      wx.showToast({title: '请先到「我的」页微信登录', icon: 'none'});
      return;
    }
    const id = event.currentTarget.dataset.id;
    api.request('/tasks/' + id + '/claim', {method: 'POST'})
      .then(() => {
        wx.showToast({title: '领取成功'});
        this.load();
      })
      .catch(error => {
        wx.showToast({
          title: error.message === 'task_already_claimed' ? '这个任务刚被别人领取了' : '领取失败，请稍后重试',
          icon: 'none'
        });
        this.load();
      });
  }
});
