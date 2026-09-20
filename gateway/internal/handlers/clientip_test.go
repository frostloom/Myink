package handlers

import (
	"context"
	"crypto/sha256"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"myink/gateway/internal/config"
	"myink/gateway/internal/pyapi"
	"myink/gateway/internal/redis"
)

func clientIPCtx(remoteAddr, xff string) *gin.Context {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest("POST", "/api/v1/auth/token", nil)
	c.Request.RemoteAddr = remoteAddr
	if xff != "" {
		c.Request.Header.Set("X-Forwarded-For", xff)
	}
	return c
}

func TestParseTrustedProxies(t *testing.T) {
	nets := ParseTrustedProxies([]string{"10.0.0.0/8", " 127.0.0.1 ", "2001:db8::1", "", "not-an-ip", "999.1.1.1/8"})
	if len(nets) != 3 {
		t.Fatalf("解析出 %d 段，期望 3（裸 IPv4 按 /32、裸 IPv6 按 /128，垃圾条目丢弃）", len(nets))
	}
	for _, want := range []string{"10.1.2.3", "127.0.0.1", "2001:db8::1"} {
		if !ipInAny(net.ParseIP(want), nets) {
			t.Fatalf("%s 应在可信段内", want)
		}
	}
	for _, reject := range []string{"11.0.0.1", "127.0.0.2", "2001:db9::1"} {
		if ipInAny(net.ParseIP(reject), nets) {
			t.Fatalf("%s 不应在可信段内", reject)
		}
	}
}

func TestClientIPTrustBoundary(t *testing.T) {
	trusted := ParseTrustedProxies([]string{"10.0.0.0/8"})
	cases := []struct {
		name       string
		remoteAddr string
		xff        string
		want       string
	}{
		{"对端不可信时忽略伪造的转发头", "203.0.113.9:5555", "1.2.3.4", "203.0.113.9"},
		{"对端可信时采信转发头", "10.0.0.7:5555", "203.0.113.9", "203.0.113.9"},
		{"自右向左取第一个不可信跳", "10.0.0.9:4444", "9.9.9.9, 203.0.113.7, 10.0.0.8", "203.0.113.7"},
		{"全为可信跳时回落直连地址", "10.0.0.9:4444", "10.0.0.1, 10.0.0.2", "10.0.0.9"},
		{"无转发头时用直连地址", "10.0.0.9:4444", "", "10.0.0.9"},
		{"垃圾跳被跳过", "10.0.0.9:4444", "garbage, 203.0.113.7", "203.0.113.7"},
		{"带端口的转发跳可解析", "10.0.0.9:4444", "203.0.113.7:6000", "203.0.113.7"},
		{"IPv6 直连地址", "[2001:db8::5]:4444", "", "2001:db8::5"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := ClientIP(clientIPCtx(tc.remoteAddr, tc.xff), trusted); got != tc.want {
				t.Fatalf("实得 %s，期望 %s", got, tc.want)
			}
		})
	}
}

func TestClientIPTrustsNobodyWhenUnconfigured(t *testing.T) {
	// 默认（TRUSTED_PROXIES 未配置）= 不信任任何代理：哪怕对端是环回也不采信转发头。
	// 这是安全默认——无代理部署下伪造 X-Forwarded-For 不能自选配额桶。
	if got := ClientIP(clientIPCtx("127.0.0.1:5555", "1.2.3.4"), ParseTrustedProxies(nil)); got != "127.0.0.1" {
		t.Fatalf("实得 %s，期望 127.0.0.1", got)
	}
}

func authRateKey(ip string) string {
	return fmt.Sprintf("rate:auth:%x", sha256.Sum256([]byte(ip)))
}

// newProxyRateRouter 造一个「网关位于 10.0.0.0/8 反代之后」的路由。
func newProxyRateRouter(t *testing.T) (*gin.Engine, *redis.Client) {
	t.Helper()
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(201)
		fmt.Fprint(w, `{"token":"t","user_id":"u","username":"n","tier":"normal","expires_in":1800}`)
	}))
	t.Cleanup(upstream.Close)
	cfg := config.Load()
	cfg.TrustedProxies = []string{"10.0.0.0/8"}
	r := newTestRedis(t)
	return NewRouter(cfg, r, nil, pyapi.New(upstream.URL, time.Second)), r
}

// 反代之后按真实客户端分桶：同一代理地址、不同 X-Forwarded-For 必须是不同配额桶。
// 修复前所有用户塌进同一个桶，一个人刷就锁死所有人登录。
func TestAuthRateLimitSeparatesBucketsByForwardedClient(t *testing.T) {
	clientA, clientB := "203.0.113.11", "203.0.113.12"
	router, r := newProxyRateRouter(t)
	for _, ip := range []string{clientA, clientB} {
		key := authRateKey(ip)
		t.Cleanup(func() { r.Raw().Del(context.Background(), key) })
	}

	send := func(client string) int {
		req := httptest.NewRequest("POST", "/api/v1/auth/register",
			strings.NewReader(`{"username":"n","password":"long-password-test"}`))
		req.RemoteAddr = "10.0.0.9:1234" // 所有请求都来自同一个可信代理
		req.Header.Set("X-Forwarded-For", client)
		result := httptest.NewRecorder()
		router.ServeHTTP(result, req)
		return result.Code
	}

	for i := 0; i < 20; i++ {
		if code := send(clientA); code != 201 {
			t.Fatalf("A 第 %d 次 = %d，期望 201", i+1, code)
		}
	}
	if code := send(clientA); code != 429 {
		t.Fatalf("A 第 21 次应 429，实得 %d", code)
	}
	if code := send(clientB); code != 201 {
		t.Fatalf("换真实客户端应换桶（B 首次 201），实得 %d", code)
	}
}
