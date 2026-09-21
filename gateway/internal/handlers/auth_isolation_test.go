package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"myink/gateway/internal/config"
	"myink/gateway/internal/pyapi"
)

const isolationUser = "a1111111-1111-4111-8111-111111111111"

func strictToken(t *testing.T, change func(jwt.MapClaims)) string {
	t.Helper()
	claims := jwt.MapClaims{"sub": isolationUser, "iss": "myink", "iat": time.Now().Unix(), "exp": time.Now().Add(time.Hour).Unix(), "ver": 1, "tier": "normal"}
	if change != nil {
		change(claims)
	}
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(config.Load().JWTSecret))
	if err != nil {
		t.Fatal(err)
	}
	return "Bearer " + token
}

func TestJWTRejectsMissingSecurityClaims(t *testing.T) {
	for _, version := range []any{0, -1, 1.5, true, "1"} {
		token := strictToken(t, func(c jwt.MapClaims) { c["ver"] = version })
		if _, _, err := verifyJWT(token, []byte(config.Load().JWTSecret)); err == nil {
			t.Fatalf("accepted invalid session version %v", version)
		}
	}
	for _, claim := range []string{"iss", "exp", "iat", "ver"} {
		t.Run(claim, func(t *testing.T) {
			token := strictToken(t, func(c jwt.MapClaims) { delete(c, claim) })
			if _, _, err := verifyJWT(token, []byte(config.Load().JWTSecret)); err == nil {
				t.Fatalf("accepted token without %s", claim)
			}
		})
	}
	for _, value := range []string{"wrong-issuer", "invalid-subject"} {
		t.Run(value, func(t *testing.T) {
			token := strictToken(t, func(c jwt.MapClaims) {
				if value == "wrong-issuer" {
					c["iss"] = "other"
				} else {
					c["sub"] = "not-a-uuid"
				}
			})
			if _, _, err := verifyJWT(token, []byte(config.Load().JWTSecret)); err == nil {
				t.Fatal("accepted invalid identity")
			}
		})
	}
}

// 伪造的 X-Myink-User 头既不能自证身份，也不能覆盖 token 里的 sub：送到 Python 归属接口的
// 必须是验签后的 sub。上游一旦看到别的值，就等于越权的钥匙被转发过去了。
func TestForgedIdentityHeaderIsIgnoredByAccessCheck(t *testing.T) {
	accessCalls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/api/v1/auth/session" {
			json.NewEncoder(w).Encode(map[string]string{"user_id": isolationUser, "username": "owner", "tier": "normal"})
			return
		}
		if strings.HasSuffix(r.URL.Path, "/access") {
			accessCalls++
			if r.Header.Get(HeaderUser) != isolationUser {
				t.Errorf("untrusted identity forwarded: %s", r.Header.Get(HeaderUser))
			}
			w.WriteHeader(403)
			fmt.Fprint(w, `{"detail":"forbidden"}`)
			return
		}
		t.Errorf("unexpected upstream call %s", r.URL.Path)
	}))
	defer upstream.Close()
	// Nil Redis ensures authorization happens before touching it.
	router := NewRouter(config.Load(), nil, pyapi.New(upstream.URL, time.Second))
	request := httptest.NewRequest("GET", "/api/v1/tasks/c1111111-1111-4111-8111-111111111111/events", nil)
	request.Header.Set("Authorization", strictToken(t, nil))
	request.Header.Set(HeaderUser, "forged-owner")
	result := httptest.NewRecorder()
	router.ServeHTTP(result, request)
	if result.Code != 403 || accessCalls != 1 {
		t.Fatalf("status=%d access checks=%d body=%s", result.Code, accessCalls, result.Body.String())
	}
}

func TestOpenSSEClosesAfterSessionRevocation(t *testing.T) {
	testSSESessionDeadline(t, false)
}

func TestOpenSSEClosesAtTokenExpiry(t *testing.T) {
	testSSESessionDeadline(t, true)
}

func testSSESessionDeadline(t *testing.T, expire bool) {
	t.Helper()
	r := newTestRedis(t)
	taskID := "d1111111-1111-4111-8111-111111111111"
	key := "queue:sse:" + taskID
	r.Raw().Del(context.Background(), key)
	r.XAdd(context.Background(), key, map[string]any{"event": "status", "status": "running"})
	t.Cleanup(func() { r.Raw().Del(context.Background(), key) })
	var revoked atomic.Bool
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.URL.Path == "/api/v1/auth/session" {
			if revoked.Load() {
				w.WriteHeader(401)
				return
			}
			json.NewEncoder(w).Encode(map[string]string{"user_id": isolationUser, "username": "owner", "tier": "normal"})
			return
		}
		fmt.Fprint(w, `{"ok":true}`)
	}))
	defer upstream.Close()
	server := httptest.NewServer(NewRouter(config.Load(), r, pyapi.New(upstream.URL, time.Second)))
	defer server.Close()
	// 撤销后的最坏发现时延 = 心跳/重验 ticker 15s（sse.go:86）+ validSession 5s 超时 = 20s。
	// 这里给 30s：若沿用 20s，测试预算恰好等于被测行为的上界，负载稍高就自己撞 deadline
	// 假失败（跨包并行 `go test ./...` 下实测偶发）。断言本身不放宽。
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", server.URL+"/api/v1/tasks/"+taskID+"/events", nil)
	req.Header.Set("Authorization", strictToken(t, func(claims jwt.MapClaims) {
		if expire {
			claims["exp"] = time.Now().Add(2 * time.Second).Unix()
		}
	}))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("status=%d", resp.StatusCode)
	}
	if resp.Header.Get("Cache-Control") != "no-store" {
		t.Fatalf("private SSE must not be cached: %s", resp.Header.Get("Cache-Control"))
	}
	if !expire {
		revoked.Store(true)
	}
	started := time.Now()
	if _, err = io.ReadAll(resp.Body); err != nil {
		t.Fatalf("revoked stream did not close before deadline: %v", err)
	}
	if expire && time.Since(started) > 10*time.Second {
		t.Fatal("expired stream waited for the 15-second session refresh")
	}
}
