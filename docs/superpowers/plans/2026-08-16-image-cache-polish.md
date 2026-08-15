# 图片与缓存体验优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变业务 API、数据模型或部署架构的条件下，稳定 H5 与微信小程序的图片加载、失败恢复和上传体验。

**Architecture:** 服务端继续提供不可变 WebP 缩略图与原图回退 URL；H5 补齐尺寸、懒加载与异步解码语义。两个微信客户端使用缩略图、固定图片区域和本地图片压缩，不引入 CDN、对象存储或新缓存服务。

**Tech Stack:** FastAPI/Pillow、原生 HTML/CSS/JavaScript、微信小程序 WXML/WXSS/JavaScript、Python `unittest`、Node `node:test`。

## Global Constraints

- 不修改公开 API 响应结构、认证和审核流程。
- 原图 URL、媒体 ID 与 `?variant=thumb` 语义必须保持兼容。
- 每张 H5 列表照片最多从缩略图回退一次原图；不得无限重试。
- 静态媒体缓存头保持 `public, max-age=31536000, immutable`。
- 不新增 CDN、对象存储、Redis、数据库迁移或服务端拓扑变更。
- 不提交用户既有未跟踪目录 `.superpowers/brainstorm/`。

---

### Task 1: 完善 H5 列表照片的浏览器加载语义

**Files:**
- Modify: `app/rescue/app.js:231-239`
- Test: `tests/test_rescue_h5_contract.py`

**Interfaces:**
- Consumes: `photoUrl(cat, "thumb")` 与 `photoUrl(cat)`。
- Produces: `catCard(cat)` 输出具备固定尺寸、懒加载、异步解码和一次回退信息的 `<img data-cat-photo>`。

- [ ] **Step 1: 写入失败测试**

在 `RescueH5ContractTests` 中添加：

```python
def test_list_cat_images_use_lazy_async_decoding_and_one_original_fallback(self):
    script = (ROOT / "app" / "rescue" / "app.js").read_text(encoding="utf-8")
    self.assertIn('width="640" height="480" loading="lazy" decoding="async"', script)
    self.assertIn('data-original-src="', script)
    self.assertIn('target.dataset.photoRetry !== "original"', script)
    self.assertIn('media.classList.add("image-failed")', script)
```

- [ ] **Step 2: 验证 RED**

Run: `python -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_list_cat_images_use_lazy_async_decoding_and_one_original_fallback -v`

Expected: FAIL，现有列表图片没有固定尺寸和 `decoding="async"`。

- [ ] **Step 3: 最小实现**

将 `catCard` 中图片拼接替换为：

```javascript
image ? '<img data-cat-photo data-original-src="' + escapeHtml(originalImage) +
  '" src="' + escapeHtml(image) + '" alt="' + escapeHtml(cat.nickname) +
  '的照片" width="640" height="480" loading="lazy" decoding="async">' : ''
```

保留现有捕获阶段 `error` 监听器：首次改用 `data-original-src`，第二次失败才隐藏图片并显示占位。

- [ ] **Step 4: 验证 GREEN**

Run: `python -m unittest tests.test_rescue_h5_contract -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/rescue/app.js tests/test_rescue_h5_contract.py
git commit -m "perf: stabilize h5 cat image loading"
```

### Task 2: 强化正式小程序列表的缩略图和失败占位

**Files:**
- Modify: `miniprogram/pages/cats/index.js`
- Modify: `miniprogram/pages/cats/index.wxml`
- Modify: `miniprogram/pages/cats/index.wxss`
- Modify: `miniprogram/pages/home/index.js`
- Modify: `miniprogram/pages/home/index.wxml`
- Test: `tests/test_miniprogram_contract.py`

**Interfaces:**
- Consumes: `api.mediaUrl(assetId)`，返回缩略图 URL。
- Produces: 每个图片项具有 `photo_failed: false`；`onPhotoError(event)` 将失败图片改为固定占位，不会循环请求。

- [ ] **Step 1: 写入失败测试**

在 `MiniProgramContractTests` 中添加：

```python
def test_public_photo_lists_use_thumbnails_lazy_loading_and_error_fallback(self):
    cats_js = (MINI / "pages/cats/index.js").read_text()
    cats_wxml = (MINI / "pages/cats/index.wxml").read_text()
    home_js = (MINI / "pages/home/index.js").read_text()
    home_wxml = (MINI / "pages/home/index.wxml").read_text()
    for source in (cats_js, home_js):
        self.assertIn("photo_failed:false", source)
        self.assertIn("onPhotoError", source)
        self.assertIn("api.mediaUrl", source)
    for source in (cats_wxml, home_wxml):
        self.assertIn('lazy-load="{{true}}"', source)
        self.assertIn('binderror="onPhotoError"', source)
        self.assertIn("wx:else", source)
```

- [ ] **Step 2: 验证 RED**

Run: `python -m unittest tests.test_miniprogram_contract.MiniProgramContractTests.test_public_photo_lists_use_thumbnails_lazy_loading_and_error_fallback -v`

Expected: FAIL，WXML 当前没有 `lazy-load`、`binderror` 或失败占位。

- [ ] **Step 3: 最小实现**

在两处映射中初始化 `photo_failed:false`，并在页面加入：

```javascript
onPhotoError(event) {
  const index = event.currentTarget.dataset.index;
  const key = event.currentTarget.dataset.collection || "items";
  const collection = this.data[key].slice();
  collection[index] = Object.assign({}, collection[index], { photo_failed: true });
  this.setData({ [key]: collection });
}
```

将图片改为（首页以 `cats` 为集合）：

```xml
<image wx:if="{{!item.photo_failed && item.photo_url}}"
  class="card-image" mode="aspectFill" lazy-load="{{true}}"
  src="{{item.photo_url}}" data-index="{{index}}" data-collection="items"
  binderror="onPhotoError" />
<view wx:else class="card-image card-image-placeholder">暂无照片</view>
```

在 WXSS 中为 `.card-image-placeholder` 添加与卡片图片相同的高度、居中布局和浅暖灰背景。

- [ ] **Step 4: 验证 GREEN**

Run: `python -m unittest tests.test_miniprogram_contract -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add miniprogram/pages/cats miniprogram/pages/home tests/test_miniprogram_contract.py
git commit -m "perf: harden mini program photo lists"
```

### Task 3: 压缩建档照片并保留可恢复上传状态

**Files:**
- Modify: `miniapp/pages/cats/new.js`
- Modify: `miniapp/pages/cats/new.wxml`
- Modify: `miniapp/pages/cats/new.wxss`
- Test: `tests/test_commercial_frontends.py`

**Interfaces:**
- Consumes: `wx.chooseMedia()` 产生的 `tempFilePath` 与 `wx.compressImage({ src, quality: 80 })`。
- Produces: `data.uploading`、`data.uploadError` 与 `data.photoPath`；上传仅使用压缩成功路径，压缩失败时安全使用原路径。

- [ ] **Step 1: 写入失败测试**

在 `CommercialFrontendContractTests` 中添加：

```python
def test_miniapp_photo_upload_compresses_and_preserves_retryable_state(self):
    source = (ROOT / "miniapp/pages/cats/new.js").read_text(encoding="utf-8")
    view = (ROOT / "miniapp/pages/cats/new.wxml").read_text(encoding="utf-8")
    self.assertIn("wx.compressImage", source)
    self.assertIn("quality: 80", source)
    self.assertIn("uploading", source)
    self.assertIn("uploadError", source)
    self.assertIn("重新上传照片", view)
```

- [ ] **Step 2: 验证 RED**

Run: `python -m unittest tests.test_commercial_frontends.CommercialFrontendContractTests.test_miniapp_photo_upload_compresses_and_preserves_retryable_state -v`

Expected: FAIL，当前直接上传原始 `tempFilePath`，没有上传中或可重试状态。

- [ ] **Step 3: 最小实现**

定义：

```javascript
function compressPhoto(src) {
  return new Promise((resolve) => wx.compressImage({
    src, quality: 80,
    success: (result) => resolve(result.tempFilePath || src),
    fail: () => resolve(src)
  }));
}
```

在 `choosePhoto` 中先 `setData({ photoPath:path, photoAssetId:"", uploading:true, uploadError:false })`，再调用 `compressPhoto(path).then(api.uploadImage)`；成功时设置 asset ID 并清除 uploading，失败时仅设置 `uploading:false, uploadError:true`，不得清空 `photoPath`。新增 `retryPhoto()`，使用既有 `photoPath` 重走压缩和上传。

在照片区下新增：

```xml
<text wx:if="{{uploading}}" class="hint">正在压缩并上传照片…</text>
<button wx:if="{{uploadError && !uploading}}" size="mini" bindtap="retryPhoto">重新上传照片</button>
```

- [ ] **Step 4: 验证 GREEN**

Run: `python -m unittest tests.test_commercial_frontends -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add miniapp/pages/cats/new.js miniapp/pages/cats/new.wxml miniapp/pages/cats/new.wxss tests/test_commercial_frontends.py
git commit -m "perf: compress retryable miniapp uploads"
```

### Task 4: 全量回归与发布检查

**Files:**
- Modify: `docs/wiki/部署回滚与运维.md`
- Test: `server/tests/test_commercial_api.py`
- Test: `tests/test_rescue_h5_contract.py`
- Test: `tests/test_miniprogram_contract.py`
- Test: `tests/test_commercial_frontends.py`
- Test: `tests/js/*.test.js`

**Interfaces:**
- Consumes: 任务 1–3 的加载和上传行为。
- Produces: 可复现的发布前图片验收项。

- [ ] **Step 1: 更新运行手册**

在 `docs/wiki/部署回滚与运维.md` 的发布验证段加入：H5 首次/缓存后二次访问、缩略图 200 与缓存头、缩略图失败回退、77 故事重试、小程序列表占位、建档照片压缩后失败重试。

- [ ] **Step 2: 运行全量验证**

Run:

```bash
python -m unittest discover -s server/tests -v
python -m unittest discover -s tests -v
node --test tests/js/*.test.js
node --check app/rescue/app.js
node --check app/rescue/api.js
node --check miniprogram/pages/home/index.js
node --check miniprogram/pages/cats/index.js
node --check miniapp/pages/cats/new.js
git diff --check
```

Expected: 所有命令以状态码 0 完成；若 Alembic 环境测试明确标记为 skip，可保留该 skip，其余用例不得失败。

- [ ] **Step 3: 手动弱网验收**

浏览器限速验证 H5 首屏、滚动缩略图、一次原图回退和 77 故事重试；微信开发者工具验证列表缩略图/占位和大图选择后的压缩上传状态。

- [ ] **Step 4: 提交**

```bash
git add docs/wiki/部署回滚与运维.md
git commit -m "docs: add image performance release checks"
```

