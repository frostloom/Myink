"""Offline derived report: immutable primary and budget-only supplement stay intact."""
import argparse
import hashlib
import html
import json
from pathlib import Path

from myink.evaluation.cases import json_text
from myink.evaluation.comparison import blind_bundle, combine_outputs


def assemble(primary: Path, supplement: Path, output: Path):
    def read(directory, name):return json.loads((directory/name).read_text(encoding='utf-8'))
    def sha(file):return hashlib.sha256(file.read_bytes()).hexdigest()
    original=read(primary,'manifest.json');extra=read(supplement,'manifest.json')
    if original['status']!='finished' or extra['status']!='finished':raise ValueError('finished runs required')
    binding=extra['supplement_source']
    if binding['run_sha256']!=sha(primary/'run.json') or binding['results_sha256']!=sha(primary/'results.json'):
        raise ValueError('supplement source hash mismatch')
    selected,attempts=combine_outputs(read(primary,'results.json'),read(supplement,'results.json'))
    for directory,manifest in ((primary,original),(supplement,extra)):
        if len(list((directory/'requests').glob('*/result.json')))!=manifest['actual_requests']:
            raise ValueError('request artifacts do not match manifest')
    summary={'planned_outputs':len(selected),'completed_outputs':sum(r['execution']=='completed' for r in selected),
             'retained_attempts':len(attempts),'retained_budget_stops':sum(r['execution']=='budget_stopped' for r in attempts),
             'actual_requests':original['actual_requests']+extra['actual_requests'],
             'estimated_cost_yuan':original['cost_reserved_or_estimated_yuan']+extra['cost_reserved_or_estimated_yuan'],
             'quality_status':'pending_independent_review',
             'limits':['historical direct inputs omitted previous_tail and explicit alias mapping; not a fair quality superiority comparison',
                       'vector embeddings disabled; no single-chapter Reflexion ablation',
                       'completed generation may still await author review; not end-to-end persistence success']}
    output.mkdir(parents=True,exist_ok=False)
    for name,value in (('selected.json',selected),('attempts.json',attempts),('summary.json',summary)):
        (output/name).write_text(json_text(value),encoding='utf-8')
    # Include stopped attempts too, rather than hiding them from the review packet.
    blind,key=blind_bundle(attempts,seed=20261008)
    (output/'blind-review.json').write_text(json_text(blind),encoding='utf-8')
    (output/'blind-key.json').write_text(json_text(key),encoding='utf-8')
    (output/'cases.json').write_text(json_text(read(primary,'run.json')['cases']),encoding='utf-8')
    manifest={'mode':'offline_comparison_assembly','sources':[
        {'directory':str(directory.resolve()),'hashes':{name:sha(directory/name) for name in ('run.json','results.json','manifest.json')}}
        for directory in (primary,supplement)],'assembler_sha256':sha(Path(__file__)),
        'blind_seed':20261008,'api_requests':0}
    (output/'manifest.json').write_text(json_text(manifest),encoding='utf-8')
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P1 对照与补跑记录</title><style>body{max-width:1050px;margin:32px auto;padding:0 20px;font:16px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #aaa;padding:14px 0}summary{cursor:pointer}</style><h1>P1 生成对照与补跑记录</h1><p>这是流程、产物与成本证据。原 direct 组遗漏前章尾文和明确别名映射，不能作为公平质量优劣结论。所有正文待独立复核，系统自审通过不等于效果优胜。首轮中止与补跑均保留。</p>',
           '<pre>'+html.escape(json_text(summary))+'</pre>']
    for index,row in enumerate(attempts,1):
        parts.append('<article><h2>'+html.escape(f'{index:02d} · {row["case_id"]} · {row["variant"]} · 第{row["repetition"]}次')+'</h2><p>'+html.escape(row['execution']+' / '+row['outcome'])+'</p><details><summary>完整正文</summary><pre>'+html.escape(row['draft'])+'</pre></details></article>')
    (output/'report.html').write_text('\n'.join(parts)+'</html>',encoding='utf-8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary',type=Path,required=True)
    parser.add_argument('--supplement',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json_text(assemble(args.primary,args.supplement,args.output)))
