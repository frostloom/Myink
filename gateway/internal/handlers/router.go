// 网关路由装配：唯一公网入口（鉴权占位 + 限流 + 三层闸门 + SSE + 转发）。
package handlers

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"

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
	// 进程内令牌桶：粗粒度限流（防外部刷接口；细粒度配额走 gates.lua §13）
	router.Use(limiter.Middleware(rate.Limit(cfg.RatePerSec), cfg.RateBurst))

	taskH := NewTaskHandler(cfg, r, py)
	sseH := NewSSEHandler(r)
	healthH := NewHealthHandler(cfg, r, py)

	api := router.Group("/api/v1")
	// 签发端点不挂 JWT（否则无法登录）；业务路由一律 Bearer（§14.1 ③）
	api.POST("/auth/token", taskH.AuthToken)

	secured := api.Group("", JWTMiddleware([]byte(cfg.JWTSecret)))
	{
		// 项目/章节读（多书展示前端，转发 Python API）
		secured.GET("/projects", taskH.ListProjects)
		secured.POST("/projects", taskH.CreateProject)
		// 作品信息更新（§6.9 每章目标字数可配）
		secured.PUT("/projects/:project_id", taskH.UpdateProject)
		secured.GET("/projects/:project_id/chapters", taskH.ListChapters)
		// 章节详情（含正文/summary，阶段 4 前端章节编辑器读取正文；转发 Python API）
		secured.GET("/projects/:project_id/chapters/:chapter_id", taskH.GetChapter)
		// 章节编辑 / 记忆校正 / 级联删除 / 全局审计（阶段 3：正文轻编辑 + 增量记忆校正 + 长线治理，转发 Python API）
		secured.PUT("/projects/:project_id/chapters/:chapter_id/content", taskH.UpdateChapterContent)
		secured.POST("/projects/:project_id/chapters/:chapter_id/correct-memory", taskH.CorrectMemory)
		secured.DELETE("/projects/:project_id/chapters/:chapter_id", taskH.DeleteChapter)
		// 章节历史版本（阶段 4 版本表：列表/回退，转发 Python API）
		secured.GET("/projects/:project_id/chapters/:chapter_id/versions", taskH.ListChapterVersions)
		secured.POST("/projects/:project_id/chapters/:chapter_id/versions/:version/restore", taskH.RestoreChapterVersion)
		secured.POST("/projects/:project_id/global-audit", taskH.GlobalAudit)
		// 全局审计报告读（阶段 4 审计视图：列表/详情，转发 Python API）
		secured.GET("/projects/:project_id/global-audit", taskH.ListGlobalAudits)
		secured.GET("/projects/:project_id/global-audit/:report_id", taskH.GetGlobalAudit)
		// 创作设置（阶段 4：文风档案/样本提取/预设导入 + 每 Agent 模型路由，转发 Python API）
		secured.GET("/projects/:project_id/settings", taskH.ListSettings)
		secured.PUT("/projects/:project_id/settings", taskH.UpdateSettings)
		secured.GET("/skill-presets", taskH.SkillPresets)
		secured.POST("/projects/:project_id/style-samples", taskH.StyleSamples)
		secured.PUT("/projects/:project_id/style-profile", taskH.PutStyleProfile)
		// 建书向导 + 设定浏览（§7.11：创建作品 / 设定草稿 / 确认落库 / 世界观 / 人物卡片，转发 Python API）
		secured.POST("/projects/:project_id/setup-draft", taskH.SetupDraft)
		secured.PUT("/projects/:project_id/setup", taskH.Setup)
		secured.GET("/projects/:project_id/world", taskH.GetWorld)
		secured.GET("/projects/:project_id/characters", taskH.GetCharacters)
		// 设定实体浏览（§7.11 ④ 自动建档：武器/功法/技能/地点）
		secured.GET("/projects/:project_id/entities", taskH.ListEntities)
		// 建单章生成任务
		secured.POST("/projects/:project_id/chapters/:chapter_id/generate", taskH.CreateChapter)
		// 建批次生成任务
		secured.POST("/projects/:project_id/batches/generate", taskH.CreateBatch)
		// 项目任务历史（阶段 4 任务视图：切书后展示该书过往任务，转发 Python API）
		secured.GET("/projects/:project_id/tasks", taskH.ListProjectTasks)
		// 任务详情（转发 Python API）
		secured.GET("/tasks/:task_id", taskH.GetTask)
		// 批次控制 pause/resume/cancel（转发 Python API）
		secured.POST("/batches/:batch_id/:action", taskH.BatchControl)
		// 记忆候选：待确认池 / 确认 / 拒绝（§6.11 确认分流，转发 Python API）
		secured.GET("/projects/:project_id/candidates", taskH.ListCandidates)
		secured.POST("/projects/:project_id/candidates/:candidate_id/:action", taskH.CandidateAction)
		secured.GET("/projects/:project_id/lessons", taskH.ListLessons)
		secured.POST("/projects/:project_id/lessons/:lesson_id/:action", taskH.LessonAction)
		// SSE 进度事件
		secured.GET("/tasks/:task_id/events", sseH.Stream)
	}

	// 探针
	router.GET("/healthz", healthH.Live)
	router.GET("/readyz", healthH.Ready)

	// 阶段 5：前端静态托管（唯一入口 8080 同源出页面 + API）。
	// /assets 静态产物走 gin.Static；其余未匹配路径：/api、探针保持 JSON 404，
	// 前端 BrowserRouter 深链（/projects/:pid 刷新等）回退 index.html（SPA fallback）。
	dist := cfg.WebDistDir
	router.Static("/assets", filepath.Join(dist, "assets"))
	router.NoRoute(func(c *gin.Context) {
		p := c.Request.URL.Path
		if strings.HasPrefix(p, "/api/") || p == "/healthz" || p == "/readyz" {
			c.JSON(http.StatusNotFound, gin.H{"error": "not_found"})
			return
		}
		rel := strings.TrimPrefix(p, "/")
		// 防路径穿越（段级判断）：统一把反斜杠归一为正斜杠，再按段判断，
		// 兼容 Windows 本地运行时（filepath 以 \ 为分隔符，/foo\..\secret 也会逃出 dist）
		rel = strings.ReplaceAll(rel, "\\", "/")
		if strings.HasPrefix(rel, "..") || strings.Contains(rel, "/..") {
			c.File(filepath.Join(dist, "index.html"))
			return
		}
		f := filepath.Join(dist, filepath.Clean(filepath.FromSlash(rel)))
		if info, err := os.Stat(f); err == nil && !info.IsDir() {
			c.File(f)
			return
		}
		c.File(filepath.Join(dist, "index.html"))
	})

	// 队列守护（退避重投 / DLQ / 崩溃认领）由 main 启动，不在路由内
	return router
}
