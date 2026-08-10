// Package limiter 网关进程内限流（令牌桶，golang.org/x/time/rate）。
// 粗粒度整体限流在网关层，防外部刷接口；细粒度按用户配额/并发/日成本走 gates.lua（§13）。
package limiter

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"
)

// Middleware 令牌桶中间件：超速返回 429，未超速放行。
func Middleware(r rate.Limit, burst int) gin.HandlerFunc {
	lim := rate.NewLimiter(r, burst)
	return func(c *gin.Context) {
		if !lim.Allow() {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": "rate_limited"})
			return
		}
		c.Next()
	}
}
