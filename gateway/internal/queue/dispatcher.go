// 网关侧 dispatcher：退避重投 / DLQ / 崩溃认领（§6.12）。
// worker 保持「读→跑→ack」哑消费者；队列机制全在网关。网关重启不丢（ZSET/PENDING 持久在 Redis）。
package queue

import (
	"context"
	"encoding/json"
	"log"
	"strconv"
	"time"

	goredis "github.com/redis/go-redis/v9"

	"aiink/gateway/internal/redis"
)

const (
	// 重投超限阈值（§6.12：退避重投超限进 DLQ 待人工）
	MaxRetries = 3
	// 消费组 PENDING 认领最小空闲（worker 崩溃后本守护认领）
	MinIdleTime = 120 * time.Second
	// ConsumerGroup 与 worker 侧消费组一致
	ConsumerGroup = "workers"
)

// Run 每秒跑一轮：ZSET 到期重投 / XAUTOCLAIM 崩溃认领 / 超限进 DLQ。
func Run(ctx context.Context, r *redis.Client, stop <-chan struct{}) {
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()
	log.Printf("[dispatcher] 启动：退避重投 / 崩溃认领 / DLQ")
	for {
		select {
		case <-stop:
			log.Printf("[dispatcher] 退出")
			return
		case <-ctx.Done():
			return
		case <-ticker.C:
			dispatchDue(ctx, r)
			claimStale(ctx, r)
		}
	}
}

// dispatchDue 把到期的 queue:delay ZSET 条目重投回主队列（超限进 DLQ）。
func dispatchDue(ctx context.Context, r *redis.Client) {
	now := time.Now().UnixMilli()
	entries, err := r.Raw().ZRangeByScore(ctx, StreamDelay, &goredis.ZRangeBy{
		Min: "-inf", Max: strconv.FormatInt(now, 10), Count: 100,
	}).Result()
	if err != nil {
		log.Printf("[dispatcher] ZRangeByScore err: %v", err)
		return
	}
	for _, member := range entries {
		var body map[string]any
		if err := json.Unmarshal([]byte(member), &body); err != nil {
			log.Printf("[dispatcher] 坏 delay 条目丢弃: %v", err)
			continue
		}
		retry := toInt(body["retry_count"])
		bodyJSON, _ := json.Marshal(body)
		if retry >= MaxRetries {
			// 超限进 DLQ（§6.12：重投超限进 DLQ 待人工）
			if _, err := r.XAdd(ctx, StreamDLQ, map[string]any{"body": string(bodyJSON), "reason": "retry_exhausted"}); err != nil {
				log.Printf("[dispatcher] DLQ XAdd err: %v", err)
			}
			log.Printf("[dispatcher] 重投超限进 DLQ: task=%v retry=%d", body["task_id"], retry)
		} else {
			// 与 worker 侧格式对齐：queue:tasks 单字段 body = 整条任务 JSON（member 即该 JSON）
			if _, err := r.XAdd(ctx, StreamTasks, map[string]any{"body": member}); err != nil {
				log.Printf("[dispatcher] 重投 XAdd err: %v", err)
			}
			log.Printf("[dispatcher] 退避到期重投: task=%v retry=%d", body["task_id"], retry)
		}
		// 无论重投或 DLQ，都从 delay ZSET 移除（条目已迁入主队列/DLQ）
		if err := r.Raw().ZRem(ctx, StreamDelay, member).Err(); err != nil {
			log.Printf("[dispatcher] ZRem err: %v", err)
		}
	}
}

// claimStale 认领消费组 PENDING 中空闲过久的消息（worker 崩溃恢复）并重投回主队列。
// XAUTOCLAIM 仅转移所有权；必须再把 body 重新 XADD 成新条目，XREADGROUP > 才会再次投递给 worker。
// 重复执行安全：worker 侧幂等检查兜底（lock:task SETNX + tasks.status，§阶段2）。
func claimStale(ctx context.Context, r *redis.Client) {
	msgs, _, err := r.Raw().XAutoClaim(ctx, &goredis.XAutoClaimArgs{
		Stream:   StreamTasks,
		Group:    ConsumerGroup,
		Consumer: "gateway-recover",
		MinIdle:  MinIdleTime,
		Start:    "0",
		Count:    10,
	}).Result()
	if err != nil {
		log.Printf("[dispatcher] XAutoClaim err: %v", err)
		return
	}
	for _, m := range msgs {
		body, ok := m.Values["body"].(string)
		if !ok {
			// 旧格式坏消息：认领即丢弃（worker 侧也会丢弃，这里直接 ACK 防残留）
			log.Printf("[dispatcher] 认领坏消息丢弃: %s", m.ID)
			_ = r.Raw().XAck(ctx, StreamTasks, ConsumerGroup, m.ID).Err()
			continue
		}
		// 重投回主队列让 XREADGROUP > 再次投递（worker 幂等检查避免重复执行）
		if _, err := r.XAdd(ctx, StreamTasks, map[string]any{"body": body}); err != nil {
			log.Printf("[dispatcher] 崩溃任务重投失败（留在 PENDING 等下次）: %s err=%v", m.ID, err)
			continue
		}
		// 已安全重投，ACK 旧条目防被再次认领造成无限重投
		_ = r.Raw().XAck(ctx, StreamTasks, ConsumerGroup, m.ID).Err()
		log.Printf("[dispatcher] 崩溃任务重投: %s task=%v", m.ID, body)
	}
}

func toInt(v any) int {
	switch t := v.(type) {
	case int:
		return t
	case int64:
		return int(t)
	case float64:
		return int(t)
	case string:
		n, _ := strconv.Atoi(t)
		return n
	}
	return 0
}
