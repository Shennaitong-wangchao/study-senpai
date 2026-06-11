#!/usr/bin/env bash
# tag_release.sh — 本地打 tag 并推送到远端，触发 GitHub Release 工作流
#
# 用法：
#   bash scripts/tag_release.sh 0.2.0
#
# 脚本行为：
#   1. 从 pyproject.toml 读取当前版本，展示给用户确认
#   2. 校验传入版本号格式（semver x.y.z）
#   3. 确认后创建带注释的 git tag v<version>
#   4. 推送 tag 到 origin（触发 release.yml）

set -euo pipefail

# ── 颜色 ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'  # No Color

# ── 参数校验 ──────────────────────────────────────────────────────────────────
if [[ $# -ne 1 ]]; then
  echo -e "${RED}错误：必须传入版本号。${NC}"
  echo "用法：bash scripts/tag_release.sh <version>"
  echo "示例：bash scripts/tag_release.sh 0.2.0"
  exit 1
fi

NEW_VERSION="$1"

# semver 格式校验（x.y.z，可带预发布后缀如 0.2.0-rc.1）
if ! echo "$NEW_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
  echo -e "${RED}错误：版本号格式不合法 → '$NEW_VERSION'${NC}"
  echo "期望格式：x.y.z 或 x.y.z-suffix（例如 0.2.0 / 1.0.0-rc.1）"
  exit 1
fi

TAG="v${NEW_VERSION}"

# ── 读取 pyproject.toml 中的当前版本 ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYPROJECT="${REPO_ROOT}/pyproject.toml"

if [[ ! -f "$PYPROJECT" ]]; then
  echo -e "${RED}错误：找不到 pyproject.toml（期望路径：${PYPROJECT}）${NC}"
  exit 1
fi

CURRENT_VERSION=$(grep -E '^version\s*=' "$PYPROJECT" | head -1 | sed 's/.*=\s*"\(.*\)"/\1/')

echo ""
echo -e "${YELLOW}═══════════════════════════════════════════${NC}"
echo -e "  当前版本（pyproject.toml）: ${GREEN}${CURRENT_VERSION}${NC}"
echo -e "  即将打 tag                : ${GREEN}${TAG}${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════${NC}"
echo ""

# ── 检查 tag 是否已存在 ───────────────────────────────────────────────────────
if git -C "$REPO_ROOT" tag --list | grep -q "^${TAG}$"; then
  echo -e "${RED}错误：tag '${TAG}' 已存在，请先删除后重试：${NC}"
  echo "  git tag -d ${TAG} && git push origin :refs/tags/${TAG}"
  exit 1
fi

# ── 确认 ──────────────────────────────────────────────────────────────────────
read -r -p "确认创建并推送 tag '${TAG}'？[y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo "已取消。"
  exit 0
fi

# ── 确保工作区干净 ────────────────────────────────────────────────────────────
if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
  echo -e "${YELLOW}警告：工作区有未提交的变更，建议先提交再打 tag。${NC}"
  read -r -p "仍要继续？[y/N] " force_continue
  if [[ ! "$force_continue" =~ ^[Yy]$ ]]; then
    echo "已取消。"
    exit 0
  fi
fi

# ── 创建带注释的 tag ──────────────────────────────────────────────────────────
echo ""
echo "正在创建 tag ${TAG}..."
git -C "$REPO_ROOT" tag -a "$TAG" -m "Release ${TAG}"

# ── 推送 tag ──────────────────────────────────────────────────────────────────
echo "正在推送 tag 到 origin..."
git -C "$REPO_ROOT" push origin "$TAG"

echo ""
echo -e "${GREEN}✓ tag '${TAG}' 已创建并推送！${NC}"
echo "  GitHub Actions release.yml 工作流将自动触发。"
echo "  查看进度：https://github.com/$(git -C "$REPO_ROOT" remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/' | sed 's/.*github.com[:/]\(.*\)/\1/')/actions"
