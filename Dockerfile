# ── Stage 1: deps ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# 创建非 root 用户
RUN addgroup --system senpai && adduser --system --ingroup senpai senpai

# 从 deps 阶段复制安装好的包
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# 复制源码
COPY src/ ./src/
COPY personas/ ./personas/

# 创建持久化数据目录
RUN mkdir -p data logs && chown -R senpai:senpai /app

USER senpai

EXPOSE 8099

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/app/data/senpai.sqlite3 \
    LOG_FILE_PATH=/app/logs/senpai.log \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8099 \
    DASHBOARD_ENABLED=true \
    DASHBOARD_AUTH_ENABLED=true \
    DASHBOARD_PUBLIC_BIND_ACKNOWLEDGED=true \
    RUN_DISCORD_BOT=false \
    RUN_BACKGROUND_WORKER=true

VOLUME ["/app/data", "/app/logs"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8099/api/health')" || exit 1

CMD ["python3", "-m", "src.main"]
