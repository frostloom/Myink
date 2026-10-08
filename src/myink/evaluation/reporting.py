"""Rebuildable summaries with confirmed and provisional results kept separate."""
from __future__ import annotations

from collections import Counter
import html
from pathlib import Path

from myink.evaluation.cases import json_text


def ratio(n,d):
    return n/d if d else None


def summarize(rows: list[dict]) -> dict:
    completed=[r for r in rows if r['execution']=='completed' and r.get('coverage')=='implemented']
    confirmed=[r for r in completed if r['review']=='confirmed' and r['label_status']=='reviewed']
    pos=[r for r in confirmed if r['polarity']=='positive']
    neg=[r for r in confirmed if r['polarity']=='negative']
    tp=sum(r['tp'] for r in confirmed);fp=sum(r['fp'] for r in confirmed);fn=sum(r['fn'] for r in confirmed)
    applicable=[r for r in rows if r.get('coverage')=='implemented']
    return {'planned':len(rows),'attempted':sum(bool(r.get('attempted')) for r in rows),
            'completed':len(completed),'execution_counts':dict(Counter(r['execution'] for r in rows)),
            'review_counts':dict(Counter(r['review'] for r in rows)),
            'label_counts':dict(Counter(r['label_status'] for r in rows)),
            'provisional_automatic':{'passed':sum(r['automatic_pass'] for r in completed),
                                     'denominator':len(completed),'note':'候选匹配，不是人工确认的准确率'},
            'confirmed':{'cases':len(confirmed),'tp':tp,'fp':fp,'fn':fn,
                         'precision':ratio(tp,tp+fp),'recall':ratio(tp,tp+fn),
                         'positive_detection':ratio(sum(r['fn']==0 for r in pos),len(pos)),
                         'negative_false_positive':ratio(sum(r['fp']>0 for r in neg),len(neg)),
                         'overall_success':ratio(sum(r['confirmed_pass'] is True for r in confirmed),len(applicable))
                             if confirmed else None},
            'evidence':{'valid_quotes':sum(r['valid_quotes'] for r in completed),
                        'total_quotes':sum(r['total_quotes'] for r in completed),
                        'findings_without_quotes':sum(r['findings_without_quotes'] for r in completed)},
            'usage':{'input_tokens':sum(r.get('input_tokens',0) for r in rows),
                     'output_tokens':sum(r.get('output_tokens',0) for r in rows),
                     'estimated_cost_yuan':sum(r.get('cost_est',0) for r in rows),
                     'unknown_usage_runs':sum(r.get('cost_status')=='unknown' for r in rows)},
            'categories':{category:{'runs':sum(r['category']==category for r in rows),
                'automatic_passed':sum(r['category']==category and r['automatic_pass'] for r in rows)}
                for category in sorted({r['category'] for r in rows})}}


def write_report(directory: Path, rows: list[dict]) -> dict:
    directory.mkdir(parents=True,exist_ok=True)
    summary=summarize(rows)
    (directory/'summary.json').write_text(json_text(summary),encoding='utf-8')
    cards=[]
    for row in rows:
        safe=html.escape(json_text({k:v for k,v in row.items() if k not in ('case','raw_output','raw_response_content')}))
        case=row.get('case') or {}
        inputs=html.escape(json_text({'input':case.get('input'),'expected':case.get('expected'),'label':case.get('label')}))
        response=html.escape(row.get('raw_output') or '无模型输出；查看执行状态和错误。')
        cards.append(f'<article><h2>{html.escape(row["case_id"])}</h2><p>执行：{html.escape(row["execution"])} '
                     f'· 复核：{html.escape(row["review"])} · 暂定自动通过：{row["automatic_pass"]}</p>'
                     f'<details><summary>输入背景、正文与预期问题</summary><pre>{inputs}</pre></details>'
                     f'<details><summary>查看模型实际输出</summary><pre>{response}</pre></details>'
                     f'<details><summary>实际输出、证据检查与复核结果</summary><pre>{safe}</pre></details></article>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Myink · P1 审核基线</title><style>body{margin:0;background:#f5f3ed;color:#20352a;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}
main{max-width:1050px;margin:auto;padding:24px}header,article{background:white;border:1px solid #ccd5ce;padding:20px;margin:18px 0;border-radius:8px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 monospace}summary{cursor:pointer}h1{font-size:32px}h2{font-size:22px}</style>
<main><header><h1>P1 · 固定文本审核基线</h1><p>自动结果只验证类型、证据来源和决策，语义判断需人工复核。confirmed 为正式复核口径；分母为零显示 null / N/A。</p>
<p>所有失败与中止记录均保留；本报告不是直接生成与完整系统的效果对照，也不是向量召回评测。</p><pre>'''
    page+=html.escape(json_text(summary))+'</pre></header>'+''.join(cards)+'</main></html>'
    (directory/'report.html').write_text(page,encoding='utf-8')
    return summary
