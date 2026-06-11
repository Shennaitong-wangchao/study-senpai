# 快速演示指南 / Quick Demo Guide

Study Senpai 五分钟体验指南——无需真实 API Key，用演示数据快速上手。

---

## 方式一：本地 Python（推荐）

```bash
# 1. 克隆并安装
git clone https://github.com/Shennaitong-wangchao/study-senpai.git
cd study-senpai
make install
cp .env.example .env

# 2. 编辑 .env，设置 LLM（可用 Ollama 实现完全免费本地运行）
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=qwen2.5:7b
# LLM_API_KEY=ollama
# RUN_DISCORD_BOT=false

# 3. 生成演示数据（可选，有真实感的示例数据）
make seed-demo

# 4. 启动（使用演示数据库）
DATABASE_PATH=data/demo.sqlite3 make dev

# 5. 打开 Dashboard
open http://127.0.0.1:8099
```

---

## 方式二：Docker

```bash
git clone https://github.com/Shennaitong-wangchao/study-senpai.git
cd study-senpai
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY 和 LLM_MODEL
docker compose up -d
open http://127.0.0.1:8099
```

---

## Dashboard 功能导览

打开 `http://127.0.0.1:8099` 后，按以下顺序探索：

### 1. 总览页（Overview）
- 查看系统统计：会话数、记忆数、任务队列状态
- 如果使用了演示数据，会看到学习统计（连续天数、今日复习数）

### 2. 💬 聊天页（Web Chat）
- 直接在浏览器中发送消息给 AI
- 支持 Markdown 渲染（代码块、加粗、列表）
- 点击"加载历史"查看演示对话

### 3. 📚 学习页（Study）
- 查看演示数据生成的三个学习目标及进度
- 今日复习卡片（SM-2 算法，到期的会显示）
- 点"查看答案"，然后评分（0-5），卡片会自动安排下次复习

### 4. 长期记忆页（Memories）
- 10 条演示记忆，包含学习习惯、情感状态、承诺记录
- 可以导出为 JSON 或 Markdown

### 5. 候选记忆页（Candidates）
- 2 条待审核的候选记忆（AI 提取但尚未确认）
- 点"批准"→ 进入长期记忆；点"拒绝"→ 丢弃

---

## API 探索

Dashboard 内置 OpenAPI 文档：

```
http://127.0.0.1:8099/api/docs    # Swagger UI
http://127.0.0.1:8099/api/redoc   # ReDoc 格式
```

### 快速 API 示例

```bash
# 获取系统概览
curl http://localhost:8099/api/overview

# 获取长期记忆列表
curl http://localhost:8099/api/memories

# 查看学习统计
curl http://localhost:8099/api/study/stats

# 今日复习卡片
curl http://localhost:8099/api/study/review

# 导出记忆备份
curl http://localhost:8099/api/memories/export?format=json > backup.json
```

---

## Discord 命令演示

如果启动了 Discord Bot（`RUN_DISCORD_BOT=true`），在 DM 中发送：

```
/help          查看所有命令
/stats         学习统计
/goals         目标列表
/review        今日复习
/addgoal 高考数学 | 数学
/addcard 导数几何意义？ | 切线斜率
```

---

## 配置不同人格

```bash
# 切换到英语教练
PERSONA_FILE=personas/english_coach.yaml DATABASE_PATH=data/demo.sqlite3 make dev

# 查看所有可用人格
python3 -c "from src.persona.registry import list_available_personas; print(list_available_personas())"
```

---

## 清理演示数据

```bash
rm -f data/demo.sqlite3 data/demo.sqlite3-wal data/demo.sqlite3-shm
```

---

## English fallback

Quick demo in 5 minutes: `make install && cp .env.example .env` → set `LLM_API_KEY`, `LLM_MODEL`, `RUN_DISCORD_BOT=false` → `make seed-demo && DATABASE_PATH=data/demo.sqlite3 make dev` → open `http://127.0.0.1:8099`.

**Key demo pages:** Overview (stats + study data), 💬 Chat (browser AI chat with Markdown), 📚 Study (goals + SM-2 review), Memories (10 sample memories), Candidates (2 pending review).

**API docs:** `http://127.0.0.1:8099/api/docs` (Swagger UI).
