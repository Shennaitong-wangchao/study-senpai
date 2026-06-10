# Study Senpai

一个本地优先的学习陪伴框架，提供长期记忆、学习支持和主动关怀能力。

Study Senpai 是一个可自托管的 Python + SQLite 陪伴系统，包含 iOS 客户端、可选 Discord Bot 路径，以及可审计的 Dashboard。它适合希望获得学习陪伴、长期记忆和可控数据状态的用户。

## 包含内容

- 使用 SQLite 持久化的 Python 后端。
- 用于记忆审阅、可观测性和本地运维的 FastAPI Dashboard。
- 供 `ios/Lover/` 下 SwiftUI iOS 客户端使用的 Mobile API。
- 可选的 Discord Bot 运行时。
- 记忆提取、审阅、归档/恢复、摘要、共享日记和主动关怀流程。

沈知微是项目内置的默认示例人格。它代表的是示例产品行为，不是固定的托管服务身份。

## 当前状态

这是一个早期源码版本，适合本地开发和个人自托管。若要用于生产部署，还需要完成常规运维工作，例如 TLS、反向代理或防火墙规则、备份、令牌轮换和监控。

## 快速开始

使用 Python 3.11 或更新版本。当前 CI 工作流使用 Python 3.11 进行测试。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，只填写你需要的配置：

```bash
LLM_API_KEY=
LLM_MODEL=gpt-4.1-mini
RUN_DISCORD_BOT=false
DASHBOARD_ENABLED=true
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8099
MOBILE_API_TOKEN=
```

启动后端和 Dashboard：

```bash
python3 -m src.main
```

在本地打开 Dashboard：

```text
http://127.0.0.1:8099
```

运行轻量检查：

```bash
python3 -m pytest
python3 scripts/mobile_contracts.py
python3 scripts/dashboard_contracts.py
python3 scripts/verify_product.py
```

## 环境变量

后端回复所需配置：

- `LLM_API_KEY`：模型服务商密钥。请保存在 `.env` 中，不要提交到仓库。
- `LLM_MODEL`：默认模型名称。
- `LLM_BASE_URL`：可选的 OpenAI 兼容 API 地址。
- `LLM_PROMPT_CACHING_ENABLED`：默认为 `true`；会将静态提示词内容放在前面以适配 OpenAI 风格的自动缓存，并在 `LLM_BASE_URL` 指向 Anthropic 时使用其原生缓存断点。

Discord 路径：

- `RUN_DISCORD_BOT`：设置为 `true` 时启动 Discord。
- `DISCORD_BOT_TOKEN`：仅在 `RUN_DISCORD_BOT=true` 时需要。
- `DISCORD_APPLICATION_ID`：可选的应用 ID。

本地状态：

- `DATABASE_PATH`：默认使用 `data/` 下的 SQLite 文件。
- `LOG_FILE_PATH`：默认使用 `logs/` 下的日志文件。
- `BOT_TIMEZONE`：默认为 `Asia/Shanghai`。

Dashboard 和 Mobile API：

- `DASHBOARD_ENABLED`：启动 FastAPI Dashboard/Mobile 后端。
- `DASHBOARD_HOST` / `DASHBOARD_PORT`：绑定地址和端口。
- `DASHBOARD_AUTH_ENABLED`、`DASHBOARD_AUTH_USERNAME`、`DASHBOARD_AUTH_PASSWORD`：Dashboard 登录配置。
- `MOBILE_API_TOKEN`：`/mobile/*` 的可选 Bearer Token。如果要在 localhost 之外暴露 Mobile API，请先设置它。

## iOS 后端配置

iOS App 不包含硬编码的公开或私有后端地址。

- Debug 默认 Server Base URL 为 `http://127.0.0.1:8000`。
- 在 iOS App 中打开 **Settings**，编辑 **Server Base URL**。
- 如果 Python 后端使用仓库默认端口，请设置为 `http://127.0.0.1:8099`。
- 如果后端设置了 `MOBILE_API_TOKEN`，请在 **Mobile API Token** 中填写同一个值。

如果要配合 iOS 默认地址进行模拟器测试，请这样启动后端：

```bash
DASHBOARD_PORT=8000 python3 -m src.main
```

## 项目结构

```text
src/
  core/          设置、日志、共享类型
  db/            SQLite schema 和迁移
  memory/        记忆提取、检索、写入和摘要
  persona/       默认沈知微人格和回复策略
  services/      陪伴、回复和记忆编排
  bot/           Discord 客户端和消息路由
  dashboard/     FastAPI Dashboard 和 /mobile API
  mobile/        Mobile API schema
  product/       附件、主动关怀、day engine、可观测性
ios/Lover/       SwiftUI iOS 客户端
scripts/         合同检查、冒烟检查和回归检查
docs/            架构、路线图、运维和演示文档
```

开发者上手、常见改动路径和测试说明见 [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)。
完整测试矩阵见 [docs/TESTING.md](docs/TESTING.md)。

## Dashboard 共享日记

Dashboard 提供独立的 **共享日记** 面板，对应 `/api/shared-diary`。它会展示 day engine 沉淀出的日常片段、用户回应、语音输入和复盘内容，并支持按关键字、`entry_type`、`role_scope` 分页筛选。移动端可通过 `/mobile/dashboard/shared-diary` 读取同一份面板数据。

## 人格

沈知微是默认示例人格。当前实现将该人格放在 `src/persona/` 下的 Python 模块，以及 `src/llm/prompts/` 下的提示词文件中。计划中的 YAML/JSON 人格注册表方向见 [docs/PERSONA_SYSTEM_PUBLIC.md](docs/PERSONA_SYSTEM_PUBLIC.md)。

## 安全与隐私

- Study Senpai 是本地优先、自托管的项目，但如果绑定到公网主机，并不意味着它会自动保持私密。
- `.env`、SQLite 数据库、`data/`、`logs/`、`secrets/`，以及 iOS 本地配置/签名文件默认会被忽略。
- 当设置了 `MOBILE_API_TOKEN` 时，`/mobile/*` 需要 `Authorization: Bearer <MOBILE_API_TOKEN>`。
- 如果没有设置 `MOBILE_API_TOKEN`，`/mobile/*` 只接受 localhost/dev 请求。不要在这种模式下公开暴露它。
- Dashboard 认证和 Mobile Token 认证是分开的。除本地开发外，请保持 Dashboard 认证开启。
- 不要提交 API Key、Discord Token、Cookie、聊天日志、生成媒体、SQLite 文件或导出的记忆数据。

发布或部署前，请先阅读 [SECURITY.md](SECURITY.md)。

## 路线图

- Stage 1.5 发布打磨：GitHub hygiene 文件、演示脚本和轻量 CI。
- 人格注册表：将人格定义迁移到可审计的 YAML/JSON 配置。
- 更安全的公网部署方案：反向代理示例、HTTPS 指引、令牌轮换流程。
- 移动端打磨：持久化服务器配置、Token 校验页面、生成媒体缓存。
- 记忆治理：导出/导入控制、脱敏流程、保留策略设置。
- 学习工作流：目标、计划、间隔复习和学习会话分析。

更多细节见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 许可证

MIT。见 [LICENSE](LICENSE)。


---

## English fallback

Local-first companion framework for learning, memory, and proactive care.

Study Senpai is a self-hosted Python + SQLite companion system with an iOS client, Discord bot path, and auditable Dashboard. It is built for people who want learning support and long-running memory while keeping state under their own control.

## What Is Included

- Python backend with SQLite persistence.
- FastAPI Dashboard for memory review, observability, and local operations.
- Mobile API used by the SwiftUI iOS client under `ios/Lover/`.
- Optional Discord bot runtime.
- Memory extraction, review, archive/restore, summaries, shared diary, and proactive check-in flows.

沈知微 is included as the default example persona. Treat it as sample product behavior, not a fixed hosted service identity.

## Status

This is an early source release. It is suitable for local development and personal self-hosting, but production deployment still needs normal operator work: TLS, reverse proxy or firewall rules, backups, token rotation, and monitoring.

## Quick Start

Use Python 3.11 or newer. The CI workflow currently tests with Python 3.11.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill only the values you need:

```bash
LLM_API_KEY=
LLM_MODEL=gpt-4.1-mini
RUN_DISCORD_BOT=false
DASHBOARD_ENABLED=true
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8099
MOBILE_API_TOKEN=
```

Start the backend and Dashboard:

```bash
python3 -m src.main
```

Open the Dashboard locally:

```text
http://127.0.0.1:8099
```

Run the lightweight checks:

```bash
python3 -m pytest
python3 scripts/mobile_contracts.py
python3 scripts/dashboard_contracts.py
python3 scripts/verify_product.py
```

## Environment Variables

Required for backend replies:

- `LLM_API_KEY`: model provider key. Keep it in `.env`; never commit it.
- `LLM_MODEL`: default model name.
- `LLM_BASE_URL`: optional OpenAI-compatible API base URL.
- `LLM_PROMPT_CACHING_ENABLED`: defaults to `true`; keeps static prompt content first for OpenAI-style automatic caching
  and uses Anthropic native cache breakpoints when `LLM_BASE_URL` points at Anthropic.

Discord path:

- `RUN_DISCORD_BOT`: set `true` to start Discord.
- `DISCORD_BOT_TOKEN`: required only when `RUN_DISCORD_BOT=true`.
- `DISCORD_APPLICATION_ID`: optional application id.

Local state:

- `DATABASE_PATH`: defaults to a SQLite file under `data/`.
- `LOG_FILE_PATH`: defaults to a log file under `logs/`.
- `BOT_TIMEZONE`: defaults to `Asia/Shanghai`.

Dashboard and mobile API:

- `DASHBOARD_ENABLED`: starts the FastAPI Dashboard/mobile backend.
- `DASHBOARD_HOST` / `DASHBOARD_PORT`: bind address and port.
- `DASHBOARD_AUTH_ENABLED`, `DASHBOARD_AUTH_USERNAME`, `DASHBOARD_AUTH_PASSWORD`: Dashboard login.
- `MOBILE_API_TOKEN`: optional Bearer token for `/mobile/*`. Set it before exposing mobile APIs beyond localhost.

## iOS Backend Configuration

The iOS app does not contain a hardcoded public or private backend URL.

- Debug default Server Base URL: `http://127.0.0.1:8000`.
- In the iOS app, open **Settings** and edit **Server Base URL**.
- If your Python backend uses the repository default port, set it to `http://127.0.0.1:8099`.
- If `MOBILE_API_TOKEN` is set on the backend, enter the same value in **Mobile API Token**.

For simulator testing with the iOS default, start the backend with:

```bash
DASHBOARD_PORT=8000 python3 -m src.main
```

## Project Structure

```text
src/
  core/          Settings, logging, shared types
  db/            SQLite schema and migrations
  memory/        Memory extraction, retrieval, writing, summaries
  persona/       Default Shen Zhiwei persona and reply policies
  services/      Companion, reply, and memory orchestration
  bot/           Discord client and message routing
  dashboard/     FastAPI Dashboard and /mobile API
  mobile/        Mobile API schemas
  product/       Attachments, proactive care, day engine, observability
ios/Lover/       SwiftUI iOS client
scripts/         Contract, smoke, and regression checks
docs/            Architecture, roadmap, operations, demos
```

See [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) for contributor setup, common change paths, and test guidance.
See [docs/TESTING.md](docs/TESTING.md) for the full test matrix.

## Dashboard Shared Diary

The Dashboard includes a **Shared Diary** panel backed by `/api/shared-diary`. It surfaces day-engine diary entries, user responses, voice snippets, and review notes with keyword, `entry_type`, `role_scope`, and pagination filters. Mobile clients can read the same panel through `/mobile/dashboard/shared-diary`.

## Persona

沈知微 is the default example persona. The current implementation keeps that persona in Python modules under `src/persona/` and prompt files under `src/llm/prompts/`. See [docs/PERSONA_SYSTEM_PUBLIC.md](docs/PERSONA_SYSTEM_PUBLIC.md) for the planned YAML/JSON persona registry direction.

## Security And Privacy

- Study Senpai is local-first and self-hosted, but it is not automatically private if you bind it to a public host.
- `.env`, SQLite databases, `data/`, `logs/`, `secrets/`, and iOS local config/signing files are ignored by default.
- `/mobile/*` requires `Authorization: Bearer <MOBILE_API_TOKEN>` when `MOBILE_API_TOKEN` is set.
- If `MOBILE_API_TOKEN` is not set, `/mobile/*` accepts localhost/dev requests only. Do not expose it publicly in that mode.
- Dashboard auth is separate from mobile token auth. Keep Dashboard auth enabled outside local development.
- Do not commit API keys, Discord tokens, cookies, chat logs, generated media, SQLite files, or exported memory data.

See [SECURITY.md](SECURITY.md) before publishing or deploying.

## Roadmap

- Stage 1.5 release polish: GitHub hygiene files, demo scripts, and lightweight CI.
- Persona registry: move persona definitions into auditable YAML/JSON configs.
- Safer public deployment profile: reverse proxy examples, HTTPS guidance, token rotation workflow.
- Mobile polish: persisted server profiles, token validation screen, generated media cache.
- Memory governance: export/import controls, redaction workflow, retention settings.
- Study workflows: goals, plans, spaced review, and learning-session analytics.

More detail: [docs/ROADMAP.md](docs/ROADMAP.md).

## License

MIT. See [LICENSE](LICENSE).
