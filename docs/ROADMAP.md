# 路线图 / Roadmap

## 中文优先

这份路线图的目标，是让项目继续作为本地优先框架保持可用，同时逐步适配更安全的公开协作。

## Phase 1：安全开源打包

- 加固 `.gitignore`，覆盖本地状态、密钥、SQLite、日志、聊天记录和 iOS 私有文件。
- 增加最小 Mobile Bearer Token 认证。
- 移除 iOS 中硬编码的后端 URL。
- 围绕 Study Senpai 重写 README。
- 增加基础开源文档和政策文件。

## Phase 1.5：发布验收与公开门面

- 收紧发布前敏感文件检查。
- 改进 GitHub 访问者首屏 README 定位。
- 使用干净 demo 数据库录制公开 demo 后再加入展示。
- 增加 GitHub issue、pull request、行为准则、更新日志和 CI hygiene 文件。
- 保持 CI 轻量：安装 Python 依赖并运行 contract/smoke 脚本。
- 将主要 Markdown 文档调整为中文优先、英文备用。

## Phase 2：配置与部署加固

- 在 CI 中增加生成密钥检查。
- 增加生产部署指南，包含反向代理、HTTPS、防火墙和 token 轮换。
- 增加 Dashboard-only、Discord-only 和 full-stack 模式的 `.env.local.example` 示例。
- 增加不泄漏私有应用状态的健康检查 profile。
- 为 mobile 和 Dashboard 写 endpoint 增加限流。

## Phase 3：人格注册表

- 将人格 metadata 和风格规则迁移到 YAML/JSON。
- 使用 typed schema 校验人格配置。
- 支持不改核心聊天代码的多人格。
- 为现有沈知微默认配置增加迁移说明。

## Phase 4：记忆治理

- 增加显式保留策略控制。
- 增加带脱敏的记忆导出/导入。
- 为敏感记忆增加审核队列。
- 增加审计视图，展示哪些记忆影响了某次回复。

## Phase 5：学习工作流

- 已落地：共享日记 Dashboard/Mobile API，用于展示 day engine 产生的日常片段、用户回应、语音输入和复盘记录。
- 增加目标计划、学习 session、间隔复习和进度摘要。
- 增加附件到学习笔记的流程。
- 增加本地 analytics，用于关注 focus、cadence 和 streak，不默认云同步。

## Phase 6：iOS 成熟度

- 增加 server profile 管理。
- 增加 token 校验和连接诊断。
- 增加认证媒体缓存。
- 改进离线时间线体验。

## English fallback

This roadmap keeps Study Senpai useful as a local-first framework while preparing it for safer public collaboration.

Phase 1 focuses on safe open-source packaging: `.gitignore` hardening, mobile Bearer token auth, removal of hardcoded iOS URLs, README positioning, and baseline policy docs.

Phase 1.5 focuses on release acceptance and public face: pre-publish sensitive checks, README polish, demo recordings from clean fake data, GitHub templates, lightweight CI, and Chinese-first Markdown docs with English fallback.

Phase 2 hardens config and deployment. Phase 3 moves persona definitions into YAML/JSON. Phase 4 adds memory governance. Phase 5 expands study workflows. Phase 6 improves iOS maturity.
