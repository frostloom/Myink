"""多进程并行回归测试的 worker 子进程入口（tests/test_multiprocess.py 用 subprocess 启动）。

pytest 的 monkeypatch 不跨进程——子进程必须自注入假 provider/embedder 后再跑真实
consumer.run()。SLOW 停顿用于检测「两个 worker 是否真的同时在跑」：
  mp:active  —— setnx 占位标记（正在执行某个 generate）
  mp:overlap —— 进入时发现 mp:active 已被占（另一 worker 正在跑）则 +1

异书并行断言 overlap>0（并发确实发生过）；同书串行断言 overlap==0（永不并发，
书锁保证）。两个 key 由测试主进程在读断言前清理/读取。
"""

from __future__ import annotations

import json
import os
import sys
import time

if os.environ.get("PI_LAB_ENV"):
    from ops.pi.lab.verify import verify_test_environment
    verify_test_environment()

# 子进程不保证 editable 安装，直接指到 src
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import redis  # noqa: E402

from myink.providers.base import ModelProvider, ModelResponse  # noqa: E402
from myink.config import settings  # noqa: E402

_R = redis.from_url(settings.redis_url, decode_responses=True)


class FakeEmbedder:
    """假 bge-m3：固定 1024 维向量，不加载真实模型（子进程复制 test_flow）。"""

    def encode(self, texts):
        return [[0.0] * 1024 for _ in texts]


class StubProvider(ModelProvider):
    """test_flow.StubProvider 的子进程复制（不依赖 pytest/monkeypatch）+ 并发检测。"""

    def __init__(self, realm_from: str, realm_to: str, slow: float = 0.0):
        self.realm_from = realm_from
        self.realm_to = realm_to
        self.slow = slow

    def name(self) -> str:
        return "stub"

    def generate(self, messages, *, model_id, max_tokens=None, temperature=None, json_mode=False,
                 tools=None, disable_thinking=False):
        if self.slow:
            # 并发检测：占位成功说明只有自己在跑；失败说明另一 worker 正在跑 → overlap+1
            if not _R.set("mp:active", "1", nx=True, ex=30):
                _R.incr("mp:overlap")
            time.sleep(self.slow)
            _R.delete("mp:active")

        node = self._infer_node(messages)
        if node == "cast":
            content = '{"cast":["林砚"],"locations":["黑市"]}'
        elif node == "plan":
            content = (
                '{"goals":["推进主线"],"scenes":[],"characters":[],'
                '"hooks_to_plant":[],"hooks_to_resolve":[],'
                '"expected_events":["林砚在黑市查探玉佩真相"],"hard_constraints":[]}'
            )
        elif node == "audit":
            content = '{"verdict":"pass","findings":[],"reasons":["章节符合计划"],"confidence":0.9}'
        elif node == "write":
            content = '林砚在黑市隐秘查探，玉佩气息若隐若现。夜色沉沉。'
        elif node == "extract":
            content = (
                '{"candidates":['
                '{"kind":"event","source_chapter":1,"confidence":0.9,"payload":{"summary":"林砚于黑市查探玉佩真相",'
                '"participants":["林砚"],"source_chapter":1,"confidence":0.9}},'
                f'{{"kind":"character_state","source_chapter":1,"confidence":0.9,"payload":{{"character_id":"林砚",'
                f'"field":"realm","old_value":"{self.realm_from}","new_value":"{self.realm_to}",'
                f'"source_chapter":1,"confidence":0.9}}}},'
                '{"kind":"foreshadow","source_chapter":1,"confidence":0.9,"payload":{"description":"玉佩气息异常，疑似与玉佩真相有关",'
                '"trigger":{"actor":"林砚","action":"发现","object":"玉佩"},"source_chapter":1,"confidence":0.9}}'
                ']}'
            )
        elif node == "revise":
            content = '=== CONTENT ===\n修订后正文\n=== RESPONSES ===\n[]'
        else:
            content = "{}"
        return ModelResponse(content=content, model_id=model_id, input_tokens=100,
                             output_tokens=200, duration_ms=50)

    def _infer_node(self, messages):
        sys_msg = messages[0]["content"] if messages else ""
        if "出场人物 Agent" in sys_msg:
            return "cast"
        if "规划 Agent" in sys_msg:
            return "plan"
        if "记忆抽取" in sys_msg:
            return "extract"
        if "修订 Agent" in sys_msg:
            return "revise"
        if "审核中枢" in sys_msg:
            return "audit"
        return "write"


def _main() -> None:
    intake=os.environ.get("B10_INTAKE")
    if intake:
        assert intake in {"intent-before-gate","gate-before-receipt","compensate-before-receipt","intake-confirm-before-receipt"}
        assert os.environ.get("PI_LAB_ENV")
        from myink.worker import enqueue as enq
        from myink.worker import amqp
        project=os.environ["B10_PROJECT"];user=os.environ["B10_USER"]
        def hold(task,stage):
            _R.set("b10:intake:"+project,json.dumps({"pid":os.getpid(),"task_id":task,"stage":stage}),ex=120)
            time.sleep(90)
            raise RuntimeError("intake boundary parent did not kill exact child")
        gate=enq._run_gates
        def gated(*args,**kwargs):
            if intake=="intent-before-gate":hold(kwargs["task_id"],intake)
            result=gate(*args,**kwargs)
            if intake=="gate-before-receipt":hold(kwargs["task_id"],intake)
            return result
        enq._run_gates=gated
        compensate=enq._compensate
        def compensated(*args,**kwargs):
            result=compensate(*args,**kwargs)
            if intake=="compensate-before-receipt":hold(kwargs["task_id"],intake)
            return result
        enq._compensate=compensated
        publish=amqp.publish
        def published(body,routing_key,**kwargs):
            if intake=="compensate-before-receipt":
                return publish(body,"b10-unbound-route",**kwargs)
            result=publish(body,routing_key,**kwargs)
            if intake=="intake-confirm-before-receipt":hold(json.loads(body)["task_id"],intake)
            return result
        amqp.publish=published
        enq.enqueue(user_id=user,project_id=project,task_type="chapter_generate",payload={"seq":1},quota_n=2,cost_est=0,priority=7,platform_chapter_max=10)
        raise RuntimeError("intake unexpectedly completed without boundary")

    import myink.providers as providers_mod
    import myink.memory.recall as recall_mod
    import myink.workflow.nodes as nodes_mod

    providers_mod.default_provider = StubProvider("金丹", "金丹", slow=0.8)
    nodes_mod.get_embedder = lambda: FakeEmbedder()
    recall_mod.get_embedder = lambda: FakeEmbedder()

    from myink.worker import consumer
    boundary=os.environ.get("B10_BOUNDARY")
    target=os.environ.get("B10_TASK")
    if boundary:
        assert boundary in {"before-ack","outbox-before-ack","after-ack","confirm-before-receipt"}
        assert target and os.environ.get("PI_LAB_ENV")
        import pika
        from myink.worker import amqp
        def hold(stage):
            _R.set("b10:boundary:"+target,json.dumps({"pid":os.getpid(),"stage":stage}),ex=120)
            time.sleep(90)
            raise RuntimeError("parent did not kill the exact boundary child")
        original_ack=pika.adapters.blocking_connection.BlockingChannel.basic_ack
        def ack(channel,*args,**kwargs):
            if current[0]==target and boundary in {"before-ack","outbox-before-ack"}:hold(boundary)
            result=original_ack(channel,*args,**kwargs)
            if current[0]==target and boundary=="after-ack":hold(boundary)
            return result
        pika.adapters.blocking_connection.BlockingChannel.basic_ack=ack
        original_publish=amqp.publish_once
        def confirmed(body,*args,**kwargs):
            result=original_publish(body,*args,**kwargs)
            if json.loads(body).get("task_id")==target and boundary=="confirm-before-receipt":hold(boundary)
            return result
        amqp.publish_once=confirmed
    current=[None]
    original_process = consumer.process
    def observed_process(body, **kwargs):
        current[0]=body.get("task_id")
        decision = original_process(body, **kwargs)
        if boundary and current[0]==target and boundary!="before-ack" and decision=="terminal":
            decision="retry"
        if body.get("test_probe"):
            _R.set("mp:probe:" + body["test_probe"], decision, ex=60)
        return decision
    consumer.process = observed_process
    consumer.run()


if __name__ == "__main__":
    _main()
