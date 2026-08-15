# 77 故事媒体可靠性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保证 77 故事图片完整可见且故障可恢复，同时锁定已确认的单一 Logo 母版。

**Architecture:** `story-77.js` 输出具有原始 URL 的可重试图片元素；`styles.css` 将故事图放进固定暖白相框并使用 `contain`。全局图片错误/点击处理只作用于故事图片。

**Tech Stack:** 原生 H5 JavaScript、CSS、Node test、Python unittest。

## Global Constraints

- 不修改 `assets/brand/helpcat-77-mark.svg` 的几何。
- 三张故事图片继续使用静态 WebP 和既有隐私处理结果。
- 故事图片不得使用 `object-fit: cover`。

---

### Task 1: 完整展示与重试交互

**Files:**
- Modify: `tests/js/rescue_story_77_runtime.test.js`
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `app/rescue/story-77.js`
- Modify: `app/rescue/app.js`
- Modify: `app/rescue/styles.css`

- [ ] **Step 1: Write failing contracts**

```javascript
assert.match(html, /data-story-image/);
assert.match(html, /data-story-retry/);
```

```python
self.assertIn(".story-visual.has-image img", styles)
self.assertIn("object-fit: contain", styles)
self.assertNotIn("object-fit: cover", story_image_rule)
```

- [ ] **Step 2: Run red tests**

Run: `node --test tests/js/rescue_story_77_runtime.test.js && python3 -m unittest tests.test_rescue_h5_contract.RescueH5ContractTests.test_story_media_is_complete_and_retryable -v`
Expected: FAIL because the current story image uses an inline `object-fit:cover` and has no retry marker.

- [ ] **Step 3: Implement minimal interaction and layout**

```javascript
image.dataset.storySource = chapter.image;
image.addEventListener("error", () => figure.classList.add("image-failed"));
retry.addEventListener("click", () => { image.src = image.dataset.storySource + "?retry=" + Date.now(); });
```

```css
.story-visual.has-image { background: var(--hero-backdrop); }
.story-visual.has-image img { object-fit: contain; }
```

- [ ] **Step 4: Run full validation and release**

Run: `node --test tests/js/rescue_story_77_runtime.test.js && python3 -m unittest discover -s tests -p 'test_*.py' -q && node --check app/rescue/app.js && node --check app/rescue/story-77.js && git diff --check`
Expected: all checks pass, then deploy atomically and request every story image over the public IP.
