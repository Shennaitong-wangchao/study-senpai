# 贡献指南 / Contributing

## 中文优先

感谢你帮助改进 Study Senpai。这个仓库仍处在早期阶段，包含本地优先陪伴系统、记忆、Discord、Dashboard 和 iOS 路径。请让贡献保持小而清晰，方便审阅和安全检查。

### 基本规则

- 不要提交 `.env`、SQLite 数据库、日志、聊天导出、Cookie、Token、生成媒体或本地 iOS 签名/配置文件。
- 不要把真实 API Key、Discord Token、Cookie、私有聊天记录或数据库内容贴到 issue、pull request 或测试中。
- 小修复里不要顺手改数据库 schema，除非该任务明确是 migration。
- 核心聊天和记忆行为的改动需要有聚焦测试覆盖。
- 除非任务明确要求，保留现有 Python 后端、Discord Bot、Dashboard 和 iOS 路径。

### 本地设置

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

仅开发 Dashboard/mobile 路径时可以使用：

```bash
RUN_DISCORD_BOT=false
DASHBOARD_ENABLED=true
```

### 检查

开 PR 前运行最小相关检查：

```bash
python3 -m pytest
python3 scripts/verify_product.py
python3 scripts/dashboard_contracts.py
python3 scripts/mobile_contracts.py
```

如果改了 Dashboard UI，也运行：

```bash
python3 scripts/dashboard_e2e.py
python3 scripts/dashboard_visual_regression.py
```

完整测试矩阵见 `docs/TESTING.md`。

### Pull Request

请说明：

- 改了什么，为什么改。
- 影响哪些路径：backend、Discord、Dashboard、mobile API、iOS、docs。
- 运行了哪些检查。
- 是否有隐私或部署影响。

### 人格改动

沈知微是默认示例人格。人格相关改动请保持隔离并写清楚。计划方向是 YAML/JSON 人格注册表，见 `docs/PERSONA_SYSTEM_PUBLIC.md`。

## English fallback

Thanks for improving Study Senpai. Keep contributions small, auditable, and privacy-aware.

Do not commit `.env`, SQLite databases, logs, exported chats, cookies, tokens, generated media, local iOS signing/config files, or real private data. Keep schema changes scoped, cover core chat/memory behavior with focused tests, and preserve existing backend, Discord, Dashboard, mobile API, and iOS paths unless the task explicitly changes them.

Local setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Before opening a PR, run the relevant checks and describe changed paths, verification, and any privacy or deployment impact.
