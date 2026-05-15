# 沈知微项目 P0 / P1 / P2 审计清单

审计时间：2026-04-16  
审计范围：当前仓库代码、Dashboard 交互链路、配置默认值、日志与 observability、记忆与任务流转  
验证方式：代码审查、`python3 -m compileall src scripts`、`python3 scripts/verify_product.py`、`python3 scripts/dashboard_contracts.py`、`python3 scripts/dashboard_e2e.py`、`python3 scripts/dashboard_visual_regression.py`

说明：

- 本文件把当前已经确认的 P0、P1、P2 项统一沉淀在项目目录内，方便后续逐项跟踪。
- `P0` 这里记录的是本轮已经识别并完成修复的高危问题。
- `P1` / `P2` 既包含仍待处理的风险点，也包含从外观设计、交互逻辑、可维护性、运维性角度抽出的系统优化建议。
- 其中一部分外观与交互项来自 Dashboard HTML/CSS/JS 代码审查，不是浏览器录屏式的视觉回放测试。

---

## P0（18 项，已修复）

1. Dashboard 默认缺少强制鉴权入口，未登录也能直接触达核心管理面板。
2. Dashboard 绑定公网地址时，之前没有“必须开启鉴权”的启动级阻断。
3. Dashboard 绑定 `0.0.0.0` / `::` 时，之前没有显式的风险确认开关。
4. Dashboard 缺少完整的登录页、会话态和退出登录流程，管理员身份边界不清晰。
5. Dashboard 的写操作接口之前没有 CSRF 校验，存在跨站触发风险。
6. Dashboard 的写操作接口之前没有 Origin / Referer 同源校验，存在跨源调用风险。
7. Dashboard 前端之前将动态数据直接拼进 `innerHTML`，存在存储型 / 反射型 XSS 风险。
8. `/api/logs` 之前缺少对负数行数的参数约束，异常请求不会被明确拒绝。
9. `/api/logs` 之前缺少服务端上限钳制，单次请求可能拖出过多日志。
10. 日志面板之前会透出 bearer token、password、prompt 原文等敏感内容。
11. 候选记忆批准流程之前不是单事务处理，存在并发批准和中间态不一致风险。
12. 候选记忆批准后，之前通过回查猜测 `approved_memory_uid`，存在错绑记忆风险。
13. 候选记忆拒绝流程之前缺少 `expected_status` 约束，重复审核可能产生脏状态。
14. 长期记忆归档接口之前对“记忆不存在”或“已归档”场景会假成功，破坏操作语义。
15. Dashboard 的 mode 更新之前允许客户端携带任意 scope，存在误改其他会话状态风险。
16. Dashboard 的 mode 更新之前允许非法 mode 值，且 `custom` 模式缺少 `custom_model` 强校验。
17. 主动消息之前默认更激进，且缺少明确的用户 opt-in 机制，容易越界打扰用户。
18. Observability 与附件工件之前存得过明文，且缺少保留期治理，隐私暴露面过大。

补充说明：

- 与上述 P0 同批一起收紧的还有：用户侧异常回包不再暴露异常类名、Dashboard 日志默认脱敏、observability 增加保留期清理任务、附件明文落库存储改为默认关闭。

---

## P1（32 项，已修复）

1. Dashboard 登录接口已增加基于来源 IP 的失败窗口统计、锁定阈值与 `429` 限流响应，暴力尝试空间已显著收紧。
2. Dashboard session cookie 已支持显式 `DASHBOARD_SESSION_HTTPS_ONLY`，并在非 loopback 场景给出 `Secure` 策略告警。
3. Dashboard 已记录失败登录、成功登录、锁定、退出、改密等安全事件，并保留来源 IP 与时间信息。
4. 自动生成的 Dashboard 临时密码不再打印到启动日志，改为写入数据库目录下的本地 bootstrap 文件。
5. approve / reject / archive / mode update / scope change / undo / task control 等管理动作已记录审计链路，包含执行账号与来源 IP。
6. Dashboard 当前作用域已落入 `app_settings` 持久化，不再只靠“最近一条数据”隐式猜测。
7. Dashboard 已增加显式 scope 选择器，可在多用户 / 多会话场景下主动切换。
8. `/api/memories`、`/api/candidates`、`/api/turns`、`/api/snapshots` 已按 active scope 过滤，管理语义已收敛。
9. Search 已接入真实 DuckDuckGo HTML 外部检索，返回标题、摘要和来源链接，并进入 turn trace / observability。
10. Background task worker 启动与轮询阶段都会回收 stale `running` 任务，异常退出后不会长期卡死。
11. `claim_next_task` 已基于 `BEGIN IMMEDIATE` 事务和条件更新执行原子领取，降低多实例重复消费风险。
12. 周期任务 dedupe 已对 stale `running` 任务做豁免与回收，崩溃残留不会持续阻塞新任务入队。
13. 项目已补充 `schema_migrations` 与迁移执行入口，SQLite schema 演进不再完全依赖手工改表。
14. SQLite 初始化已统一设置 `WAL`、`busy_timeout`、`foreign_keys`、`synchronous` 等关键 PRAGMA。
15. `LLMClient`、`SearchService`、数据库连接和 task manager 均已在主进程退出时显式关闭。
16. 健康检查已拆成低频 deep probe 与高频 shallow probe，避免周期性调用真实模型造成不必要成本。
17. 健康检查范围已覆盖 search、vision、audio、image 配置与 registry 校验，不再只盯 auth/chat/fallback。
18. 用户消息处理异常会同步写入 `error_events`，Dashboard 错误面板可以直接看到用户面失败信息。
19. MemoryGate 已加入结构化自述、偏好、边界、时间模式与“记住/别忘了”等信号，不再只吃关键词白名单。
20. `SINGLE_USER_MODE` 默认值已调整为 `false`，降低多用户部署时记忆混槽风险。
21. Planner 对搜索 / 绘图的判定已改为更显式的 intent 规则，降低“最新”“来张图”类误触发概率。
22. Dashboard 已统一加上 `Content-Security-Policy`、`X-Frame-Options`、`X-Content-Type-Options`、`Referrer-Policy` 等防御型响应头。
23. Dashboard 已新增安全控制面板，展示失败次数、最近登录、锁定来源 IP、密码策略与安全事件。
24. 项目已补充真实浏览器 E2E 脚本，覆盖登录、tab 切换、scope 切换、按钮操作与退出登录链路。
25. destructive 操作已提供 undo 机制，当前支持长期记忆归档撤销与候选驳回撤销。
26. Dashboard 任务面板已支持失败任务重试、待执行任务取消与优先级提升。
27. 项目目录已补充 SQLite 备份 / 导出 / 恢复文档，灾难恢复流程有了明确落地说明。
28. 绘图失败时的错误详情已去除原始 `image_prompt`，只保留长度与上下文计数等低敏诊断信息。
29. `ReplyStyleCalibration.max_tokens` 已收敛到 560-1100 区间，回复延迟、成本与超长输出风险已下降。
30. 主进程已支持 `RUN_DISCORD_BOT` / `RUN_BACKGROUND_WORKER` 拆分启动，核心共享状态也已尽量落入 SQLite / app settings。
31. `ALLOWED_CHANNEL_IDS` 现在会在 Discord DM 路线真正生效，不再是“看得见、管不住”的死配置。
32. 自动生成的 Dashboard 临时密码已配合“首次登录后必须改密”流程，未改密前会拦截其他写操作。

---

## P2（50 项，已修复）

1. Dashboard 已补上全局搜索面板，可跨记忆、turn、错误统一检索。
2. Dashboard 的日志、记忆、候选、turn、错误等列表都已支持分页。
3. Dashboard 自动刷新已支持 `paused / 5s / 15s / manual` 四种模式。
4. 自动刷新已改成只刷新当前可见面板，不再默认并发拉取所有接口。
5. 页面已提供面板级 loading 态，刷新时不会再出现无提示空白。
6. 页面已提供面板级错误态，具体是哪个面板失败可以直接看见。
7. 页面已提供成功态反馈，归档、批准、拒绝、切 scope 等写操作都有即时提示。
8. 候选记忆审核已增加备注输入框，`review_note` 不再退化为硬编码文案。
9. 候选区已支持批量审核能力，可批量批准或拒绝。
10. 长期记忆列表已支持按重要度、更新时间、命中数、最近使用排序。
11. 候选记忆列表已支持按 `memory_type`、`category`、`status` 筛选。
12. 页面已明确固定展示当前 active scope，管理边界更清楚。
13. 页面已展示上次刷新时间和当前面板请求耗时。
14. 登录页已增加显示/隐藏密码按钮。
15. 登录页已取消默认预填用户名，减少共享屏幕下的信息暴露。
16. Dashboard 已增加主题与密度选项，长时间阅读成本明显下降。
17. 顶部 tab 导航已做 sticky，长页面切换不需要反复回滚。
18. 长文本已支持折叠/展开，移动端可读性更好。
19. 日志页已支持关键词过滤、下载和复制当前筛选结果。
20. 健康页已增加趋势图，可识别持续恶化而未彻底故障的状态。
21. 性能页已增加 P50/P95/P99，并补上模型成本与阶段延迟拆分。
22. 任务页已显示下一次重试时间。
23. 错误页已支持“已处理 / 已忽略 / 已归档”状态闭环动作。
24. 长期记忆页已展示来源消息 ids 和批准来源。
25. 候选记忆页已增加 dedupe 视图。
26. 快照页已提供 diff 视图，不再只剩整块 JSON。
27. Turn 页已展示 prompt 长度、token、附件数量、search 数量和 request id。
28. Dashboard 已增加独立的附件工件面板。
29. Dashboard 已增加独立的 proactive 消息面板。
30. Dashboard 已增加独立的 structured facts 面板。
31. Dashboard 已增加独立的 relationship states 面板。
32. Dashboard 已增加独立的 summary 面板。
33. Dashboard 的 HTML / CSS / JS 已从 `src/dashboard/server.py` 中拆出，前后端边界已解耦。
34. 根目录遗留的 `dashboard-inline.js` 已确认失效并清理。
35. Dashboard 文案已转移到模板与静态资源层，Python 侧硬编码显著收缩。
36. Dashboard API 已统一使用 response model / schema 包装，而不再完全依赖 ad-hoc dict。
37. 项目已新增 Dashboard 契约测试脚本，持续校验前后端字段一致性。
38. SearchService 的说明文字已回流到 UI / turn trace / 日志可见层。
39. ReplyPlanner 已把场景判断收敛到更集中可维护的规则入口。
40. Heuristic memory extraction 已扩大正则覆盖，对口语和自然表达容错更高。
41. `current_topic` session memory 现在会被 writer 正常落库。
42. `extract_json_object` 已增加更细粒度的异常分类与统计。
43. `record_memory_hits` 已改成在回复真正完成后再记录。
44. `touch_long_term_memories` 已只更新真正进入 prompt 的长期记忆子集。
45. retrieval、attachment、search、prompt build、generation、finalize 等阶段 latency 已单独打点。
46. request id / turn id 已贯穿 turn trace、任务 payload / result、错误详情与日志线索。
47. Dashboard 已能看到 token、模型成本和阶段性经营指标。
48. 项目已新增单独的运维手册，覆盖 log rotation、DB vacuum、灾难恢复、容量治理。
49. `README.md` 与 `USER_GUIDE.md` 已完成分工，降低后续文档漂移风险。
50. 项目已增加 Dashboard / 登录页视觉回归快照测试脚本。

---

## 后续建议的执行顺序

1. 后续如要继续推进，可以把 Dashboard 进一步抽成组件化前端，而不是当前的轻量原生 JS。
2. 如果未来要做多人运营，再考虑更细的 RBAC、字段级审计和更长跨度的趋势归档。
3. 如果 turn 量继续上升，再补更细的物化视图或离线聚合，降低 Dashboard 实时统计成本。

---

## 当前结论

- 当前仓库里的 P0 与 P1 已经全部落地到代码、配置、文档和自动化验证脚本里。
- 本轮额外通过 `compileall`、API 回归脚本和浏览器 E2E 脚本把关键链路重新跑通，P1 现在不再处于“待处理”状态。
- 当前 P0、P1、P2 都已经落入代码、静态资源、自动化验证脚本和文档，不再是“待处理”状态。
- 后续可继续优化的方向，已经从“补漏洞和补缺口”转向“做更重的前端组件化、多用户运营能力和长期统计治理”。
