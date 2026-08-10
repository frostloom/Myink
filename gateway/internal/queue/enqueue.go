// Package queue 任务入队 + 三层闸门（§13）+ 退避重投 / DLQ / 崩溃认领（§6.12）。
package queue

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"

	"aiink/gateway/internal/config"
	"aiink/gateway/internal/redis"
)

//go:embed gates.lua
var gatesScript string

const (
	StreamTasks = "queue:tasks"
	StreamDelay = "queue:delay"
	StreamDLQ   = "queue:dlq"
)

type EnqueueResult struct {
	TaskID  string `json:"task_id"`
	TraceID string `json:"trace_id"`
}

type GateError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

func (e *GateError) Error() string { return e.Message }

// Enqueue 原子执行三层闸门 + 入队（gates.lua，消灭 TOCTOU）。
// userID 阶段 2 占位（X-AiInk-User 头）；projectID 由网关从路径取。
// taskType: chapter_generate | batch_generate。
// payload 含章节/批次参数；quotaDeductN 单章=1、批次=N（§13 批次扣减）。
func Enqueue(ctx context.Context, r *redis.Client, cfg config.Config,
	userID, projectID, taskType string, payload map[string]any, quotaDeductN int, costEst float64) (*EnqueueResult, error) {

	now := time.Now()
	taskID := uuid.NewString()
	quotaKey := fmt.Sprintf("rate:quota:%s:%s", userID, now.Format("2006-01-02"))
	costKey := fmt.Sprintf("rate:cost:%s", now.Format("2006-01-02"))

	// 消息体与 worker 侧对齐（consumer 读 fields["body"]，processor 取 task_id/payload/...）：
	// queue:tasks 单字段 body = 整条任务字典 JSON，payload 保持嵌套对象而非字符串。
	bodyJSON, err := json.Marshal(map[string]any{
		"task_id":     taskID,
		"task_type":   taskType,
		"project_id":  projectID,
		"user_id":     userID,
		"payload":     payload,
		"trace_id":    taskID,
		"request_id":  taskID,
		"retry_count": 0,
		"created_at":  now.UnixMilli(),
	})
	if err != nil {
		return nil, err
	}

	res, err := r.Eval(ctx, gatesScript,
		// 并发闸门按书粒度（§13 BYOK：每书 1 并发，异书并行；同书串行靠 worker 侧 book 锁）
		[]string{StreamTasks, quotaKey, fmt.Sprintf("rate:inflight:%s:%s", userID, projectID), costKey,
			// 每书日配额（多书写书双层限制）
			fmt.Sprintf("rate:bookquota:%s:%s:%s", userID, projectID, now.Format("2006-01-02")),
			// 每天最多 N 本不同书（Set 去重，成员=project_id）
			fmt.Sprintf("rate:bookcnt:%s:%s", userID, now.Format("2006-01-02"))},
		taskID, string(bodyJSON),
		fmt.Sprint(quotaDeductN), fmt.Sprint(costEst),
		fmt.Sprint(cfg.QuotaDaily), fmt.Sprint(cfg.DailyBudget), fmt.Sprint(cfg.BookQuotaDaily),
		fmt.Sprint(cfg.BooksPerDay), projectID)
	if err != nil {
		return nil, err
	}
	// Lua 返回 []any{int64 code, string reason, ...}
	arr, ok := res.([]any)
	if !ok || len(arr) == 0 {
		return nil, fmt.Errorf("gates.lua 异常返回: %v", res)
	}
	code := arr[0].(int64)
	if code != 1 {
		reason, _ := arr[1].(string)
		return nil, &GateError{Code: reason, Message: reason}
	}
	return &EnqueueResult{TaskID: taskID, TraceID: taskID}, nil
}
