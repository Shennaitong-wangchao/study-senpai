# 更新日志 / Changelog

## 中文优先

所有值得记录的 Study Senpai 变更都会写在这里。在正式 release tag 引入前，本项目先使用简单、可读的人类维护版更新日志。

## 未发布

- 将项目整理为 Study Senpai 的初始公开 GitHub 发布形态。
- 增加本地优先 README 定位和 demo 录制说明。
- 增加最小 `/mobile/*` Bearer Token 文档和发布安全说明。
- 增加 GitHub hygiene 文件和轻量 CI 工作流。
- 保留沈知微作为默认示例人格。
- 将主要 Markdown 文档调整为中文优先、英文备用。
- 增加共享日记 Dashboard/Mobile API 面板，展示 day engine 沉淀的复盘、回应和语音片段。
- 增加 `pyproject.toml`、pytest 回归测试和开发者上手指南。
- 扩展 pytest 覆盖到 utils、配置加载、Dashboard 安全、记忆门控、沉浸文案和体验指标，并增加测试指南。
- 增加 `scripts/release_gate.py`，在 CI 中检查被跟踪的本地私有文件和高置信凭据模式。
- 增加 HealthCheck 浅/深巡检单测，覆盖模型注册、chat/fallback ping 和降级路径。
- 增加后台任务管理器单测，覆盖入队默认值、成功执行、缺失 handler 和超时处理。
- 增加流式切块和类人分段发送单测，覆盖 Markdown 代码块、长文本切分和 typing/send 行为。
- 增加附件和搜索服务单测，覆盖文件 payload、大小上限、image/audio 分析、DuckDuckGo HTML 解析和失败降级。

## 0.1.0 - 计划中

- 第一个公开源码版本。
- 基线 Python 后端、Dashboard、Discord 路径和 iOS 客户端路径。
- 可审计记忆工作流和学习陪伴流程。

## English fallback

All notable Study Senpai changes are documented here. Until release tags are introduced, the project uses a simple human-readable changelog.

## Unreleased

- Prepared the project for an initial public GitHub release as Study Senpai.
- Added local-first README positioning and demo recording notes.
- Added minimal `/mobile/*` Bearer token documentation and release safety notes.
- Added GitHub hygiene files and lightweight CI workflow.
- Kept 沈知微 as the default example persona.
- Made primary Markdown docs Chinese-first with English fallback.
- Added a shared diary Dashboard/Mobile API panel for day-engine review notes, responses, and voice snippets.
- Added `pyproject.toml`, pytest regression coverage, and a developer onboarding guide.
- Expanded pytest coverage across utilities, settings, Dashboard security, memory gating, immersive voice repair, and experience metrics, with a dedicated testing guide.
- Added `scripts/release_gate.py` to block tracked local-private files and high-confidence credential patterns in CI.
- Added HealthCheck shallow/deep probe tests for model registry checks, chat/fallback pings, and degraded paths.
- Added background task manager tests for enqueue defaults, successful execution, missing handlers, and timeouts.
- Added streaming chunk and human delivery tests for Markdown fences, long text splitting, and typing/send behavior.
- Added attachment and search service tests for file payloads, byte limits, image/audio analysis, DuckDuckGo HTML parsing, and degraded search paths.

## 0.1.0 - Planned

- First public source release.
- Baseline Python backend, Dashboard, Discord path, and iOS client path.
- Auditable memory workflows and study companion flows.
