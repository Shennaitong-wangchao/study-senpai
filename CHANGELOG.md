# 更新日志 / Changelog

## 中文优先

所有值得记录的 Study Senpai 变更都会写在这里。

---

## v0.2.0 — 未发布（开发中）

### 核心新功能（第一波）

- **Persona YAML 注册表**：人格定义 YAML 化，6 个内置人格（沈知微、学术助手、英语教练、代码导师、历史教授、健康伙伴）。
- **Docker 支持**：`docker compose up -d` 一键部署，含健康检查和持久化 volume。
- **内置 Web Chat UI**：Dashboard `💬 聊天` 标签页，浏览器直接对话，Markdown 渲染，消息历史加载。
- **记忆导出/导入**：JSON/Markdown 格式导出，content 去重导入。
- **学习目标 + SM-2 间隔复习**：完整学习系统，7 个 REST 端点。
- **Discord 文本命令**：`/help /goals /review /stats /addgoal /addcard /plan /start /done`。
- **每日学习摘要**：本地计算，后台 Discord DM 推送。

### 核心新功能（第二波）

- **学习计划生成器**：基于目标日期自动计算紧迫度（low/medium/high/critical），生成每日学习计划。
- **Anki 闪卡导入/导出**：TSV 格式兼容 Anki，支持批量导入海量闪卡资源。
- **学习热力图数据 API**：90 天日历热力图数据（GitHub 贡献图风格）。
- **学科分布统计**：按学科统计卡片数量和掌握情况。
- **成就系统**：13 个成就（streak/掌握/目标/时长），Dashboard 可视化展示。
- **记忆关系图谱**：节点+边数据，基于 category/tags/content 自动计算关系权重。
- **WebSocket 实时通知**：断线自动重连，toast 通知支持多种消息类型。
- **Dashboard 键盘快捷键**：`g+h/m/s/c/t/p`，`/` 聚焦搜索，`Esc` 清空。
- **高级记忆搜索过滤**：`min_importance`, `min_confidence`, `tags`, `created_after/before`。
- **API 速率限制**：滑动窗口 120 req/60s，保护写操作端点。
- **演示数据生成器**：`make seed-demo` 生成逼真的演示数据库。

### CI/CD 和工程

- GitHub Actions 扩展：Python 3.11 + 3.12 矩阵、ruff lint、TruffleHog 密钥扫描、Docker 构建验证、测试覆盖率报告。
- `release.yml`：测试 → Docker 推送 → GitHub Release 自动化（`v*.*.*` tag 触发）。
- `Makefile`：`install-dev/test-cov/lint-fix/type-check/seed-demo/docker-restart/release` 目标。
- `scripts/tag_release.sh`：本地打 tag 辅助脚本。
- `scripts/migrate_from_v01.py`：数据库迁移脚本。
- FastAPI OpenAPI 文档：`/api/docs`、`/api/redoc`。
- `.github/CODEOWNERS`、`.github/FUNDING.yml`。

### 文档

- README 全面重写：Badge（指向真实仓库）、6 人格展示表、Discord 命令表、Dashboard 面板表、架构图、快速开始。
- 新增：`DEMO.md`（5 分钟快速体验）、`docs/FAQ.md`、`docs/PRIVACY.md`、`docs/DEPLOYMENT.md`、`docs/LLM_PROVIDERS.md`。
- 新增：`personas/PERSONAS.md`（人格画廊）。
- 更新：`USER_GUIDE.md`（v0.2.0 速查）、`docs/ROADMAP.md`、`docs/PERSONA_SYSTEM_PUBLIC.md`、`CONTRIBUTING.md`、`SECURITY.md`。

### 测试

- **总测试数：332 个全部通过**（v0.1.x 基线：93 个）
- 新增测试文件：
  - `test_persona_registry.py`（42）
  - `test_memory_export_import.py`（13）
  - `test_study_system.py`（36）
  - `test_discord_commands.py`（11）
  - `test_study_summary.py`（37）
  - `test_memory_advanced_filter.py`（12）
  - `test_study_plan.py`（37）
  - `test_study_anki.py`（20）
  - `test_study_visualization.py`（17）
  - `test_memory_graph.py`（14）

---

## v0.1.x — 已发布基线

见 GitHub 提交历史。

---

## English fallback

**v0.2.0 highlights:** Persona YAML registry (6 built-in), Docker, Web Chat (Markdown), memory export/import, study system (goals + SM-2 + Anki import/export), Discord text commands (9 commands), daily study summary, study plan generator, achievement system (13 achievements), memory graph API, WebSocket notifications, Dashboard keyboard shortcuts, advanced memory filters, rate limiting, demo seeder, 100+ improvements. **332 tests all passing.**


## 中文优先

所有值得记录的 Study Senpai 变更都会写在这里。

---

## v0.2.0 — 未发布（开发中）

### 核心新功能

- **Persona YAML 注册表**：人格定义从 Python 代码迁移到 YAML 文件，支持多人格，无需改核心代码。通过 `PERSONA_FILE` 环境变量切换。内置 6 个人格（沈知微、学术助手、英语教练、代码导师、历史教授、健康伙伴）。
- **Docker 支持**：多阶段 `Dockerfile`、`docker-compose.yml`，`docker compose up -d` 一键部署，含健康检查和持久化 volume。
- **内置 Web Chat UI**：Dashboard `💬 聊天` 标签页，浏览器直接与 AI 对话，支持 Markdown 渲染、消息历史加载、流式打字机效果。
- **记忆导出/导入**：`GET /api/memories/export`（JSON/Markdown）和 `POST /api/memories/import`（按 content 去重）。
- **学习目标 + SM-2 间隔复习**：`study_goals`、`review_items`、`study_sessions` 三张新表，7 个 REST 端点（`/api/study/*`），SM-2 算法自动调度复习时间。
- **Discord 文本命令**：在 DM 中支持 `/help`、`/goals`、`/review`、`/stats`、`/addgoal`、`/addcard`。
- **每日学习摘要**：本地计算每日摘要（复习数、连续天数、成就），可通过 `/api/study/summary` 获取，后台任务自动发送 Discord DM。
- **Dashboard 学习面板**（`📚 学习`）：目标管理、复习队列、统计卡片，支持内联添加目标和卡片，复习结果一键记录。

### CI/CD 和工程

- GitHub Actions 扩展：Python 3.11 + 3.12 矩阵、ruff lint、TruffleHog 密钥扫描、Docker 构建验证。
- 新增 `release.yml`：测试 → Docker 推送 → GitHub Release 自动化（`v*.*.*` tag 触发）。
- 新增 `pr-checks.yml`：PR 强制 ruff lint 检查。
- `Makefile`：`install/dev/test/lint/check/docker-*` 目标。
- `scripts/tag_release.sh`：本地打 tag 辅助脚本。
- FastAPI OpenAPI 文档：`/api/docs` 和 `/api/redoc`。

### 文档

- README 全面重写：Badge、功能表、架构图、Docker 快速开始、LLM 兼容性表、环境变量参考、Discord 命令说明、Persona 展示。
- 新增文档：`docs/FAQ.md`、`docs/PRIVACY.md`、`docs/DEPLOYMENT.md`、`docs/LLM_PROVIDERS.md`。
- 更新文档：`docs/ROADMAP.md`、`docs/PERSONA_SYSTEM_PUBLIC.md`、`CONTRIBUTING.md`。
- Persona 贡献 issue 模板：`.github/ISSUE_TEMPLATE/persona_contribution.md`。

### 测试

- 总测试数：**232 个全部通过**（v0.1.x 基线：93 个）
- 新增测试文件：
  - `test_persona_registry.py`（42 个）
  - `test_memory_export_import.py`（13 个）
  - `test_study_system.py`（36 个）
  - `test_discord_commands.py`（11 个）
  - `test_study_summary.py`（37 个）

---

## v0.1.x — 已发布基线

- Python 后端 + SQLite 持久化。
- FastAPI Dashboard（审核、可观测性、记忆治理）。
- Discord Bot 运行时。
- Mobile API（iOS + 第三方客户端）。
- SwiftUI iOS 客户端。
- 长期记忆自动提取、候选审核。
- 共享日记 Dashboard/Mobile API 面板。
- 主动关怀消息（ProactiveMessageService）。
- CompanionDayEngine（AI 日常状态）。
- RealityContextService（天气/日历感知）。
- 附件分析（PDF、Word、图片、音频）。
- 后台任务管理器。
- Dashboard 安全认证（CSRF、登录锁定、审计日志）。
- CI 工作流（轻量测试 + 合同检查）。

---

## English fallback

All notable Study Senpai changes are documented here.

**v0.2.0 (unreleased):** Persona YAML registry (6 built-in), Docker, Web Chat UI with Markdown, memory export/import, learning goals + SM-2 spaced repetition, Discord text commands (/goals /review /stats /addgoal /addcard), daily study summary, Dashboard Study panel, CI matrix (3.11+3.12), release automation, 5 new docs files. **232 tests all passing.**

**v0.1.x baseline:** Python backend, SQLite, Dashboard, Discord bot, iOS client, memory pipeline, proactive messaging, day engine, reality context, attachments, background tasks, dashboard auth.
