# Myink 边缘层镜像：前端静态产物 + Caddy 二进制。
#
# 静态产物（web/dist）与 Caddy 二进制同镜像：发前端的人就是 Caddy，多阶段构建到同层里。
#
# 基础镜像源可用 build arg 覆盖（国内 docker.io 直连可能超时；compose 当前环境传
# NODE_IMAGE/CADDY_IMAGE=docker.m.daocloud.io/library/...，见 docker-compose.yml）。
#
# 阶段 1：构建前端静态产物（vite build，base=/，产物含 index.html/assets/favicon）
ARG NODE_IMAGE=node:20-alpine
ARG CADDY_IMAGE=caddy:2.11.4-alpine
FROM ${NODE_IMAGE} AS web
# npm 源可覆盖（国内 registry.npmjs.org 可能不通，compose 传 npmmirror）
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --registry=${NPM_REGISTRY}
COPY web/ ./
RUN npm run build

# 阶段 2：Caddy 运行层（Caddyfile + dist）
FROM ${CADDY_IMAGE}
COPY caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web /app/web/dist /srv/web/dist
# 构建期校验配置语法：Caddyfile 写错要在 build 就红，而不是留到部署时容器起不来。
# 用默认 SITE_ADDRESS（http://localhost）校验 —— 语法不随取值变化，只有协议/证书那段不同。
RUN caddy validate --config /etc/caddy/Caddyfile
EXPOSE 80 443 443/udp
