# 图片加载优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 降低猫咪列表图片首屏传输量，并让失败图片有确定的恢复路径。

**Architecture:** `server/helpcat/app.py` 在媒体存储旁生成可再生 WebP 缩略图，`GET /api/v1/media/{id}?variant=thumb` 返回它。前端始终先用该 variant，失败时切换一次既有原图端点。

**Tech Stack:** FastAPI、Pillow、原生 H5 JavaScript、微信小程序 JavaScript、Python unittest。

## Global Constraints

- 原媒体 ID 与 `/api/v1/media/{id}` 兼容不变。
- 缩略图最长边为 640 像素、格式为 WebP。
- 资源响应包含 `Cache-Control: public, max-age=31536000, immutable`。
- 首次加载失败只允许一次原图兜底，随后显示占位。

---

### Task 1: 媒体缩略图接口

**Files:**
- Modify: `server/tests/test_commercial_api.py`
- Modify: `server/helpcat/app.py`

- [ ] **Step 1: Write the failing test**

```python
status, headers, body = self.request_bytes("GET", "/api/v1/media/%s?variant=thumb" % uploaded["id"])
self.assertEqual(status, 200)
self.assertEqual(headers["cache-control"], "public, max-age=31536000, immutable")
with Image.open(io.BytesIO(body)) as thumb:
    self.assertEqual(thumb.format, "WEBP")
    self.assertLessEqual(max(thumb.size), 640)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest server.tests.test_commercial_api.CommercialApiTests.test_uploaded_image_has_cached_webp_thumbnail -v`
Expected: FAIL because `variant=thumb` returns the original image.

- [ ] **Step 3: Write minimal implementation**

```python
def media_thumbnail_path(storage_root, object_key):
    return storage_root / (Path(object_key).stem + ".thumb.webp")

def create_media_thumbnail(source, target):
    with Image.open(source) as image:
        thumb = ImageOps.exif_transpose(image).convert("RGB")
        thumb.thumbnail((640, 640), Image.Resampling.LANCZOS)
        thumb.save(target, format="WEBP", quality=76, method=6)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest server.tests.test_commercial_api.CommercialApiTests.test_uploaded_image_has_cached_webp_thumbnail -v`
Expected: PASS.

### Task 2: 客户端优先缩略图与兜底

**Files:**
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `app/rescue/app.js`
- Modify: `miniprogram/utils/api.js`

- [ ] **Step 1: Write the failing contract test**

```python
self.assertIn('variant=thumb', script)
self.assertIn('data-original-src', script)
self.assertIn('photoRetry', script)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_cat_card_prefers_thumbnail_then_retries_original -v`
Expected: FAIL because the existing card uses only the original image.

- [ ] **Step 3: Write minimal implementation**

```javascript
function photoUrl(cat, variant) {
  var base = api.API_BASE + "/api/v1/media/" + encodeURIComponent(cat.photo_asset_id);
  return variant === "thumb" ? base + "?variant=thumb" : base;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_cat_card_prefers_thumbnail_then_retries_original -v`
Expected: PASS.

### Task 3: 全量验证与发布

**Files:**
- Modify: files from Tasks 1-2 only

- [ ] **Step 1: Run targeted and full regression suites**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -q && python3 -m unittest discover -s server/tests -p 'test_*.py' -q`
Expected: all tests pass.

- [ ] **Step 2: Run static checks**

Run: `node --check app/rescue/app.js && node --check miniprogram/utils/api.js && git diff --check`
Expected: exit 0.

- [ ] **Step 3: Commit and deploy**

Run: `git add server/helpcat/app.py server/tests/test_commercial_api.py app/rescue/app.js miniprogram/utils/api.js tests/test_rescue_h5_contract.py docs/superpowers && git commit -m "feat: optimize cat photo delivery"`
Expected: commit succeeds, then deploy via the established atomic release procedure and verify an existing image produces a cached thumbnail.
