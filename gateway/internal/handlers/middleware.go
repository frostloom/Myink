// Package handlers 网关 HTTP 层（阶段 2，唯一公网入口）。
// 身份阶段 3：JWT 验证（§14.1 ③ 归属校验双保险第一道门，替换阶段 2 X-AiInk-User 占位）。
// 网关验签 → 解出可信 sub(user_id) → 写入上下文 + 透传 X-AiInk-User 头给 Python API
// （Python 侧 require_owner 断言 project.user_id == 该身份，RLS 之外第二道门，见 api/auth.py）。
package handlers

import (
	"errors"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"

	"aiink/gateway/internal/trace"
)

const HeaderUser = "X-AiInk-User"

// AuthError 是 JWT 校验失败（缺/坏 token）的错误，调用方转 401。
type AuthError struct{ msg string }

func (e *AuthError) Error() string { return e.msg }

// JWT 校验失败统一 401（缺 token / 坏 token / 过期 / 签名不符）。
var (
	errMissingToken   = &AuthError{"missing_bearer_token"}
	errInvalidToken   = &AuthError{"invalid_token"}
	errInvalidSubject = &AuthError{"invalid_subject"}
)

// JWTMiddleware 要求 `Authorization: Bearer <jwt>`，验签（HS256，secret 与 Python 共享
// .env）后把可信 sub(user_id) 写入 context 并透传 X-AiInk-User 响应头。
// 缺/坏 token → 401：网关是唯一公网入口，身份头从此只在网关内部写入，外部不可伪造
// （否则 Python 侧归属断言可被绕过，§14.1 ③）。
func JWTMiddleware(secret []byte) gin.HandlerFunc {
	return func(c *gin.Context) {
		sub, err := verifyJWT(c.GetHeader("Authorization"), secret)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
			return
		}
		c.Set("user_id", sub)
		c.Header(HeaderUser, sub)
		c.Next()
	}
}

// verifyJWT 解析 `Bearer <token>` 并验签，返回可信 sub。失败返回对应 AuthError。
func verifyJWT(authHeader string, secret []byte) (string, error) {
	if authHeader == "" {
		return "", errMissingToken
	}
	parts := strings.SplitN(authHeader, " ", 2)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") || strings.TrimSpace(parts[1]) == "" {
		return "", errInvalidToken
	}
	token, err := jwt.Parse(parts[1], func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected_signing_method")
		}
		return secret, nil
	}, jwt.WithValidMethods([]string{"HS256"}))
	if err != nil || !token.Valid {
		return "", errInvalidToken
	}
	sub, err := token.Claims.GetSubject()
	if err != nil || sub == "" {
		return "", errInvalidSubject
	}
	return sub, nil
}

// GetUserID 取当前请求用户 ID（JWTMiddleware 之后，可信 sub）。
func GetUserID(c *gin.Context) string {
	if v, ok := c.Get("user_id"); ok {
		if s, ok := v.(string); ok && s != "" {
			return s
		}
	}
	return ""
}

// GetTraceID 取当前请求 trace_id（trace.Middleware 之后）。
func GetTraceID(c *gin.Context) string {
	return trace.GetRequestID(c)
}
