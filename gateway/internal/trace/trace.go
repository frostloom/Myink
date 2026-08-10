// Package trace 全链路 trace（§17.2）：request_id → task_id(thread_id) → agent_runs。
// 网关中间件生成 request_id，随任务消息入队；响应头 + 响应体都带。
package trace

import (
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

const (
	HeaderRequestID = "X-Request-ID"
	HeaderTraceID   = "X-Trace-ID"
)

// Middleware 为每个请求生成 request_id（幂等：已带则不覆盖），写日志 + 响应头。
func Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := c.GetHeader(HeaderRequestID)
		if rid == "" {
			rid = uuid.NewString()
		}
		c.Set("request_id", rid)
		c.Set("trace_id", rid)
		c.Header(HeaderRequestID, rid)
		c.Next()
	}
}

// GetRequestID 从上下文取 request_id（middleware 之后可用）。
func GetRequestID(c *gin.Context) string {
	if v, ok := c.Get("request_id"); ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
}
