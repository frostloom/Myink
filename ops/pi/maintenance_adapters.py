"""Trusted adapters for finite local handoff. Model text never supplies paths."""
from copy import deepcopy
import json
from pathlib import Path
import time

from .contracts import Receipt
from .container_runtime import verify_source
from .development_inputs import (FIELDS,authorization_hash,digest,file_hash,ledger_snapshot,
    path,prepare,prepare_template,read_json,tree_hash,validate_review)
from .development_launcher import atomic_write,require
from .selection_launcher import execute as run_selection


class SelectionAdapter:
    def __init__(self,config_path,config_sha256,*,transport=None):
        self.config_path,self.config_sha256=Path(config_path),config_sha256
        self.transport=transport

    def __call__(self,context):
        require(file_hash(self.config_path)==self.config_sha256,'frozen selection config drift')
        require((context['mode']=='ACTUAL' and self.transport is None)
                or (context['mode']=='SIMULATED' and callable(self.transport)),'explicit selection provider mode required')
        result=run_selection(self.config_path,context,transport=self.transport,
                             expected_config_sha256=self.config_sha256)
        status='done' if result.get('verified') is True else 'blocked' if result.get('closed_verified') is True else 'uncertain'
        evidence=dict(mode=context['mode'],binding=context['input_hash'],verified=status=='done',
            result_path=str(Path(read_json(self.config_path)['root'])/'result.json'),result=result)
        if status=='done':evidence['proposal']=result['proposal']
        return Receipt(context['operation_id'],status,evidence)


class FileReview:
    """Wait for an external independent reviewer; never generate an approval."""
    def __init__(self,seconds=240):
        require(type(seconds) is int and 0<seconds<=600,'bounded review wait required')
        self.seconds=seconds

    def __call__(self,config_path,context):
        cancel=context['cancel'];until=min(context['deadline'],time.monotonic()+self.seconds)
        require(not cancel.is_set() and time.monotonic()<until,'review cancelled or expired')
        config=read_json(config_path);target=Path(config['review_path'])
        while not target.exists():
            require(not cancel.is_set() and time.monotonic()<until,'independent review unavailable')
            cancel.wait(min(.1,max(0,until-time.monotonic())))
        require(not cancel.is_set() and time.monotonic()<until,'review arrived too late')
        return read_json(path(target,private=True))


def preflight_templates(templates,billing,reviewer,context):
    """Check every catalog package before selection can contact a provider."""
    try:
        require(not context['cancel'].is_set() and time.monotonic()<context['deadline'],
                'package check cancelled or expired')
        require(context['mode'] in ('ACTUAL','SIMULATED') and
                (context['mode']!='ACTUAL' or type(reviewer) is FileReview),
                'actual development requires external file review')
        checked={}
        for task in context['tasks']:
            require(not context['cancel'].is_set() and time.monotonic()<context['deadline'],
                    'package check cancelled or expired')
            template=templates[task['task_id']]
            target=path(template['path'],private=True)
            require(file_hash(target)==template['sha256'],'trusted template drift')
            c,_,plan,baseline,*_=prepare_template(target)
            require(c['source_sha256']==task['source_sha256'] and c['test_sha256']==task['test_sha256']
                and c['test_cases']==task['test_cases'] and list(plan.files)==task['files']
                and digest(baseline.get('reproduction'))==digest(task['baseline']), 'template task drift')
            require(path(c['ledger_path'],private=True)==billing,'template billing identity drift')
            require(file_hash(target)==template['sha256'],'template drift during package check')
            checked[task['task_id']]=template['sha256']
        require(not context['cancel'].is_set() and time.monotonic()<context['deadline'],
                'package check cancelled or expired')
        return Receipt(context['operation_id'],'done',dict(verified=True,mode=context['mode'],
            binding=context['input_hash'],catalog_sha256=digest(context['tasks']),templates=checked))
    except (ValueError,OSError,KeyError,TypeError) as error:
        return Receipt(context['operation_id'],'blocked',dict(mode=context['mode'],
            reason='task_package_rejected',error_class=type(error).__name__))

class FrozenDevelopmentAdapter:
    def __init__(self,templates,root,billing_ledger_path,reviewer):
        self.templates=deepcopy(templates);self.root=path(root)
        self.billing=path(billing_ledger_path);self.reviewer=reviewer
        require(self.root.is_dir() and self.root.stat().st_mode&0o777==0o700 and callable(reviewer),
                'private prepared-config root and trusted review required')

    def preflight(self,context):
        return preflight_templates(self.templates,self.billing,self.reviewer,context)

    def __call__(self,context):
        try:return self._prepare(context)
        except (ValueError,OSError,KeyError,TypeError) as error:
            return Receipt(context['operation_id'],'blocked',dict(mode=context['mode'],
                reason='frozen_development_rejected',error_class=type(error).__name__))

    def _prepare(self,context):
        cancel=context['cancel'];task=context['task'];mode=context['mode']
        require(not cancel.is_set() and time.monotonic()<context['deadline'],'freeze cancelled or expired')
        require(mode in ('ACTUAL','SIMULATED') and (mode!='ACTUAL' or type(self.reviewer) is FileReview),
                'actual development requires external file review')
        template=self.templates[task['task_id']];template_path=path(template['path'],private=True)
        require(file_hash(template_path)==template['sha256'],'trusted template drift')
        c=read_json(template_path)
        require(isinstance(c,dict) and set(c)==FIELDS and c['schema']=='pi-development-v1','strict development template required')
        plan=read_json(path(c['plan_path'],private=True));baseline=read_json(path(c['baseline_path'],private=True))
        require(c['source_sha256']==task['source_sha256'] and c['test_sha256']==task['test_sha256']
            and c['test_cases']==task['test_cases'] and plan['files']==task['files']
            and digest(baseline.get('reproduction'))==digest(task['baseline']),'template task drift')
        for key in ('policy','credential','plan','baseline','test'):
            require(file_hash(path(c[key+'_path'],private=True))==c[key+'_sha256'],key+' template drift')
        require(tree_hash(path(c['source_path']))==c['source_sha256'],'template source drift')
        verify_source(path(c['runtime_path']),c['runtime_sha256'])
        require(path(c['ledger_path'],private=True)==self.billing,'template billing identity drift')
        c['ledger_sha256']=ledger_snapshot(self.billing)['sha256']
        c['deadline_seconds']=min(c['deadline_seconds'],int(context['deadline']-time.monotonic())-2)
        require(c['deadline_seconds']>=plan['time_estimate'] and c['deadline_seconds']>0,'insufficient remaining development time')
        target=self.root/task['task_id'];require(target.parent==self.root and not target.exists(),'new frozen task identity required')
        target.mkdir(mode=0o700);c['review_path']=str(target/'review.json');c['review_sha256']='0'*64
        config_path=target/'config.json'
        def write(p,value):atomic_write(p,json.dumps(value,ensure_ascii=True,indent=2).encode()+b'\n')
        write(config_path,c)
        write(target/'review-request.json',dict(authorization_sha256=authorization_hash(c),plan_hash=digest(plan),
            base=c['source_sha256'],candidate_id=c['run_id'],config_path=str(config_path),task_id=task['task_id']))
        review=self.reviewer(config_path,context)
        validate_review(review,c,digest(plan),c['source_sha256'])
        review_path=Path(c['review_path'])
        if review_path.exists():require(digest(read_json(review_path))==digest(review),'external review changed')
        else:write(review_path,review)
        c['review_sha256']=file_hash(path(review_path,private=True));write(config_path,c)
        require(not cancel.is_set() and time.monotonic()<context['deadline'],'freeze review expired')
        prepare(config_path)
        require(file_hash(template_path)==template['sha256'],'template changed during independent review')
        return Receipt(context['operation_id'],'done',dict(verified=True,mode=mode,binding=context['input_hash'],
            config_path=str(config_path),config_sha256=file_hash(config_path)))
