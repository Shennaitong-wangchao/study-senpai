# Demo 录制脚本 / Demo Script

## 中文优先

这些脚本用于公开 README GIF。录制时只能使用临时数据库和假数据。不要录入真实聊天历史、记忆行、token、cookie、私有后端地址或个人位置。

## Demo 1：iOS 聊天演示

**录制目标**：展示 iOS 客户端能连接本地 Study Senpai 后端，发送学习相关消息，流式接收回复，并把互动保留在移动端时间线里。

**README GIF 文件名**：`docs/assets/demo-ios-chat.gif`

**假数据准备**：

- 专门为录制创建的临时 SQLite 数据库。
- 假学习者姓名，例如 `Alex`。
- 假学习提示词：`I have 45 minutes. Help me plan a focused review block for calculus.`
- 可选假附件：不含真实姓名或账号数据的空白练习纸或合成笔记。
- 可以设置 `MOBILE_API_TOKEN`，但绝不能在屏幕上显示真实值。

**录制步骤**：

1. 使用临时数据库在本地启动后端。
2. 在 Simulator 中打开 iOS App。
3. 打开 **Settings**，将 **Server Base URL** 设置为本地后端。
4. 如果启用了 token auth，输入 **Mobile API Token** 后先退出 Settings，再录制主流程。
5. 发送假学习提示词。
6. 等流式回复完成。
7. 短暂切到 timeline 或 home view，展示消息仍然可见。

**画面中应该出现**：

- iOS chat view。
- 一条假的用户学习请求。
- 一条包含计划、时间块或下一步的助手回复。
- 不出现 token、不出现 localhost 之外的真实 endpoint、不出现真实聊天历史。

**安全注意**：

- 如果输入过 token，请裁掉 Settings。
- 不要露出真实 App 的推送预览。
- 不要露出真实日历、位置、Discord 或账号数据。

## Demo 2：记忆 Dashboard 演示

**录制目标**：展示记忆在成为长期上下文前可以被审计和撤销。

**README GIF 文件名**：`docs/assets/demo-memory-dashboard.gif`

**假数据准备**：

- 专门为录制创建的临时 SQLite 数据库。
- 至少 seed 一段假对话和一条假候选记忆。
- 候选记忆示例：`Alex prefers 25-minute focus blocks with 5-minute breaks.`
- 结构化事实示例：`study_style = pomodoro`。

**录制步骤**：

1. 在本地启动后端和 Dashboard。
2. 使用本地开发凭据登录，避免最终画面中出现可见密码。
3. 打开候选记忆面板。
4. 确认一条假候选。
5. 打开长期记忆面板，展示已确认的假记忆。
6. 归档这条假记忆。
7. 恢复它，展示可逆性。
8. 如果不泄漏私有数据，可以打开审计或详情面板。

**画面中应该出现**：

- Dashboard memory/candidate 面板。
- 一条明显的假候选记忆。
- approve、archive、restore 控件。
- 假记忆的状态变化或审计行。

**安全注意**：

- 永远不要录制真实生产数据库。
- 不要展示原始 SQL 工具或包含用户名的文件系统路径。
- 隐藏浏览器自动补全、密码管理器和地址历史。

## Demo 3：学习工作流演示

**录制目标**：展示学习模式、计划和主动关怀如何配合一次学习 session。

**README GIF 文件名**：`docs/assets/demo-study-workflow.gif`

**假数据准备**：

- 专门为录制创建的临时 SQLite 数据库。
- 假学习目标：`Review derivatives and complete 10 practice problems.`
- 假可用时间：`45 minutes before dinner`。
- 假主动偏好：第一段学习后允许 check-in。

**录制步骤**：

1. 使用假数据在本地启动后端。
2. 在 iOS 或 Discord 中开启学习模式。
3. 发送假学习目标和可用时间。
4. 展示助手创建短学习计划。
5. 打开 Dashboard mode 或 proactive 面板。
6. 展示假主动偏好和一条生成的 check-in。
7. 回到聊天，展示下一步学习建议。

**画面中应该出现**：

- 学习模式已开启。
- 有具体步骤的短学习计划。
- Dashboard 状态反映 mode/proactive 设置。
- 一条假主动 check-in 或 planned nudge。

**安全注意**：

- 只使用假目标和假日程数据。
- 不要展示真实通知历史或个人日历。
- 不要暴露 `MOBILE_API_TOKEN`、Dashboard 凭据、私有主机名或真实聊天记录。

## 录制检查清单

- 使用被忽略的本地目录下的临时数据库。
- 可见设置界面中只使用 placeholder 模型和 Discord 凭据。
- 如果必须展示设置界面，将密钥脱敏为 `[REDACTED]`。
- 所有可见数据都保持合成。
- 将 GIF 导出为上面列出的精确文件名。

## English fallback

These scripts are for public README GIFs. Use a temporary database and fake data only. Do not record real chat history, memory rows, tokens, cookies, private backend addresses, or personal locations.

Demo 1 shows the iOS client connecting to a local backend, sending a fake study request, streaming a reply, and keeping the message in the mobile timeline.

Demo 2 shows the Dashboard memory workflow with fake candidate memory approval, archive, restore, and audit/status changes.

Demo 3 shows learning mode, a short study plan, proactive preference, and a fake check-in working together for a study session.

Always use synthetic data, hide credentials and real endpoints, redact secrets as `[REDACTED]`, and export GIFs to the filenames documented above.
