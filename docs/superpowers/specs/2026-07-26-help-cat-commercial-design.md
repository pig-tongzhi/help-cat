# 帮帮小猫 Help Cat 商业化重构设计

## 目标

把当前仅用于验证业务的 localStorage H5 改造成可真实运营的产品：微信小程序服务普通用户和志愿者，管理后台服务管理员，统一访问生产 API；支持杭州富阳区银湖街道下按街道/小区管理猫咪档案、照片、投喂点、任务和审核状态。

## 调研结论

- 动物救助产品的核心不是单一地图，而是可检索的动物完整档案、照片、健康/TNR 状态、位置和协作任务。
- 小程序登录以微信临时登录凭证换取服务端会话；AppSecret 只能放在服务端，不能进入小程序代码。
- 图片使用微信文件选择/拍摄后上传到后端对象存储；服务端必须校验 MIME、大小、扩展名并生成不可猜测对象名。
- 小程序生产请求必须使用配置过的 HTTPS 合法域名；上线前需要域名、证书、小程序 AppID 和隐私指引配置。

## 产品边界

### 用户端小程序

- 微信登录；未登录可浏览公开猫咪档案和小区。
- 搜索街道/小区，查看公开猫咪档案和投喂点的模糊位置。
- 新增猫咪档案：照片、名称、活动位置、居住情况、说明；进入待审核。
- 新增小区建议；进入待审核。
- 查看自己的提交及状态。
- 查看管理员发布任务并领取；一个任务只能有一个当前领取人。

### 管理后台

- 管理员登录和权限校验。
- 小区/街道管理：新增、编辑、审核、隐藏、归档。
- 猫咪档案库：搜索全部档案，审核、编辑、公开、隐藏、归档。
- 投喂点、上报、任务、物资、操作日志和导出。
- 所有写操作记录 actor、时间、对象、前后状态。

## 技术架构

```text
微信小程序 / 管理后台 H5
        ↓ HTTPS JSON + multipart
FastAPI API（无状态）
        ├── MySQL 8：用户、社区、猫咪、照片元数据、任务、审计
        ├── Redis：会话/限流（第一版可关闭，配额仍由 DB 事务保证）
        └── 对象存储：COS/S3；本地磁盘只用于开发回退
```

- 后端：FastAPI + SQLAlchemy 2，生产数据库使用 MySQL 8，开发环境允许 SQLite。
- 认证：`wx.login` code 由服务端换取 openid/session_key；服务端签发 HttpOnly Cookie 或短期 Bearer Token。AppSecret 不落前端。
- 权限：`USER`、`VOLUNTEER`、`ADMIN`，后端每个写接口二次校验，前端隐藏不等于权限控制。
- 配额：数据库按 `user_id + Asia/Shanghai calendar date` 计数；创建猫咪在同一事务内锁定配额记录，超过 3 条回滚。
- 删除：猫咪和社区只做 `HIDDEN/ARCHIVED` 软删除；管理员可恢复隐藏但不能恢复已归档，避免历史丢失。
- 图片：单张主图，最大 5MB，白名单 `image/jpeg,image/png,image/webp`；后端压缩/转码可在第二阶段接入，第一版保存原图与尺寸元数据。

## 数据模型

- `users(id, openid, role, status, nickname, created_at, last_login_at)`
- `communities(id, city, district, street, name, status, created_by, reviewed_by, created_at, updated_at)`
- `feeding_points(id, community_id, label, latitude, longitude, precision, status)`
- `cats(id, community_id, feeding_point_id, code, nickname, living_status, health_status, location_note, review_status, visibility_status, created_by, created_at, updated_at)`
- `cat_photos(id, cat_id, object_key, content_type, byte_size, width, height, status, created_at)`
- `tasks(id, title, description, status, published, assignee_id, created_by, created_at, updated_at)`
- `audit_logs(id, actor_id, action, entity_type, entity_id, before_json, after_json, created_at)`

## API 契约

- `POST /api/v1/auth/wechat-login`
- `GET /api/v1/communities?q=`
- `POST /api/v1/communities`（用户建议/管理员直接创建）
- `PATCH /api/v1/communities/{id}`（管理员）
- `POST /api/v1/communities/{id}/review`（管理员）
- `POST /api/v1/communities/{id}/archive`（管理员）
- `GET /api/v1/cats?q=&community_id=&review_status=&visibility_status=`
- `POST /api/v1/cats`
- `POST /api/v1/cats/{id}/review`（管理员）
- `POST /api/v1/cats/{id}/visibility`（管理员）
- `POST /api/v1/cats/{id}/archive`（管理员）
- `POST /api/v1/media/images`
- `GET /api/v1/me/submissions`
- `GET /api/v1/tasks`
- `POST /api/v1/tasks/{id}/claim`
- `GET /api/v1/admin/audit-logs`（管理员）

## 商业上线门禁

- 小程序 AppID、AppSecret、主体资质和类目确认。
- 备案域名、HTTPS 证书、合法域名配置。
- 隐私保护指引：微信身份、照片、位置、日志的用途、保存期限和删除方式。
- 生产数据库备份恢复演练。
- 图片访问不暴露对象存储永久密钥，公开图片使用签名 URL 或 CDN。
- 监控健康检查、错误日志、慢查询和磁盘空间。

## 分期

1. **商业后端基础**：数据库模型、认证接口、权限、社区/猫咪/图片/任务 API。
2. **用户小程序**：登录、搜索、建档、拍照上传、我的提交、任务领取。
3. **管理员后台**：档案治理、审核、任务、日志、导出。
4. **上线部署**：域名 HTTPS、MySQL、对象存储、备份、微信开发者工具体验版。
