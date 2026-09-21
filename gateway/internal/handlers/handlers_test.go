// 网关 HTTP 层测试（httptest 直打 router）：SSE 中继 + JWT 身份断言。
// 活 Redis :6380（SSE 读写 queue:sse:{task_id}）；Python API 用内存 httptest 假服务替代
// （只实现 SSE 需要的两个内部端点：/auth/session 与 /tasks/{id}/access）。
package handlers

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"

	"myink/gateway/internal/config"
	"myink/gateway/internal/pyapi"
	"myink/gateway/internal/redis"
)

func testIdentity(label string) string {
	if _, err := uuid.Parse(label); err == nil {
		return label
	}
	return uuid.NewSHA1(uuid.NameSpaceOID, []byte(label)).String()
}

// bearer 生成 JWT Bearer 头（§14.1 ③：业务路由一律要求已签名 token）。
// 密钥与 newRouter 的 cfg.JWTSecret 同源（config.Load：默认 DevJWTSecret，环境显式
// 设 JWT_SECRET 时两边读同一值），验签一致。
func bearer(t *testing.T, sub string) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub":  testIdentity(sub),
		"tier": "normal",
		"iss":  "myink",
		"iat":  time.Now().Unix(),
		"ver":  1,
		"exp":  time.Now().Add(time.Hour).Unix(),
	})
	s, err := tok.SignedString([]byte(config.Load().JWTSecret))
	if err != nil {
		t.Fatalf("签 JWT 失败: %v", err)
	}
	return "Bearer " + s
}

func newRouter(t *testing.T, r *redis.Client, py *pyapi.Client) *gin.Engine {
	t.Helper()
	cfg := config.Load()
	cfg.RatePerSec = 1000 // 测试不触发限流
	cfg.RateBurst = 1000
	return NewRouter(cfg, r, py)
}

func newTestRedis(t *testing.T) *redis.Client {
	t.Helper()
	r := redis.New(config.Load().RedisAddr, "")
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := r.Ping(ctx); err != nil {
		t.Skipf("myink-redis 不可达: %v", err)
	}
	return r
}

// fakePy 内存假 Python API：只认 SSE 需要的两个内部端点（会话复检 / 归属断言），
// 其余路径一律 404——网关现在也只转发这两个。
func fakePy() *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if serveAuthFixture(w, req) {
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
	}))
}

func TestSSEFrameForward(t *testing.T) {
	r := newTestRedis(t)
	py := pyapi.New(fakePy().URL, 3*time.Second)
	router := newRouter(t, r, py)

	// 预写 running + done 事件到通道（模拟 worker 完整链路；done 触发 handler 收尾）
	// 与 worker 侧 XADD 扁平字段对齐：event=status, status=done
	taskID := "sse-test-task"
	ctx := context.Background()
	// 清理：测试直写不经 worker（无 TTL），不留键会泄漏（曾留一个永不过期的 queue:sse:sse-test-task）
	defer r.Raw().Del(ctx, "queue:sse:"+taskID)
	_, _ = r.XAdd(ctx, "queue:sse:"+taskID, map[string]any{
		"event": "status", "task_id": taskID, "status": "running",
	})
	_, _ = r.XAdd(ctx, "queue:sse:"+taskID, map[string]any{
		"event": "status", "task_id": taskID, "status": "done",
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+taskID+"/events", nil)
	req.Header.Set("Authorization", bearer(t, "dev"))
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("SSE 应 200，实际 %d", w.Code)
	}
	if ct := w.Header().Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") {
		t.Fatalf("应 text/event-stream，实际 %q", ct)
	}
	if buffering := w.Header().Get("X-Accel-Buffering"); buffering != "no" {
		t.Fatalf("SSE 必须显式关闭代理缓冲，实际 %q", buffering)
	}
	out := w.Body.String()
	if !strings.Contains(out, `"status":"running"`) {
		t.Fatalf("应转发 running 帧，实际 %s", out)
	}
	if !strings.Contains(out, `"status":"done"`) {
		t.Fatalf("应转发 done 帧，实际 %s", out)
	}
}

func TestSSEReplayContinuesPastHistoricalTerminal(t *testing.T) {
	r := newTestRedis(t)
	py := pyapi.New(fakePy().URL, 3*time.Second)
	router := newRouter(t, r, py)

	taskID := "sse-resumed-task"
	ctx := context.Background()
	key := "queue:sse:" + taskID
	defer r.Raw().Del(ctx, key)
	events := []map[string]any{
		{"event": "status", "task_id": taskID, "status": "running"},
		{"event": "status", "task_id": taskID, "status": "awaiting_plan"},
		{"event": "status", "task_id": taskID, "status": "queued"},
		{"event": "status", "task_id": taskID, "status": "running"},
		{"event": "artifact_reset", "task_id": taskID, "stage": "write", "chapter_seq": 15, "artifact_id": "write-1"},
		{"event": "artifact_delta", "task_id": taskID, "stage": "write", "chapter_seq": 15, "artifact_id": "write-1", "content": "正文已在生成"},
		{"event": "artifact_complete", "task_id": taskID, "stage": "write", "chapter_seq": 15, "artifact_id": "write-1", "offset": 6},
		{"event": "status", "task_id": taskID, "status": "awaiting_review"},
	}
	for _, event := range events {
		if _, err := r.XAdd(ctx, key, event); err != nil {
			t.Fatal(err)
		}
	}

	req := httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+taskID+"/events", nil)
	req.Header.Set("Authorization", bearer(t, "dev"))
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)
	out := w.Body.String()
	if strings.Contains(out, `"status":"awaiting_plan"`) {
		t.Fatalf("续跑后的回放不应发送历史 awaiting_plan 终态: %s", out)
	}
	if !strings.Contains(out, `"type":"artifact_delta"`) || !strings.Contains(out, "正文已在生成") {
		t.Fatalf("应越过历史终态并回放正文片段: %s", out)
	}
	if !strings.Contains(out, `"status":"awaiting_review"`) {
		t.Fatalf("应以当前最终状态结束回放: %s", out)
	}
}

func TestSSEStreamExpiredReturns410(t *testing.T) {
	r := newTestRedis(t)
	py := pyapi.New(fakePy().URL, 3*time.Second)
	router := newRouter(t, r, py)

	// 任务终态且流已过期（键不存在）。必须在写响应头之前判定：响应头一旦 Flush 就
	// 提交了 200，此后的 410 只能落进 body，浏览器读成 eof 后无限重连 → 写按钮永久禁用。
	taskID := "sse-expired-task"
	ctx := context.Background()
	_ = r.Raw().Del(ctx, "queue:sse:"+taskID).Err()

	req := httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+taskID+"/events", nil)
	req.Header.Set("Authorization", bearer(t, "dev"))
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	if w.Code != http.StatusGone {
		t.Fatalf("流已过期应 410，实际 %d body=%s", w.Code, w.Body.String())
	}
	// Content-Type 是 JSON 而非 text/event-stream，正好证明响应头未被提前提交
	if ct := w.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("410 应为 JSON（响应头未提交），实际 %q", ct)
	}
	if !strings.Contains(w.Body.String(), "sse_stream_expired") {
		t.Fatalf("应提示流过期回退快照，实际 %s", w.Body.String())
	}
}

func TestHealthz(t *testing.T) {
	r := newTestRedis(t)
	router := newRouter(t, r, pyapi.New(fakePy().URL, 3*time.Second))

	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"ok"`) {
		t.Fatalf("healthz 应 200 ok，实际 %d body=%s", w.Code, w.Body.String())
	}
}

// ---- JWT 身份断言（§14.1 ③：长连接只能由网关自己按次验签）----

func TestJWTRejectsMissingToken(t *testing.T) {
	r := newTestRedis(t)
	router := newRouter(t, r, pyapi.New(fakePy().URL, 3*time.Second))

	w := httptest.NewRecorder()
	router.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/v1/tasks/some-task/events", nil))
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("缺 token 应 401，实际 %d body=%s", w.Code, w.Body.String())
	}
}

func TestJWTRejectsBadToken(t *testing.T) {
	r := newTestRedis(t)
	router := newRouter(t, r, pyapi.New(fakePy().URL, 3*time.Second))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/tasks/some-task/events", nil)
	req.Header.Set("Authorization", "Bearer not-a-real-token")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("坏 token 应 401，实际 %d body=%s", w.Code, w.Body.String())
	}
}

func TestJWTGoodTokenSetsTrustedHeader(t *testing.T) {
	// 验签通过 → 透传 X-Myink-User = 可信 sub（身份由 token 决定，与请求里带什么头无关）。
	r := newTestRedis(t)
	router := newRouter(t, r, pyapi.New(fakePy().URL, 3*time.Second))

	taskID := "sse-header-task"
	ctx := context.Background()
	defer r.Raw().Del(ctx, "queue:sse:"+taskID)
	_, _ = r.XAdd(ctx, "queue:sse:"+taskID, map[string]any{
		"event": "status", "task_id": taskID, "status": "done",
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+taskID+"/events", nil)
	req.Header.Set("Authorization", bearer(t, "user-123"))
	req.Header.Set(HeaderUser, "forged-owner")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("好 token 应 200，实际 %d body=%s", w.Code, w.Body.String())
	}
	if got := w.Header().Get(HeaderUser); got != testIdentity("user-123") {
		t.Fatalf("应透传 X-Myink-User=token 里的 sub，实际 %q", got)
	}
}
