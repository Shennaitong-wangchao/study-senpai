# 部署指南 / Deployment Guide

本文档覆盖从零到生产的完整部署流程，包含 Docker 部署（推荐）和 Python 直接部署两种方式，以及安全配置、备份、日志和性能调优。

---

## 目录

1. [前置条件](#1-前置条件)
2. [Docker 部署（推荐）](#2-docker-部署推荐)
3. [Python 直接部署（systemd）](#3-python-直接部署systemd)
4. [最小安全配置清单](#4-最小安全配置清单)
5. [公网暴露前检查清单](#5-公网暴露前检查清单)
6. [HTTPS + Nginx 反向代理](#6-https--nginx-反向代理)
7. [SQLite 备份策略](#7-sqlite-备份策略)
8. [环境变量安全存储](#8-环境变量安全存储)
9. [日志轮转配置](#9-日志轮转配置)
10. [性能调优](#10-性能调优)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. 前置条件

| 组件 | 最低要求 |
|------|----------|
| OS | Ubuntu 20.04+ / Debian 11+ / CentOS 8+ |
| CPU | 1 核 |
| 内存 | 512 MB（仅 bot）/ 1 GB（含 Dashboard） |
| 磁盘 | 2 GB 可用空间 |
| 网络 | 可访问目标 LLM API |
| Docker（方式一） | Docker 24+ + Docker Compose v2 |
| Python（方式二） | Python 3.11+ |

---

## 2. Docker 部署（推荐）

Docker 部署将应用、依赖、配置完整隔离，升级和回滚都更简单。

### 2.1 克隆代码

```bash
git clone https://github.com/<your-org>/ai-gf-zhiwei.git /opt/shen-zhiwei-bot
cd /opt/shen-zhiwei-bot
```

### 2.2 创建 .env 文件

```bash
cp .env.example .env      # 如果存在示例文件
# 或者手动创建：
nano .env
```

最小必填配置：

```env
# Discord Bot（如不使用 Discord 则设为 false）
DISCORD_BOT_TOKEN=<your-discord-bot-token>
RUN_DISCORD_BOT=true

# LLM 配置（必填）
LLM_API_KEY=<your-llm-api-key>
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini

# Dashboard 鉴权
DASHBOARD_AUTH_ENABLED=true
DASHBOARD_AUTH_USERNAME=admin
DASHBOARD_AUTH_PASSWORD=<your-strong-password-at-least-12-chars>
DASHBOARD_SESSION_SECRET=<random-64-char-string>

# 数据持久化路径（Docker 内部路径，无需修改）
DATABASE_PATH=/app/data/senpai.sqlite3
LOG_FILE_PATH=/app/logs/senpai.log
```

### 2.3 构建并启动

```bash
# 构建镜像
docker compose build

# 后台启动
docker compose up -d

# 查看启动日志
docker compose logs -f --tail=50
```

### 2.4 验证运行状态

```bash
# 容器状态
docker compose ps

# 健康检查
curl http://127.0.0.1:8099/api/health
```

成功响应示例：

```json
{"status": "ok", "timestamp": "..."}
```

### 2.5 停止 / 重启

```bash
docker compose stop
docker compose restart
docker compose down          # 停止并移除容器（数据卷保留）
docker compose down -v       # 危险：连数据卷一起删除
```

### 2.6 升级

```bash
git pull
docker compose build
docker compose up -d
```

### 2.7 Nginx 反向代理配置示例

配合 Nginx 将 Dashboard 暴露到 HTTPS（具体 HTTPS 配置见第 6 节）：

在 `docker-compose.yml` 中，**不要**把 `8099` 端口直接映射到公网，改为只绑定 localhost：

```yaml
# docker-compose.yml（生产调整）
services:
  senpai:
    ports:
      - "127.0.0.1:8099:8099"    # 只监听本机，由 Nginx 转发
```

修改后重启：

```bash
docker compose up -d
```

---

## 3. Python 直接部署（systemd）

适合不想用 Docker 或服务器资源极度有限的情况。

### 3.1 准备目录和依赖

```bash
# 推荐部署路径
sudo mkdir -p /opt/shen-zhiwei-bot
sudo chown $USER:$USER /opt/shen-zhiwei-bot

# 克隆代码
git clone https://github.com/<your-org>/ai-gf-zhiwei.git /opt/shen-zhiwei-bot
cd /opt/shen-zhiwei-bot

# 创建虚拟环境
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### 3.2 创建 .env 文件

```bash
nano /opt/shen-zhiwei-bot/.env
```

内容同 Docker 部署的最小必填配置，注意路径改为实际路径：

```env
DATABASE_PATH=/opt/shen-zhiwei-bot/data/shen_zhiwei.sqlite3
LOG_FILE_PATH=/opt/shen-zhiwei-bot/logs/shen_zhiwei.log
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8099
```

保护文件权限：

```bash
chmod 600 /opt/shen-zhiwei-bot/.env
```

### 3.3 安装 systemd service

模板文件位于 `deploy/systemd/shen-zhiwei-bot.service`。

修改模板中的占位符：

```bash
# 编辑模板
nano /opt/shen-zhiwei-bot/deploy/systemd/shen-zhiwei-bot.service
```

需要修改的字段：

```ini
[Service]
User=<your-linux-username>          # 替换为实际用户名
Group=<your-linux-username>         # 替换为实际用户组
WorkingDirectory=/opt/shen-zhiwei-bot
EnvironmentFile=/opt/shen-zhiwei-bot/.env
ExecStart=/opt/shen-zhiwei-bot/.venv/bin/python -m src.main
```

安装并启动：

```bash
sudo cp /opt/shen-zhiwei-bot/deploy/systemd/shen-zhiwei-bot.service \
        /etc/systemd/system/shen-zhiwei-bot.service

sudo systemctl daemon-reload
sudo systemctl enable shen-zhiwei-bot    # 开机自启
sudo systemctl start shen-zhiwei-bot
```

### 3.4 常用管理命令

```bash
# 查看运行状态
sudo systemctl status shen-zhiwei-bot

# 实时查看日志
sudo journalctl -u shen-zhiwei-bot -f

# 查看最近 100 条日志
sudo journalctl -u shen-zhiwei-bot -n 100

# 重启服务
sudo systemctl restart shen-zhiwei-bot

# 停止服务
sudo systemctl stop shen-zhiwei-bot

# 验证 Dashboard 端口
sudo ss -lntp | grep 8099
curl http://127.0.0.1:8099/api/health
```

### 3.5 升级

```bash
cd /opt/shen-zhiwei-bot
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart shen-zhiwei-bot
```

---

## 4. 最小安全配置清单

以下 5 项必须在上线前完成：

- [ ] **1. 设置强密码**

  ```env
  DASHBOARD_AUTH_PASSWORD=<至少12位，包含大小写+数字+特殊字符>
  ```

- [ ] **2. 设置随机 Session 密钥**

  ```bash
  # 生成 64 字符随机字符串
  python3 -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

  ```env
  DASHBOARD_SESSION_SECRET=<上面生成的字符串>
  ```

- [ ] **3. 启用 Dashboard 鉴权**

  ```env
  DASHBOARD_AUTH_ENABLED=true
  ```

- [ ] **4. Dashboard 默认只监听 localhost**

  ```env
  DASHBOARD_HOST=127.0.0.1    # 不要设为 0.0.0.0，除非已配置 Nginx + HTTPS
  ```

- [ ] **5. 保护 .env 文件权限**

  ```bash
  chmod 600 .env
  ```

---

## 5. 公网暴露前检查清单

在将 Dashboard 对外开放之前，逐项确认：

- [ ] Nginx 已配置 HTTPS（Let's Encrypt 或自签证书）
- [ ] Dashboard 鉴权已启用（`DASHBOARD_AUTH_ENABLED=true`）
- [ ] `.env` 中密码强度足够（≥12 位）
- [ ] 防火墙只放行 80/443，不直接开放 8099
- [ ] 已配置 `DASHBOARD_SESSION_HTTPS_ONLY=true`（HTTPS 模式下自动启用）
- [ ] 了解当前没有内建 IP 封禁，建议在 Nginx 层加速率限制
- [ ] 如使用公有云，安全组规则已正确配置

---

## 6. HTTPS + Nginx 反向代理

### 6.1 安装 Nginx 和 Certbot

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

### 6.2 Nginx 配置模板（复制即可用）

创建配置文件：

```bash
sudo nano /etc/nginx/sites-available/shen-zhiwei-bot
```

写入以下内容（替换 `<your-domain.com>`）：

```nginx
# HTTP → HTTPS 跳转
server {
    listen 80;
    server_name <your-domain.com>;
    return 301 https://$host$request_uri;
}

# HTTPS 反向代理
server {
    listen 443 ssl http2;
    server_name <your-domain.com>;

    # SSL 证书路径（Certbot 自动填写）
    ssl_certificate     /etc/letsencrypt/live/<your-domain.com>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<your-domain.com>/privkey.pem;

    # 安全配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;

    # 速率限制（防暴力破解）
    limit_req_zone $binary_remote_addr zone=dashboard_login:10m rate=5r/m;

    # 登录端点限速
    location /api/auth/login {
        limit_req zone=dashboard_login burst=3 nodelay;
        proxy_pass http://127.0.0.1:8099;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 其余请求
    location / {
        proxy_pass http://127.0.0.1:8099;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

启用配置并申请证书：

```bash
sudo ln -s /etc/nginx/sites-available/shen-zhiwei-bot \
           /etc/nginx/sites-enabled/

sudo nginx -t                           # 检查配置语法

# 申请 Let's Encrypt 证书（自动修改 Nginx 配置填入证书路径）
sudo certbot --nginx -d <your-domain.com>

sudo systemctl reload nginx
```

### 6.3 证书自动续期

Certbot 安装后会自动创建定时任务，手动测试续期：

```bash
sudo certbot renew --dry-run
```

---

## 7. SQLite 备份策略

> 详细的导出 / 恢复流程参见 `docs/SQLITE_BACKUP_AND_RECOVERY.md`。

### 7.1 每日自动备份（cron）

```bash
# 编辑 crontab
crontab -e
```

添加以下行（每天凌晨 3:00 执行）：

```cron
0 3 * * * sqlite3 /opt/shen-zhiwei-bot/data/shen_zhiwei.sqlite3 \
  ".backup '/opt/shen-zhiwei-bot/data/backups/shen_zhiwei-$(date +\%Y\%m\%d).sqlite3'" \
  >> /opt/shen-zhiwei-bot/logs/backup.log 2>&1
```

### 7.2 保留最近 30 天备份

```cron
# 每天凌晨 3:05 清理 30 天前的旧备份
5 3 * * * find /opt/shen-zhiwei-bot/data/backups -name "*.sqlite3" \
  -mtime +30 -delete >> /opt/shen-zhiwei-bot/logs/backup.log 2>&1
```

### 7.3 手动备份（维护前必做）

```bash
# 在线备份（服务运行中也可用）
sqlite3 /opt/shen-zhiwei-bot/data/shen_zhiwei.sqlite3 \
  ".backup '/opt/shen-zhiwei-bot/data/backups/shen_zhiwei-manual-$(date +%Y%m%d-%H%M%S).sqlite3'"
```

### 7.4 验证备份可用性

```bash
sqlite3 /opt/shen-zhiwei-bot/data/backups/shen_zhiwei-<date>.sqlite3 \
  "SELECT COUNT(*) FROM messages;"
```

---

## 8. 环境变量安全存储

### 基本原则

- `.env` 文件权限设为 `600`，只有运行用户可读
- 不要把 `.env` 提交到 Git（`.gitignore` 已默认排除）
- 生产环境建议用密钥管理服务（AWS Secrets Manager / HashiCorp Vault）

### 权限设置

```bash
chmod 600 /opt/shen-zhiwei-bot/.env
chown <your-linux-user>:<your-linux-user> /opt/shen-zhiwei-bot/.env
```

### 验证 .env 已被 Git 忽略

```bash
git check-ignore -v .env
# 应输出：.gitignore:1:.env
```

### 最小权限原则

为 bot 创建专用系统用户，避免以 root 运行：

```bash
sudo useradd --system --no-create-home --shell /bin/false shen-zhiwei-bot
sudo chown -R shen-zhiwei-bot:shen-zhiwei-bot /opt/shen-zhiwei-bot
```

然后在 systemd service 中设置：

```ini
User=shen-zhiwei-bot
Group=shen-zhiwei-bot
```

---

## 9. 日志轮转配置

### logrotate 配置

```bash
sudo nano /etc/logrotate.d/shen-zhiwei-bot
```

写入：

```
/opt/shen-zhiwei-bot/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 640 shen-zhiwei-bot shen-zhiwei-bot
    postrotate
        systemctl kill -s HUP shen-zhiwei-bot 2>/dev/null || true
    endscript
}
```

手动测试轮转：

```bash
sudo logrotate -d /etc/logrotate.d/shen-zhiwei-bot   # 演习，不实际操作
sudo logrotate -f /etc/logrotate.d/shen-zhiwei-bot   # 强制执行
```

### 调整日志级别

```env
# 生产环境建议 INFO，调试时临时改为 DEBUG
LOG_LEVEL=INFO
```

### Dashboard 日志行数上限

```env
# Dashboard 实时日志最多显示的行数（默认 400）
DASHBOARD_LOG_MAX_LINES=400
```

---

## 10. 性能调优

### 数据库 VACUUM

SQLite 长期运行后文件碎片化，定期执行 VACUUM 可释放空间、提升查询性能。

```bash
# 停止服务后执行（或使用 VACUUM INTO 做在线操作）
sudo systemctl stop shen-zhiwei-bot
sqlite3 /opt/shen-zhiwei-bot/data/shen_zhiwei.sqlite3 "VACUUM;"
sudo systemctl start shen-zhiwei-bot
```

每月 VACUUM cron（凌晨 4:00，每月 1 日）：

```cron
0 4 1 * * systemctl stop shen-zhiwei-bot && \
  sqlite3 /opt/shen-zhiwei-bot/data/shen_zhiwei.sqlite3 "VACUUM;" && \
  systemctl start shen-zhiwei-bot
```

### 请求超时调整

```env
# LLM 请求超时（秒）
LLM_TIMEOUT_SECONDS=60

# 后台任务单次超时（秒）
BACKGROUND_TASK_TIMEOUT_SECONDS=180

# 联网搜索超时（秒）
SEARCH_TIMEOUT_SECONDS=8
```

### 内存压力优化

减少内存中保留的历史消息条数：

```env
# 发送给 LLM 的最大消息条数（默认 20）
HISTORY_MESSAGE_LIMIT=15

# 最近活跃窗口（默认 10）
RECENT_TURN_WINDOW=8

# 长期记忆注入上限（默认 8）
LONG_TERM_MEMORY_LIMIT=6
```

### 后台任务频率

```env
# 后台任务轮询间隔（秒，默认 2）
BACKGROUND_POLL_SECONDS=2

# 主动消息扫描频率（分钟，默认 20）
PROACTIVE_SCAN_MINUTES=20
```

### 可观测性数据保留

```env
# 可观测性数据保留天数（默认 30）
OBSERVABILITY_RETENTION_DAYS=30
```

---

## 11. Troubleshooting

### Dashboard 无法访问

**症状：** 浏览器提示连接拒绝或超时

**检查步骤：**

```bash
# 1. 确认服务正在运行
sudo systemctl status shen-zhiwei-bot
# 或 Docker：
docker compose ps

# 2. 确认端口在监听
sudo ss -lntp | grep 8099

# 3. 本机能否访问
curl http://127.0.0.1:8099/api/health

# 4. 检查 .env 中 DASHBOARD_HOST 是否为 0.0.0.0
grep DASHBOARD_HOST .env

# 5. 检查防火墙
sudo ufw status
```

---

### Discord Bot 不响应

**症状：** Bot 在线但不回复消息

**检查步骤：**

```bash
# 查看日志中是否有频道 ID 过滤导致消息被跳过
sudo journalctl -u shen-zhiwei-bot -n 200 | grep -i "channel\|ignore\|skip"
```

```env
# 如果设置了频道白名单，确认 Bot 所在频道 ID 已包含
ALLOWED_CHANNEL_IDS=123456789,987654321
# 留空则允许所有频道
```

---

### LLM 报错 / 无响应

```bash
# 查看最近 LLM 相关错误
sudo journalctl -u shen-zhiwei-bot -n 500 | grep -i "llm\|timeout\|429\|401"
```

常见错误：

| 错误码 | 原因 | 解决方案 |
|--------|------|----------|
| 401 | API Key 无效 | 检查 `LLM_API_KEY` |
| 404 | 模型名不存在 | 检查 `LLM_MODEL` 是否正确 |
| 429 | 速率限制 | 降低请求频率或升级套餐 |
| 503 | 提供商服务异常 | 等待或切换备用提供商 |

---

### 数据库相关错误

```bash
# database is locked
# → 多个进程同时访问，确认只有一个实例在运行
pgrep -a python3 | grep src.main

# disk I/O error
# → 检查磁盘空间
df -h /opt/shen-zhiwei-bot/data
```

---

### 生成初始 bootstrap 密码

首次部署如果没有设置 `DASHBOARD_AUTH_PASSWORD`，系统会自动生成并写入：

```
data/dashboard_bootstrap_password.txt
```

```bash
cat /opt/shen-zhiwei-bot/data/dashboard_bootstrap_password.txt
```

查看后立即在 Dashboard 设置页面修改密码，并从 `.env` 写入固定密码。
