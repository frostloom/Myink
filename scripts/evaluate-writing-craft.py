"""Bounded, explicit live prose comparison using synthetic cases and published public rules.

Runs in a temporary worker container, reads model/catalog configuration, creates
no projects/tasks/agent_runs and never prints credentials or provider addresses.
The HTTP request hook caps retries as well as logical calls. Output is JSONL.
"""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
import logging
import os
import random
import re

parser = argparse.ArgumentParser()
parser.add_argument('--allow-live', action='store_true')
parser.add_argument('--max-requests', type=int, default=15)
args = parser.parse_args()
if not args.allow_live or not 1 <= args.max_requests <= 15:
    parser.error('Explicit --allow-live and a request cap of 1–15 are required')
logging.disable(logging.CRITICAL)
payload = json.loads(base64.b64decode(os.environ['CRAFT_EVAL_PAYLOAD']))
from myink.db import new_session
from myink.platform_configuration import load_configuration, resolve_connection
from myink.providers import _chain_from_override
from myink.providers.connections import price_table
from myink.providers.prices import lookup_prices
from myink.seed import STYLE_PRESETS
from myink.writing_resources import catalog, capture_role_prompts
from myink.writing_resource_runtime import bind_resources
from myink.workflow import prompts
from myink.workflow.nodes import _parse_json

config = load_configuration()
connection = resolve_connection('writer', {}, config, tier='normal')
if not connection:
    raise RuntimeError('No published normal-tier writer model')
chain = _chain_from_override(connection, False)
provider = chain.providers[0]
attempts = 0
def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)
def cap_request(request):
    global attempts
    if attempts >= args.max_requests:
        raise RuntimeError('Live evaluation HTTP request cap reached')
    attempts += 1
    emit({'event': 'request_started', 'attempt': attempts})
provider._client.event_hooks['request'].append(cap_request)
prices = price_table(connection) or lookup_prices(connection['model'])
emit({'event': 'start', 'model': connection['model'], 'temperature': .7,
      'request_cap': args.max_requests, 'prices_known': prices is not None,
      'synthetic_inputs_only': True, 'variant_specs': payload.get('variant_specs'), 'app_source': payload['app_source']})
with new_session() as db:
    documents = catalog(db, include_automatic=True)
    roles = capture_role_prompts(db)
base_ids = {'writing-rule:continuity', 'expression-rule:bans', 'expression-rule:prose',
            'writing-rule:scene-causality', 'expression-rule:dialogue', 'writing-rule:genre-pacing'}
rules = [dict(resource_id=r['id'], kind=r['kind'], name=r['name'], origin='platform',
              version=r['current_version'], body=r['body']) for r in documents if r['id'] in base_ids]
assert {r['resource_id'] for r in rules} == base_ids
candidate_definitions = {}
if payload.get('candidate_bundle'):
    from myink.writing_resource_seed import builtin_resources
    candidate_definitions = {r['id']: r for r in builtin_resources()}
baseline_style = next(p['style_profile'] for p in STYLE_PRESETS if p['id'] == 'natural-narration')

def call(messages, *, judge=False):
    response = provider.generate(messages, model_id=connection['model'], max_tokens=2400,
                                 temperature=.2 if judge else .7, disable_thinking=True)
    if response.error or not response.content or response.finish_reason == 'length':
        emit({'event': 'failed', 'error': 'provider_error_or_truncated', 'attempts': attempts,
              'input_tokens': response.input_tokens, 'output_tokens': response.output_tokens})
        raise RuntimeError('Evaluation stopped; failed output is not a passing sample')
    return response

def inputs(case, variant):
    selections = deepcopy(rules)
    genre = next((r for r in documents if r['kind'] == 'genre' and r['name'] == case['genre']), None)
    if not genre:
        raise RuntimeError('Benchmark genre is not in the published catalog')
    selections.append(dict(resource_id=genre['id'], kind='genre', name=genre['name'],
                           origin='platform', version=genre['current_version'], body=genre['body']))
    for r in documents:
        if r['kind'] == 'genre_rule' and genre['body']['catalog_id'] in r['body'].get('genre_ids', []):
            selections.append(dict(resource_id=r['id'], kind=r['kind'], name=r['name'],
                                   origin='platform', body=r['body']))
    admitted_roles = deepcopy(roles)
    if payload.get('candidate_bundle') and variant != 'baseline':
        for selection in selections:
            if selection['resource_id'] == 'writing-rule:continuity':
                selection['body'] = deepcopy(candidate_definitions[selection['resource_id']]['body'])
        entry = candidate_definitions['genre-rule:craft-realism-suspense']
        if genre['body']['catalog_id'] in entry['body']['genre_ids']:
            selections.append(dict(resource_id=entry['id'], kind=entry['kind'], name=entry['name'], origin='platform', body=deepcopy(entry['body'])))
        for role in ('writer', 'planner'):
            admitted_roles[role] = {'body': deepcopy(candidate_definitions['role-prompt:' + role]['body'])}
        selections.sort(key=lambda item: item['resource_id'])
    spec = payload.get('variant_specs', {}).get(variant, {
        'continuity': variant != 'baseline', 'lesson': variant == 'craft',
        'profiles': variant == 'craft',
    })
    if spec.get('continuity'):
        body = next(r for r in selections if r['resource_id'] == 'writing-rule:continuity')['body']
        for role in ('writer', 'planner', 'audit'):
            body['roles'][role] = spec.get('continuity_text', payload['continuity']) + (payload.get('review_policy', '') if role == 'audit' else '')
    if spec.get('lesson'):
        body = next(r for r in selections if r['resource_id'] == 'expression-rule:prose')['body']
        for role in ('writer', 'audit'):
            body['roles'][role] += '\n' + payload['lesson']
    style = payload['profiles'][case['style']] if spec.get('profiles') else baseline_style
    context = {'short_context': [{'kind': 'prev_chapter_tail', 'tail': case['previous_tail']}],
               'long_term_facts': [{'content': fact, 'is_hard': True} for fact in case['facts']]}
    events = list(case.get('expected_events', []))
    if case['must_end'] not in events:
        events.append(case['must_end'])
    plan = {'goals': [case['goal']], 'expected_events': events, 'hard_constraints': case['facts'],
            'transition': {'mode': 'continue', 'pending_action': case['goal'], 'opening_beat': case['goal']}}
    return {'configured': True, 'selections': selections, 'role_prompts': admitted_roles}, style, context, plan

def generate(case, variant, repeat=False):
    snapshot, style, context, plan = inputs(case, variant)
    with bind_resources(snapshot):
        messages = prompts.write_messages(context, plan, style_profile=style, target_words=650)
    if variant != 'baseline' and payload.get('completion_sections'):
        section = payload['completion_sections'][case['id']]
        user_message = next(m for m in reversed(messages) if m['role'] == 'user')
        user_message['content'] = user_message['content'].removesuffix('\n请输出本章正文。') + section + '\n请输出本章正文。'
    frame = None
    if payload.get('frame_scaffold'):
        frame_system = ('你是小说段落框架编辑。只写本章首段和末段，不写中间，不解释。首段从给定上章结尾的未完成话语/动作继续，保持开场人物位置、手持物件、历史记录，不重演完成动作。末段把本章要求的终态与动作写成现场实际发生的事情，指定人物亲自完成，不能约定明天再办。框架要克制且符合作者文风，不给正文增加新谜团或冲突，不用总结冒充实际动作。每段约80-180字，篇幅可随必需事件调整。只输出JSON：{"opening":"首段正文","closing":"末段正文"}。\n作者文风：\n' + prompts._style_section(style, None))
        response = call([{'role': 'system', 'content': frame_system}, {'role': 'user', 'content': json.dumps(case, ensure_ascii=False)}], judge=True)
        frame = _parse_json(response.content)
        assert isinstance(frame.get('opening'), str) and frame['opening'].strip()
        assert isinstance(frame.get('closing'), str) and frame['closing'].strip()
        frame = {key: frame[key].strip() for key in ('opening', 'closing')}
        emit({'event': 'frame', 'case': case['id'], 'repeat': repeat, 'frame': frame,
              'input_tokens': response.input_tokens, 'output_tokens': response.output_tokens})
        user_message = next(m for m in reversed(messages) if m['role'] == 'user')
        user_message['content'] += ('\n\n【本章首尾段框架】\n' + json.dumps(frame, ensure_ascii=False)
            + '\n请仍输出完整本章正文和原有CONTENT标记：首段逐字采用opening，末段逐字采用closing。中间写出从首段到末段的过程，保持两端位置/知识/物件状态能接得上；不要在中间提前写到末段之后，也不重演首末段动作。不要输出框架JSON或字段名。')
    rendered = '\n'.join(m['content'] for m in messages)
    for requirement in [case['previous_tail'], case['goal'], *case['facts'], *plan['expected_events']]:
        assert requirement in rendered or json.dumps(requirement, ensure_ascii=False)[1:-1] in rendered, 'Required benchmark input was not delivered to writer'
    response = call(messages)
    assert '=== CONTENT ===' in response.content, 'Missing required CONTENT protocol marker'
    text = response.content.split('=== CONTENT ===', 1)[-1].strip()
    result = {'case': case['id'], 'variant': variant, 'repeat': repeat, 'text': text,
              'frame_adherence': (text.startswith(frame['opening']) and text.endswith(frame['closing'])) if frame else None,
              'chars': len(re.findall(r'[\u3400-\u9fff]', text)), 'model': response.model_id,
              'input_tokens': response.input_tokens, 'output_tokens': response.output_tokens,
              'duration_ms': response.duration_ms, 'finish_reason': response.finish_reason,
              'cache_hit': response.cache_hit, 'usage_complete': response.usage_complete,
              'cost_est_cny': response.cost_est if prices is not None else None,
              'messages_sha256': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()}
    emit({'event': 'sample', **result})
    return result

if payload.get('direct_requests'):
    for request in payload['direct_requests']:
        case = next(c for c in payload['cases'] if c['id'] == request['case'])
        generate(case, request['variant'], request.get('repeat', False))
    emit({'event': 'complete', 'attempts': attempts, 'mode': 'independent_review_only'})
    raise SystemExit(0)

if payload.get('contract_samples'):
    for sample in payload['contract_samples']:
        case = next(c for c in payload['cases'] if c['id'] == sample['case'])
        snapshot, style, context, plan = inputs(case, 'craft')
        with bind_resources(snapshot):
            base_messages = prompts.audit_messages(sample['text'], plan, context, 2, style_profile=style)
        for mode in payload.get('audit_modes', ('current', 'obligations', 'proof')):
            messages = deepcopy(base_messages)
            if mode != 'current':
                obligations = [{'type': 'hard_constraint', 'requirement': item} for item in plan.get('hard_constraints', [])]
                obligations += [{'type': 'expected_event', 'requirement': item} for item in plan.get('expected_events', [])]
                user_message = next(m for m in reversed(messages) if m['role'] == 'user')
                user_message['content'] += '\n\n【本章逐项验收要求】\n' + json.dumps(obligations, ensure_ascii=False)
                user_message['content'] += '\n先独立核对每项要求与正文实际发生的事，再决定verdict。匹配名词不等于动作、主体、用途与结果相同；不能用想象补足缺失或改写要求。'
                if mode == 'proof':
                    user_message['content'] += '\nreasons必须按上表逐项给出结论与正文逐字证据，明确是满足、违背或尚未兑现；不确定的地方写不确定。发现违背或关键结果未兑现时，findings给出对应原文与修改建议。先核完这些要求，最后再决定是否pass。'
            if mode in ('focused', 'focused_temporal'):
                messages = [
                    {'role': 'system', 'content': '你是事实校对员。只核对给定事实、上一段末尾和指定本段结果，与待校对正文是否一致。完全忽略文采、句式禁令、题材模板与是否好看。先分别提取事实表说的是什么、原文实际说的是什么，最后比较；不要因为出现相同词就判断相符。正文缺失不可脑补。输出JSON：{"checks":[{"requirement":"逐字的给定要求","actual_quote":"正文逐字证据，无则空","result":"supported|violated|missing|uncertain","difference":"具体差异或为何一致"}],"internal_contradictions":[{"quote_a":"原文逐字片段","quote_b":"原文逐字片段","difference":"互相冲突的内容"}]}。每条给定事实、本段结果都必须有一个check。不要返回pass/rewrite，不润色、不夸奖。'},
                    {'role': 'user', 'content': json.dumps({'facts': case['facts'], 'previous_tail': case['previous_tail'], 'required_result': case['must_end'], 'text': sample['text']}, ensure_ascii=False)},
                ]
            if mode == 'focused_temporal':
                messages[0]['content'] += '\n事实表描述的是开场已知事实，正文可以通过明确发生的新动作改变状态。先区分历史记录、开场状态、持续限制和本段必须结果，禁止把所有开场状态冻结成永久禁令。例：前段甲尚不知道真相，乙在正文告知后甲知情，这是正常推进；前段钥匙在桌上，正文甲拿起来，这是有过程的变化，不是矛盾。相反，前段登记某次事件08:05，正文回指同一事件08:07且无校正依据，这是历史改写。逐项核对previous_tail的动作和记录数值，不能只核对facts列表。追踪同一物件或记录全文每一次出现，若原文一处放入口袋、另一处仍摊桌上且无取出过程，才是矛盾。没有写出每个中间动作不等于错误，常识可补的小动作不误报；只能提供确实互斥的两段引文，不许把先前没做、后来做了误当自相矛盾。'
            response = call(messages, judge=True)
            judgment = _parse_json(response.content)
            emit({'event': 'contract_audit', 'sample': sample['id'], 'case': case['id'], 'mode': mode,
                  'judgment': judgment, 'input_tokens': response.input_tokens, 'output_tokens': response.output_tokens})
    emit({'event': 'complete', 'attempts': attempts, 'mode': 'obligation_comparison'})
    raise SystemExit(0)

if payload.get('review_samples'):
    for sample in payload['review_samples']:
        case = next(c for c in payload['cases'] if c['id'] == sample['case'])
        snapshot, style, context, plan = inputs(case, sample['variant'])
        draft = sample['text']
        with bind_resources(snapshot):
            messages = prompts.audit_messages(draft, plan, context, 2, style_profile=style)
        response = call(messages, judge=True)
        judgment = _parse_json(response.content)
        emit({'event': 'pipeline_audit', 'case': case['id'], 'variant': sample['variant'],
              'judgment': judgment, 'input_tokens': response.input_tokens, 'output_tokens': response.output_tokens})
        if judgment.get('verdict') == 'rewrite':
            with bind_resources(snapshot):
                messages = prompts.revise_messages(draft, judgment.get('findings', []), 2,
                    context=context, plan=plan, style_profile=style, target_words=650)
            response = call(messages)
            draft = response.content.split('=== CONTENT ===', 1)[-1].strip()
            emit({'event': 'pipeline_revision', 'case': case['id'], 'variant': sample['variant'],
                  'text': draft, 'input_tokens': response.input_tokens, 'output_tokens': response.output_tokens})
        emit({'event': 'pipeline_final', 'case': case['id'], 'variant': sample['variant'],
              'text': draft, 'audit_verdict': judgment.get('verdict')})
    emit({'event': 'complete', 'attempts': attempts, 'mode': 'existing_audit_revision_pipeline'})
    raise SystemExit(0)

variants = ['baseline', 'continuity', 'craft']
samples = {}
for case in payload['cases']:
    # Rotate order to reduce a consistent temporal/cache/order advantage.
    order = variants[payload['cases'].index(case):] + variants[:payload['cases'].index(case)]
    for variant in order:
        samples[(case['id'], variant)] = generate(case, variant)

rank_totals = dict.fromkeys(variants, 0)
for case in payload['cases']:
    order = variants[:]
    random.Random(case['id'] + ':blind').shuffle(order)
    labels = dict(zip('XYZ', order))
    texts = {label: samples[(case['id'], variant)]['text'] for label, variant in labels.items()}
    messages = [{'role': 'system', 'content': '你是小说编辑。对匿名稿件做相对盲评；不要猜写作规则，不偏好篇幅长或华丽辞藻。事实、衔接和人物认知不能为文笔让路。只返回JSON。'},
                {'role': 'user', 'content': json.dumps({'case': case, 'drafts': texts,
                 'task': '按衔接保真、人物对白、具体细节/视角、句段自然、题材推进评价。列出各稿的具体原句证据与硬事实违反，返回ranking（X/Y/Z从好到差，恰好各一次）、reasons、hard_violations。不能把没写的内容当证据；相近就明确差异很小。'}, ensure_ascii=False)}]
    response = call(messages, judge=True)
    judgment = _parse_json(response.content)
    ranking = judgment.get('ranking')
    assert isinstance(ranking, list) and len(ranking) == 3 and set(ranking) == set(labels)
    for rank, label in enumerate(ranking):
        rank_totals[labels[label]] += rank
    emit({'event': 'blind_judge', 'case': case['id'], 'labels': labels, 'judgment': judgment,
          'input_tokens': response.input_tokens, 'output_tokens': response.output_tokens,
          'cache_hit': response.cache_hit, 'usage_complete': response.usage_complete,
          'cost_est_cny': response.cost_est if prices is not None else None})

winner = min(variants, key=lambda v: rank_totals[v])
emit({'event': 'provisional_result', 'rank_totals_lower_better': rank_totals, 'winner': winner,
      'limits': 'Same-model small-sample blind ranking; independent review and fact checking still required'})
if winner != 'baseline':
    for case in payload['cases']:
        generate(case, winner, repeat=True)
emit({'event': 'complete', 'attempts': attempts, 'winner': winner, 'prices_known': prices is not None})
