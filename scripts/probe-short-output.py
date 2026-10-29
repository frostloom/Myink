"""SHORT-FORM 门禁实测（Phase 0）：单次输出 2 万字不被截断。

决策文档 §7 第一条：单次生成的输出上限必须实测，不能靠猜。这一步不过，
短篇「整篇一次成稿」这条路整个作废。

直调 provider、不碰数据库、必须显式 --live（与 scripts/eval-logic.py 同一约定）。

密钥只从环境变量读，不落盘、不进代码：
    export MYINK_PROBE_API_KEY=sk-...
端点与模型可覆盖：
    export MYINK_PROBE_BASE_URL=https://api.deepseek.com   # 默认
    --model-id deepseek-v4-pro

prompt 的写法对齐参考实现 inkos 的短篇写手（prompts/short-fiction.ts）：
显式 block 标记 + 逐章点名 + 「字数是校准不是平均数学」的反梗概指令。
实测差别的来源：同样要 2 万字，要 5 章 × 4000 字只拿回 ~4500 字，
要 10 章 × 2000 字才拿得回全量（模型的自然章长约 1000 字）。

结果写 docs/evaluations/short-output-probe.json；门禁不过 exit 1。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from myink.config import settings
from myink.context_budget import estimate_tokens
from myink.providers.base import MODEL_REGISTRY
from myink.providers.deepseek import DeepSeekProvider
from myink.workflow.nodes import _MAX_TOKENS, _WRITE_TOKENS_PER_CHAR

DEFAULT_OUT = Path("docs/evaluations/short-output-probe.json")

# inkos SYSTEM_SHORT_FICTION_WRITER 的要点（反梗概 + 反注水 + block 纪律）
SYSTEM = (
    "你是中文短篇写手。你要根据故事方案一次写完整短篇正文。\n"
    "这不是长篇连载续写，也不是章节梗概。每章都要有当场发生的戏：人物行动、对话或反应、"
    "局面变化、章尾继续读的理由。\n"
    "标题和章节标题要像平台内容，不要文艺化总结。正文保持移动端节奏，段落短但不要写成电报体。\n"
    "字数是校准，不是平均数学题。大场面可略长，过渡章可略短；明显偏短通常说明写成了梗概，"
    "必须补有效场面。\n"
    "输出必须严格使用指定 block，不要写作者说明、字数说明、审稿意见或格式解释。"
)

# 10 章 × 约 2000 字 = 20000（SHORT_TOTAL_MAX 与 SHORT_CHAPTER_MAX 同时取到的边界）。
# 每章按 SYSTEM_SHORT_PLAN 的硬要求写足：标题方向 / 关键场面 / 角色动作 / 压力升级或回报 / 章尾钩子。
FAKE_PLAN = """【方案】《最后一班渡船》

题材：现代奇幻 + 小城悬疑。主角：青溪渡口老船工陈守田（62 岁）、返乡女记者林砚（29 岁）。
核心：青溪渡每天只发一班夜船，三十年未断。林砚回来查一桩旧案，发现渡船每次靠岸都会多载一个人。

第 1 章《回来的船》：林砚深夜抵达青溪渡，赶上最后一班船。关键场面：船到中流陈守田突然熄火，对着空荡河面低声报出四个名字。角色动作：林砚偷拍乘客名单，陈守田发现却不阻止，只说「你不该记这个」。章尾钩子：名单上有第五个名字——她父亲。

第 2 章《第五个名字》：林砚在船上反复核对名单。关键场面：她认出父亲的字迹出现在三十年前的旧票根上。角色动作：她质问陈守田，陈守田拒绝回答，只把船靠岸。压力升级：陈守田说「他昨晚也上了船」，而父亲三年前已在省城下葬。章尾钩子：岸上站着一个撑伞的人，伞下没有脸。

第 3 章《多出来的座位》：林砚回村翻查渡口三十年的航行日志。关键场面：每次「多一个人」都对应村里一次意外死亡，且死者次日才被发现。角色动作：她抄录日期，发现与父亲的死期只差一天。回报：日志里夹着一张父亲的船票。章尾钩子：船票背面写着「替我」。

第 4 章《烧掉的日志》：林砚找当年的老支书对质。关键场面：老支书承认当年压下了案子，随即连夜把日志烧了。角色动作：林砚冲进火堆抢出一页残页。压力升级：老支书警告她「你爸是自己要上船的」。章尾钩子：残页上是父亲的笔迹，画着一艘船，船底写着「第九班」——而渡口一天只发一班。

第 5 章《守田的规矩》：陈守田讲出他守了三十年的规矩。关键场面：他年轻时也曾「多载一个人」，那年冬天他的女儿落了水。角色动作：他给林砚看自己手腕上的一圈绳痕。回报：他承认每个名字都是他自己报的。章尾钩子：他说「我是在替他们点名」。

第 6 章《河心的呼唤》：陈守田第一次让林砚掌舵。关键场面：林砚在河心听见水下有人叫她的名字，声音是她父亲的。角色动作：她松开舵想去够水面，被陈守田一把拽回。压力升级：船自己转了个向，朝着没有渡口的方向走。章尾钩子：陈守田的手开始不听使唤。

第 7 章《撑不住的手》：陈守田坦白他撑不住了。关键场面：他握不住舵，绳子从手里滑脱，船在河心打转。角色动作：林砚接过舵，问他「第九班是什么」。回报：他说第九班是留给撑船人自己的那班。章尾钩子：他说「下一班，名单上会有我」。

第 8 章《第九班》：林砚决定替陈守田走完这一班。关键场面：船上真的出现第九个乘客——不是父亲，是三年前的自己。角色动作：她与「自己」对质，问出父亲当年为何瞒着她上船。回报：父亲是用自己的名字换了她那一年的手术费。章尾钩子：船靠岸，父亲的座位是空的，河面上浮起一件旧外套。

第 9 章《旧外套》：林砚捡回外套，口袋里有父亲最后一封信。关键场面：信里说「名字给出去了，人就能回来一趟」。角色动作：她去找陈守田，发现他已经在船头睡着了。压力升级：天亮后渡船本该停航，可船还在河心。章尾钩子：陈守田的手表停在三十年前女儿落水的时刻。

第 10 章《靠岸》：最后一班船到岸，各人各自了结。关键场面：林砚把残页和信一起投进河里，替所有名字念了一遍；陈守田第一次在白天下水。收官：渡口停航，渡船凿沉在青溪渡口，村里的旧案卷宗被重新翻出。章尾钩子（余韵）：三年后有人拍到，青溪渡深夜仍有一盏灯在河心亮着。
"""


def build_messages(chars: int, chapters: int) -> list[dict]:
    per = max(1, chars // chapters)
    blocks = ["=== SHORT_FICTION_TITLE ===", "（这里写标题）"]
    for i in range(1, chapters + 1):
        blocks += [f"=== CHAPTER {i} TITLE ===", f"=== CHAPTER {i} CONTENT ==="]
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            f"{FAKE_PLAN}\n\n## 任务\n"
            f"一次写完整 {chapters} 章，每章约 {per} 字（合计约 {chars} 字）。\n"
            "严格按下面的 block 顺序输出；每章都必须有正文，不要漏章，不要用梗概代替正文：\n"
            + "\n".join(blocks)
        )},
    ]


def count_chapters(text: str) -> int:
    """数出真正带正文的章节块（漏章是短篇最要命的失败模式）。"""
    n = 0
    for i in range(1, 100):
        head = text.find(f"=== CHAPTER {i} CONTENT ===")
        if head < 0:
            break
        nxt = text.find("=== CHAPTER ", head + 1)
        body = text[head + len(f"=== CHAPTER {i} CONTENT ==="):nxt if nxt > 0 else len(text)]
        if body.strip():
            n += 1
    return n


def gate_budget(messages: list[dict], max_tokens: int, model_id: str) -> tuple[int, int]:
    """复刻 nodes.py `_bounded_generate` 的闸门算式（同源 import，数值不会各自漂移）。"""
    estimated = estimate_tokens({"messages": messages, "tools": []})
    spec = MODEL_REGISTRY.get(model_id)
    limits = [spec.context_window - (max_tokens or 8192) - 1000] if spec else []
    budget = min([settings.request_token_budget, *limits])
    return estimated, budget


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", required=True)
    p.add_argument("--model-id", default="deepseek-v4-pro")
    p.add_argument("--chars", type=int, default=20000)
    p.add_argument("--chapters", type=int, default=10)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = p.parse_args()

    api_key = os.environ.get("MYINK_PROBE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("未设置 MYINK_PROBE_API_KEY（密钥只从环境变量读，不进代码）")
    base_url = os.environ.get("MYINK_PROBE_BASE_URL") or None

    # 输入侧：方案 + 已写正文一起进 revise 时最挤（决策文档 §8 第二条风险）
    plan_and_draft = [{"role": "user", "content": FAKE_PLAN + "　" * 1 + "正文" * a.chars}]
    revise_in, revise_budget = gate_budget(plan_and_draft, _MAX_TOKENS["revise"], a.model_id)

    max_tokens = int(a.chars * _WRITE_TOKENS_PER_CHAR * 1.25)
    messages = build_messages(a.chars, a.chapters)
    write_in, write_budget = gate_budget(messages, max_tokens, a.model_id)

    provider = DeepSeekProvider(api_key=api_key, base_url=base_url)
    resp = provider.generate(
        messages, model_id=a.model_id, max_tokens=max_tokens,
        temperature=0.58, json_mode=False, disable_thinking=True,
    )

    result = {
        "model_id": a.model_id,
        "requested_chars": a.chars,
        "requested_chapters": a.chapters,
        "max_tokens": max_tokens,
        "content_chars": len(resp.content),
        "chapters_with_content": count_chapters(resp.content),
        "output_tokens": resp.output_tokens,
        "input_tokens": resp.input_tokens,
        "finish_reason": resp.finish_reason,
        "duration_ms": resp.duration_ms,
        "cost_est_cny": resp.cost_est,
        "error": resp.error,
        "input_side": {
            "write_estimated_tokens": write_in, "write_budget": write_budget,
            "revise_estimated_tokens": revise_in, "revise_budget": revise_budget,
        },
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

    truncated = resp.finish_reason == "length"
    print(f"\n输出 {len(resp.content)} 字 / 目标 {a.chars} 字；"
          f"带正文的章 {result['chapters_with_content']} / {a.chapters}；"
          f"{resp.output_tokens} tokens / 上限 {max_tokens}；"
          f"finish_reason={resp.finish_reason}；{resp.duration_ms / 1000:.1f}s；"
          f"¥{resp.cost_est:.4f}", flush=True)
    print(f"输入侧 write  {write_in}/{write_budget} tokens；"
          f"revise {revise_in}/{revise_budget} tokens"
          f"（超了就 CONTEXT_BUDGET_EXCEEDED，调用根本发不出去）", flush=True)

    if resp.error:
        print(f"✗ 门禁不过：调用失败 {resp.error}", flush=True)
        return 1
    if truncated:
        print("✗ 门禁不过：finish_reason=length，被 max_tokens 截断", flush=True)
        return 1
    if len(resp.content) < a.chars * 0.9:
        print(f"⚠ 未截断，但只产出 {len(resp.content)} 字（目标 {a.chars} 字）。"
              f"单次成稿撑不到这个量级，总量上限要回去找用户定。", flush=True)
        return 1
    print(f"✓ 门禁通过：{a.chars} 字一次成稿完整返回，未被截断", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())