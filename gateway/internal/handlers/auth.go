package handlers

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"time"

	"github.com/gin-gonic/gin"
	"myink/gateway/internal/pyapi"
)

// checkAccess 向 Python 的归属接口确认「当前身份能否访问这个对象」，不能则直接结束响应。
//
// 身份取自 JWT 验签后的 sub（GetUserID），不是请求里带的头——伪造的头在这里没有任何作用。
func checkAccess(c *gin.Context, py *pyapi.Client, kind, id string, writing ...bool) bool {
	if py == nil {
		c.AbortWithStatusJSON(503, gin.H{"error": "authorization_unavailable"})
		return false
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	header := http.Header{HeaderUser: []string{GetUserID(c)}, "Authorization": []string{c.GetHeader("Authorization")}}
	query := url.Values{}
	if len(writing) > 0 && writing[0] {
		query.Set("write", "true")
	}
	resp, err := py.Forward(ctx, http.MethodGet, "/api/v1/"+kind+"/"+url.PathEscape(id)+"/access", query, header, nil)
	if err != nil {
		c.AbortWithStatusJSON(503, gin.H{"error": "authorization_unavailable"})
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		if resp.StatusCode == http.StatusConflict && query.Get("write") == "true" {
			c.AbortWithStatusJSON(http.StatusConflict, gin.H{"error": "PROJECT_NOT_READY"})
			return false
		}
		status := resp.StatusCode
		if status != 400 && status != 401 && status != 403 && status != 404 {
			status = 503
		}
		c.AbortWithStatusJSON(status, gin.H{"error": "access_denied"})
		return false
	}
	var result struct {
		OK bool `json:"ok"`
	}
	if json.NewDecoder(io.LimitReader(resp.Body, 65536)).Decode(&result) != nil || !result.OK {
		c.AbortWithStatusJSON(503, gin.H{"error": "authorization_unavailable"})
		return false
	}
	return true
}
