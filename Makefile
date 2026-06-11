.PHONY: help install dev test lint docker-build docker-up docker-down clean

PYTHON ?= python3
VENV   ?= .venv

help:  ## 显示帮助
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Setup ────────────────────────────────────────────────────────────────────

install:  ## 安装依赖（创建 .venv）
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt
	@echo "Done. Run: source $(VENV)/bin/activate"

# ── Dev ──────────────────────────────────────────────────────────────────────

dev:  ## 启动开发服务器（仅 Dashboard）
	$(VENV)/bin/python -m src.main

dev-discord:  ## 启动含 Discord Bot 的完整服务
	RUN_DISCORD_BOT=true $(VENV)/bin/python -m src.main

# ── Test ─────────────────────────────────────────────────────────────────────

test:  ## 运行全量测试
	$(VENV)/bin/python -m pytest

test-fast:  ## 快速测试（跳过 dashboard_context 慢 fixtures）
	$(VENV)/bin/python -m pytest -x -q --ignore=tests/test_memory_export_import.py

test-cov:  ## 带覆盖率报告的测试
	$(VENV)/bin/python -m pytest --cov=src --cov-report=term-missing

# ── Quality ──────────────────────────────────────────────────────────────────

lint:  ## 运行 ruff lint
	$(VENV)/bin/python -m ruff check src/ tests/ scripts/ --select E,W,F,I --ignore E501

check:  ## 运行所有质量检查
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

docker-logs:  ## 查看 Docker 日志
	docker compose logs -f

# ── Clean ────────────────────────────────────────────────────────────────────

clean:  ## 清理临时文件
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name ".pytest_cache" -delete
	find . -type d -name ".ruff_cache" -delete
