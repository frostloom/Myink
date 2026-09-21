// Myink 网关：SSE 中继（进度事件流）。Caddy 是公网入口，其余 /api/v1/* 直达 Python。
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/joho/godotenv"

	"myink/gateway/internal/config"
	"myink/gateway/internal/handlers"
	"myink/gateway/internal/pyapi"
	"myink/gateway/internal/redis"
)

// loadDotEnv 从当前工作目录向上逐级找项目根 .env（与 Python config.py 同一文件，
// §17.2 环境分层），找到即加载。godotenv 不覆盖已存在的真实环境变量——
// shell 显式传的值优先，.env 只填空缺。找不到文件直接忽略（裸环境跑也 OK）。
func loadDotEnv() {
	dir, err := os.Getwd()
	if err != nil {
		return
	}
	for {
		envPath := filepath.Join(dir, ".env")
		if _, err := os.Stat(envPath); err == nil {
			_ = godotenv.Load(envPath)
			return
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return // 到盘根也没找到
		}
		dir = parent
	}
}

func main() {
	loadDotEnv()
	cfg := config.Load()
	r := redis.New(cfg.RedisAddr, cfg.RedisPassword)

	// 启动前探活 Redis（失败直接退出，不进入半可用状态）
	ctx0, cancel0 := context.WithTimeout(context.Background(), 3*time.Second)
	if err := r.Ping(ctx0); err != nil {
		cancel0()
		log.Fatalf("[gateway] Redis 不可达 %s: %v", cfg.RedisAddr, err)
	}
	cancel0()

	// RabbitMQ 不再由网关连接：入队与三层闸门已搬到 Python（见 src/myink/worker/enqueue.py）。
	// internal/queue 与两份 .lua 保留在仓库里作为闸门语义的参照实现（parity 见 tests/test_gates_parity.py）。
	py := pyapi.New(cfg.PythonAPIBase, 30*time.Second)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           handlers.NewRouter(cfg, r, py),
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		log.Printf("[gateway] 监听 :%s（Redis=%s PythonAPI=%s）", cfg.Port, cfg.RedisAddr, cfg.PythonAPIBase)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("[gateway] 服务异常退出: %v", err)
		}
	}()

	<-ctx.Done()
	log.Printf("[gateway] 收到退出信号，优雅关闭（最多 10s）")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("[gateway] 关闭异常: %v", err)
	}
	log.Printf("[gateway] 已退出")
}
