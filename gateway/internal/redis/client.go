// Package redis 网关侧 Redis 客户端（key 前缀遵守 §14：queue: / lock: / rate: / cache:）。
package redis

import (
	"context"
	"time"

	goredis "github.com/redis/go-redis/v9"
)

type Client struct {
	rdb *goredis.Client
}

func New(addr, password string) *Client {
	rdb := goredis.NewClient(&goredis.Options{
		Addr:         addr,
		Password:     password,
		DB:           0,
		DialTimeout:  5 * time.Second,
		ReadTimeout:  3 * time.Second,
		WriteTimeout: 3 * time.Second,
		PoolSize:     10,
	})
	return &Client{rdb: rdb}
}

func (c *Client) Ping(ctx context.Context) error {
	return c.rdb.Ping(ctx).Err()
}

func (c *Client) XAdd(ctx context.Context, stream string, fields map[string]any) (string, error) {
	return c.rdb.XAdd(ctx, &goredis.XAddArgs{
		Stream: stream,
		Values: fields,
	}).Result()
}

// XRangeLast 读取流最后 N 条（SSE 断线重放用 XRange，这里提供 last-N 兜底）。
func (c *Client) XRangeLast(ctx context.Context, stream string, count int64) ([]goredis.XMessage, error) {
	return c.rdb.XRangeN(ctx, stream, "-", "+", count).Result()
}

// XReadStream 从指定 ID 之后读（SSE 断线续流：Last-Event-ID → XRANGE）。
func (c *Client) XReadStream(ctx context.Context, stream, afterID string, count int64) ([]goredis.XMessage, error) {
	return c.rdb.XRangeN(ctx, stream, afterID, "+", count).Result()
}

// Expire 设置 key TTL（SSE stream MAXLEN 裁剪兜底）。
func (c *Client) Expire(ctx context.Context, key string, ttl time.Duration) error {
	return c.rdb.Expire(ctx, key, ttl).Err()
}

// Eval 执行 Lua 脚本（gates.lua 原子三层闸门）。
func (c *Client) Eval(ctx context.Context, script string, keys []string, args ...any) (any, error) {
	return c.rdb.Eval(ctx, script, keys, args...).Result()
}

func (c *Client) Raw() *goredis.Client { return c.rdb }
