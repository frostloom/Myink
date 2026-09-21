# Myink Go 网关镜像：SSE 中继二进制 + 精简运行层。
# 前端静态产物与 Caddy 一起构建，见 caddy/Dockerfile（网关不再托管 web/dist）。
#
# 基础镜像源可用 build arg 覆盖（国内 docker.io 直连可能超时；compose 当前环境传
# GOLANG_IMAGE/DEBIAN_IMAGE=docker.m.daocloud.io/library/...，见 docker-compose.yml）。
ARG GOLANG_IMAGE=golang:1.26.1-alpine
ARG DEBIAN_IMAGE=debian:bookworm-slim

# 阶段 1：构建网关二进制（pure Go 静态编译，alpine 可跑）
FROM ${GOLANG_IMAGE} AS build
# go 模块代理可覆盖（国内 proxy.golang.org 不通，compose 传 goproxy.cn）
ARG GOPROXY=https://proxy.golang.org,direct
ENV GOPROXY=${GOPROXY}
WORKDIR /app/gateway
COPY gateway/go.mod gateway/go.sum ./
RUN go mod download
COPY gateway/ ./
RUN CGO_ENABLED=0 go build -o /out/gateway ./cmd/gateway

# 阶段 2：精简运行层（debian slim，只含二进制）
FROM ${DEBIAN_IMAGE}
COPY --from=build /out/gateway /usr/local/bin/gateway
EXPOSE 8080
# compose 通过环境变量注入 REDIS_ADDR/PYTHON_API_BASE/RATE_PER_SEC/RATE_BURST
# （无需 .env 文件，main.go loadDotEnv 找不到即忽略）
ENTRYPOINT ["gateway"]
