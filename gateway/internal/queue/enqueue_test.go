// 三层闸门 + 入队测试（活 Redis :6380，键用随机 task_id 隔离）。
package queue

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"aiink/gateway/internal/config"
	"aiink/gateway/internal/redis"
)

func newTestRedis(t *testing.T) *redis.Client {
	t.Helper()
	r := redis.New("localhost:6380", "")
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := r.Ping(ctx); err != nil {
		t.Skipf("aiink-redis 不可达: %v", err)
	}
	return r
}

func testConfig() config.Config {
	cfg := config.Load()
	cfg.QuotaDaily = 2
	cfg.ConcurrencyLimit = 1
	cfg.DailyBudget = 1.0
	cfg.CostPerChapter = 0.05
	return cfg
}

// 清理闸门键：避免测试相互污染（每用户独立键 + 每书并发键 + 全局日成本键）。
func cleanupGates(t *testing.T, r *redis.Client, uid string) {
	t.Helper()
	ctx := context.Background()
	today := time.Now().Format("2006-01-02")
	keys, _ := r.Raw().Keys(ctx, "rate:quota:"+uid+":*").Result()
	inflights, _ := r.Raw().Keys(ctx, "rate:inflight:"+uid+":*").Result()
	bookquotas, _ := r.Raw().Keys(ctx, "rate:bookquota:"+uid+":*").Result()
	bookcnts, _ := r.Raw().Keys(ctx, "rate:bookcnt:"+uid+":*").Result()
	keys = append(keys, inflights...)
	keys = append(keys, bookquotas...)
	keys = append(keys, bookcnts...)
	keys = append(keys, "rate:cost:"+today)
	if len(keys) > 0 {
		_ = r.Raw().Del(ctx, keys...).Err()
	}
	cleanupTestMessages(t, r)
}

// 清理本测试入队的消息（proj-1/proj-2 是测试书标记，非 UUID）：
// 否则每次 go test 都在 queue:tasks 累积残留，Python worker 多进程测试会误读。
func cleanupTestMessages(t *testing.T, r *redis.Client) {
	t.Helper()
	ctx := context.Background()
	msgs, err := r.Raw().XRange(ctx, StreamTasks, "-", "+").Result()
	if err != nil {
		return
	}
	var ids []string
	for _, m := range msgs {
		bodyRaw, ok := m.Values["body"].(string)
		if !ok {
			continue
		}
		var body struct {
			Project string `json:"project_id"`
		}
		if json.Unmarshal([]byte(bodyRaw), &body) != nil {
			continue
		}
		if body.Project == "proj-1" || body.Project == "proj-2" {
			ids = append(ids, m.ID)
		}
	}
	if len(ids) > 0 {
		_ = r.Raw().XDel(ctx, StreamTasks, ids...).Err()
	}
}

// costKeyToday 与 gates 侧 costKey 同规则（全局日成本键）。
func costKeyToday() string {
	return "rate:cost:" + time.Now().Format("2006-01-02")
}

func TestEnqueueOK(t *testing.T) {
	r := newTestRedis(t)
	cfg := testConfig()
	cfg.QuotaDaily = 10 // 并发用例需多次入队，配额不能先撞闸
	uid := "dev-test-user-ok"
	cleanupGates(t, r, uid)
	defer cleanupGates(t, r, uid)

	ctx := context.Background()
	res, err := Enqueue(ctx, r, cfg, uid, "proj-1", "chapter_generate",
		map[string]any{"seq": 1, "user_instruction": "写"}, 1, cfg.CostPerChapter)
	if err != nil {
		t.Fatalf("enqueue 应成功: %v", err)
	}
	if res.TaskID == "" {
		t.Fatal("应返回 task_id")
	}
	// 入队后：配额 +1、并发占 1、流中有消息
	quota := r.Raw().Get(ctx, "rate:quota:"+uid+":"+time.Now().Format("2006-01-02")).Val()
	if quota != "1" {
		t.Fatalf("配额应扣 1，实际 %q", quota)
	}
	inflight, _ := r.Raw().SCard(ctx, "rate:inflight:"+uid+":proj-1").Result()
	if inflight != 1 {
		t.Fatalf("并发应占 1，实际 %d", inflight)
	}
	// BYOK 多书：异书应各自独立并发（同 uid 不同 pid 不同 key，不互斥）
	if _, err := Enqueue(ctx, r, cfg, uid, "proj-2", "chapter_generate",
		map[string]any{"seq": 1}, 1, cfg.CostPerChapter); err != nil {
		t.Fatalf("异书入队应不受同书并发闸门影响: %v", err)
	}
	inflight2, _ := r.Raw().SCard(ctx, "rate:inflight:"+uid+":proj-2").Result()
	if inflight2 != 1 {
		t.Fatalf("异书并发应各自占 1，实际 %d", inflight2)
	}
	// 同书第二次入队仍被并发闸门拒绝（同书串行）
	if _, err := Enqueue(ctx, r, cfg, uid, "proj-1", "chapter_generate",
		map[string]any{"seq": 2}, 1, cfg.CostPerChapter); err == nil {
		t.Fatal("同书第二次入队应被并发闸门拒绝")
	} else if ge, ok := err.(*GateError); !ok || ge.Code != "CONCURRENCY_LIMIT" {
		t.Fatalf("应返回 CONCURRENCY_LIMIT，实际 %v", err)
	}
	n, _ := r.Raw().XLen(ctx, StreamTasks).Result()
	if n < 1 {
		t.Fatalf("主队列应有消息，实际 %d", n)
	}
	// 协议回归防护：消息必须是单字段 body = 整条任务 JSON（worker consumer 读 fields["body"]）
	// —— 曾因写成扁平字段导致 worker 全部丢弃。
	msgs, _ := r.Raw().XRange(ctx, StreamTasks, "-", "+").Result()
	if len(msgs) < 1 {
		t.Fatalf("应读到入队消息，实际 %d", len(msgs))
	}
	last := msgs[len(msgs)-1]
	bodyRaw, ok := last.Values["body"].(string)
	if !ok {
		t.Fatalf("消息应含 body 字段，实际 %v", last.Values)
	}
	var body struct {
		TaskID   string `json:"task_id"`
		TaskType string `json:"task_type"`
		Project  string `json:"project_id"`
		User     string `json:"user_id"`
		Retry    int    `json:"retry_count"`
	}
	if err := json.Unmarshal([]byte(bodyRaw), &body); err != nil {
		t.Fatalf("body 应为合法 JSON: %v", err)
	}
	// 最后一条消息是异书 proj-2（按书并发后它入队成功）；协议回归防护的核心是
	// 「单字段 body = 完整任务 JSON」不塌成扁平字段——校验字段完整即可，
	// 不再与 res.TaskID 耦合（改按书并发后 XRange 末条已非首个任务的。
	if body.TaskID == "" || body.TaskType != "chapter_generate" ||
		body.Project != "proj-2" || body.User == "" || body.Retry != 0 {
		t.Fatalf("body 字段应完整对齐，实际 %+v", body)
	}
}

func TestEnqueueQuotaExceeded(t *testing.T) {
	r := newTestRedis(t)
	cfg := testConfig()
	uid := "dev-test-user-quota"
	cleanupGates(t, r, uid)
	defer cleanupGates(t, r, uid)

	ctx := context.Background()
	// 用满配额：先手动把 quota 键设到上限（模拟已有消耗）
	_ = r.Raw().Set(ctx, "rate:quota:"+uid+":"+time.Now().Format("2006-01-02"), "2", 0).Err()

	_, err := Enqueue(ctx, r, cfg, uid, "proj-1", "chapter_generate",
		map[string]any{"seq": 1}, 1, cfg.CostPerChapter)
	if err == nil {
		t.Fatal("配额已满应拒绝")
	}
	ge, ok := err.(*GateError)
	if !ok || ge.Code != "QUOTA_EXCEEDED" {
		t.Fatalf("应返回 GateError QUOTA_EXCEEDED，实际 %v", err)
	}
}

func TestEnqueueBookQuotaExceeded(t *testing.T) {
	// 每书日配额（多书写书 5 本×5 章）：单书配额用满应拒绝，即使总配额未满。
	r := newTestRedis(t)
	cfg := testConfig()
	cfg.BookQuotaDaily = 3 // 单测收紧便于构造
	uid := "dev-test-user-bookq"
	cleanupGates(t, r, uid)
	defer cleanupGates(t, r, uid)

	ctx := context.Background()
	// 手动把这本书的配额键设到上限（模拟已有消耗）
	_ = r.Raw().Set(ctx, "rate:bookquota:"+uid+":proj-1:"+time.Now().Format("2006-01-02"), "3", 0).Err()

	_, err := Enqueue(ctx, r, cfg, uid, "proj-1", "chapter_generate",
		map[string]any{"seq": 1}, 1, cfg.CostPerChapter)
	if err == nil {
		t.Fatal("每书配额已满应拒绝")
	}
	ge, ok := err.(*GateError)
	if !ok || ge.Code != "BOOK_QUOTA_EXCEEDED" {
		t.Fatalf("应返回 BOOK_QUOTA_EXCEEDED，实际 %v", err)
	}
}

func TestEnqueueBookCntExceeded(t *testing.T) {
	// 每天最多 N 本不同书（多书写书：一天最多 10 本书）：书数达到上限后，第 N+1 本
	// 新书即使每本配额未满也应拒绝；已碰过的书重复写不受书数闸门影响。
	r := newTestRedis(t)
	cfg := testConfig()
	cfg.BooksPerDay = 3
	cfg.QuotaDaily = 100 // 排除总量干扰
	uid := "dev-test-user-bookcnt"
	cleanupGates(t, r, uid)
	defer cleanupGates(t, r, uid)

	ctx := context.Background()
	// 前 3 本书各入队 1 章 → 全部通过（书数 1→3）
	for i := 1; i <= 3; i++ {
		pid := fmt.Sprintf("proj-bc-%d", i)
		if _, err := Enqueue(ctx, r, cfg, uid, pid, "chapter_generate",
			map[string]any{"seq": 1}, 1, cfg.CostPerChapter); err != nil {
			t.Fatalf("第 %d 本书应通过: %v", i, err)
		}
	}
	// 第 4 本新书 → BOOK_CNT_EXCEEDED
	if _, err := Enqueue(ctx, r, cfg, uid, "proj-bc-4", "chapter_generate",
		map[string]any{"seq": 1}, 1, cfg.CostPerChapter); err == nil {
		t.Fatal("第 4 本新书应被书数闸门拒绝")
	} else if ge, ok := err.(*GateError); !ok || ge.Code != "BOOK_CNT_EXCEEDED" {
		t.Fatalf("应返回 BOOK_CNT_EXCEEDED，实际 %v", err)
	}
	// 已碰过的书重复入队 → 仍应通过（书数去重，不累加）。
	// 模拟 worker 终态 SREM 释放 proj-bc-1 的并发占位（否则同书第二任务被并发闸门挡，
	// 那不是书数闸门语义），再对同一本书重复入队 → 书数去重应放行。
	members, _ := r.Raw().SMembers(ctx, "rate:inflight:"+uid+":proj-bc-1").Result()
	if len(members) > 0 {
		args := make([]interface{}, len(members))
		for i, m := range members {
			args[i] = m
		}
		_ = r.Raw().SRem(ctx, "rate:inflight:"+uid+":proj-bc-1", args...).Err()
	}
	if _, err := Enqueue(ctx, r, cfg, uid, "proj-bc-1", "chapter_generate",
		map[string]any{"seq": 2}, 1, cfg.CostPerChapter); err != nil {
		t.Fatalf("已碰过的书重复写应通过: %v", err)
	}
}

func TestEnqueueConcurrencyLimit(t *testing.T) {
	r := newTestRedis(t)
	cfg := testConfig()
	uid := "dev-test-user-conc"
	cleanupGates(t, r, uid)
	defer cleanupGates(t, r, uid)

	ctx := context.Background()
	// 手动占用本书并发闸门（模拟已有 running 任务）
	_ = r.Raw().SAdd(ctx, "rate:inflight:"+uid+":proj-1", "existing-task").Err()

	_, err := Enqueue(ctx, r, cfg, uid, "proj-1", "chapter_generate",
		map[string]any{"seq": 1}, 1, cfg.CostPerChapter)
	if err == nil {
		t.Fatal("并发闸门被占应拒绝")
	}
	ge, ok := err.(*GateError)
	if !ok || ge.Code != "CONCURRENCY_LIMIT" {
		t.Fatalf("应返回 CONCURRENCY_LIMIT，实际 %v", err)
	}
}

func TestEnqueueDailyBudgetExceeded(t *testing.T) {
	r := newTestRedis(t)
	cfg := testConfig()
	uid := "dev-test-user-budget"
	cleanupGates(t, r, uid)
	defer cleanupGates(t, r, uid)

	ctx := context.Background()
	// 成本键已用满（日预算 1.0）
	_ = r.Raw().Set(ctx, costKeyToday(), "1.0", 0).Err()

	_, err := Enqueue(ctx, r, cfg, uid, "proj-1", "batch_generate",
		map[string]any{"size": 2, "start": 1}, 2, cfg.CostPerChapter*2)
	if err == nil {
		t.Fatal("日成本超限应拒绝")
	}
	ge, ok := err.(*GateError)
	if !ok || ge.Code != "DAILY_BUDGET_EXCEEDED" {
		t.Fatalf("应返回 DAILY_BUDGET_EXCEEDED，实际 %v", err)
	}
}

func TestEnqueueBatchDeductN(t *testing.T) {
	r := newTestRedis(t)
	cfg := testConfig()
	cfg.QuotaDaily = 10 // 批次 size=3 要能通过配额
	uid := "dev-test-user-batch"
	cleanupGates(t, r, uid)
	defer cleanupGates(t, r, uid)

	ctx := context.Background()
	_, err := Enqueue(ctx, r, cfg, uid, "proj-1", "batch_generate",
		map[string]any{"size": 3, "start": 1}, 3, cfg.CostPerChapter*3)
	if err != nil {
		t.Fatalf("批次入队应成功: %v", err)
	}
	quota := r.Raw().Get(ctx, "rate:quota:"+uid+":"+time.Now().Format("2006-01-02")).Val()
	if quota != "3" {
		t.Fatalf("批次应一次性扣 N=3，实际 %q", quota)
	}
}
