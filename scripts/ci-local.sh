#!/usr/bin/env bash
# Ai Ink 本地 CI 一键复现（与 .github/workflows/ci.yml 同一套门禁，未配 git remote 时本地验证用）。
# 覆盖：Python 语法门禁 + 全量回归（全新 PG？否——复用本地 compose 的 pg/redis，角色/init 已就绪）
#        → Go 网关 vet+test → 前端 lint+test+build → 镜像构建。
# 前置：Docker Desktop 运行中；根目录 .env 已配（无 key 也能跑，测试全 mock LLM）；Python venv 已激活。
# 用法：bash scripts/ci-local.sh          # 全部门禁
#       SKIP_IMAGES=1 bash scripts/ci-local.sh   # 跳过镜像构建（本地日常快跑）
set -euo pipefail

# Windows 控制台默认 GBK：rich 的 ✓/✗ 等符号会 UnicodeEncodeError（aiink init 输出），强制 UTF-8。
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 基础设施：确保 pg/redis 起；停 aiink-worker 防抢 Redis 队列（DEPLOY.md 已知约束），退出时恢复。
docker compose up -d aiink-pg aiink-redis
docker compose stop aiink-worker >/dev/null 2>&1 || true
trap 'docker compose start aiink-worker >/dev/null 2>&1 || true' EXIT

echo "==> [1/4] Python：语法门禁 + 初始化 + 全量回归"
python -m compileall -q src tests
aiink init
EMBED_ENABLED=0 python -m pytest tests/ -q

echo "==> [2/4] Go 网关：vet + 单测（需 Redis :6380，上面已起）"
(cd gateway && go vet ./... && go test -count=1 ./...)

echo "==> [3/4] 前端：lint + 单测 + 构建"
(cd web && npm ci && npm run lint && npm test && npm run build)

if [[ "${SKIP_IMAGES:-0}" != "1" ]]; then
  echo "==> [4/4] 镜像构建（Python + 网关）"
  # 走 compose build 而非裸 docker build：国内网络要 daocloud 基础镜像 + 阿里云 pip / npmmirror /
  # goproxy.cn 覆盖（compose 已配好，DRY 不重复写 build args）；GitHub Actions 境外 runner 用官方源（ci.yml）。
  docker compose build aiink-api aiink-gateway
else
  echo "==> [4/4] 镜像构建已跳过（SKIP_IMAGES=1）"
fi

echo "✔ CI 本地复现全部通过（与 .github/workflows/ci.yml 对齐）"
