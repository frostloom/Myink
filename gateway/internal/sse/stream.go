// Package sse 网关侧 SSE 转发：把 worker 写入 Redis Stream 的进度帧转发给浏览器。
// 断线重连支持 Last-Event-ID 重放（XRange 追平），流被 MAXLEN/TTL 裁剪则客户端回退 GET 快照。
package sse

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	goredis "github.com/redis/go-redis/v9"

	"aiink/gateway/internal/redis"
)

const (
	// StreamPrefix SSE 通道 key 前缀（§14：queue:）
	StreamPrefix = "queue:sse:"
	// MaxLen 每条 SSE 通道最大帧数（worker 侧 MAXLEN 一致）
	MaxLen = 1000
	// TTL 通道存活时间（任务终态后 1h 内可重放）
	TTL = 3600 * time.Second
)

// StreamKey 返回指定任务的 SSE 通道 key。
func StreamKey(taskID string) string { return StreamPrefix + taskID }

// Event 是 SSE 帧的载体（对应 worker 侧 XADD 的 fields）。
type Event struct {
	ID      string `json:"id"`
	Type    string `json:"type"` // status | node | heartbeat | done
	TaskID  string `json:"task_id,omitempty"`
	Node    string `json:"node,omitempty"`
	Status  string `json:"status,omitempty"`
	Message string `json:"message,omitempty"`
}

// ErrStreamGone 通道不存在（任务终态且流已过期）→ 客户端应回退 GET 快照。
var ErrStreamGone = fmt.Errorf("sse 通道不存在")

// Replay 通过 ctx 逐帧转发通道中 afterID 之后的已有帧，返回最后已转发的流 ID
// （供 Subscribe 的 XREAD 从该 ID 之后继续，避免已有帧被重复读取）。
// 返回 ErrStreamGone 表示通道已不存在。
func Replay(ctx context.Context, r *redis.Client, taskID, afterID string, send func(Event) error) (string, error) {
	key := StreamKey(taskID)
	exists, err := r.Raw().Exists(ctx, key).Result()
	if err != nil {
		return afterID, err
	}
	if exists == 0 {
		return afterID, ErrStreamGone
	}
	// Last-Event-ID 之后的所有帧（复用 XRangeN，afterID 为上一帧 ID）
	msgs, err := r.Raw().XRangeN(ctx, key, afterID, "+", 1000).Result()
	if err != nil {
		return afterID, err
	}
	last := afterID
	for _, m := range msgs {
		ev, ok := decodeEvent(m)
		if !ok {
			continue
		}
		if err := send(ev); err != nil {
			return last, err
		}
		last = m.ID
	}
	return last, nil
}

// Subscribe 阻塞式把通道事件持续转发给 send，直到 ctx 取消或 send 返回错误。
// afterID 为断线重放起点（Last-Event-ID），0-0 表示从头。
func Subscribe(ctx context.Context, r *redis.Client, taskID, afterID string, send func(Event) error) error {
	key := StreamKey(taskID)
	lastID := afterID
	// 追平已有帧（断线 Last-Event-ID 重放）；XREAD 从最后已转发帧之后继续，防重复
	replayed, err := Replay(ctx, r, taskID, lastID, send)
	if err != nil {
		return err
	}
	lastID = replayed
	// XREAD 阻塞等待新帧（空转 5s 无帧则检查 ctx 后继续）
	for {
		res, err := r.Raw().XRead(ctx, &goredis.XReadArgs{
			Streams: []string{key, lastID},
			Count:   100,
			Block:   5 * time.Second,
		}).Result()
		if err != nil {
			if err == goredis.Nil {
				select {
				case <-ctx.Done():
					return nil
				default:
					continue
				}
			}
			return err
		}
		for _, s := range res {
			for _, m := range s.Messages {
				ev, ok := decodeEvent(m)
				if !ok {
					continue
				}
				if err := send(ev); err != nil {
					return err
				}
				lastID = m.ID
			}
		}
		select {
		case <-ctx.Done():
			return nil
		default:
		}
	}
}

// decodeEvent 把 Redis Stream 消息解码成 Event。字段与 worker 侧 XADD 扁平结构对齐：
// event=status|node，status=queued/running/done/...，node=节点名（status 事件时为空）。
// ID 用 Redis 流 ID 保证单调递增（断线重放一致）。
func decodeEvent(m goredis.XMessage) (Event, bool) {
	var ev Event
	typ, ok := m.Values["event"].(string)
	if !ok || typ == "" {
		return ev, false
	}
	ev.Type = typ
	ev.ID = m.ID
	ev.TaskID, _ = m.Values["task_id"].(string)
	ev.Node, _ = m.Values["node"].(string)
	ev.Status, _ = m.Values["status"].(string)
	ev.Message, _ = m.Values["message"].(string)
	return ev, true
}

// WriteEvent 把 Event 序列化为 SSE 帧文本（data: + 可选 event: 行）。
func WriteEvent(ev Event) string {
	data, _ := json.Marshal(map[string]any{
		"type":    ev.Type,
		"task_id": ev.TaskID,
		"node":    ev.Node,
		"status":  ev.Status,
		"message": ev.Message,
	})
	var b []byte
	if ev.Type != "" && ev.Type != "message" {
		b = append(b, []byte("event: "+ev.Type+"\n")...)
	}
	b = append(b, []byte("id: "+ev.ID+"\n")...)
	b = append(b, []byte("data: "+string(data)+"\n\n")...)
	return string(b)
}

// ParseLastEventID 解析 Last-Event-ID 头（Redis 流 ID 格式如 "1700000000000-0"）。
func ParseLastEventID(h string) string {
	if h == "" {
		return "0-0"
	}
	parts := strings.SplitN(h, "-", 2)
	if len(parts) != 2 {
		return "0-0"
	}
	if _, err := strconv.ParseInt(parts[0], 10, 64); err != nil {
		return "0-0"
	}
	seq, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil || seq < 0 {
		seq = 0
	}
	return fmt.Sprintf("%s-%d", parts[0], seq)
}
