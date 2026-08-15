const api = require('../../utils/api');
Page({
  data: { loading: true, error: '', empty: false, metrics: {}, cats: [], tasks: [] },
  onLoad() { this.load(); },
  onPullDownRefresh() { this.load().finally(wx.stopPullDownRefresh); },
  load() {
    this.setData({loading:true,error:''});
    return Promise.all([
      api.request('/public/metrics'), api.request('/cats?limit=4'), api.request('/tasks?limit=1')
    ]).then(([metrics,cats,tasks]) => {
      const items = (cats.items||[]).map(item => Object.assign({}, item, {photo_url: api.mediaUrl(item.photo_asset_id)}));
      this.setData({metrics,cats:items,tasks:tasks.items||[],empty:!items.length,loading:false});
    })
      .catch(() => this.setData({error:'暂时无法连接服务，请稍后重试',loading:false}));
  },
  openStory() { wx.navigateTo({url:'/pages/cats/index?profile=story-77'}); }
});
