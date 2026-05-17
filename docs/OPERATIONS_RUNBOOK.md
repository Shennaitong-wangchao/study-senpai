# 沈知微运维手册 / Operations Runbook

## 中文优先

这份文档只管运维，不重复解释聊天逻辑、环境变量和日常使用。配置与启动请看根目录的 `USER_GUIDE.md`。

---

## 1. 日常巡检

建议每天至少看一次：

- Dashboard `健康趋势`
- Dashboard `错误闭环`
- Dashboard `后台任务`
- Dashboard `性能成本`
- Dashboard `运行日志`

重点信号：

- `error_events` 里 `open` 数量是否持续上升
- `background_tasks` 是否长时间堆积在 `retrying` / `running`
- `turn_traces` 的 `P95/P99` 是否明显抬高
- `estimated_cost_usd` 是否突然放大
- `health_checks` 是否长期处于 `degraded`

---

## 2. Log Rotation

默认日志路径由 `LOG_FILE_PATH` 控制，常见值：

```text
logs/shen_zhiwei.log
```

建议配合系统的 `logrotate` 或宿主机日志轮转。

推荐策略：

- 保留 7 到 14 个轮转文件
- 单文件达到 20MB 到 50MB 就轮转
- 轮转后压缩历史日志
- 配合 `copytruncate` 或重启进程切换文件句柄

一个可参考的 `logrotate` 片段：

```conf
/path/to/project/logs/shen_zhiwei.log {
  daily
  rotate 14
  compress
  missingok
  notifempty
  copytruncate
}
```

---

## 3. SQLite 维护

数据库默认路径由 `DATABASE_PATH` 控制，常见值：

```text
data/shen_zhiwei.sqlite3
```

项目启动时会自动启用：

- `WAL`
- `busy_timeout`
- `foreign_keys`
- `synchronous=NORMAL`

### 3.1 什么时候做 `VACUUM`

建议在下面这些场景做：

- 大量归档 / 删除 observability 数据之后
- 长时间运行后数据库文件明显膨胀
- 做完手工恢复、导入或批量修复之后

执行前先停写流量，至少停掉：

- Discord bot 进程
- background worker
- Dashboard 写操作

执行：

```bash
sqlite3 data/shen_zhiwei.sqlite3 "VACUUM;"
```

如果你想顺手检查页大小和空闲页：

```bash
sqlite3 data/shen_zhiwei.sqlite3 "PRAGMA page_count; PRAGMA freelist_count;"
```

### 3.2 WAL 文件治理

如果发现 `.sqlite3-wal` 文件长期偏大，可以在低峰期执行：

```bash
sqlite3 data/shen_zhiwei.sqlite3 "PRAGMA wal_checkpoint(TRUNCATE);"
```

---

## 4. 备份与恢复

完整备份 / 导出 / 恢复步骤请看：

- `docs/SQLITE_BACKUP_AND_RECOVERY.md`

运维侧要记住的最短原则：

- 先备份再修复
- 不要在写流量很高的时候直接覆盖数据库文件
- 恢复后第一时间跑 `scripts/verify_product.py`
- 恢复后再跑 `scripts/dashboard_contracts.py`

---

## 5. 容量治理

当前最容易涨的表：

- `messages`
- `turn_traces`
- `health_checks`
- `experience_metric_events`
- `attachment_artifacts`
- `error_events`

当前已经有 observability retention 清理任务，会按 `OBSERVABILITY_RETENTION_DAYS` 清历史。

建议每周检查：

- 数据库文件大小
- 日志目录大小
- `turn_traces` 行数
- `attachment_artifacts` 行数
- `error_events` 未关闭比例

如果要保守一点：

- 下调 `OBSERVABILITY_RETENTION_DAYS`
- 关闭 `ATTACHMENT_ARTIFACT_STORE_TEXT`
- 缩短日志保留天数

---

## 6. 故障分流

### 6.1 Dashboard 打不开

先看：

- 进程是否启动
- `DASHBOARD_ENABLED`
- `DASHBOARD_HOST`
- `DASHBOARD_PORT`
- 端口是否被占用

再看日志里是否有：

- 鉴权配置错误
- Session secret 缺失
- 模板 / 静态资源加载错误

### 6.2 能登录，但列表空白

先看：

- 当前 active scope 是否切错
- `messages` / `long_term_memories` 是否真的有数据
- 面板顶部有没有局部错误提示
- 浏览器里是否切到了错误的过滤条件

### 6.3 后台任务堆积

先看：

- `RUN_BACKGROUND_WORKER`
- `background_tasks` 里是否大量 `retrying`
- `last_error`
- worker 进程是否退出

必要时：

- 重启 worker
- 在 Dashboard 里对失败任务做 `重试`
- 对明显失效的任务做 `取消`

### 6.4 成本异常升高

先看 Dashboard：

- `性能成本`
- `Turn Trace`
- `后台任务`

重点排查：

- 是否有某个模型被误切到更贵的档位
- 是否出现异常重试
- 是否搜索 / 附件链路被频繁触发
- `ReplyStyleCalibration.max_tokens` 是否被改坏

---

## 7. 发布后回归

每次涉及 Dashboard、API、样式或 observability 改动后，建议按下面顺序回归：

```bash
python3 -m compileall src scripts
python3 scripts/verify_product.py
python3 scripts/dashboard_contracts.py
python3 scripts/dashboard_e2e.py
python3 scripts/dashboard_visual_regression.py
```

如果这 4 类检查都过了，再放行到长期运行环境，会稳很多。

---

## English fallback

This runbook covers operations only. For chat behavior, environment variables, and day-to-day usage, see `USER_GUIDE.md`.

Daily checks: Dashboard health trends, error closure, background tasks, performance/cost, and runtime logs. Watch for rising open errors, stuck `background_tasks`, elevated P95/P99 latency, cost spikes, or long-term `degraded` health checks.

Logs are controlled by `LOG_FILE_PATH`; pair them with host log rotation. SQLite state is controlled by `DATABASE_PATH`; stop write traffic before `VACUUM` or manual recovery. Use `wal_checkpoint(TRUNCATE)` during low traffic if WAL files remain large.

For recovery, back up first, avoid overwriting a live database under write traffic, then run `scripts/verify_product.py` and `scripts/dashboard_contracts.py`.

After Dashboard, API, style, or observability changes, run:

```bash
python3 -m compileall src scripts
python3 scripts/verify_product.py
python3 scripts/dashboard_contracts.py
python3 scripts/dashboard_e2e.py
python3 scripts/dashboard_visual_regression.py
```
