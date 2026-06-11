<div align="center">

# Study Senpai — 本地优先 AI 学习陪伴框架

**长期记忆 · 学习目标 · 间隔复习 · 主动关怀 · 完全自托管**

[![CI](https://github.com/Shennaitong-wangchao/study-senpai/actions/workflows/ci.yml/badge.svg)](https://github.com/Shennaitong-wangchao/study-senpai/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![SQLite](https://img.shields.io/badge/storage-SQLite-003B57.svg)](https://www.sqlite.org/)
[![FastAPI](https://img.shields.io/badge/dashboard-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Discord](https://img.shields.io/badge/runtime-Discord-5865F2.svg)](https://discord.com/)
[![iOS](https://img.shields.io/badge/client-iOS%20SwiftUI-000000.svg)](ios/Lover/)
[![Tests](https://img.shields.io/badge/tests-195%20passing-brightgreen.svg)](#开发与测试)

[English](#english-fallback) · [快速开始](#快速开始) · [功能特性](#功能特性) · [人格系统](#人格系统) · [架构](#架构) · [文档](#文档) · [贡献](#贡献)

</div>

---

Study Senpai 是一个**可自托管的 AI 学习陪伴系统**。它在本地运行，数据完全在你手里。搭配 Discord、Web 浏览器或 iOS App 使用，支持长期记忆、主动关怀、学习目标追踪和间隔复习。

你可以直接用内置的沈知微人格，也可以用 YAML 定义自己的 AI 伴侣，无需改任何核心代码。

---

## 功能特性

### 核心能力

| 功能 | 说明 |
|------|------|
| **长期记忆** | 自动提取会话记忆，按重要性分层存储，跨会话持续记住用户 |
| **主动关怀** | 定时主动发起关心消息，支持深夜安静模式和节奏管控 |
| **学习目标** | 创建学习目标，追踪进度，生成学习报告 |
| **间隔复习** | SM-2 算法闪卡系统，科学安排复习时间 |
| **多入口** | Discord Bot、Web Dashboard、iOS App、Mobile API 四端同步 |
| **YAML 人格** | 通过 YAML 定义完整人格，支持多人格注册表 |
| **记忆治理** | Dashboard 可审核候选记忆、导出备份、调整保留策略 |
| **现实感知** | 接入天气、日历，让 AI 的发言有真实时间和场景依据 |
| **附件理解** | 支持 PDF、Word、图片、音频文件分析 |

### 运行时

- **Discord Bot** — 在 Discord 频道直接聊天
- **Web Dashboard** — 浏览器中管理记忆、查看指标、审核候选记忆
- **Mobile API** — 供 iOS App 和第三方客户端调用的 REST API
- **iOS Client** — 原生 SwiftUI 应用，支持聊天、时间线、附件

### LLM 兼容性

支持任何 OpenAI 兼容的 API 端点：

| 提供商 | 设置方式 |
|--------|---------|
| OpenAI | `LLM_BASE_URL=https://api.openai.com/v1` |
| Anthropic Claude | `LLM_BASE_URL=https://api.anthropic.com/v1` |
| Ollama (本地) | `LLM_BASE_URL=http://localhost:11434/v1` |
| Groq | `LLM_BASE_URL=https://api.groq.com/openai/v1` |
| DeepSeek | `LLM_BASE_URL=https://api.deepseek.com/v1` |
| 任意 OpenAI 兼容 API | 设置 `LLM_BASE_URL` 即可 |

---

## 快速开始

### 方式一：Python 直接运行（推荐本地开发）

**前置要求：** Python 3.11+，任意 OpenAI 兼容 API Key

```bash
# 克隆仓库
git clone https://github.com/username/study-senpai.git
cd study-senpai

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置（只填你需要的）
cp .env.example .env
```

最小配置，只启动 Dashboard：

```env
LLM_API_KEY=your-api-key-here
LLM_MODEL=gpt-4.1-mini
RUN_DISCORD_BOT=false
DASHBOARD_ENABLED=true
```

```bash
# 启动
python3 -m src.main

# 打开 Dashboard
open http://127.0.0.1:8099
```

> 想快速看到完整的 Demo 效果（含学习数据）？用 `make seed-demo` 生成演示数据库，详见 [DEMO.md](DEMO.md)。

### 方式二：Docker（推荐生产部署）

```bash
# 复制配置
cp .env.example .env
# 编辑 .env 填入你的 API Key 和 Model

# 一键启动
docker compose up -d

# 查看日志
docker compose logs -f

# 打开 Dashboard
open http://127.0.0.1:8099
```

### 加入 Discord Bot

在 `.env` 中追加：

```env
RUN_DISCORD_BOT=true
DISCORD_BOT_TOKEN=your-discord-bot-token
```

然后重启服务。

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                         运行入口                              │
│  Discord Bot  │  Web Dashboard  │  iOS App  │  Mobile API   │
└───────┬───────┴────────┬────────┴─────┬─────┴───────┬───────┘
        │                │              │             │
        └────────────────┴──────────────┴─────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    CompanionService      │
                    │  - 消息写入 & Presence   │
                    │  - 回复规划 & LLM 调用   │
                    │  - 附件处理 & 搜索       │
                    └────────────┬────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
   ┌──────▼──────┐     ┌─────────▼────────┐    ┌───────▼───────┐
   │MemoryPipeline│    │  ReplyService    │    │ProductStore   │
   │ - 提取候选   │    │  - Prompt 构建   │    │ - 任务队列    │
   │ - 长期写入   │    │  - LLM 流式调用  │    │ - 可观测性    │
   │ - 会话摘要   │    │  - 备用模型降级  │    │ - 安全审计    │
   └──────┬──────┘    └──────────────────┘    └───────────────┘
          │
   ┌──────▼──────────────────────────────────────┐
   │              SQLite (本地存储)                 │
   │  messages · memories · facts · relationships │
   │  tasks · audit · diary · goals · review      │
   └─────────────────────────────────────────────┘
```

### 目录结构

```
src/
  core/          设置加载、日志、异常、共享类型
  db/            SQLite schema、迁移
  memory/        记忆提取、检索、写入、会话摘要
  persona/       人格系统（Python + YAML 注册表）
  services/      CompanionService、ReplyService、MemoryService
  bot/           Discord 客户端和消息路由
  dashboard/     FastAPI Dashboard + /mobile API
  llm/           LLM 客户端、Prompt 构建器
  product/       附件、Day Engine、Proactive、Health、学习系统
  mobile/        Mobile API Schema
personas/        YAML 人格注册表（可社区贡献）
ios/Lover/       SwiftUI iOS 客户端
scripts/         合同检查、冒烟测试、发布门禁
docs/            架构、路线图、运维手册、测试指南
```

---

## 人格系统

Study Senpai 使用 YAML 定义人格，无需修改核心代码：

```yaml
# personas/my_persona.yaml
name: 林晴
age: 20
school_role: 大二学姐
public_title: 活泼温柔的学习陪伴者
core_identity: |
  你是林晴，20岁，活泼开朗的理工科女生。
  你喜欢用清晰的逻辑帮别人理清思路，也喜欢在学习间隙聊聊轻松的话题。
tone: 活泼自然，偶尔俏皮，但认真起来非常靠谱
language: 默认使用中文，支持切换英文
# ... 其他字段
```

通过环境变量指定人格：

```env
PERSONA_FILE=personas/my_persona.yaml
```

内置人格（6 个，社区可贡献更多）：

| 文件 | 人格 | 风格 |
|------|------|------|
| `personas/shen_zhiwei.yaml` | 沈知微（默认） | 温柔克制、高三学姐 |
| `personas/study_buddy.yaml` | 林晓研 | 学术严谨、研究生助手 |
| `personas/english_coach.yaml` | Alex | 耐心风趣、英语口语教练 |
| `personas/code_mentor.yaml` | 林程远 | 务实引导、全栈代码导师 |
| `personas/history_teacher.yaml` | 史云飞教授 | 幽默博学、历史故事讲述者 |
| `personas/wellness_buddy.yaml` | 何悠悠 | 温暖细腻、健康生活伙伴 |

---

## Dashboard

> 运行在 `http://127.0.0.1:8099`，包含以下功能面板：

| 面板 | 功能 |
|------|------|
| **总览** | 会话、记忆、任务统计 |
| **💬 聊天** | 浏览器内直接对话 AI |
| **📚 学习** | 目标管理、SM-2 复习队列、统计卡片 |
| **长期记忆** | 记忆列表、归档/恢复、导出 |
| **候选记忆** | 批量审核 AI 提取的记忆 |
| **共享日记** | Day Engine 日记面板 |
| **她的一天** | AI 当日状态时间线 |
| **Turn Trace** | 每次对话的完整可观测性 |
| **主动消息** | 主动关怀发送历史 |
| **性能成本** | LLM 延迟、token 消耗 |
| **安全控制** | 登录审计、操作日志 |

---

## Discord 命令

在 Discord DM 中可使用文本命令：

```
/help          — 查看所有命令
/stats         — 学习统计（streak、今日复习等）
/goals         — 查看学习目标列表
/review        — 今日到期复习卡片
/addgoal <标题> | <学科>   — 添加学习目标
/addcard <问题> | <答案>   — 添加复习卡片
```

其他消息直接发给 AI 陪伴。

---

## 学习功能

### 学习目标

```bash
# 通过 Dashboard API 创建目标
curl -X POST http://localhost:8099/api/study/goals \
  -H "Content-Type: application/json" \
  -d '{"title": "高考数学备考", "subject": "数学", "target_date": "2026-06-07"}'
```

### 间隔复习（SM-2 算法）

```bash
# 添加复习卡片
curl -X POST http://localhost:8099/api/study/review/items \
  -d '{"front": "什么是导数的几何意义？", "back": "切线斜率", "subject": "数学"}'

# 获取今日到期卡片
curl http://localhost:8099/api/study/review

# 记录复习结果（quality 0-5）
curl -X POST http://localhost:8099/api/study/review/items/{uid}/result \
  -d '{"quality": 4}'
```

---

## 记忆治理

### 导出记忆备份

```bash
# 导出为 JSON（可用于迁移）
curl http://localhost:8099/api/memories/export?format=json -o memories_backup.json

# 导出为 Markdown（人类可读）
curl http://localhost:8099/api/memories/export?format=markdown -o memories.md
```

### 从备份导入

```bash
curl -X POST http://localhost:8099/api/memories/import \
  -F "file=@memories_backup.json"
```

---

## 部署指南

### 生产部署注意事项

1. **设置 `MOBILE_API_TOKEN`** — 保护 `/mobile/*` 端点
2. **启用 Dashboard Auth** — 设置强密码，避免公开暴露
3. **TLS 终止** — 使用 Nginx/Caddy 反向代理 + HTTPS
4. **备份 SQLite** — 定期备份 `data/` 目录

最小生产配置示例：

```env
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4.1-mini
RUN_DISCORD_BOT=false
DASHBOARD_ENABLED=true
DASHBOARD_HOST=127.0.0.1
DASHBOARD_AUTH_ENABLED=true
DASHBOARD_AUTH_USERNAME=admin
DASHBOARD_AUTH_PASSWORD=your-strong-password-here
MOBILE_API_TOKEN=your-mobile-token-here
```

详见 [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md) 和 [SECURITY.md](SECURITY.md)。

---

## iOS 配置

iOS App 在 `ios/Lover/` 目录。不包含硬编码的后端地址。

1. 在 iOS App **Settings** 中设置 **Server Base URL**
2. 如使用仓库默认端口：`http://127.0.0.1:8099`
3. 如果设置了 `MOBILE_API_TOKEN`，在 **Mobile API Token** 中填入相同的值

模拟器测试快捷启动：

```bash
DASHBOARD_PORT=8000 python3 -m src.main
```

---

## 环境变量参考

**LLM 配置**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | **必填** API Key |
| `LLM_MODEL` | — | **必填** 主模型名 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | API 基地址，支持任意 OpenAI 兼容端点 |
| `LLM_REPLY_MODEL_FAST` | — | 快速回复模型（覆盖主模型） |
| `LLM_REPLY_MODEL_THINKING` | — | 深思模式模型 |
| `LLM_BACKUP_MODEL` | — | 主模型失败时的备用模型 |
| `LLM_TIMEOUT_SECONDS` | `60` | LLM 请求超时 |

**人格**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PERSONA_FILE` | `personas/shen_zhiwei.yaml` | 人格 YAML 文件路径 |

**Dashboard 和 Mobile API**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHBOARD_ENABLED` | `true` | 启动 Dashboard |
| `DASHBOARD_HOST` | `127.0.0.1` | 绑定地址 |
| `DASHBOARD_PORT` | `8099` | 绑定端口 |
| `DASHBOARD_AUTH_ENABLED` | `true` | 启用登录认证 |
| `DASHBOARD_AUTH_USERNAME` | `admin` | 登录用户名 |
| `DASHBOARD_AUTH_PASSWORD` | 自动生成 | 登录密码 |
| `MOBILE_API_TOKEN` | — | `/mobile/*` Bearer Token |

**Discord**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RUN_DISCORD_BOT` | `true` | 启动 Discord Bot |
| `DISCORD_BOT_TOKEN` | — | Discord Bot Token |

**本地状态**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_PATH` | `data/shen_zhiwei.sqlite3` | SQLite 数据库路径 |
| `LOG_FILE_PATH` | `logs/shen_zhiwei.log` | 日志文件路径 |
| `BOT_TIMEZONE` | `Asia/Shanghai` | 时区 |

完整变量列表见 [.env.example](.env.example)。

---

## 开发与测试

```bash
# 运行测试
python3 -m pytest

# 合同检查
python3 scripts/release_gate.py
python3 scripts/mobile_contracts.py
python3 scripts/dashboard_contracts.py
python3 scripts/verify_product.py

# 质量分析
python3 scripts/quality_triage.py
```

详细测试矩阵见 [docs/TESTING.md](docs/TESTING.md)。
开发者上手指南见 [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)。

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构和数据流 |
| [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) | 本地开发设置和常见改动路径 |
| [docs/TESTING.md](docs/TESTING.md) | 测试矩阵和测试规范 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 功能路线图 |
| [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md) | 生产运维手册 |
| [docs/QUALITY_BASELINE.md](docs/QUALITY_BASELINE.md) | 发布门禁和质量基线 |
| [docs/PERSONA_SYSTEM_PUBLIC.md](docs/PERSONA_SYSTEM_PUBLIC.md) | 人格系统设计文档 |
| [USER_GUIDE.md](USER_GUIDE.md) | 用户使用指南 |
| [SECURITY.md](SECURITY.md) | 安全和隐私说明 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献指南 |

---

## 贡献

欢迎贡献！特别期待以下方向：

- **新人格** — 在 `personas/` 下提交 YAML 人格文件
- **LLM 提供商** — 测试并记录新的兼容提供商
- **iOS 功能** — 改进 `ios/Lover/` 客户端
- **Dashboard UI** — 改进 `src/dashboard/` 界面

请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

```bash
# 贡献流程
fork → git clone → python3 -m venv .venv → pip install -r requirements.txt
→ 改动 → python3 -m pytest → PR
```

---

## 安全与隐私

- Study Senpai 是本地优先、自托管的项目
- 数据不离开你的机器（除非 LLM API 调用）
- `.env`、SQLite、日志、聊天数据默认被 `.gitignore` 忽略
- 请阅读 [SECURITY.md](SECURITY.md) 再进行公网部署

---

## 许可证

[MIT License](LICENSE) — 自由使用、修改、部署。

---

## English fallback

Study Senpai is a **self-hosted, local-first AI companion framework** for learning and long-term memory. It runs entirely on your machine with data under your control.

**Key features:** long-term memory across sessions, proactive check-ins, study goal tracking, spaced repetition (SM-2), YAML persona registry, Discord bot + Web Dashboard + iOS client, and compatibility with any OpenAI-compatible LLM API.

**Quick start:**

```bash
git clone https://github.com/username/study-senpai.git && cd study-senpai
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # set LLM_API_KEY and LLM_MODEL
python3 -m src.main
# open http://127.0.0.1:8099
```

Or with Docker:

```bash
cp .env.example .env  # fill in LLM_API_KEY and LLM_MODEL
docker compose up -d
```

See the Chinese sections above for full documentation — all docs include English fallback sections.

**Custom personas** — drop a YAML file in `personas/` and set `PERSONA_FILE=personas/my_persona.yaml`. No code changes needed.

**LLM providers** — works with OpenAI, Anthropic, Ollama (local), Groq, DeepSeek, or any OpenAI-compatible endpoint via `LLM_BASE_URL`.

[Architecture](#架构) · [Deployment](#部署指南) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [License](LICENSE)
