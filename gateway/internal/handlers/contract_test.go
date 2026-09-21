// 契约一致性测试：网关转发契约与 Python 侧单一事实源 spec/api-openapi.json 对齐。
//
// 独立运行：不依赖 Redis，只依赖已提交的契约文件 + 标准库 encoding/json。
package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
)

// forwardedPaths：网关**仍然**直连 Python 的路径表。
//
// 刻意只剩两条，不是搬了一半——Caddy 接管公网入口后，83 条业务转发全部改由 Caddy
// 分流到 Python（见 caddy/Caddyfile），Go 只剩 SSE 这一条长连接，以及它沿途需要的
// 两次身份往返。path 用 FastAPI 模板形式。
var forwardedPaths = []struct{ method, path string }{
	{"GET", "/api/v1/tasks/{task_id}/access"}, // checkAccess：SSE 连接的归属断言（middleware 之外，auth.go）
	{"GET", "/api/v1/auth/session"},           // SSE 每 15 秒的会话复检（sse.go:134）
}

func loadContract(t *testing.T) map[string]any {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("无法定位测试源码路径")
	}
	p := filepath.Join(filepath.Dir(file), "..", "..", "..", "spec", "api-openapi.json")
	raw, err := os.ReadFile(p)
	if err != nil {
		t.Fatalf("读契约文件失败: %v（先 myink contract export 并提交 spec/api-openapi.json）", err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("契约 JSON 解析失败: %v", err)
	}
	return doc
}

var pathParamRe = regexp.MustCompile(`\{[^}]*\}`)

// normPath：{project_id}/{task_id} 等模板参数名归一为 {}——契约方改参数名不误报路径漂移。
func normPath(p string) string {
	return pathParamRe.ReplaceAllString(p, "{}")
}

// 网关这几个内部路径是字符串拼出来的（checkAccess 用 kind+id 拼、sse.go 直接写字面量），
// 编译器拦不住路径漂移（历史上真出过 BatchControl 转发错路径 404）。所以显式列全再比对：
// Python 侧改了路由而这里没跟上，本测试即红。
func TestContractHasAllForwardedPaths(t *testing.T) {
	doc := loadContract(t)
	paths, _ := doc["paths"].(map[string]any)
	if paths == nil {
		t.Fatal("契约缺 paths")
	}
	// 契约路径模板参数名（{project_id}/{task_id}…）与网关路径表一致，归一后对比
	normPaths := make(map[string]map[string]any, len(paths))
	for k, v := range paths {
		if ops, ok := v.(map[string]any); ok {
			normPaths[normPath(k)] = ops
		}
	}
	for _, r := range forwardedPaths {
		ops, ok := normPaths[normPath(r.path)]
		if !ok {
			t.Errorf("网关转发路径 %s 不在契约里（Python 侧可能已改路由，网关未同步）", r.path)
			continue
		}
		if _, ok := ops[strings.ToLower(r.method)]; !ok {
			t.Errorf("网关转发 %s %s 在契约里缺 method", r.method, r.path)
		}
	}
}
