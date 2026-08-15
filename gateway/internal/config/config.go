// Package config 网关配置（阶段 2）。从环境变量读取，与 Python 侧 config.py 对齐。
package config

import (
	"os"
	"strconv"
)

// JWT 身份断言（§14.1 ③）：dev 默认密钥与 Python config.py 的 _DEV_JWT_SECRET 同值，
// 两端 HS256 签名才互通；生产必须显式设置（Python validate 会拒默认值，网关不校验
// APP_ENV——真实密钥由部署注入，无默认则演示口令失效即 401）。
const DevJWTSecret = "dev-jwt-secret-change-me"

type Config struct {
	Port             string
	RedisAddr        string
	RedisPassword    string
	PythonAPIBase    string
	// 阶段 5：前端静态托管目录（web/dist，容器内 /app/dist；不存在时 SPA fallback 自动降级为 404）
	WebDistDir       string
	// 三层闸门（§13）：每日配额（章）、并发上限（进行中任务）、日成本上限（¥）
	QuotaDaily       int
	// 每书每日配额（章）：单用户同时写多本书时限制单书用量（默认 50 章/书/日）
	BookQuotaDaily   int
	// 每用户每天最多碰几本不同书（去重计数，Set rate:bookcnt，默认 10 本/日）
	BooksPerDay      int
	ConcurrencyLimit int
	DailyBudget      float64
	CostPerChapter   float64
	// 批次硬上限（与 Python config.batch_max_hard 对齐，§6.11 成本熔断第一道闸）
	BatchMaxHard     int
	// 进程内令牌桶（DoS 盾，非业务配额）
	RatePerSec       int
	RateBurst        int
	// 阶段 3：JWT 身份断言（§14.1 ③）。密钥与 Python config.py 共享同一 .env；dev 默认
	// 保证本地演示两端互通，生产由部署注入强随机密钥（Python prod 校验会拒绝默认值）。
	JWTSecret        string
	JWTTTL           int
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func envFloat(key string, def float64) float64 {
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return def
}

func Load() Config {
	return Config{
		Port:             env("GATEWAY_PORT", "8080"),
		RedisAddr:        env("REDIS_ADDR", "localhost:6380"),
		RedisPassword:    env("REDIS_PASSWORD", ""),
		PythonAPIBase:    env("PYTHON_API_BASE", "http://127.0.0.1:8100"),
		WebDistDir:       env("WEB_DIST_DIR", "web/dist"),
		QuotaDaily:       envInt("QUOTA_DAILY_CHAPTERS", 500),
		BookQuotaDaily:   envInt("BOOK_QUOTA_DAILY_CHAPTERS", 50),
		BooksPerDay:      envInt("BOOKS_PER_DAY", 10),
		ConcurrencyLimit: envInt("CONCURRENCY_LIMIT", 1),
		DailyBudget:      envFloat("DAILY_BUDGET_YUAN", 2.0),
		CostPerChapter:   envFloat("COST_PER_CHAPTER_YUAN", 0.05),
		BatchMaxHard:     envInt("BATCH_MAX_HARD", 20),
		RatePerSec:       envInt("RATE_PER_SEC", 20),
		RateBurst:        envInt("RATE_BURST", 40),
		JWTSecret:        env("JWT_SECRET", DevJWTSecret),
		JWTTTL:           envInt("JWT_TTL", 1800),
	}
}
