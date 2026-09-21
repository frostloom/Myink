// 网关路由装配：Caddy 成为边缘之后，Go 只服务一条业务路由（SSE 进度事件流）。
package handlers

import (
	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"

	"myink/gateway/internal/config"
	"myink/gateway/internal/limiter"
	"myink/gateway/internal/pyapi"
	"myink/gateway/internal/redis"
	"myink/gateway/internal/trace"
)

// NewRouter 装配 SSE 路由与中间件。
//
// 静态托管、API 转发、admin 代理、三层闸门与入队都已交给 Caddy / Python
// （分流见 caddy/Caddyfile）。留在这里的是唯一需要长连接的一条：进度事件流。
func NewRouter(cfg config.Config, r *redis.Client, py *pyapi.Client) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(trace.Middleware())
	// 进程内令牌桶：粗粒度限流（防外部刷接口；细粒度配额走 Python 的三层闸门 §13）
	router.Use(limiter.Middleware(rate.Limit(cfg.RatePerSec), cfg.RateBurst))

	sseH := NewSSEHandler(r, py)

	// 业务路由一律 Bearer（§14.1 ③）。Caddy 只把 /api/v1/tasks/*/events 分流到这里，
	// 其余 /api/v1/* 直达 Python——所以这里没有 SessionMiddleware：会话撤销由 Python
	// 验签 + auth_version 比对负责，Go 侧保留 15 秒一次的自查（见 sse.go）。
	secured := router.Group("/api/v1", JWTMiddleware([]byte(cfg.JWTSecret)))
	secured.GET("/tasks/:task_id/events", sseH.Stream)

	// 存活探针。就绪探针（Redis / DB / worker 心跳）由 Python 的 /readyz 承担，
	// Caddy 把 /healthz 与 /readyz 都分流给 myink-api。
	router.GET("/healthz", Live)

	return router
}
