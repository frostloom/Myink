#!/usr/bin/env bash
# Myink 本地 CI 一键复现（与 .github/workflows/ci.yml 同一套门禁，未配 git remote 时本地验证用）。
# 覆盖：Python 语法门禁 + 全量回归（独立临时 PG / Redis / RabbitMQ）
#        → 前端 lint+test+build → 镜像构建。
# 前置：Docker Desktop 运行中；根目录 .env 已配（无 key 也能跑，测试全 mock LLM）；Python venv 已激活。
# 用法：bash scripts/ci-local.sh          # 全部门禁
#       SKIP_IMAGES=1 bash scripts/ci-local.sh   # 跳过镜像构建（本地日常快跑）
set -euo pipefail

# Windows 控制台默认 GBK：rich 的 ✓/✗ 等符号会 UnicodeEncodeError（myink init 输出），强制 UTF-8。
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 专用端口、临时 PG 数据，避免测试清理或 worker 抢队列影响开发作品。
export DATABASE_URL=postgresql+psycopg://myink_app:myink@127.0.0.1:15432/myink
export ADMIN_DATABASE_URL=postgresql+psycopg://myink:myink@127.0.0.1:15432/myink
export REDIS_URL=redis://127.0.0.1:16380/0
export REDIS_ADDR=127.0.0.1:16380
export AMQP_URL=amqp://myink:myink@127.0.0.1:15673/
export APP_ENV=test
export EMBED_ENABLED=0
export RANKINGS_ENABLED=0
# 身份边界换血后 Python 自己验 JWT，密钥短于 32 字节 → require_auth_configuration 让业务路由全 503。
# CI 没有 .env，必须显式给足长度（与 tests/conftest.py 的 TEST_JWT_SECRET 同值）。
export JWT_SECRET=test-jwt-secret-at-least-32-bytes-long
compose_test=(docker compose -p myink-test -f docker-compose.test.yml)
trap '"${compose_test[@]}" down --volumes >/dev/null 2>&1 || true' EXIT
"${compose_test[@]}" up -d --wait

echo "==> [1/3] Python：语法门禁 + 初始化 + 契约 diff 闸 + 全量回归"
python -m compileall -q src tests
myink init --seed
myink contract export
git diff --exit-code -- spec/api-openapi.json
EMBED_ENABLED=0 python -m pytest tests/ -q

echo "==> [2/3] 前端：lint + 单测 + 构建"
(cd web && npm ci && npm run lint && npm test && npm run build)

if [[ "${SKIP_IMAGES:-0}" != "1" ]]; then
  echo "==> [3/3] 镜像构建（Python + Caddy）"
  # 走 compose build 而非裸 docker build：国内网络要 daocloud 基础镜像 + 阿里云 pip / npmmirror
  # 覆盖（compose 已配好，DRY 不重复写 build args）；GitHub Actions 境外 runner 用官方源（ci.yml）。
  # Caddy 镜像在同一构建里跑 caddy validate：Caddyfile 语法错在这里就红，不留到部署。
  docker compose build myink-api myink-caddy
else
  echo "==> [3/3] 镜像构建已跳过（SKIP_IMAGES=1）"
fi

echo "✔ CI 本地复现全部通过（与 .github/workflows/ci.yml 对齐）"
