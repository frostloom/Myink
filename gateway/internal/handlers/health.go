// 网关存活探针。
package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// Live 存活探针：进程在即 200（K8s liveness，不做依赖检查）。
// GET /healthz
//
// 就绪探针（Redis / Python API / worker 心跳）已移交 Python 的 /readyz——
// 网关不再是公网入口，依赖状态由真正持有依赖的那个进程报告。
func Live(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}
