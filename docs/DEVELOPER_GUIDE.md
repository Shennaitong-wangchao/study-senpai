# 开发者上手指南 / Developer Guide

## 定位

Study Senpai 是本地优先的学习陪伴框架。核心路径是 Python + SQLite 后端、FastAPI Dashboard、Mobile API 和 SwiftUI iOS 客户端。默认人格“沈知微”只是示例产品行为，代码应保持可替换、可审计、可自托管。

## 本地环境

| 工具 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 后端、Dashboard、契约测试 |
| SQLite | Python 内置 | 本地状态持久化 |
| Xcode | 15+ 建议 | iOS 客户端开发 |

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

只开发 Dashboard 或 Mobile API 时，`.env` 可先使用：

```bash
RUN_DISCORD_BOT=false
DASHBOARD_ENABLED=true
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8099
LLM_API_KEY=dummy
LLM_MODEL=gpt-4.1-mini
```

启动：

```bash
python -m src.main
```

## 验证入口

```bash
python -m pytest
python scripts/mobile_contracts.py
python scripts/dashboard_contracts.py
python scripts/verify_product.py
```

如果改了 Dashboard UI，再运行：

```bash
python scripts/dashboard_e2e.py
python scripts/dashboard_visual_regression.py
```

## 架构速览

```text
Discord / iOS / Dashboard
        |
        v
src/services/companion_service.py
        |
        +--> src/llm/                 LLM 客户端与提示词构建
        +--> src/memory/              记忆提取、候选、检索、摘要
        +--> src/product/             主动消息、附件、现实锚点、健康与指标
        +--> src/dashboard/server.py  Dashboard 与 Mobile API
        v
SQLite database under data/
```

## 关键目录

| 路径 | 说明 |
|------|------|
| `src/core/` | 设置、日志、异常和共享类型 |
| `src/db/` | SQLite schema 初始化 |
| `src/memory/` | 长期记忆、候选记忆、事实、关系和摘要 |
| `src/product/` | 产品层能力：主动消息、day engine、附件、健康、指标 |
| `src/dashboard/` | FastAPI Dashboard、静态前端、Mobile API |
| `src/services/` | 会话编排、回复生成和记忆流程 |
| `ios/Lover/` | SwiftUI iOS 客户端 |
| `scripts/` | 合同检查、产品验收和视觉回归脚本 |
| `tests/` | pytest 回归测试 |

## 新增 Dashboard 面板的步骤

1. 在 `src/dashboard/server.py` 增加 API，优先复用 `PanelEnvelope`。
2. 如果数据来自 SQLite，使用 `_run_paged_select` 和参数绑定。
3. 在 `src/dashboard/templates/dashboard.html` 增加 Tab。
4. 在 `src/dashboard/static/dashboard.js` 增加 `state.panels`、`renderActivePanel` 分支和渲染函数。
5. 在 `scripts/dashboard_contracts.py` 和 `scripts/mobile_contracts.py` 加入响应模型校验。
6. 为关键行为补 `tests/` 下的 pytest。

## 共享日记面板

`shared_diary_entries` 由 day engine 写入，用于沉淀“她的一天”、用户回应、语音片段和复盘内容。现在 Dashboard 通过 `/api/shared-diary` 独立展示，移动端可通过 `/mobile/dashboard/shared-diary` 使用同一份面板数据。

支持筛选：

- `q`：搜索标题、内容、标签、来源和元信息。
- `entry_type`：例如 `day_event`、`day_response`、`voice_input`。
- `role_scope`：例如 `companion`、`user`、`shared`。
- `page` / `page_size`：分页。

## 安全注意

- 不提交 `.env`、数据库、日志、聊天导出、Cookie、Token、生成媒体或 iOS 签名文件。
- `/mobile/*` 在公网访问时必须设置 `MOBILE_API_TOKEN`。
- Dashboard 公网绑定必须开启认证，并设置 `DASHBOARD_PUBLIC_BIND_ACKNOWLEDGED=true`。
- UI 中渲染用户内容时必须经过 `escapeHtml` 或 DOM `textContent`。

## PR 自查

- 是否改动了数据库 schema；如果改了，是否有迁移和回归验证。
- 是否影响 Dashboard、Mobile API、Discord 或 iOS 任一路径。
- 是否补充了 pytest、contract 或产品验证。
- 是否更新 README、用户文档或运维文档。
- 是否引入新的隐私、认证、日志或部署风险。
