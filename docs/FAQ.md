# 常见问题 / FAQ

## 中文优先

---

## 安装和配置

### Q: 必须用 OpenAI 吗？

不。支持任何 OpenAI 兼容 API 端点，包括：

- **完全本地运行**：[Ollama](https://ollama.ai) + llama3/qwen2.5（无需 API Key）
- **国内快速访问**：DeepSeek、SiliconFlow、Moonshot
- **其他云服务**：Groq、Anthropic Claude

设置 `LLM_BASE_URL` 和 `LLM_MODEL` 即可切换，详见 [docs/LLM_PROVIDERS.md](LLM_PROVIDERS.md)。

---

### Q: 启动时报 "Missing required environment variables" 怎么办？

检查 `.env` 文件是否存在，以及是否设置了 `LLM_API_KEY` 和 `LLM_MODEL`：

```bash
cp .env.example .env
# 编辑 .env 文件，至少填写：
# LLM_API_KEY=your-key-here
# LLM_MODEL=gpt-4.1-mini
# RUN_DISCORD_BOT=false  （如果不用 Discord）
```

如果只启动 Dashboard，还需要设置 `RUN_DISCORD_BOT=false`（否则也会要求 Discord Token）。

---

### Q: Dashboard 密码在哪里？

首次启动时，如果没有设置 `DASHBOARD_AUTH_PASSWORD`，系统会自动生成一个密码并写入 `data/dashboard_bootstrap_password.txt`。

```bash
cat data/dashboard_bootstrap_password.txt
```

建议登录后立即修改密码（Dashboard 右上角）。

---

### Q: MOBILE_API_TOKEN 是什么？什么时候需要设置？

`MOBILE_API_TOKEN` 是保护 `/mobile/*` API 端点的 Bearer Token，主要供 iOS App 使用。

- **只在本机测试**：不需要设置，localhost 请求默认允许通过
- **iOS App 连接本机**：不需要设置
- **公网部署 + iOS**：必须设置，然后在 iOS App Settings 中填入相同的值
- **只用 Dashboard**：不需要设置

---

### Q: 如何更换人格（Persona）？

创建 YAML 人格文件，然后在 `.env` 中指定：

```bash
# 使用内置的学术型助手人格
PERSONA_FILE=personas/study_buddy.yaml

# 使用自定义人格
PERSONA_FILE=personas/my_persona.yaml
```

参考 `personas/schema.yaml` 格式创建自定义人格，`personas/shen_zhiwei.yaml` 是完整示例。

---

## 功能使用

### Q: AI 为什么不记得之前说过的话？

可能的原因：

1. **候选记忆未审核**：AI 提取了记忆但需要你在 Dashboard 审核批准（打开 Dashboard → "候选记忆" 标签页）
2. **会话超时**：`SESSION_TIMEOUT_MINUTES` 默认 180 分钟，超时后会话重置
3. **记忆提取还在队列**：后台任务处理有延迟，等待几秒后刷新

快速验证：打开 Dashboard → "长期记忆" 标签页，看是否有相关记忆。

---

### Q: 间隔复习卡片怎么用？

通过 Dashboard API 或 HTTP 请求使用：

```bash
# 添加卡片
curl -X POST http://localhost:8099/api/study/review/items \
  -H "Content-Type: application/json" \
  -d '{"front": "牛顿第一定律内容?", "back": "惯性定律：物体保持静止或匀速运动的状态", "subject": "物理"}'

# 获取今日到期卡片
curl http://localhost:8099/api/study/review

# 记录复习结果（quality: 0=完全忘了, 3=记住了, 5=完美）
curl -X POST http://localhost:8099/api/study/review/items/{item_uid}/result \
  -d '{"quality": 4}'
```

系统使用 SM-2 算法自动计算下次复习时间。quality 越高，间隔越长。

---

### Q: 可以导入之前的聊天记录吗？

不能直接导入聊天消息，但可以导入**记忆摘要**（从别处导出的 JSON 格式）：

```bash
# 导出
curl http://localhost:8099/api/memories/export?format=json -o backup.json

# 导入（到新实例）
curl -X POST http://localhost:8099/api/memories/import -F "file=@backup.json"
```

---

### Q: Discord Bot 不响应怎么办？

常见原因：

1. **Bot Token 错误**：检查 `DISCORD_BOT_TOKEN` 是否正确
2. **Bot 没有权限**：确保 Bot 有 `Read Messages` 和 `Send Messages` 权限
3. **频道限制**：如果设置了 `ALLOWED_CHANNEL_IDS`，Bot 只在指定频道响应
4. **服务未运行**：检查 `RUN_DISCORD_BOT=true` 是否已设置

查看日志：

```bash
tail -f logs/shen_zhiwei.log | grep -i discord
```

---

### Q: 主动消息（Proactive）如何工作？

AI 会在以下条件满足时主动发送消息：

- 用户超过 `PROACTIVE_IDLE_HOURS`（默认 18 小时）没有对话
- 满足时间窗口（非深夜）
- 距上次主动消息超过 `PROACTIVE_MIN_INTERVAL_MINUTES`

在 Dashboard "主动消息" 标签页可以查看发送记录，在"主动偏好"设置中可以调整频率或关闭。

---

## 隐私和安全

### Q: 数据存在哪里？会上传吗？

所有数据存储在本地 `data/` 目录的 SQLite 文件中，**不会**主动上传到任何云端。

唯一离开本机的数据：调用 LLM API 时发送的**当前对话上下文**（包含相关记忆摘要）。这是功能运行的必要开销。

---

### Q: 可以完全离线运行吗？

可以，配合 [Ollama](https://ollama.ai) 在本机运行 LLM：

```bash
# 安装 Ollama 并下载模型
ollama pull qwen2.5:7b

# 配置 .env
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=ollama  # 任意非空字符串
```

---

### Q: 如何彻底删除所有数据？

```bash
# 停止服务
# 删除数据库文件
rm -f data/*.sqlite3 data/*.sqlite3-wal data/*.sqlite3-shm
# 删除日志
rm -f logs/*.log
```

重启后会创建新的空数据库。

---

## 部署

### Q: Docker 和 Python 直接运行哪个更好？

| 场景 | 推荐 |
|------|------|
| 本地开发、快速试用 | Python 直接运行 |
| 长期运行（服务器） | Docker |
| 想要自动重启 | Docker 或 systemd |
| 多实例部署 | Docker Compose |

---

### Q: 如何让家人或朋友也能用？

当前版本是单实例设计，最简单方式是为每人部署一套独立实例。

公网暴露前**必须**：
1. 设置强密码 `DASHBOARD_AUTH_PASSWORD`
2. 设置 `MOBILE_API_TOKEN`
3. 反向代理 + HTTPS（见 [docs/DEPLOYMENT.md](DEPLOYMENT.md)）
4. 设置防火墙

---

### Q: 如何备份数据？

```bash
# 简单备份
cp data/shen_zhiwei.sqlite3 backups/shen_zhiwei_$(date +%Y%m%d).sqlite3

# 自动每日备份（cron）
0 2 * * * cp /path/to/data/shen_zhiwei.sqlite3 /path/to/backups/shen_zhiwei_$(date +\%Y\%m\%d).sqlite3
```

详见 [docs/SQLITE_BACKUP_AND_RECOVERY.md](SQLITE_BACKUP_AND_RECOVERY.md)。

---

## English fallback

**Quick answers:**

- **Do I need OpenAI?** No — works with Ollama (local), Groq, DeepSeek, or any OpenAI-compatible API.
- **Where is my data?** Local SQLite in `data/`. Only LLM API calls leave the machine.
- **AI doesn't remember?** Check Dashboard → Candidates tab — memories need review approval.
- **Change persona?** Create a YAML file in `personas/`, set `PERSONA_FILE=personas/my.yaml`.
- **Offline mode?** Yes — use Ollama locally: `LLM_BASE_URL=http://localhost:11434/v1`.

See [docs/DEPLOYMENT.md](DEPLOYMENT.md) for production setup.
See [docs/LLM_PROVIDERS.md](LLM_PROVIDERS.md) for provider-specific configuration.
