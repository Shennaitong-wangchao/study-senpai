# 路线图 / Roadmap

## 中文优先

这份路线图的目标，是让 Study Senpai 成为最好用的本地优先 AI 学习陪伴框架。

---

## 已完成（v0.1.x）

- [x] 本地优先 Python 后端 + SQLite 持久化
- [x] FastAPI Dashboard（审核、可观测性、记忆治理）
- [x] Discord Bot 运行时
- [x] Mobile API（供 iOS App 和第三方客户端）
- [x] SwiftUI iOS 客户端
- [x] 长期记忆自动提取、候选审核
- [x] 共享日记 Dashboard/Mobile API
- [x] 主动关怀消息（ProactiveMessageService）
- [x] CompanionDayEngine（AI 日常状态）
- [x] RealityContextService（天气/日历感知）
- [x] 附件分析（PDF、Word、图片、音频）
- [x] 后台任务管理器
- [x] 健康检查（浅/深巡检）
- [x] Dashboard 安全认证（CSRF、登录锁定、审计日志）
- [x] **Persona YAML 注册表** — 多人格，无需改代码
- [x] **Docker 支持** — `docker compose up -d` 一键部署
- [x] **内置 Web Chat UI** — 浏览器直接对话
- [x] **记忆导出/导入** — JSON/Markdown 备份与迁移
- [x] **学习目标 + SM-2 间隔复习** — 闪卡系统
- [x] **CI/CD 增强** — 多 Python 版本、lint、密钥扫描、Docker 构建
- [x] **完整文档体系** — FAQ、Privacy、Deployment、LLM Providers

---

## Phase 2 — 体验打磨（进行中）

### 2.1 Web Chat 增强
- [ ] Markdown 渲染（代码块高亮、粗体）
- [ ] 图片/文件拖拽上传
- [ ] 打字状态动画（dots）
- [ ] 消息时间戳

### 2.2 Dashboard 改进
- [ ] 学习目标看板（进度可视化）
- [ ] 间隔复习面板（Dashboard 内可直接练习）
- [ ] 深色主题优化

### 2.3 人格系统
- [ ] 社区人格库 — `personas/community/` 目录，欢迎 PR
- [ ] 人格热重载（运行时切换，不重启）
- [ ] 人格版本控制（支持 `@version` 字段）

---

## Phase 3 — 学习功能深化

- [ ] **学习会话分析**：专注时长、完成率、streak 统计
- [ ] **Anki 卡片导入**：从 `.apkg` 文件导入闪卡
- [ ] **学习目标 AI 分解**：输入大目标，AI 自动分解成子任务
- [ ] **知识图谱可视化**：展示学习内容之间的关联
- [ ] **错题本**：自动记录复习失败的卡片，重点复习

---

## Phase 4 — 部署与安全加固

- [ ] **Nginx/Caddy 反向代理一键配置**：开箱即用的 HTTPS 配置
- [ ] **多用户支持**：独立用户空间隔离（适合家庭/小团队部署）
- [ ] **限流和请求配额**：保护公网部署
- [ ] **备份自动化**：定时备份 + 验证

---

## Phase 5 — 记忆治理

- [ ] **记忆保留策略**：设置记忆过期时间
- [ ] **记忆脱敏工具**：批量处理敏感记忆
- [ ] **记忆版本历史**：查看记忆变更记录
- [ ] **记忆导出完整版**：包含聊天历史

---

## Phase 6 — iOS 成熟度

- [ ] **Server Profile 管理**：多服务端配置切换
- [ ] **Token 校验页面**：连接诊断 UI
- [ ] **认证媒体缓存**：离线查看生成的图片
- [ ] **推送通知**：主动消息本地通知
- [ ] **iCloud 同步**：服务端配置跨设备同步

---

## 长期方向

- **插件 API**：允许社区扩展工具和集成
- **知识库接入**：接入 Notion、Obsidian 等笔记工具
- **语音支持**：语音输入/输出（TTS/STT）
- **多平台 Bot**：微信、Telegram、Slack、飞书

---

## English fallback

**Completed in v0.1.x:** Python backend, SQLite, Dashboard, Discord bot, iOS client, memory pipeline, proactive messaging, day engine, reality context, attachments, Persona YAML registry, Docker, Web Chat UI, memory export/import, spaced repetition with SM-2, CI/CD, and full documentation suite.

**Phase 2:** Web Chat improvements (Markdown, file upload), Dashboard study panels, persona hot-reload.

**Phase 3:** Study session analytics, Anki import, AI goal decomposition, knowledge graph.

**Phase 4:** Nginx/Caddy config, multi-user isolation, rate limiting, automated backups.

**Phase 5:** Memory retention policies, redaction tools, export versioning.

**Phase 6:** iOS server profiles, push notifications, iCloud sync.

**Long-term:** Plugin API, knowledge base integration (Notion/Obsidian), voice, multi-platform bots.
