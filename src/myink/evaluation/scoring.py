"""Deterministic evidence checks; semantic matches require explicit review."""
from __future__ import annotations

import json

from pydantic import ConfigDict, Field
from myink.schemas import AuditVerdict, Finding
from myink.schemas.contract import EvidenceItem
from myink.evaluation.cases import Case, pointer


class EvaluationEvidence(EvidenceItem):
    model_config=ConfigDict(extra='forbid',strict=True)


class EvaluationFinding(Finding):
    model_config=ConfigDict(extra='forbid',strict=True)
    evidence:list[EvaluationEvidence]=Field(default_factory=list)


class EvaluationVerdict(AuditVerdict):
    model_config=ConfigDict(extra='forbid',strict=True)
    findings:list[EvaluationFinding]


def score_case(case: Case, result: dict, review: dict | None = None) -> dict:
    score={**result,'case_id':case.id,'case':case.model_dump(),'polarity':case.polarity,'category':case.category,
           'label_status':case.label.status,'review':'provisional','output_valid':False,
           'verdict_match':False,'automatic_pass':False,'confirmed_pass':None,
           'candidates':{},'evidence':{},'tp':0,'fp':0,'fn':len(case.expected.required_issues),
           'duplicates':0,'valid_quotes':0,'total_quotes':0,'findings_without_quotes':0}
    if result.get('execution')!='completed':
        if review:raise ValueError('cannot review a run without output')
        return score
    try:
        verdict=EvaluationVerdict.model_validate(json.loads(result['raw_output']))
    except (ValueError,KeyError,TypeError):
        if review:
            if not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip() or review.get('decisions')!={}:
                raise ValueError('invalid output cannot have finding decisions')
            score.update(review='confirmed',reviewer=review['reviewer'],confirmed_pass=False)
            if review.get('label_confirmed') is True:score['label_status']='reviewed'
        return score
    score['output_valid']=True
    score['verdict_match']=verdict.verdict in case.expected.allowed_verdicts
    score['verdict']=verdict.model_dump(mode='json')
    issues=case.expected.required_issues
    # Evidence validity uses every supplied chapter-labelled text. Target matching
    # below is stricter and uses only that issue's labelled evidence sources.
    sources=[(s.chapter,pointer(case.model_dump(),s.pointer)) for i in issues for s in i.evidence_sources]
    sources.append((case.input.chapter_seq,case.input.draft))
    def collect(value,chapter=None):
        if isinstance(value,dict):
            chapter=value.get('chapter',chapter)
            for child in value.values():collect(child,chapter)
        elif isinstance(value,list):
            for child in value:collect(child,chapter)
        elif isinstance(value,str) and type(chapter) is int:
            sources.append((chapter,value))
    collect(case.input.context)
    def valid_quote(evidence, pool):
        quote=evidence.quote.replace('\r\n','\n')
        return bool(quote.strip()) and any(evidence.chapter==chapter and quote in text.replace('\r\n','\n')
                                         for chapter,text in pool)
    for index,finding in enumerate(verdict.findings):
        fid=str(index)
        checks=[valid_quote(e,sources) for e in finding.evidence]
        score['evidence'][fid]=checks
        score['total_quotes']+=len(checks);score['valid_quotes']+=sum(checks)
        score['findings_without_quotes']+=not bool(checks)
        matches=[]
        for issue in issues:
            # Require evidence from every labelled source, not only the current draft.
            cites_all=all(any(e.chapter==s.chapter and valid_quote(e,[(s.chapter,pointer(case.model_dump(),s.pointer))])
                              for e in finding.evidence) for s in issue.evidence_sources)
            if (finding.conflict_type in issue.allowed_conflict_types and finding.severity in issue.allowed_severities
                    and checks and all(checks) and cites_all):
                matches.append(issue.id)
        score['candidates'][fid]=matches
    candidates=score['candidates']
    assigned={}
    def assign(iid,seen):
        for fid,values in candidates.items():
            if iid not in values or fid in seen:continue
            seen.add(fid)
            if fid not in assigned or assign(assigned[fid],seen):
                assigned[fid]=iid;return True
        return False
    matched_all=all(assign(issue.id,set()) for issue in issues)
    score['automatic_pass']=bool(score['verdict_match'] and
        (not verdict.findings if case.polarity=='negative' else
         matched_all and all(candidates.values())))
    if not review:return score
    if not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip() or not isinstance(review.get('decisions'),dict):
        raise ValueError('review needs reviewer and decisions')
    if review.get('label_confirmed') is True:
        score['label_status']='reviewed'
    decisions=review['decisions']
    if set(decisions)-set(candidates):raise ValueError('review refers to unknown finding')
    matched=set();duplicates=0;fp=0;disputed=False
    for fid,decision in decisions.items():
        if not isinstance(decision,dict):raise ValueError('finding decision must be an object')
        kind=decision.get('kind');iid=decision.get('issue_id')
        if kind in ('match','duplicate'):
            if iid not in candidates[fid]:raise ValueError('review cannot override invalid candidate evidence/type')
            if kind=='match':
                if iid in matched:raise ValueError('duplicate match needs duplicate decision')
                matched.add(iid)
            else:duplicates+=1
        elif kind=='false_positive':fp+=1
        elif kind in ('disputed','label_gap'):disputed=True
        else:raise ValueError('invalid review kind')
    for decision in decisions.values():
        if decision.get('kind')=='duplicate' and decision.get('issue_id') not in matched:
            raise ValueError('duplicate requires a confirmed original match')
    if set(decisions)!=set(candidates) or disputed:
        score['review']='disputed' if disputed else 'provisional'
        return score
    score.update(review='confirmed',reviewer=review['reviewer'],tp=len(matched),fp=fp,
                 fn=len(issues)-len(matched),duplicates=duplicates)
    score['confirmed_pass']=bool(score['verdict_match'] and score['fn']==0 and fp==0
                                 and score['label_status']=='reviewed')
    return score
