package sse

import (
	"encoding/json"
	"strings"
	"testing"

	goredis "github.com/redis/go-redis/v9"
)

func TestArtifactEventRoundTrip(t *testing.T) {
	msg := goredis.XMessage{ID: "10-2", Values: map[string]any{
		"event": "artifact_delta", "task_id": "task-1", "stage": "write",
		"chapter_seq": "17", "attempt": "2", "offset": "32",
		"artifact_id": "a-1", "content": "正文片段",
	}}
	ev, ok := decodeEvent(msg)
	if !ok {
		t.Fatal("artifact 事件应可解码")
	}
	if ev.Type != "artifact_delta" || ev.Chapter != 17 || ev.Attempt != 2 || ev.Offset != 32 {
		t.Fatalf("artifact 数值字段丢失: %+v", ev)
	}
	frame := WriteEvent(ev)
	if !strings.Contains(frame, "event: artifact_delta\n") {
		t.Fatalf("SSE event 行错误: %s", frame)
	}
	dataLine := strings.Split(strings.Split(frame, "data: ")[1], "\n")[0]
	var body map[string]any
	if err := json.Unmarshal([]byte(dataLine), &body); err != nil {
		t.Fatalf("SSE data 不是 JSON: %v", err)
	}
	if body["content"] != "正文片段" || body["artifact_id"] != "a-1" {
		t.Fatalf("artifact 内容未透传: %v", body)
	}
}
