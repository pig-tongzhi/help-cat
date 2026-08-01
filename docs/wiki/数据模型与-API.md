# 数据模型与 API

## 数据模型

### users

| 字段 | 说明 |
|---|---|
| `id` | UUID hex 主键 |
| `openid` | 微信 OpenID 或 `local:<username>` |
| `username` | 本地账号名，可空、唯一 |
| `password_hash` | 密码哈希，可空 |
| `role` | USER / ADMIN / SUPER_ADMIN |
| `status` | 当前使用 ACTIVE |
| `nickname` | 显示名称 |
| `created_at`、`last_login_at` | 创建和最近登录时间 |

### sessions

保存 Bearer Token、用户 ID、过期时间和撤销时间。Token 是随机 URL-safe 字符串，退出后通过 `revoked_at` 失效。

### communities

| 字段 | 说明 |
|---|---|
| `city`、`district`、`street`、`name` | 行政和小区信息 |
| `status` | PENDING_REVIEW / ACTIVE / HIDDEN / ARCHIVED |
| `created_by`、`reviewed_by` | 创建者和审核者 |
| `created_at`、`updated_at` | 时间戳 |

### cats

关联小区，保存猫咪编号、名称、居住/健康状态、模糊位置、可选坐标、可选图片、审核状态、可见性和创建者。

猫咪编号格式为随机生成的 `HC-XXXXXXXX`。

### daily_cat_quotas

联合主键为 `user_id + quota_date`，记录普通用户当天已使用的建档数量。

### media_assets

保存随机对象键、内容类型、字节数、创建者和创建时间。二进制文件当前保存在本地目录。

### tasks

保存标题、说明、可选小区、状态、创建者、领取者和领取时间。

### audit_logs

保存操作者、动作、实体类型、实体 ID、操作前后 JSON 和时间。当前有写入能力，没有公开查询 API。

## API 约定

- 基础前缀：`/help-cat-api/api/v1`（Nginx 转发后）。
- JSON 请求使用 `Content-Type: application/json`。
- 认证请求使用 `Authorization: Bearer <token>`。
- 错误响应包含稳定 `code` 和可选 `message`。
- H5 根据错误 code 映射用户可读中文，不依赖 HTTP 文本。

## 健康与认证

| 方法 | 路径 | 权限 | 作用 |
|---|---|---|---|
| GET | `/health` | 公开 | 服务健康和版本 |
| POST | `/auth/register` | 公开 | 创建 USER 本地账号 |
| POST | `/auth/login` | 公开 | 用户名密码登录 |
| POST | `/auth/wechat-login` | 公开 | 微信登录入口；真实 Provider 尚未完成 |
| GET | `/auth/me` | 登录 | 恢复当前用户与角色 |
| POST | `/auth/logout` | 登录 | 撤销当前 Session |

## 小区

| 方法 | 路径 | 权限 | 作用 |
|---|---|---|---|
| GET | `/communities` | 公开 | 只返回 ACTIVE 小区，支持 `q` |
| GET | `/admin/communities` | ADMIN+ | 返回全部小区 |
| POST | `/communities` | 登录 | USER 待审；ADMIN+ 直接开放 |
| PATCH | `/communities/{id}` | ADMIN+ | 修改名称和街道 |
| POST | `/communities/{id}/review` | ADMIN+ | 通过变 ACTIVE，不通过变 HIDDEN |
| POST | `/communities/{id}/archive` | ADMIN+ | 归档 |

## 猫咪

| 方法 | 路径 | 权限 | 作用 |
|---|---|---|---|
| GET | `/cats` | 公开/可选管理员 Token | 访客仅看 APPROVED+ACTIVE；管理员看全部 |
| POST | `/cats` | 登录 | USER 待审且有每日配额；ADMIN+ 直接通过 |
| POST | `/cats/{id}/review` | ADMIN+ | 审核通过或拒绝 |
| POST | `/cats/{id}/visibility` | ADMIN+ | 公开或隐藏 |
| POST | `/cats/{id}/archive` | ADMIN+ | 归档 |
| GET | `/me/submissions` | 登录 | 当前用户的小区和猫咪提交 |

## 任务

| 方法 | 路径 | 权限 | 作用 |
|---|---|---|---|
| GET | `/tasks` | 公开 | 开放任务列表 |
| POST | `/tasks` | ADMIN+ | 创建任务 |
| POST | `/tasks/{id}/claim` | 登录 | 原子领取任务 |

## 媒体

| 方法 | 路径 | 权限 | 作用 |
|---|---|---|---|
| POST | `/media/images` | 登录 | 上传并校验单张图片 |
| GET | `/media/{asset_id}` | 公开 | 读取媒体文件 |

媒体读取当前为公开 ID 地址。规模化前需评估防盗链、CDN、内容审核、隐私和删除策略。

## 用户与角色管理

| 方法 | 路径 | 权限 | 作用 |
|---|---|---|---|
| GET | `/admin/users` | SUPER_ADMIN | 全量用户列表 |
| POST | `/admin/users/{id}/role` | SUPER_ADMIN | USER 与 ADMIN 之间切换 |

## 常见错误码

| code | 含义 |
|---|---|
| `invalid_credentials` | 账号或密码错误 |
| `username_exists` | 用户名已存在 |
| `unauthorized` / `session_expired` | 未登录或会话过期 |
| `user_disabled` | 账号停用 |
| `forbidden` | 当前角色无权限 |
| `super_admin_required` | 需要超级管理员 |
| `super_admin_immutable` | 不能修改唯一超级管理员 |
| `community_exists` | 小区已存在或正在审核 |
| `community_not_found` | 小区不存在或未开放 |
| `daily_cat_limit_reached` | 普通用户达到每日建档上限 |
| `task_already_claimed` | 任务已被领取 |
| `unsupported_image_type` | 不支持的图片 MIME |
| `image_too_large` | 图片超过上限 |
| `image_content_mismatch` | MIME 与实际文件签名不符 |

## 数据库迁移

- SQLAlchemy 模型是运行时数据结构来源。
- Alembic 位于 `server/helpcat/migrations/`。
- `ensure_schema()` 为早期 SQLite 试运行提供小范围向前兼容补列，不应替代正式生产迁移。
- 迁移 PostgreSQL 前必须先做数据备份、双向数量校验、业务抽样和回滚演练。

