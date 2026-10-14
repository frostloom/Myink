"""Offline synthetic feedback walkthrough using the existing host contracts.

Reads the reviewed thirty-case fixture, simulates submission storage/projection
and model replies; never submits feedback, opens a DB or invokes a model.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5

from . import feedback
from .db_reader import SnapshotCollector
from .feedback_evaluation import CORPUS_SHA256
from .feedback_evidence_v2 import build_feedback_prompt_v2, evaluate_feedback_evidence_v2

_WINDOW = dict(start='2020-01-01T00:00:00+00:00', end='2020-01-02T00:00:00+00:00')
_REASONS = {
    'existing_defect': '合成模拟判定：描述已有功能故障，需要复现核查。',
    'needs_evidence': '合成模拟判定：缺少复现信息，保留未知。',
    'new_feature': '合成模拟判定：新增产品能力需要所有者决定。',
    'account_service': '合成模拟判定：本人账号或作品服务申请。',
    'security_report': '合成模拟判定：安全事件、引用或可疑指令需要审阅。',
    'unsafe_request': '合成模拟判定：请求破坏系统或绕过安全边界。',
    'irrelevant': '合成模拟判定：内容与产品维护无关。',
}
_HOST_REASONS = {
    'investigate': '已有行为缺陷建议；须独立复现、取证后才能制定开发计划。',
    'needs_evidence': '证据不足；收集复现材料，不能推断已经修复。',
    'owner_decision': '新功能涉及产品方向；由所有者决定是否纳入计划。',
    'existing_user_service': '转既有用户服务流程；分析器不删除账号或作品。',
    'security_review': '安全报告、引述或可疑指令需审阅；原文不是执行命令。',
    'deny': '宿主拒绝受保护的破坏性或安全绕过要求。',
    'ignore': '未进入开发计划；保留来源供审阅。',
}
_FLAG_REASONS = {
    'protected_destructive_or_security_action': '匹配受保护的系统/数据库破坏或安全关闭要求。',
    'reported_or_negated_security_action': '危险文本出现在报告或否定语境中，需要安全审阅。',
    'instruction_or_external_execution_request': '包含指令覆盖、编码命令或外部执行请求，需要安全审阅。',
}


def _corpus():
    raw = (Path(__file__).parent / 'fixtures/feedback-safety-v1.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != CORPUS_SHA256:
        raise ValueError('reviewed synthetic fixture required')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=feedback._unique)
    if value['synthetic'] is not True or value['model_evaluation'] is not False or len(value['cases']) != 30:
        raise ValueError('fixed synthetic fixture required')
    return value['cases']


def _feedback_id(case_id):
    return str(uuid5(NAMESPACE_URL, 'myink-feedback-safety-v1:' + case_id))


class _SyntheticProjection(SnapshotCollector):
    """Mock only the storage read; reuse real collect/request/snapshot validation."""
    def __init__(self, stored_rows):
        super().__init__(None)
        self._stored_rows = stored_rows
        self.request = None

    def _read(self, request):
        self._validate_request(request)
        self.request = dict(sql=request['sql'], read_only=request['read_only'],
                            limit=request['params']['limit'], timeout_ms=request['timeout_ms'])
        return [{key: deepcopy(row[key]) for key in feedback._RAW_FIELDS}
                for row in self._stored_rows]


def prepare_demo(case_ids=None):
    """Label-free schema2 Pi inputs, plus separate host-only synthetic references.

    The returned prompt can be submitted only by an independently authorized,
    metered host caller. This function performs no transport or approval.
    """
    cases = _corpus()
    by_id = {case['case_id']: case for case in cases}
    if case_ids is not None:
        if (not isinstance(case_ids, list) or not case_ids
                or any(not isinstance(key, str) or key not in by_id for key in case_ids)
                or len(set(case_ids)) != len(case_ids)):
            raise ValueError('unique known synthetic case selection required')
        cases = [by_id[key] for key in case_ids]
    batches = []
    for index in range(0, len(cases), 5):
        selected = cases[index:index + 5]
        submissions, stored = [], []
        for case in selected:
            # Same text/category/contact/page_url/files shape as POST feedback;
            # no HTTP request, upload or actual user record is created.
            category = 'other'
            submission = dict(description=case['text'], category=category,
                              contact='synthetic-contact@example.invalid',
                              page_url='https://example.invalid/synthetic', files=[])
            submissions.append(dict(case_id=case['case_id'], submission=submission))
            stored.append(dict(id=_feedback_id(case['case_id']), category=category,
                               description=submission['description'], status='open',
                               created_at=_WINDOW['start'], updated_at=_WINDOW['start'],
                               contact=submission['contact'], page_url=submission['page_url'],
                               user_id='synthetic-user-private', user_agent='synthetic-browser-private', attachments=[]))
        stored.sort(key=lambda row: row['id'])
        reader = _SyntheticProjection(stored)
        snapshot = reader.collect_feedback(_WINDOW, admin_scope=True)
        prompt = build_feedback_prompt_v2(snapshot)
        batches.append(dict(batch_id=f'synthetic-feedback-{index // 5 + 1:02d}',
                            synthetic=True, submissions=submissions, snapshot=snapshot,
                            read_request=reader.request, prompt=prompt,
                            prompt_sha256=hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
                            tools=[], references=deepcopy(selected)))
    return dict(schema_version=1, synthetic=True, corpus_sha256=CORPUS_SHA256,
                database_execution='MOCK', model_execution='NOT_RUN',
                api_submission_performed=False, automatic_execution=False,
                candidate_allowed=False, batches=batches)


def mock_response(batch):
    """Deliberately imperfect proposed model labels from the existing fixture."""
    references = {_feedback_id(case['case_id']): case for case in batch['references']}
    return feedback._encoded(dict(schema_version=2, snapshot_sha256=batch['snapshot']['snapshot_sha256'],
        items=[dict(feedback_id=row['id'], row_fingerprint=row['row_fingerprint'],
                    classification=references[row['id']]['model_classification'],
                    reason=_REASONS[references[row['id']]['model_classification']],
                    refs=[dict(quote=row['description'])]) for row in batch['snapshot']['rows']])).decode('utf-8')


def evaluate_demo_response(batch, raw_output):
    """Use the production quote-only validator; malformed replies stay unknown."""
    return evaluate_feedback_evidence_v2(raw_output, batch['snapshot'])


def run_demo(case_ids=None):
    prepared = prepare_demo(case_ids)
    cases = []
    for batch in prepared['batches']:
        checked = evaluate_demo_response(batch, mock_response(batch))
        rows = {row['id']: row for row in batch['snapshot']['rows']}
        observed = {row['feedback_id']: row for row in checked['cases']}
        items = {row['feedback_id']: row for row in checked['analysis']['items']} if checked['analysis'] else {}
        for reference in batch['references']:
            key = _feedback_id(reference['case_id'])
            outcome = observed[key]
            host = checked['analysis']['host_routes'][key] if checked['analysis'] else None
            route = outcome['host_route']
            flags = host['risk_flags'] if host else []
            cases.append(dict(case_id=reference['case_id'], feedback_id=key,
                submission=dict(category=rows[key]['category'], description=reference['text']),
                projected_description=rows[key]['description'],
                omitted_fields=['contact', 'page_url', 'user_id', 'user_agent', 'attachments'],
                snapshot_sha256=batch['snapshot']['snapshot_sha256'], row_fingerprint=rows[key]['row_fingerprint'],
                model_classification=outcome['model_classification'],
                model_reason=items[key]['reason'] if key in items else None,
                host_route=route, risk_flags=flags,
                host_reason=(_HOST_REASONS[route] + ' ' + ' '.join(_FLAG_REASONS[flag] for flag in flags)) if route else '输出合同无效，判定保留 unknown。',
                expected_classification=reference['expected_classification'],
                expected_host_route=reference['expected_host_route'], status=outcome['status'],
                automatic_execution=False, candidate_allowed=False))
    return dict(schema_version=1, synthetic=True, corpus_sha256=CORPUS_SHA256,
                database_execution='MOCK', model_execution='MOCK', api_submission_performed=False,
                semantic_quality='unknown', labels_kind='proposed_synthetic_references',
                case_count=len(cases), valid_case_count=sum(c['status'] == 'valid' for c in cases),
                route_agreement_count=sum(c['host_route'] == c['expected_host_route'] for c in cases),
                automatic_execution=False, candidate_allowed=False, cases=cases)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid synthetic demo arguments')


def main(argv=None):
    parser = _Parser(description='Offline synthetic feedback demo; no DB, API or model calls.')
    parser.add_argument('--case', action='append', dest='case_ids')
    try:
        args = parser.parse_args(argv)
        result = run_demo(args.case_ids)
    except ValueError:
        print('Invalid synthetic feedback demo selection or fixture.', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
