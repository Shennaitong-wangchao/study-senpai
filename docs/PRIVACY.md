# 隐私和数据说明 / Privacy & Data

## 中文优先

Study Senpai 是本地优先、自托管的项目，你对数据有完全控制权。

---

## 数据存储在哪里

所有数据存储在本地 SQLite 数据库（默认路径：`data/shen_zhiwei.sqlite3`）。

| 数据类型 | 存储位置 | 是否离开本机 |
|---------|---------|------------|
| 聊天消息 | 本地 SQLite | 否 |
| 长期记忆 | 本地 SQLite | 否（作为 LLM 上下文时会发送摘要） |
| 结构化事实 | 本地 SQLite | 否 |
| 学习目标 / 复习卡片 | 本地 SQLite | 否 |
| 日志文件 | 本地 `logs/` | 否 |
| Dashboard 审计日志 | 本地 SQLite | 否 |

---

## 什么数据会发送给 LLM API

每次 AI 回复时，系统会向配置的 LLM 服务发送：

- 当前消息的内容
- 最近 N 条历史消息（受 `HISTORY_MESSAGE_LIMIT` 控制）
- 相关长期记忆摘要（受 `LONG_TERM_MEMORY_LIMIT` 控制）
- 结构化事实摘要（受 `FACT_LIMIT` 控制）
- 关系状态摘要
- 当前 Day Engine 状态（如启用）
- 现实上下文（天气/日历，如启用）

**这是功能运行的必要开销**，无法避免（除非完全离线使用 Ollama）。

### 减少发送数据量的配置

```env
HISTORY_MESSAGE_LIMIT=8        # 减少历史消息条数
LONG_TERM_MEMORY_LIMIT=4       # 减少发送的记忆数
FACT_LIMIT=6                   # 减少发送的事实数
REALITY_CONTEXT_ENABLED=false  # 关闭天气/日历上下文
```

---

## 使用完全离线模式

配合 [Ollama](https://ollama.ai) 可以完全不连接外部网络：

```bash
ollama pull qwen2.5:7b  # 或其他模型
```

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=ollama
```

---

## 审计 AI 使用了哪些记忆

在 Dashboard 中可以审计：

1. **Turn Trace**（`/api/turns`）- 查看每次对话的完整 Prompt 上下文（如启用 `DEBUG_PROMPTS`）
2. **长期记忆**（`/api/memories`）- 查看所有记忆及其命中次数
3. **候选记忆**（`/api/candidates`）- 审核 AI 提取的候选记忆，可拒绝不合适的
4. **审计日志**（`/api/audits`）- 查看所有 Dashboard 操作记录

---

## 导出和删除数据

### 导出记忆备份

```bash
# JSON 格式（可导入到其他实例）
curl http://localhost:8099/api/memories/export?format=json -o memories_backup.json

# Markdown 格式（人类可读）
curl http://localhost:8099/api/memories/export?format=markdown -o memories.md
```

### 删除所有数据

```bash
# 停止服务后
rm -f data/*.sqlite3 data/*.sqlite3-wal data/*.sqlite3-shm
rm -f logs/*.log
rm -f data/dashboard_bootstrap_password.txt
```

重启后数据库会重新初始化（空白状态）。

---

## 公网部署的隐私风险

将 Study Senpai 暴露到公网时需要额外注意：

| 风险 | 缓解措施 |
|------|---------|
| Dashboard 被未授权访问 | 强密码 + Dashboard Auth |
| Mobile API 被滥用 | 设置 `MOBILE_API_TOKEN` |
| 传输中数据被截获 | HTTPS（反向代理 + TLS）|
| 日志文件泄露 | 合理设置文件权限（chmod 600）|

---

## GDPR 适用性

Study Senpai 是自托管项目，用户即数据控制者。项目本身不收集、不处理、不存储任何遥测数据。

如果你在为第三方用户部署（如为朋友搭建），则你作为数据控制者，需要遵守适用的隐私法规。

---

## 与云端 AI 服务的对比

| 特性 | Study Senpai（自托管） | 云端 AI 服务 |
|------|---------------------|------------|
| 数据存储位置 | 你的机器 | 服务商服务器 |
| 聊天记录归属 | 你 | 服务条款决定 |
| 数据用于训练 | 不（除非你主动上传） | 服务条款决定 |
| 访问控制 | 你完全控制 | 服务商账号体系 |
| 删除权 | 随时删除 | 需要申请 |
| 离线使用 | 支持（Ollama） | 不支持 |
| 成本 | API 调用费（或免费 Ollama） | 订阅费 |

---

## English fallback

**Where is data stored?** Local SQLite at `data/shen_zhiwei.sqlite3`. Never auto-uploaded anywhere.

**What leaves the machine?** Only LLM API calls — current message + recent history + relevant memory summaries. Fully offline mode is possible with Ollama.

**Audit memory usage:** Dashboard → Turn Trace (see full prompt context), Memories tab (hit counts), Candidates tab (review and reject extracted memories).

**Delete all data:** Stop service, `rm -f data/*.sqlite3*`, restart.

**GDPR:** Study Senpai collects zero telemetry. When self-hosting, you are the data controller.
