const api = require('../../utils/api');

// 健康枚举不直接展示给用户
const HEALTH_LABELS = {HEALTHY: '状态良好', NEEDS_HELP: '需要关注', UNKNOWN: '待观察'};

Page({
  data: {loading: true, error: '', empty: false, items: [], profile_key: ''},
  onLoad(options) {
    // 首页「77 的故事」会带 ?profile=story-77 进来；之前这个参数被忽略，用户会看到全部档案
    const profileKey = (options && options.profile) || '';
    this.setData({profile_key: profileKey});
    this.load();
  },
  onPullDownRefresh() { this.load().finally(wx.stopPullDownRefresh); },
  load() {
    this.setData({loading: true, error: ''});
    const path = this.data.profile_key
      ? '/public/profiles/' + encodeURIComponent(this.data.profile_key)
      : '/cats?limit=24';
    return api.request(path).then(data => {
      const list = this.data.profile_key ? [data] : (data.items || []);
      const items = list.map(item => Object.assign({}, item, {
        photo_url: api.mediaUrl(item.photo_asset_id), photo_failed:false,
        health_label: HEALTH_LABELS[item.health_status] || item.health_status || '待观察'
      }));
      this.setData({items, empty: !items.length, loading: false});
    }).catch(() => this.setData({error: '档案加载失败，请稍后重试', loading: false}));
  },
  onPhotoError(event) {
    const index = event.currentTarget.dataset.index;
    const key = event.currentTarget.dataset.collection || 'items';
    const collection = this.data[key].slice();
    collection[index] = Object.assign({}, collection[index], {photo_failed:true});
    this.setData({[key]: collection});
  }
});
