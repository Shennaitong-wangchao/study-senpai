.PHONY: help install install-dev dev dev-discord test test-fast test-cov lint type-check check docker-build docker-up docker-down docker-logs clean

PYTHON ?= python3
VENV   ?= .venv

help:  ## 显示帮助
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Setup ────────────────────────────────────────────────────────────────────

install:  ## 安装生产依赖（创建 .venv）
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt
	@echo "Done. Run: source $(VENV)/bin/activate"

install-dev:  ## 安装开发依赖（含 ruff, mypy, pytest-cov）
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt
	$(VENV)/bin/pip install ruff mypy pytest-cov
	@echo "Dev deps installed."

# ── Dev ──────────────────────────────────────────────────────────────────────

dev:  ## 启动开发服务器（仅 Dashboard，RUN_DISCORD_BOT=false）
	RUN_DISCORD_BOT=false $(VENV)/bin/python -m src.main

dev-discord:  ## 启动含 Discord Bot 的完整服务
	RUN_DISCORD_BOT=true $(VENV)/bin/python -m src.main

# ── Test ─────────────────────────────────────────────────────────────────────

test:  ## 运行全量测试
	$(VENV)/bin/python -m pytest

test-fast:  ## 快速测试（跳过慢 dashboard_context fixtures）
	$(VENV)/bin/python -m pytest -x -q --ignore=tests/test_memory_export_import.py

test-cov:  ## 带覆盖率报告的测试（需要 pytest-cov）
	$(VENV)/bin/python -m pytest --cov=src --cov-report=term-missing --cov-report=html:htmlcov
	@echo "HTML report: htmlcov/index.html"

# ── Quality ──────────────────────────────────────────────────────────────────

lint:  ## 运行 ruff lint（需要 ruff，make install-dev）
	$(VENV)/bin/python -m ruff check src/ tests/ scripts/ --select E,W,F,I --ignore E501

lint-fix:  ## 自动修复 ruff 可修复问题
	$(VENV)/bin/python -m ruff check src/ tests/ scripts/ --select E,W,F,I --ignore E501 --fix

type-check:  ## 运行 mypy 类型检查（需要 mypy，make install-dev）
	$(VENV)/bin/python -m mypy src/ --ignore-missing-imports --no-strict-optional --exclude '\.venv'

check:  ## 运行全量质量检查（测试 + 合同 + lint）
	$(VENV)/bin/python -m pytest
	$(VENV)/bin/python scripts/release_gate.py
	$(VENV)/bin/python scripts/mobile_contracts.py
	$(VENV)/bin/python scripts/dashboard_contracts.py
	$(VENV)/bin/python scripts/verify_product.py

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build:  ## 构建 Docker 镜像
	docker build -t study-senpai:latest .

docker-up:  ## 启动 Docker Compose 服务
	docker compose up -d

docker-down:  ## 停止 Docker Compose 服务
	docker compose down

docker-logs:  ## 查看容器日志（跟随）
	docker compose logs -f

docker-restart:  ## 重启容器
	docker compose restart

# ── Release ──────────────────────────────────────────────────────────────────

release:  ## 打新 tag 并推送（会触发 GitHub Actions release）
	@echo "用法: bash scripts/tag_release.sh <version>"
	@echo "例如: bash scripts/tag_release.sh 0.2.0"

# ── Clean ────────────────────────────────────────────────────────────────────

clean:  ## 清理 Python 缓存和构建产物
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean done."
