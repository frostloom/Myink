# Myink 边缘层镜像：前端静态产物 + Caddy 二进制。
#
# 静态产物（web/dist）与 Caddy 二进制同镜像：发前端的人就是 Caddy，多阶段构建到同层里。
#
# 基础镜像源可用 build arg 覆盖（国内 docker.io 直连可能超时；compose 当前环境传
# NODE_IMAGE/CADDY_IMAGE=docker.m.daocloud.io/library/...，见 docker-compose.yml）。
#
# 阶段 1：构建前端静态产物（vite build，base=/，产物含 index.html/assets/favicon）
ARG NODE_IMAGE=node:24.22.1-alpine
ARG CADDY_IMAGE=caddy:2.11.4-alpine
# Vue is the normal product; React remains an explicit rollback build.
ARG FRONTEND_VARIANT=vue
FROM ${NODE_IMAGE} AS web
# npm 源可覆盖（国内 registry.npmjs.org 可能不通，compose 传 npmmirror）
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --registry=${NPM_REGISTRY}
COPY web/ ./
ARG FRONTEND_VARIANT
RUN case "$FRONTEND_VARIANT" in \
      react) npm run build:react && mkdir -p /app/frontend-dist && cp -a dist/. /app/frontend-dist/ ;; \
      vue) npm run build && mkdir -p /app/frontend-dist && cp -a dist-vue/. /app/frontend-dist/ ;; \
      *) echo "FRONTEND_VARIANT must be react or vue" >&2; exit 64 ;; \
    esac

COPY caddy/retained-assets/ /app/retained-assets/
RUN node scripts/merge-retained-assets.mjs /app/retained-assets /app/frontend-dist/assets

# 阶段 2：Caddy 运行层（Caddyfile + dist）
FROM ${CADDY_IMAGE}
ARG FRONTEND_VARIANT
LABEL io.myink.frontend=${FRONTEND_VARIANT}
COPY caddy/Caddyfile /etc/caddy/Caddyfile
# 站点块用 import 按 CADDY_SITE_TLS 选这两个片段（默认 tls-auto.caddyfile 是空操作）。
# 必须一起 COPY：import 的目标文件在运行时要真的存在，缺了会在启动时找不到文件。
COPY caddy/tls-auto.caddyfile /etc/caddy/tls-auto.caddyfile
COPY caddy/tls-public-ip.caddyfile /etc/caddy/tls-public-ip.caddyfile
COPY --from=web /app/frontend-dist /srv/web/dist
# 构建期校验配置语法：Caddyfile 写错要在 build 就红，而不是留到部署时容器起不来。
# 用默认 SITE_ADDRESS（http://localhost）校验 —— 语法不随取值变化，只有协议/证书那段不同。
RUN caddy validate --config /etc/caddy/Caddyfile

# 非 root 运行（alpine 的 busybox adduser）。容器内非 root 也能绑 80/443：Docker 默认
# 能力集里就有 NET_BIND_SERVICE。Caddy 要写的是 /data（证书 + ACME 账户）与 /config
#（自动保存的运行配置），这两个在 compose 里都是命名卷——全新卷会继承这里的属主，
# 已存在的卷仍是 root，切换前要 chown 一次，见 docs/DEPLOY.md。
RUN addgroup -S -g 10001 caddy && adduser -S -D -H -u 10001 -G caddy caddy \
    && chown -R caddy:caddy /data /config
USER 10001

EXPOSE 80 443 443/udp
# 构建来源自证，与 Python 镜像同一套（compose 传 GIT_REVISION，读法见 docs/DEPLOY.md）。
# 前端与后端是两个镜像，各自带同一个 revision，出问题时能确认「这页面对的是这版后端」。
ARG GIT_REVISION=unknown
LABEL org.opencontainers.image.revision=${GIT_REVISION}
