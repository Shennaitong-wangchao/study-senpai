# SQLite 备份 / 导出 / 恢复手册

## 适用范围

本项目默认把核心数据写入 `DATABASE_PATH` 指向的 SQLite 数据库，同时在同目录生成 `-wal` / `-shm` 辅助文件。

高价值数据主要包括：

- `messages`
- `long_term_memories`
- `candidate_memories`
- `structured_facts`
- `relationship_states`
- `background_tasks`
- `dashboard_security_events`
- `dashboard_action_audits`

## 建议的备份频率

- 本地开发：做结构调整前手动备份一次
- 线上或长期运行：至少每天一次冷备份
- 做 schema 迁移、批量导入、手动清理前：先做即时备份

## 推荐备份方式

### 方式一：SQLite 在线备份

适合正在运行中的实例，优先推荐。

```bash
sqlite3 data/shen_zhiwei.sqlite3 ".backup 'data/backups/shen_zhiwei-$(date +%Y%m%d-%H%M%S).sqlite3'"
```

### 方式二：暂停进程后整体拷贝

如果你已经停掉 bot / dashboard / worker，可以一起复制主库和 sidecar 文件。

```bash
cp data/shen_zhiwei.sqlite3 data/backups/shen_zhiwei.sqlite3
cp data/shen_zhiwei.sqlite3-wal data/backups/shen_zhiwei.sqlite3-wal 2>/dev/null || true
cp data/shen_zhiwei.sqlite3-shm data/backups/shen_zhiwei.sqlite3-shm 2>/dev/null || true
```

## 导出建议

### 导出完整 SQL

```bash
sqlite3 data/shen_zhiwei.sqlite3 ".output data/exports/shen_zhiwei.sql" ".dump"
```

### 导出单表 CSV

```bash
sqlite3 -header -csv data/shen_zhiwei.sqlite3 "select * from long_term_memories;" > data/exports/long_term_memories.csv
```

## 恢复步骤

### 恢复整个数据库

1. 停掉正在运行的 bot / dashboard / worker。
2. 备份当前损坏库，避免覆盖最后现场。
3. 用最近一次可用备份覆盖 `DATABASE_PATH`。
4. 重新启动服务。
5. 先运行 `python3 scripts/verify_product.py`，再登录 Dashboard 检查记忆、任务和安全事件。

示例：

```bash
mv data/shen_zhiwei.sqlite3 data/shen_zhiwei.sqlite3.broken.$(date +%Y%m%d-%H%M%S)
cp data/backups/shen_zhiwei-20260416-180000.sqlite3 data/shen_zhiwei.sqlite3
python3 scripts/verify_product.py
```

### 从 SQL 导出恢复

```bash
sqlite3 data/shen_zhiwei.sqlite3 < data/exports/shen_zhiwei.sql
```

## 故障排查

- 如果看到 `database is locked`，先确认没有多个进程在抢同一个文件，再检查是否意外复制了不匹配的 `-wal` 文件。
- 如果恢复后 Dashboard 能登录但数据不完整，优先对比 `messages`、`long_term_memories`、`background_tasks` 三张表。
- 如果改密后忘记密码，可以在停机状态下备份数据库后，清理 `app_settings` 里的 `dashboard_password_hash`，再重启走 bootstrap 文件流程。

## 额外建议

- 定期保留一份只读归档备份，不和当前工作库放在同一路径。
- 数据库目录同时会包含 `dashboard_bootstrap_password.txt` 这类本地敏感文件，备份时请一起考虑权限控制。
- 如果你准备做大规模数据修复，先导出 SQL，再做结构化修改，避免只剩单一快照。
