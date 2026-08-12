// 网关任务路由：建章 / 建批次 → 三层闸门入队；任务详情 → 转发 Python API（§17.2）。
package handlers

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"aiink/gateway/internal/config"
	"aiink/gateway/internal/pyapi"
	"aiink/gateway/internal/queue"
	"aiink/gateway/internal/redis"
)

type TaskHandler struct {
	cfg config.Config
	r   *redis.Client
	py  *pyapi.Client
}

func NewTaskHandler(cfg config.Config, r *redis.Client, py *pyapi.Client) *TaskHandler {
	return &TaskHandler{cfg: cfg, r: r, py: py}
}

// 建单章生成任务（三层闸门扣 1）。
// POST /api/v1/projects/:project_id/chapters/:chapter_id/generate
// body: {"seq": N, "user_instruction": "...", "rewrite": false}
// rewrite=true 显式重写已确认章（§7.3 失效重建，worker _guard_write_order 放行）。
func (h *TaskHandler) CreateChapter(c *gin.Context) {
	projectID := c.Param("project_id")
	chapterID := c.Param("chapter_id")
	var req struct {
		Seq             int    `json:"seq"`
		UserInstruction string `json:"user_instruction"`
		Rewrite         bool   `json:"rewrite"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_body"})
		return
	}
	payload := map[string]any{
		"chapter_id":       chapterID,
		"seq":              req.Seq,
		"user_instruction": req.UserInstruction,
	}
	if req.Rewrite {
		payload["rewrite"] = true
	}
	h.enqueue(c, projectID, "chapter_generate", payload, 1, h.cfg.CostPerChapter)
}

// 建批次生成任务（三层闸门扣 size）。
// POST /api/v1/projects/:project_id/batches/generate
// body: {"size": N, "start": M}
func (h *TaskHandler) CreateBatch(c *gin.Context) {
	projectID := c.Param("project_id")
	var req struct {
		Size  int `json:"size"`
		Start int `json:"start"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid_body"})
		return
	}
	// 批次上限（§6.11 成本熔断第一道闸）：前端可调 ≤ 默认，超硬上限 clamp（不拒绝，
	// 与 Python 侧 batch_max_hard 对齐；worker 消费时同 clamp 双保险）
	if req.Size < 1 {
		req.Size = 1
	}
	if req.Size > h.cfg.BatchMaxHard {
		req.Size = h.cfg.BatchMaxHard
	}
	// start 缺省/非法 → 1（复查 B1）：Go 零值 0 会穿透到 worker，让批次从第 0 章写起；
	// 权威写序校验在 worker（_guard_write_order，首章必须 = max_seq+1），网关只做语法层。
	if req.Start < 1 {
		req.Start = 1
	}
	payload := map[string]any{"size": req.Size, "start": req.Start}
	h.enqueue(c, projectID, "batch_generate", payload, req.Size, h.cfg.CostPerChapter*float64(req.Size))
}

// enqueue 三层闸门 → 入队 → 202 + task_id；闸门拒绝转对应状态码。
func (h *TaskHandler) enqueue(c *gin.Context, projectID, taskType string, payload map[string]any, quotaN int, costEst float64) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()

	res, err := queue.Enqueue(ctx, h.r, h.cfg, GetUserID(c), projectID, taskType, payload, quotaN, costEst)
	if err != nil {
		var ge *queue.GateError
		if errors.As(err, &ge) {
			// 三层闸门拒绝：配额/并发/成本超限
			c.JSON(http.StatusTooManyRequests, gin.H{"error": ge.Code})
			return
		}
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "enqueue_failed"})
		return
	}
	c.JSON(http.StatusAccepted, gin.H{
		"task_id":  res.TaskID,
		"trace_id": res.TraceID,
		"status":   "queued",
	})
}

// 任务详情：转发 Python API（任务状态 + 批次进度 i/N）。
// GET /api/v1/tasks/:task_id
func (h *TaskHandler) GetTask(c *gin.Context) {
	taskID := c.Param("task_id")
	body, status, err := h.py.GetTaskDetail(c.Request.Context(), taskID)
	if err != nil {
		// 上游明确"任务不存在"（入队→DB 物化的异步窗口内正常）→ 透传 404，
		// 前端轮询视为"在途"继续等，而非报错；其余 5xx/连接失败才按不可达 502。
		if status == http.StatusNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "task_not_found"})
			return
		}
		c.JSON(http.StatusBadGateway, gin.H{"error": "python_api_unreachable"})
		return
	}
	c.Data(http.StatusOK, "application/json; charset=utf-8", body)
}

// 批次控制：pause / resume / cancel，转发 Python API。
// POST /api/v1/batches/:batch_id/:action  (action: pause|resume|cancel)
// 转发到 /internal/v1/tasks/{id}/{action}（Python API 任务控制端点；批次 id = batch 任务 id）。
func (h *TaskHandler) BatchControl(c *gin.Context) {
	batchID := c.Param("batch_id")
	action := c.Param("action")
	h.forwardToPy(c, "/internal/v1/tasks/"+batchID+"/"+action, nil)
}

// 项目列表：转发 Python API（多本书展示前端侧边栏，唯一入口仍走网关）。
// GET /api/v1/projects
func (h *TaskHandler) ListProjects(c *gin.Context) {
	h.forwardToPy(c, "/internal/v1/projects", nil)
}

// 记忆候选：待确认池（§6.11 确认分流）。GET /api/v1/projects/:project_id/candidates
func (h *TaskHandler) ListCandidates(c *gin.Context) {
	pid := c.Param("project_id")
	h.forwardToPy(c, "/internal/v1/projects/"+pid+"/candidates", nil)
}

// 候选确认/拒绝（§7.3 事实生命周期，编排层写库）。
// POST /api/v1/projects/:project_id/candidates/:candidate_id/:action  (action: confirm|reject)
func (h *TaskHandler) CandidateAction(c *gin.Context) {
	pid := c.Param("project_id")
	cid := c.Param("candidate_id")
	action := c.Param("action")
	h.forwardToPy(c, "/internal/v1/projects/"+pid+"/candidates/"+cid+"/"+action, nil)
}

// 写作经验列表（§8.9 reflexion：经验池展示）。
// GET /api/v1/projects/:project_id/lessons
func (h *TaskHandler) ListLessons(c *gin.Context) {
	pid := c.Param("project_id")
	h.forwardToPy(c, "/internal/v1/projects/"+pid+"/lessons", nil)
}

// 经验确认/拒绝（§8.9 reflexion 确认分流，编排层写库）。
// POST /api/v1/projects/:project_id/lessons/:lesson_id/:action  (action: confirm|reject)
func (h *TaskHandler) LessonAction(c *gin.Context) {
	pid := c.Param("project_id")
	lid := c.Param("lesson_id")
	action := c.Param("action")
	h.forwardToPy(c, "/internal/v1/projects/"+pid+"/lessons/"+lid+"/"+action, nil)
}

// 章节列表：转发 Python API（RLS 由 Python 侧 tenant_session 过滤）。
// GET /api/v1/projects/:project_id/chapters
func (h *TaskHandler) ListChapters(c *gin.Context) {
	pid := c.Param("project_id")
	h.forwardToPy(c, "/internal/v1/projects/"+pid+"/chapters", nil)
}

// 编辑章节正文（阶段 3 轻编辑：只更新正文不触记忆，零 LLM）。
// PUT /api/v1/projects/:project_id/chapters/:chapter_id/content
func (h *TaskHandler) UpdateChapterContent(c *gin.Context) {
	pid := c.Param("project_id")
	cid := c.Param("chapter_id")
	body, _ := io.ReadAll(c.Request.Body)
	h.forwardToPy(c, "/internal/v1/projects/"+pid+"/chapters/"+cid+"/content", body)
}

// 显式校正记忆（阶段 3：编辑后正文重新抽取 → 与该章已落库记忆 diff → 变更集进待确认池）。
// 同步 LLM 调用（一次 extract），网关超时 30s；超时属正常，前端可提示重试。
// POST /api/v1/projects/:project_id/chapters/:chapter_id/correct-memory
func (h *TaskHandler) CorrectMemory(c *gin.Context) {
	pid := c.Param("project_id")
	cid := c.Param("chapter_id")
	body, _ := io.ReadAll(c.Request.Body)
	h.forwardToPy(c, "/internal/v1/projects/"+pid+"/chapters/"+cid+"/correct-memory", body)
}

// 级联删除章节（阶段 3：删除该章及其后全部章节正文 + 记忆 + 池候选，进度回退）。
// DELETE /api/v1/projects/:project_id/chapters/:chapter_id
func (h *TaskHandler) DeleteChapter(c *gin.Context) {
	pid := c.Param("project_id")
	cid := c.Param("chapter_id")
	h.forwardToPy(c, "/internal/v1/projects/"+pid+"/chapters/"+cid, nil)
}

// forwardToPy 把请求体原样转发 Python API 并透传响应。
func (h *TaskHandler) forwardToPy(c *gin.Context, path string, body []byte) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()

	header := c.Request.Header.Clone()
	header.Set(HeaderUser, GetUserID(c))
	resp, err := h.py.Forward(ctx, c.Request.Method, path, c.Request.URL.Query(), header, bytes.NewReader(body))
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": "python_api_unreachable"})
		return
	}
	defer resp.Body.Close()
	c.Status(resp.StatusCode)
	c.Header("Content-Type", resp.Header.Get("Content-Type"))
	if _, err := io.Copy(c.Writer, resp.Body); err != nil {
		c.Abort()
	}
}
