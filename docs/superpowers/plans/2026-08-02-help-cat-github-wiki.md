# Help Cat GitHub Wiki Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可持续维护的多页面 GitHub Wiki，准确记录 Help Cat 已实现/未实现功能、架构、权限、业务、API、部署、测试和规模化路线。

**Architecture:** `docs/wiki/` 作为代码仓库内的文档源，GitHub Wiki 仓库作为发布镜像。所有页面使用相对 Wiki 链接；发布前执行敏感信息扫描、占位符扫描和链接检查。

**Tech Stack:** Markdown、GitHub Wiki Git 仓库、Git、`gh` CLI。

## Global Constraints

- Wiki 必须详细区分“已实现”“部分实现”“未实现”，不得把路线图写成现状。
- 不写入密码、Token、SSH 私钥、真实联系方式或精确猫窝位置。
- 架构必须明确当前单机 SQLite/本地文件的容量边界。
- GitHub 网络操作使用 ClashX；生产服务器 `175.178.41.19` 直连。

---

### Task 1: 创建 Wiki 源文件与导航

**Files:**
- Create: `docs/wiki/Home.md`
- Create: `docs/wiki/功能清单与状态.md`
- Create: `docs/wiki/系统架构.md`
- Create: `docs/wiki/角色与权限.md`
- Create: `docs/wiki/核心业务流程.md`
- Create: `docs/wiki/数据模型与-API.md`
- Create: `docs/wiki/部署回滚与运维.md`
- Create: `docs/wiki/测试与质量保障.md`
- Create: `docs/wiki/微信小程序接入.md`
- Create: `docs/wiki/规模化路线图.md`
- Create: `docs/wiki/变更记录.md`
- Create: `docs/wiki/_Sidebar.md`

**Interfaces:**
- Consumes: 代码、测试、设计文档、生产部署证据和 PR #1。
- Produces: 12 个互相链接的 Markdown 页面。

- [ ] **Step 1: 编写 Home 与侧边栏**

Home 包含产品目标、当前阶段、线上入口、仓库/PR、核心状态和全部页面导航；`_Sidebar.md` 使用 GitHub Wiki 页面链接。

- [ ] **Step 2: 编写功能清单与状态**

按 H5、管理后台、API、微信小程序列出状态表。每项包含用户价值、入口、状态、测试覆盖和已知限制。

- [ ] **Step 3: 编写架构、权限、流程和数据/API**

使用 Mermaid 或文本流程说明客户端、Nginx、FastAPI、SQLite、媒体目录和管理端关系；列出角色矩阵、状态机、核心表与 API 分组。

- [ ] **Step 4: 编写部署、测试、小程序、规模路线和变更记录**

记录可回滚发布流程、测试命令、当前 miniapp 骨架和微信上线前置条件；规模路线按触发条件和验收指标分阶段，变更记录链接 PR #1。

---

### Task 2: 校验 Wiki 准确性与安全性

**Files:**
- Verify: `docs/wiki/*.md`

**Interfaces:**
- Consumes: Task 1 页面。
- Produces: 可安全公开的 Wiki 源。

- [ ] **Step 1: 扫描占位符和敏感模式**

```bash
if rg -n 'T[B]D|T[O]DO|PLACEHOLD[E]R|gho_|BEGIN (RSA|OPENSSH) PRIVATE KEY|password\s*[:=]' docs/wiki; then exit 1; fi
```

Expected: 无输出，退出 0。

- [ ] **Step 2: 检查页面、标题和相对链接**

确认 12 个文件存在，每个页面只有一个一级标题，所有侧边栏目标有对应文件，未实现功能明确标记。

- [ ] **Step 3: 对照代码和测试抽查事实**

核对 API 路由、角色、数据库表、生产路径、测试数量、微信 Provider 状态和当前架构边界，不使用推测填充。

- [ ] **Step 4: 提交 Wiki 源文件**

```bash
git add docs/wiki
git commit -m "Document Help Cat architecture and product status"
```

---

### Task 3: 初始化并发布 GitHub Wiki

**Files:**
- Publish: `https://github.com/pig-tongzhi/help-cat/wiki`

**Interfaces:**
- Consumes: `docs/wiki/*.md`。
- Produces: `pig-tongzhi/help-cat.wiki.git` 多页面 Wiki。

- [ ] **Step 1: 初始化空 Wiki**

仓库已启用 Wiki 但 `.wiki.git` 尚不存在。使用已登录 GitHub 会话创建首个 `Home` 页面，不覆盖任何现有内容。

- [ ] **Step 2: 克隆 Wiki Git 仓库并同步页面**

使用临时目录克隆 `https://github.com/pig-tongzhi/help-cat.wiki.git`，将 `docs/wiki/*.md` 同步到 Wiki 根目录，提交并推送。

- [ ] **Step 3: 验证发布结果**

检查 Wiki Home、侧边栏、全部页面链接与 Mermaid 渲染；通过 `git ls-remote` 确认远端提交存在。

- [ ] **Step 4: 更新 PR 与变更记录**

把 Wiki 链接和文档验证结果写入 PR #1；`变更记录` 标明本次角色、小区、版本和 Wiki 整改。
