# 帮帮小猫品牌与 77 首屏精修实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让线上页头、浏览器图标、PWA、登录页和后台统一使用示范图风格的 77 黑眼斑猫头，并让桌面与手机 hero 形成无中缝的连续暖白背板。

**Architecture:** 保持现有静态 H5 与后端接口不变。品牌以一个 SVG 母版为源，所有矢量入口直接复用，位图图标由母版确定性导出；hero 通过重新生成的公开 WebP 与单一 CSS 背景色融合，不增加运行时图片处理。

**Tech Stack:** SVG、HTML、CSS、ES5 JavaScript、Pillow/WebP、Python `unittest`、Node syntax check、Nginx immutable release。

## Global Constraints

- 唯一参考为 `codex-clipboard-851d1ca3-570e-4eef-adb4-18d77986eae6.png`。
- 品牌必须为白脸、细墨线、右眼黑斑、小粉鼻；所有入口共用同一几何。
- Hero 背景统一为 `#F5F1EB`，桌面左右不得出现色差、边线或拼接缝。
- 77 的双耳、双眼和右眼黑斑在桌面及手机首屏均完整可见。
- 不虚构业务数据，不改变登录、档案、任务、管理权限和审核流程。

---

### Task 1: 锁定品牌一致性与连续背板合同

**Files:**
- Modify: `tests/test_rescue_h5_contract.py`
- Modify: `tests/test_commercial_frontends.py`

**Interfaces:**
- Consumes: `app/rescue/index.html`、`app/rescue/styles.css`、品牌资产和 `admin/index.html`。
- Produces: `test_brand_uses_one_77_master_across_all_surfaces` 与 `test_hero_uses_one_continuous_warm_backdrop` 回归门禁。

- [ ] **Step 1: 写失败合同**

在 H5 合同中断言 `helpcat-77-mark.svg?v=20260812-brand-hero-r2`、favicon/PWA 新指纹、CSS token `--hero-backdrop: #F5F1EB`、hero 容器和图片区域相同背景、无 `border-left`；在后台合同中断言后台引用同一母版路径。

- [ ] **Step 2: 验证 RED**

Run: `python3 -m unittest tests.test_rescue_h5_contract tests.test_commercial_frontends -q`

Expected: FAIL，缺少新版本指纹、后台统一母版和连续背景规则。

- [ ] **Step 3: 提交测试**

```bash
git add tests/test_rescue_h5_contract.py tests/test_commercial_frontends.py
git commit -m "test: lock unified 77 brand and hero backdrop"
```

### Task 2: 重绘唯一 77 SVG 母版并派生图标

**Files:**
- Modify: `app/rescue/assets/brand/helpcat-77-mark.svg`
- Modify: `app/rescue/assets/brand/favicon.svg`
- Modify: `app/rescue/assets/brand/apple-touch-icon.png`
- Modify: `app/rescue/assets/brand/icon-192.png`
- Modify: `app/rescue/assets/brand/icon-512.png`
- Modify: `app/rescue/manifest.webmanifest`
- Modify: `admin/index.html`

**Interfaces:**
- Consumes: 示范图猫头轮廓与 `64×64` SVG viewBox。
- Produces: 单一 SVG 几何及其 192/512/Apple 位图派生物。

- [ ] **Step 1: 用代码原生 SVG 重绘母版**

保留 `viewBox="0 0 64 64"`，使用一条完整脸部外轮廓、两耳、右眼周围非对称黑斑、两只小眼、小粉鼻和克制嘴线；16px 预览仍能辨识黑眼斑。

- [ ] **Step 2: 让 favicon 复用相同几何**

将 `favicon.svg` 与母版保持字节一致；用 Pillow/CairoSVG 从母版派生 192、512 和 Apple 图标，不在位图中重画第二套图形。

- [ ] **Step 3: 统一页面与后台引用**

H5 页头、登录层和后台页头引用 `helpcat-77-mark.svg?v=20260812-brand-hero-r2`；manifest 与 HTML 图标链接增加相同发布指纹。

- [ ] **Step 4: 验证 GREEN 与资产尺寸**

Run: `python3 -m unittest tests.test_rescue_h5_contract tests.test_commercial_frontends -q`

Run: `python3 - <<'PY'
from PIL import Image
for p, size in [('app/rescue/assets/brand/apple-touch-icon.png', 180), ('app/rescue/assets/brand/icon-192.png', 192), ('app/rescue/assets/brand/icon-512.png', 512)]:
    assert Image.open(p).size == (size, size), (p, Image.open(p).size)
PY`

Expected: PASS。

- [ ] **Step 5: 提交品牌资产**

```bash
git add app/rescue/assets/brand app/rescue/manifest.webmanifest app/rescue/index.html admin/index.html
git commit -m "feat: unify 77 brand mark across surfaces"
```

### Task 3: 生成无中缝的桌面与手机 77 Hero

**Files:**
- Modify: `app/rescue/assets/77/hero-desktop.webp`
- Modify: `app/rescue/assets/77/hero-mobile.webp`
- Modify: `app/rescue/styles.css`
- Modify: `app/rescue/index.html`
- Modify: `app/rescue/version.js`

**Interfaces:**
- Consumes: 现有去元数据 77 公开 hero 和 `--hero-backdrop`。
- Produces: 背景边缘为 `#F5F1EB` 的 960×720 与 600×680 WebP。

- [ ] **Step 1: 编辑 hero 背景并保留 77**

仅替换/融合背景：桌面、手机图片四周背景收敛为 `#F5F1EB`，保持 77 面部、毛色、双耳、双眼和黑斑不变；输出后清除 EXIF/XMP。

- [ ] **Step 2: 统一 CSS 背板**

在最终 `:root` 中定义 `--hero-backdrop: #F5F1EB`；`.editorial-hero`、`.editorial-hero-copy`、`.editorial-hero-visual` 使用该色，去除图片区分割边框和造成中缝的独立背景。

- [ ] **Step 3: 更新资源版本**

将 HTML、CSS、JS 和 hero 查询指纹统一更新为 `20260812-brand-hero-r2`，避免旧 favicon/hero 缓存。

- [ ] **Step 4: 验证像素与合同**

运行脚本检查两张 hero 尺寸、边缘取样与 `#F5F1EB` 的 RGB 距离、无 EXIF/XMP，并运行 Task 1 合同。

- [ ] **Step 5: 提交 hero 精修**

```bash
git add app/rescue/assets/77 app/rescue/styles.css app/rescue/index.html app/rescue/version.js tests/test_rescue_h5_contract.py
git commit -m "feat: blend 77 hero into one warm backdrop"
```

### Task 4: 多视口视觉验收与发布

**Files:**
- Modify: `docs/wiki/变更记录.md`
- Create: `.superpowers/sdd/screenshots/brand-hero-desktop-1440x900.png`
- Create: `.superpowers/sdd/screenshots/brand-hero-mobile-390x844.png`

**Interfaces:**
- Consumes: Task 2 品牌资产与 Task 3 hero。
- Produces: 可复查截图、新 Git 提交与生产 immutable release。

- [ ] **Step 1: 运行全量门禁**

Run: `python3 -m unittest discover -s server/tests -p 'test_*.py' -q`

Run: `python3 -m unittest discover -s tests -p 'test_*.py' -q`

Run: `node --test tests/js/*.test.js && find app admin -name '*.js' -type f -print0 | xargs -0 -n1 node --check && git diff --check`

Expected: 全部 PASS，仅保留已记录的环境性 Alembic skip。

- [ ] **Step 2: 生成桌面与手机实拍**

在 1440×900 和 390×844 检查：logo 与示范图轮廓一致、hero 无中缝、77 裁切完整、无横向溢出、桌面无底栏、手机底栏不遮挡。

- [ ] **Step 3: 更新 Wiki 并推送**

记录版本、测试、截图和回滚点；提交并通过 ClashX 代理推送 `agent/mobile-upload-admin-entry`。

- [ ] **Step 4: 不可变部署**

备份当前 release 与 IP fallback 静态目录，上传完整 release、核对 SHA-256、原子切换 `/opt/help-cat/current`、`nginx -t` 后 reload；失败保持旧 release。

- [ ] **Step 5: 公网验收**

备案未完成期间从 `http://175.178.41.19/help-cat/rescue/index.html` 验证新版本、hero、favicon、API、77 档案与后台均 200；备案完成后再验收正式 HTTPS 域名。
