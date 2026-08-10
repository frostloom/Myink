// Package handlers 网关 HTTP 层（阶段 2，唯一公网入口）。
// 身份阶段 2 占位：X-AiInk-User 头，缺省 dev-user（阶段 3 换 JWT + project.user_id 断言）。
package handlers

import (
	"github.com/gin-gonic/gin"

	"aiink/gateway/internal/trace"
)

const HeaderUser = "X-AiInk-User"

// UserMiddleware 从请求头取用户身份，写入上下文 + 透传响应头。
// 网关只做占位解析，RLS 租户上下文由 Python API 侧维护（安全真源，§17.2）。
func UserMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		uid := c.GetHeader(HeaderUser)
		if uid == "" {
			uid = "dev-user"
		}
		c.Set("user_id", uid)
		c.Header(HeaderUser, uid)
		c.Next()
	}
}

// GetUserID 取当前请求用户 ID（UserMiddleware 之后）。
func GetUserID(c *gin.Context) string {
	if v, ok := c.Get("user_id"); ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return "dev-user"
}

// GetTraceID 取当前请求 trace_id（trace.Middleware 之后）。
func GetTraceID(c *gin.Context) string {
	return trace.GetRequestID(c)
}
