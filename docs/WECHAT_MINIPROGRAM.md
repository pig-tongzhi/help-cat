# 帮帮小猫微信小程序接入说明

## 当前实现

仓库 `miniprogram/` 是原生微信小程序工程，可直接用微信开发者工具导入。首版已经接入现有 `/api/v1`：

- 首页：77 主视觉、公益数据、公开猫咪、开放任务。
- 猫咪档案：公开档案列表和照片。
- 救助任务：开放任务列表、登录后领取。
- 我的：`wx.login` 登录、服务端会话保存、退出登录。
- 状态处理：四个页面都有加载、空数据和错误状态。

## 上线前必须完成

1. 等 `helpcat.xyz` 在腾讯云完成 ICP 备案。目前 DNS、Let's Encrypt 证书和 Nginx 已配置，腾讯云在备案通过前会拦截外部 HTTPS。
2. 在微信公众平台创建小程序，取得正式 AppID；把 `miniprogram/project.config.json` 的 `touristappid` 替换为正式 AppID。
3. 在小程序后台“开发管理 → 开发设置 → 服务器域名”配置：
   - request 合法域名：`https://helpcat.xyz`
   - uploadFile 合法域名：`https://helpcat.xyz`
   - downloadFile 合法域名：`https://helpcat.xyz`
4. 在服务器的 `help-cat.service` 环境变量中配置：
   - `HELPCAT_WECHAT_APP_ID`
   - `HELPCAT_WECHAT_APP_SECRET`
5. 重启 `help-cat.service` 后，用真机调用“微信一键登录”。AppSecret 只能存在服务器环境变量中，禁止写入小程序代码或 Git。

## 本地开发

备案完成前，开发者工具可在本地调试阶段临时关闭“校验合法域名、web-view、TLS 版本以及 HTTPS 证书”，但体验版、审核版和正式版必须使用可公网访问的 HTTPS 合法域名。

导入目录：

```text
<repository>/miniprogram
```

默认 API：

```text
https://helpcat.xyz/api/v1
```

## 微信登录流程

```text
小程序 wx.login
  → POST /api/v1/auth/wechat-login { code }
  → 服务端调用微信 code2Session
  → 服务端只保存 openid 并签发帮帮小猫会话
  → 小程序保存 access_token
```

`session_key` 不返回客户端、不写日志、不保存到小程序本地。

## 后续迭代

- 猫咪建档表单、相册选择与 `wx.uploadFile`。
- 小区候选提交和审核进度。
- 我的提交、任务详情、领取确认。
- 订阅消息（审核结果、任务状态变化）。
- 隐私保护指引、用户隐私授权弹窗和小程序备案/审核材料。
