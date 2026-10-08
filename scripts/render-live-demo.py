"""Render a newly captured synthetic run with full drafts and persisted evidence."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
from pathlib import Path


def render(source: Path) -> str:
    raw = source.read_bytes()
    report = json.loads(raw)
    evidence = report['artifacts']
    initial, final = evidence['initial'], evidence['final']
    feedback = evidence['human_feedback']
    runs = report['runs']
    esc = lambda value: html.escape(str(value))

    def block(value):
        if value is None:
            return '<p>本次没有该项产物。</p>'
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        return '<pre>' + esc(text) + '</pre>'

    def section(sid, title, explanation, value):
        return f'<section id="{sid}"><h2>{title}</h2><p>{explanation}</p>{block(value)}</section>'

    total_in = sum(run.get('input_tokens', 0) for run in runs)
    total_out = sum(run.get('output_tokens', 0) for run in runs)
    models = sorted({run['model_id'] for run in runs if run.get('model_id')})
    verdict = (final.get('audit_verdict') or {}).get('verdict', '未留存')
    removed = report['bad_sentence_removed']
    content_matches = any(row.get('content') == final.get('draft')
                          for row in evidence['database']['chapters'])
    overview = f'''<header><p>MYINK / 本轮真实模型执行 / 合成故事</p>
<h1>雨夜检修：看见生成、反馈和修改</h1>
<p>这次保存了完整初稿和修订稿。先读故事，再看脚本加入的问题句，最后核对修订结果。</p>
<p>开始：{esc(evidence['started_at'])}；结束：{esc(evidence['finished_at'])}（UTC）</p>
<p>模型：{esc(', '.join(models))} · {len(runs)} 条运行记录 · 输入 {total_in} / 输出 {total_out} tokens</p>
<div class="metrics"><span>问题句移除：{'是' if removed else '否'}</span><span>最终审核：{esc(verdict)}</span>
<span>正文与落库一致：{'是' if content_matches else '否'}</span>
<span>仍需人工处理：{'是' if final.get('needs_review') else '否'}</span></div>
<p>本案例使用隔离数据库；人为加入的错误明确标注。它验证一条实际执行路径，不代表长期生成质量。</p></header>'''
    nav = '<nav>' + ''.join(f'<a href="#{sid}">{label}</a>' for sid, label in (
        ('task', '任务'), ('context', '背景'), ('plan', '计划'), ('initial', '初稿'),
        ('feedback', '人工反馈'), ('final', '修订稿'), ('diff', '修改对比'),
        ('saved', '最终保存'), ('timeline', '运行过程'))) + '</nav>'
    parts = [overview, nav]
    parts.append(section('task', '01 · 要完成什么', '这是实际送入章节工作流的写作指令和硬约束。',
                         {'写作指令': evidence['instruction'], '硬约束': evidence['constraints']}))
    parts.append(section('context', '02 · Agent 拿到了哪些背景',
                         '人物来自本次合成作品库；context 是工作流实际使用的上下文。零条目表示本次无相关记忆。',
                         {'人物': initial['characters'], '召回上下文': initial['context']}))
    parts.append(section('plan', '03 · 先决定怎么写', '以下是模型产生的出场规划与章节计划。',
                         {'出场规划': initial['cast'], '章节计划': initial['plan']}))
    parts.append(section('initial', '04 · 首次生成的完整正文',
                         '这是第一轮工作流结束时的正文，尚未加入用于测试的错误句。', initial['draft']))
    parts.append(section('feedback', '05 · 人工反馈具体改什么',
                         '为验证人工拒绝后的修订，评测脚本在初稿末尾加入下方错误句，再调用候选拒绝与审核恢复流程。',
                         {'人为加入的错误句': feedback['injected_sentence'], '拒绝理由': feedback['reason']}))
    parts.append('<details><summary>查看送入修订的完整正文（含注入错误）</summary>'
                 + block(feedback['rejected_draft']) + '</details>')
    parts.append(section('final', '06 · 修改后的完整正文', '这是修订复审后的实际正文。', final['draft']))
    diff = difflib.HtmlDiff(wrapcolumn=48).make_table(
        feedback['rejected_draft'].splitlines(), (final['draft'] or '').splitlines(),
        fromdesc='送入修订的正文（含人为错误）', todesc='实际修订结果', context=True, numlines=2)
    parts.append('<section id="diff"><h2>07 · 修订前后逐行对比</h2><p>红色为删除，绿色为新增，黄色为修改。'
                 '正文可能整体重写；移除问题句之外的变化也如实保留。</p><div class="diff-wrap">' + diff + '</div></section>')
    parts.append(section('audit', '08 · 为什么允许保存', '这是最终审核结论及实际规则检查结果。',
                         {'模型审核': final['audit_verdict'], '规则校验': final['report']}))
    database = evidence['database']
    parts.append(section('saved', '09 · 数据库最后保存了什么',
                         '以下是临时库实际导出的摘要、事实、人物状态、事件与候选。保留确认状态、失效字段和审核记录，'
                         '不能把待确认或失效条目当成有效记忆。',
                         {'章节': [{k: v for k, v in row.items() if k != 'content'} for row in database['chapters']],
                          '事实': database['facts'], '人物状态': database['character_states'],
                          '事件': database['events'], '候选与审核状态': database['memory_candidates']}))
    parts.append('<section id="timeline"><h2>10 · 实际运行过程</h2><p>程序节点不调用模型，所以 tokens 为零；'
                 '原始模型消息及运行详情放在展开项中，截断以记录中的标记为准。</p>')
    for i, run in enumerate(runs, 1):
        detail = run.get('detail') or {}
        reasons = (detail.get('audit_verdict') or {}).get('reasons', [])
        parts.append(f'<article><h3>{i:02d} · {esc(run["node"])}</h3><p>输入 {run["input_tokens"]} / '
                     f'输出 {run["output_tokens"]} tokens · 耗时 {run.get("duration_ms", 0)} ms</p>')
        if reasons:
            parts.append('<ul>' + ''.join('<li>' + esc(reason) + '</li>' for reason in reasons) + '</ul>')
        elif not run.get('model_id'):
            parts.append('<p>程序执行节点，执行统计见下方详情。</p>')
        else:
            parts.append('<p>模型调用记录；完整关键产物见上方计划、正文和审核区。</p>')
        parts.append('<details><summary>查看实际运行记录</summary>' + block(run) + '</details></article>')
    parts.append('</section>')
    parts.append(section('source', '来源与限制', '完整机器可读记录及内容摘要校验。',
                         {'来源': source.as_posix(), 'SHA-256': hashlib.sha256(raw).hexdigest(),
                          'task_id': evidence['task_id'], '限制': evidence['limitations']}))
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Myink · 本轮完整执行案例</title><style>
:root{color-scheme:light dark;--bg:#f5f3ed;--ink:#20352a;--card:#fff;--line:#d0d8d0;--accent:#28654a}
@media(prefers-color-scheme:dark){:root{--bg:#101b18;--ink:#e3ece6;--card:#192823;--line:#42584b;--accent:#9bd7b5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif}
main{max-width:1120px;margin:auto;padding:30px 20px}h1{font-size:clamp(28px,5vw,40px);line-height:1.3}h2{font-size:24px}
header,section,article{padding:22px;background:var(--card);border:1px solid var(--line);border-radius:8px;margin:18px 0}
article{padding:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.9 system-ui,"Microsoft YaHei",sans-serif}
nav,.metrics{display:flex;gap:12px;flex-wrap:wrap}nav a,.metrics span{padding:7px 12px;border:1px solid var(--line);border-radius:5px}
a{color:var(--accent)}summary{cursor:pointer;font-weight:600}details{margin:12px 0}.diff-wrap{overflow:auto}
table.diff{border-collapse:collapse;font:13px/1.6 monospace;background:#fff;color:#222;width:100%}table.diff td,table.diff th{padding:4px;border:1px solid #ddd}
.diff_header{background:#e8ece9}.diff_next{background:#e8ece9}.diff_add{background:#b5edc6}.diff_sub{background:#f6bab7}.diff_chg{background:#ffed95}
section{scroll-margin-top:15px}</style><main>''' + ''.join(parts) + '</main></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve():
        parser.error('output must not overwrite source')
    page = render(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding='utf-8')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
