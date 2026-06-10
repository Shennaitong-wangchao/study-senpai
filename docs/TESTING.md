# 测试指南 / Testing Guide

## 目标

Study Senpai 的测试体系分三层：

- **pytest 单元/轻集成测试**：覆盖纯函数、安全边界、配置加载、记忆门控、人格修复和关键 Dashboard API。
- **contract 脚本**：验证 Dashboard 和 Mobile API 响应模型，避免客户端契约漂移。
- **产品级验证脚本**：覆盖核心 P0/P1 行为，包括认证、CSRF、移动端鉴权、day engine、共享日记、现实锚点和日志脱敏。

## 本地必跑

```bash
python -m pytest
python scripts/release_gate.py
python scripts/mobile_contracts.py
python scripts/dashboard_contracts.py
python scripts/verify_product.py
```

提示词缓存相关改动额外运行：

```bash
python scripts/verify_prompt_caching.py
```

Dashboard UI 改动额外运行：

```bash
python scripts/dashboard_e2e.py
python scripts/dashboard_visual_regression.py
```

## 当前 pytest 覆盖点

| 文件 | 覆盖内容 |
|------|----------|
| `tests/test_dashboard_shared_diary.py` | 共享日记 Dashboard API、筛选、移动端桥接 |
| `tests/test_dashboard_security.py` | Dashboard 密码哈希、hash 校验、请求来源 IP |
| `tests/test_memory_persona_rules.py` | 记忆提取门控、重复模式识别、沉浸文案修复 |
| `tests/test_product_health.py` | HealthCheck 浅/深巡检、模型注册、降级路径 |
| `tests/test_product_metrics.py` | 附件上下文、搜索摘要、体验指标评分 |
| `tests/test_release_gate.py` | 发布门禁、私有路径拦截、高置信凭据扫描 |
| `tests/test_settings.py` | 配置加载、必填环境变量、自动生成 Dashboard 凭据、模型解析 |
| `tests/test_utils.py` | JSON 提取、文本处理、时间工具 |

## 写新测试的规则

- 优先测试纯函数和边界条件，再补 API/端到端。
- 不在测试中写真实 API Key、Token、Cookie、聊天记录或私有数据库内容。
- 避免把示例密钥写成 `password = "..."`、`token = "..."` 这类会触发静态扫描的形式。
- Dashboard API 测试优先使用临时 SQLite 数据库和 `TestClient`。
- Mobile API 测试需要覆盖 localhost/dev 模式和 Bearer Token 模式。
- 涉及用户内容渲染时，要验证 HTML 被转义或通过 Pydantic/JSON 安全返回。

## CI 门禁

GitHub Actions 当前执行：

```text
python -m pytest
python scripts/release_gate.py
python scripts/mobile_contracts.py
python scripts/dashboard_contracts.py
python scripts/verify_product.py
```

未来应继续补：

- coverage 报告和最低阈值。
- Dashboard 视觉回归 artifact 上传。
- iOS 单元/UI 测试的独立 job。
- 静态安全扫描误报基线和真实高危问题分流。

## English fallback

Study Senpai uses a layered test strategy: fast pytest coverage for utilities and critical boundaries, contract scripts for Dashboard/Mobile API response shapes, and a product verification script for P0/P1 flows such as auth, CSRF, mobile access control, day engine, shared diary, reality context, and log redaction.

Run before opening a PR:

```bash
python -m pytest
python scripts/release_gate.py
python scripts/mobile_contracts.py
python scripts/dashboard_contracts.py
python scripts/verify_product.py
```
