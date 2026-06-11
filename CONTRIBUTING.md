# 贡献指南 / Contributing

## 中文优先

欢迎贡献 Study Senpai！这份指南帮你快速上手，让贡献保持安全、可审计。

## 目录

- [快速开始](#快速开始)
- [贡献类型](#贡献类型)
- [安全规则](#安全规则)
- [开发流程](#开发流程)
- [测试要求](#测试要求)
- [Pull Request 指引](#pull-request-指引)

---

## 快速开始

```bash
git clone https://github.com/username/study-senpai.git
cd study-senpai

# 安装依赖（或用 make install）
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 配置（只填你需要的）
cp .env.example .env
# 设置 LLM_API_KEY 和 LLM_MODEL

# 启动开发服务器（或用 make dev）
python3 -m src.main
```

运行测试：

```bash
make test        # 全量测试
make check       # 全量质量检查
make lint        # 仅 lint
```

---

## 贡献类型

### 人格贡献（最欢迎！）

在 `personas/` 目录下创建 YAML 文件，参考 `personas/schema.yaml` 格式：

```bash
# 验证人格格式
python3 -c "from src.persona.registry import load_persona; p = load_persona('personas/my_persona.yaml'); print('OK:', p.name)"
```

不需要改任何核心代码，只提交 YAML 文件即可。

### Bug 修复

1. 确认问题可复现
2. 写测试覆盖修复
3. 只改必要的代码，不顺手重构

### 新功能

1. 先开 Issue 讨论，避免白做
2. 保持改动小而聚焦
3. 覆盖核心行为的测试是必需的

### 文档改进

- `docs/` 目录下的文档
- README.md 改进
- 代码注释

### iOS 客户端

`ios/Lover/` 是 SwiftUI 项目。iOS 变更需要额外说明 Xcode 版本和测试设备。

---

## 安全规则

**绝对不要提交：**

- `.env` 文件或任何包含真实 API Key、Token 的文件
- SQLite 数据库文件（`*.sqlite3`、`*.sqlite3-wal`）
- 真实聊天记录、私人对话截图
- Discord Bot Token、Cookie 等认证凭据
- iOS 签名文件、provisioning profile

**测试和示例中：**

- 只使用假数据（fake IDs、占位文本）
- 不要粘贴真实的 LLM 响应或对话内容

**改 schema 时：**

- 迁移必须是幂等的（`CREATE TABLE IF NOT EXISTS`）
- 新列有默认值
- 单独 PR，不与功能混搭

---

## 开发流程

### 改动路径

| 改什么 | 主要文件 |
|--------|---------|
| 人格系统 | `personas/*.yaml`, `src/persona/` |
| LLM 调用 | `src/llm/` |
| 记忆提取 | `src/memory/` |
| Dashboard UI | `src/dashboard/server.py`, `src/dashboard/static/`, `src/dashboard/templates/` |
| Mobile API | `src/dashboard/server.py` 中的 `/mobile/*` 路由, `src/mobile/schemas.py` |
| 后台任务 | `src/product/tasks.py`, `src/product/store.py` |
| 数据库 schema | `src/db/schema.py`, `src/db/migrations.py` |
| iOS 客户端 | `ios/Lover/` |
| 配置 | `src/core/settings.py`, `.env.example` |

### 分支命名

```
feature/add-persona-voice-style
fix/memory-extraction-timeout
docs/add-ollama-guide
```

---

## 测试要求

新功能需要对应测试。改动核心行为（记忆、回复、认证）时测试是必需的，不是可选的。

```bash
# 运行全量测试
python3 -m pytest

# 运行合同检查
python3 scripts/release_gate.py
python3 scripts/mobile_contracts.py
python3 scripts/dashboard_contracts.py
python3 scripts/verify_product.py
```

测试规范见 [docs/TESTING.md](docs/TESTING.md)。

**测试 fixtures 注意事项：**

- 用 `tmp_path` 创建临时数据库，不要使用真实数据库
- `dashboard_context` fixture 使用 `FakeLLMClient`，不要发出真实 LLM 请求
- 示例 user_id 用 `"user-test-1"` 格式，conversation_id 用 `"conv-test-1"` 格式

---

## Pull Request 指引

### PR 清单

开 PR 前确认：

- [ ] `python3 -m pytest` 全部通过
- [ ] `python3 scripts/release_gate.py` 通过（无敏感文件泄露）
- [ ] 没有提交真实数据、API Key 或私有截图
- [ ] 如果改了 schema，迁移是幂等的
- [ ] 如果改了核心聊天行为，有对应测试

### PR 描述应包含

- 改了什么以及为什么
- 影响哪些路径（backend、Discord、Dashboard、mobile API、iOS、docs）
- 运行了哪些检查
- 是否有隐私或部署影响

---

## English fallback

Thanks for contributing to Study Senpai. Keep contributions small, auditable, and privacy-aware.

**Most welcome:** YAML persona files in `personas/` — no core code change needed, just drop a YAML file and open a PR.

**Hard rules:** No `.env`, SQLite databases, real API keys, real chat logs, or private screenshots. Use fake data in all tests and examples.

**Quick start:** Fork → clone → `make install` → `cp .env.example .env` → set `LLM_API_KEY` + `LLM_MODEL` → `make dev`.

**Before opening a PR:** `make check` must pass. Describe what changed and why.

See [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) for detailed setup and change paths.
See [docs/QUALITY_BASELINE.md](docs/QUALITY_BASELINE.md) for the release baseline and known static-analysis noise.
