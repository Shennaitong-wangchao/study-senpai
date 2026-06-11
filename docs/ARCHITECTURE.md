# 架构 / Architecture

## 中文优先

Study Senpai 是一个本地优先的陪伴系统框架，围绕一个 Python 后端和多个用户入口构建。

## 运行入口

- **Discord**：`src/bot/` 接收 Discord 消息，并路由到陪伴服务。
- **Dashboard**：`src/dashboard/server.py` 暴露 FastAPI 路由，用于审核、可观测性、记忆治理和运维。
- **Mobile API**：`/mobile/*` 路由运行在 Dashboard app 内，复用同一组 store 和 service。
- **iOS**：`ios/Lover/` 是 SwiftUI 客户端，支持移动聊天、时间线、附件、设置和 Dashboard 面板。

## v0.2.0 新增组件

### PersonaRegistry（`src/persona/registry.py`）

人格注册表，负责从 YAML 文件加载和校验 `PersonaProfile`。支持：

- 从任意路径加载单个 YAML 人格文件。
- 加载默认人格（`personas/shen_zhiwei.yaml`）。
- 列出可用人格文件。
- 完整的必填字段校验，缺失字段时给出明确错误提示。

### StudyService（`src/product/study.py`）

学习功能服务层，封装 `study_goals`、复习卡片、学习会话和统计的全部 CRUD 操作。由 `CommandRouter` 和 Dashboard 路由共用，是 v0.2.0 引入 study_goals 表的主要使用方。

### CommandRouter（`src/bot/commands.py`）

Discord 命令路由器，统一解析和派发 `!` 前缀命令。内部持有 `StudyService` 实例；所有命令在执行前检查调用方身份，拒绝越权操作。

### SimpleRateLimitMiddleware（`src/dashboard/server.py`）

FastAPI 中间件，对写操作（POST / PUT / PATCH / DELETE）和 `/api/chat/stream` 端点实施基于 IP 的滑动窗口速率限制：

- 默认：120 次请求 / 60 秒窗口。
- 超限返回 HTTP 429，携带 `Retry-After: 60` 响应头。
- 挂载顺序：`SimpleRateLimitMiddleware` → `DashboardSecurityMiddleware` → Session Auth（最外层先执行）。

详见 [SECURITY.md](../SECURITY.md#速率限制)。

## 核心后端流程

1. 用户消息从 Discord 或 `/mobile/chat/stream` 进入。
2. `CompanionService` 写入用户消息、更新 presence、规划工具并构建回复上下文。
3. `ReplyService` 通过 `LLMClient` 调用配置好的 LLM。
4. 助手消息写入 SQLite。
5. 后台后处理提取候选记忆、摘要、事实、关系状态和可观测性指标。
6. Dashboard/mobile 视图从同一套 SQLite store 读取数据进行审核和展示。

## 存储

SQLite 是默认本地存储：

- 聊天消息和会话。
- 长期记忆和候选记忆。
- 结构化事实和关系状态。
- Dashboard 审计/安全事件。
- 后台任务和产品可观测性。

第一阶段开源打包不改变数据库 schema。

## 配置

后端配置通过 `src/core/settings.py` 从环境变量读取。本地密钥应放在 `.env`，该文件已被 git 忽略。

关键边界：

- `DATABASE_PATH` 和 `LOG_FILE_PATH` 控制本地状态路径。
- `MOBILE_API_TOKEN` 在 localhost/dev 之外保护 `/mobile/*`。
- `DASHBOARD_AUTH_*` 控制 Dashboard 登录和 session 行为。
- `RUN_DISCORD_BOT`、`RUN_BACKGROUND_WORKER` 和 `DASHBOARD_ENABLED` 控制运行角色。

## 人格

沈知微是默认示例人格。当前实现位于：

- `src/persona/`
- `src/llm/prompts/`

计划方向是数据驱动的人格注册表，见 `docs/PERSONA_SYSTEM_PUBLIC.md`。

## 安全边界

Dashboard 认证和 Mobile Token 认证是分开的：

- Dashboard 路由使用 session auth 和 CSRF 检查。
- 设置 `MOBILE_API_TOKEN` 时，`/mobile/*` 使用 Bearer Token 认证。
- 空 Mobile Token 模式仅用于 localhost/dev。

未设置 Dashboard auth、`MOBILE_API_TOKEN` 和网络层保护前，不要将后端公开暴露。

## English fallback

Study Senpai is a local-first companion framework built around one Python backend and multiple user surfaces.

Runtime paths:

- **Discord**: `src/bot/` receives Discord messages and routes them into the companion service.
- **Dashboard**: `src/dashboard/server.py` exposes FastAPI routes for review, observability, memory governance, and operations.
- **Mobile API**: `/mobile/*` routes live in the Dashboard app and reuse the same stores and services.
- **iOS**: `ios/Lover/` is a SwiftUI client for mobile chat, timeline, attachments, settings, and dashboard panels.

v0.2.0 new components:

- **PersonaRegistry** (`src/persona/registry.py`): loads and validates `PersonaProfile` objects from YAML files with strict required-field checks.
- **StudyService** (`src/product/study.py`): CRUD layer for study goals, flashcards, study sessions, and statistics; shared by `CommandRouter` and Dashboard routes.
- **CommandRouter** (`src/bot/commands.py`): Discord command dispatcher that parses `!`-prefixed commands, enforces caller identity checks, and delegates to `StudyService`.
- **SimpleRateLimitMiddleware** (`src/dashboard/server.py`): sliding-window IP rate limiter (120 req / 60 s) applied to write methods and `/api/chat/stream`; returns HTTP 429 with `Retry-After: 60` on breach.

Core flow: a message enters through Discord or `/mobile/chat/stream`, `CompanionService` stores it and builds context, `ReplyService` calls the configured LLM, the assistant message is stored in SQLite, and background jobs extract memories, summaries, facts, relationship state, and observability metrics.

SQLite stores messages, memories, structured facts, relationship states, dashboard audit/security events, background tasks, and product observability. The first open-source phase does not change database schema.

Environment-driven configuration lives in `src/core/settings.py`. Keep local secrets in ignored `.env` files. Do not expose the backend publicly without Dashboard auth, `MOBILE_API_TOKEN`, and network-level protection.
