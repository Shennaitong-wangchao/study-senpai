# 安全策略 / Security Policy

## 中文优先

本仓库是本地优先的陪伴系统框架。当前安全边界面向本地开发、私人服务器，以及经过严格控制的个人自托管部署。

### 敏感数据

不要提交或公开以下内容：

- `.env` 文件或任何环境专属配置。
- API Key、Discord Token、Mobile API Token、Cookie、Session Secret、Dashboard 密码。
- SQLite 数据库、WAL/SHM 文件、备份、记忆导出、聊天日志、生成图片、附件或本地日志。
- iOS 签名文件、Provisioning Profile、私有 xcconfig 文件或本地 Secret Swift 文件。

如果安全问题涉及密钥或私有用户内容，请用 `[REDACTED]` 替换真实值。

### Mobile API 认证

`/mobile/*` 使用最小 Bearer Token 保护：

- 非本地部署请在后端环境中设置 `MOBILE_API_TOKEN`。
- iOS 客户端或其他 Mobile API 调用方发送 `Authorization: Bearer <token>`。
- 如果 `MOBILE_API_TOKEN` 为空，后端只接受 localhost/dev 风格请求。

示例：

```bash
export MOBILE_API_TOKEN="replace-with-a-long-random-token"
```

```bash
curl -H "Authorization: Bearer $MOBILE_API_TOKEN" \
  http://127.0.0.1:8099/mobile/bootstrap
```

不要在公网反向代理后依赖空 token 的 localhost fallback。公开暴露后端前，请先设置 token。

### Dashboard 安全

- 除本地实验外，保持 `DASHBOARD_AUTH_ENABLED=true`。
- 设置强 `DASHBOARD_AUTH_PASSWORD`，或首次启动后立即更换自动生成的 bootstrap 密码。
- 生产近似环境中设置 `DASHBOARD_SESSION_SECRET`。
- 通过 HTTPS 提供服务时，优先启用 TLS 终止和 `DASHBOARD_SESSION_HTTPS_ONLY=true`。
- 如果绑定 `DASHBOARD_HOST=0.0.0.0`，同时设置 `DASHBOARD_PUBLIC_BIND_ACKNOWLEDGED=true`，并使用防火墙、VPN 或反向代理保护服务。

### 速率限制

v0.2.0 起，Dashboard 和 Mobile API 共用 `SimpleRateLimitMiddleware` 滑动窗口速率限制：

- **默认限额**：每个 IP 在 60 秒窗口内最多 120 次请求（`max_requests=120, window_seconds=60`）。
- **适用范围**：所有写操作（POST / PUT / PATCH / DELETE）以及 `/api/chat/stream` 端点；只读 GET 请求不受限。
- **超限响应**：HTTP 429，响应头携带 `Retry-After: 60`。
- **IP 来源**：优先读取 `X-Forwarded-For`（反向代理场景），回退到直连 IP。
- **注意**：该限制基于内存，重启后清零；高并发生产环境建议在反向代理层（Nginx / Caddy）叠加外部速率限制。

### v0.2.0 安全改进

| 改进项 | 说明 |
|--------|------|
| `SimpleRateLimitMiddleware` | 写操作 + chat stream 滑动窗口速率限制，防止暴力枚举和刷接口 |
| `PersonaRegistry` YAML 校验 | 加载人格文件时强制校验所有必填字段，拒绝格式不合规的文件 |
| `StudyService` 输入校验 | study_goals 所有写入路径添加类型和长度检查 |
| `CommandRouter` 鉴权边界 | Discord 命令路由统一检查调用方身份，拒绝越权操作 |
| 数据库迁移脚本 | `scripts/migrate_from_v01.py` 提供从 v0.1.x 安全迁移的幂等工具 |

### 质量和安全门禁

发布前门禁、secret scan、静态分析口径、已知误报和阻断规则见 [docs/QUALITY_BASELINE.md](docs/QUALITY_BASELINE.md)。

### 漏洞报告

请通过私有安全公告或维护者私下渠道报告。不要包含真实密钥、聊天日志、数据库行或可识别用户的数据；敏感值统一替换为 `[REDACTED]`。

报告中请尽量包含：

- 简短影响说明。
- 受影响路径或 endpoint。
- 使用假数据的复现步骤。
- 已知的修复建议。

## English fallback

This repository is a local-first companion framework for local development, private servers, and carefully controlled personal deployments.

Never commit `.env` files, API keys, tokens, cookies, session secrets, dashboard passwords, SQLite databases, chat logs, memory exports, generated media, local logs, or iOS signing/private config files. Use `[REDACTED]` when reporting secrets or private content.

`/mobile/*` uses Bearer token authentication when `MOBILE_API_TOKEN` is set. Empty-token mode is for localhost/dev only and must not be exposed through a public reverse proxy.

Keep Dashboard authentication enabled outside local experiments, set a strong password and session secret, prefer HTTPS, and protect any `0.0.0.0` bind with network controls.

Since v0.2.0, `SimpleRateLimitMiddleware` applies a sliding-window rate limit of 120 requests per 60 seconds per IP, covering write methods and `/api/chat/stream`. Requests that exceed the limit receive HTTP 429 with a `Retry-After: 60` header. For high-traffic production deployments, add a network-layer rate limit on the reverse proxy as well.

Release gates, secret scanning, static-analysis interpretation, known false positives, and blocking rules are tracked in [docs/QUALITY_BASELINE.md](docs/QUALITY_BASELINE.md).

Report vulnerabilities privately and include impact, affected paths, dummy-data reproduction steps, and suggested fixes when available.
