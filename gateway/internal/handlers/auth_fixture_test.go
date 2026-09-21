package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"myink/gateway/internal/config"
)

// SSE 假上游要实现的正是网关仅剩的两个直连 Python 端点：会话复检（sse.go 每 15 秒一次）
// 与归属断言（checkAccess）。两者都在这里按真实语义应答——/auth/session 会真的验签，
// 所以「撤销/过期后流被关掉」这类断言靠的是真逻辑，不是被 stub 掉的恒真。
func serveAuthFixture(w http.ResponseWriter, req *http.Request) bool {
	if req.URL.Path == "/api/v1/auth/session" {
		user, tier, err := verifyJWT(req.Header.Get("Authorization"), []byte(config.Load().JWTSecret))
		if err != nil {
			w.WriteHeader(401)
			return true
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"user_id": user, "username": "fixture", "tier": tier})
		return true
	}
	if strings.HasSuffix(req.URL.Path, "/access") {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"ok":true}`)
		return true
	}
	return false
}
