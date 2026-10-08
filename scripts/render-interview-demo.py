"""Render the committed synthetic live-model recovery record without calling services."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path


LABELS = {
    "load_state": "加载作品状态", "recall": "召回记忆", "plan_chapter": "规划章节",
    "plan_cast": "确定出场人物", "write": "生成正文", "extract": "抽取候选",
    "validate": "规则校验", "audit": "模型审核 / 工具查证", "route": "路由决定",
    "persist": "落库", "summarize": "摘要沉淀", "revise": "人工拒绝后的修订",
}


def render(source: Path) -> str:
    raw = source.read_bytes()
    report = json.loads(raw)
    runs = report["runs"]
    if not isinstance(runs, list) or not runs:
        raise ValueError("source must contain recorded runs")
    sections = []
    for index, run in enumerate(runs, 1):
        node = run["node"]
        detail = run.get("detail") or {}
        body = json.dumps(detail, ensure_ascii=False, indent=2)
        verdict = detail.get("audit_verdict") or {}
        reasons = verdict.get("reasons") or []
        reason_html = ''.join(f'<li>{html.escape(str(reason))}</li>' for reason in reasons)
        human = ''
        if node == 'revise':
            human = '<aside>评测脚本人为植入“瞬间移动”设定，作者以现实题材不允许此设定为由拒绝；此处进入修订。该操作说明来自 scripts/eval-workflow-recovery.py，并非日志新增的事件。</aside>'
        sections.append(
            f'<article data-stage="{html.escape(node, quote=True)}"><h2>{index:02d} · {html.escape(LABELS.get(node, node))}</h2>'
            f'<p><code>{html.escape(node)}</code> · 输入 {run.get("input_tokens", 0)} / 输出 {run.get("output_tokens", 0)} tokens</p>'
            f'{human}<ul>{reason_html}</ul><details><summary>查看已留存原始 detail</summary><pre>{html.escape(body)}</pre></details></article>'
        )
    digest = hashlib.sha256(raw).hexdigest()
    summary = {key: report.get(key) for key in ('fixture', 'initial', 'final_chars', 'error', 'needs_review', 'bad_sentence_removed')}
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Myink · Agent 历史执行案例</title><style>
:root{color-scheme:light dark;--bg:#f5f3ed;--ink:#202d29;--card:#fff;--line:#ccd5ce;--accent:#28654a}
@media(prefers-color-scheme:dark){:root{--bg:#101b18;--ink:#e3ece6;--card:#192823;--line:#42584b;--accent:#9bd7b5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.7 system-ui,"Microsoft YaHei",sans-serif}
main{max-width:1000px;margin:auto;padding:40px 24px}h1{font-size:clamp(28px,5vw,44px);line-height:1.2}h2{font-size:22px}
article,header,aside{padding:20px;border:1px solid var(--line);background:var(--card);margin:18px 0;border-radius:8px}
aside{border-left:4px solid var(--accent)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}code{overflow-wrap:anywhere}
button,select{font:inherit;padding:9px;border:1px solid var(--line);border-radius:4px;background:var(--card);color:var(--ink)}
nav{display:flex;flex-wrap:wrap;gap:12px;align-items:center}a{color:var(--accent)}[hidden]{display:none}
</style><main><header><p>MYINK / 历史真实模型记录 / 合成现实题材</p><h1>从生成到人工拒绝，再到修订落库</h1>
<p>离线浏览已保存证据，不会调用模型、读取作品库或重跑任务。来源是仓库已有的历史评测，不能当作 2026-10-08 新执行结果或长篇质量结论。</p>
<p>原始记录未包含完整初稿、完整修订稿、全部请求和模型版本/耗时/价格字段，故不能展示逐字 diff、核算成本或精确复现模型响应。空 detail 代表没有留存。</p>
<p>当前图已新增 plan_cast 等步骤；本页忠实保留历史记录的节点顺序。</p><p>来源：docs/evaluations/workflow-recovery.json<br>SHA-256：<code>''' + digest + '''</code></p>
<pre>''' + html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + '''</pre></header>
<nav aria-label="案例筛选"><label>显示 <select id="filter"><option value="all">全部节点</option><option value="audit">审核与查证</option><option value="route">路由</option><option value="revise">人工修订</option><option value="persist">落库</option></select></label><button id="expand" type="button">展开全部证据</button><span id="count" aria-live="polite"></span></nav>
''' + ''.join(sections) + '''<footer><p>讲解顺序：目标与现实约束 → 召回 → 计划与正文 → 工具和审核 → 实际路由 → 人工拒绝 → 修订/重新抽取/复审 → 落库时旧记忆失效。</p><p>配套说明：<a href="../INTERVIEW-ROADMAP.md">优化路线</a> · <a href="../DEMO.md">演示步骤与证据边界</a></p></footer></main>
<script>const articles=[...document.querySelectorAll('article')];const filter=document.getElementById('filter');function apply(){let n=0;for(const a of articles){a.hidden=filter.value!=='all'&&a.dataset.stage!==filter.value;if(!a.hidden)n++;}document.getElementById('count').textContent=n+' / '+articles.length+' 个节点';}filter.addEventListener('change',apply);document.getElementById('expand').addEventListener('click',()=>{const ds=[...document.querySelectorAll('article:not([hidden]) details')];const open=ds.some(d=>!d.open);for(const d of ds)d.open=open;document.getElementById('expand').textContent=open?'收起证据':'展开全部证据';});apply();</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('docs/evaluations/workflow-recovery.json'))
    parser.add_argument('--output', type=Path, default=Path('docs/interview/agent-execution.html'))
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve():
        parser.error('output must not overwrite the source record')
    page = render(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding='utf-8')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
