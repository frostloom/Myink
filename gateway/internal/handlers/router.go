// 网关路由装配：唯一公网入口（鉴权占位 + 限流 + 三层闸门 + SSE + 转发）。
package handlers

import (
	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"

	"aiink/gateway/internal/config"
	"aiink/gateway/internal/limiter"
	"aiink/gateway/internal/pyapi"
	"aiink/gateway/internal/redis"
	"aiink/gateway/internal/trace"
)

// NewRouter 装配全部路由与中间件。
func NewRouter(cfg config.Config, r *redis.Client, py *pyapi.Client) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(trace.Middleware())
	router.Use(UserMiddleware())
	// 进程内令牌桶：粗粒度限流（防外部刷接口；细粒度配额走 gates.lua §13）
	router.Use(limiter.Middleware(rate.Limit(cfg.RatePerSec), cfg.RateBurst))

	taskH := NewTaskHandler(cfg, r, py)
	sseH := NewSSEHandler(r)
	healthH := NewHealthHandler(cfg, r, py)

	api := router.Group("/api/v1")
	{
		// 项目/章节读（多书展示前端，转发 Python API）
		api.GET("/projects", taskH.ListProjects)
		api.GET("/projects/:project_id/chapters", taskH.ListChapters)
		// 章节编辑 / 记忆校正 / 级联删除（阶段 3：正文轻编辑 + 增量记忆校正，转发 Python API）
		api.PUT("/projects/:project_id/chapters/:chapter_id/content", taskH.UpdateChapterContent)
		api.POST("/projects/:project_id/chapters/:chapter_id/correct-memory", taskH.CorrectMemory)
		api.DELETE("/projects/:project_id/chapters/:chapter_id", taskH.DeleteChapter)
		// 建单章生成任务
		api.POST("/projects/:project_id/chapters/:chapter_id/generate", taskH.CreateChapter)
		// 建批次生成任务
		api.POST("/projects/:project_id/batches/generate", taskH.CreateBatch)
		// 任务详情（转发 Python API）
		api.GET("/tasks/:task_id", taskH.GetTask)
		// 批次控制 pause/resume/cancel（转发 Python API）
		api.POST("/batches/:batch_id/:action", taskH.BatchControl)
		// 记忆候选：待确认池 / 确认 / 拒绝（§6.11 确认分流，转发 Python API）
		api.GET("/projects/:project_id/candidates", taskH.ListCandidates)
		api.POST("/projects/:project_id/candidates/:candidate_id/:action", taskH.CandidateAction)
		api.GET("/projects/:project_id/lessons", taskH.ListLessons)
		api.POST("/projects/:project_id/lessons/:lesson_id/:action", taskH.LessonAction)
		// SSE 进度事件
		api.GET("/tasks/:task_id/events", sseH.Stream)
	}

	// 探针
	router.GET("/healthz", healthH.Live)
	router.GET("/readyz", healthH.Ready)

	// 队列守护（退避重投 / DLQ / 崩溃认领）由 main 启动，不在路由内
	return router
}
