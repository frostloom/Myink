// 网关 SSE 路由：浏览器订阅 queue:sse:{task_id}，断线 Last-Event-ID 重放。
package handlers

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"aiink/gateway/internal/redis"
	"aiink/gateway/internal/sse"
)

// 硬超时兜底：防止终态事件缺失时连接挂死（正常由 done/failed 事件收尾）
const sseMaxDuration = 30 * time.Minute

// errTerminal 内部哨兵：SSE 收到终态帧后停止订阅
var errTerminal = errors.New("terminal_event")

type SSEHandler struct {
	r *redis.Client
}

func NewSSEHandler(r *redis.Client) *SSEHandler { return &SSEHandler{r: r} }

// Stream 订阅任务进度事件并转发 SSE 帧。
// GET /api/v1/tasks/:task_id/events?last_event_id=xxx
func (h *SSEHandler) Stream(c *gin.Context) {
	taskID := c.Param("task_id")
	after := c.Query("last_event_id")
	if after == "" {
		after = c.GetHeader("Last-Event-ID")
	}
	after = sse.ParseLastEventID(after)

	// 强制响应头：SSE 必须 text/event-stream + 关缓冲
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Writer.Flush()

	ctx, cancel := context.WithTimeout(c.Request.Context(), sseMaxDuration)
	defer cancel()

	// 15s 心跳注释帧保中间代理连接（终态帧触发收尾前一直发）
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				_, _ = fmt.Fprint(c.Writer, ": keepalive\n\n")
				c.Writer.Flush()
			}
		}
	}()

	err := sse.Subscribe(ctx, h.r, taskID, after, func(ev sse.Event) error {
		_, werr := fmt.Fprint(c.Writer, sse.WriteEvent(ev))
		c.Writer.Flush()
		if isTerminal(ev) {
			return errTerminal // 终态帧 → 停止订阅收尾
		}
		return werr
	})
	switch {
	case err == nil || errors.Is(err, errTerminal):
		// 正常结束（终态帧已发 / 客户端断开）
		return
	case errors.Is(err, sse.ErrStreamGone):
		// 通道不存在：任务终态且流已过期 → 客户端回退 GET 快照
		c.AbortWithStatusJSON(http.StatusGone, gin.H{"error": "sse_stream_expired", "hint": "fallback_get_snapshot"})
	default:
		c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": "sse_read_failed"})
	}
}

// isTerminal 终态判定：worker 终态事件是 event=status + status∈{done,failed,awaiting_review}。
func isTerminal(ev sse.Event) bool {
	switch ev.Status {
	case "done", "failed", "awaiting_review", "cancelled":
		return true
	}
	return false
}
