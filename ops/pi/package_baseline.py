"""Host-only draft to isolated baseline; no model, budget or approval action."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
from threading import Event, Timer
import time
import uuid
from urllib.parse import urlsplit

from .container_probe import ProbeHost
from .development_inputs import file_hash, path, read_json, tree_hash, digest
from .development_launcher import _fixed_check, atomic_write, Limits, OwnedHosts
from .maintenance_handoff import _catalog
from .task_package import _case_hints, _regular, _require, _stable, _publish_new, REQUIRES
from .unit_feedback import REPORT_FIELDS, validate_report

FIELDS = {'schema','baseline_id','draft_path','draft_sha256','root','docker','endpoint',
          'daemon_id','checker_image_id','deadline_seconds'}
DRAFT_FIELDS = {'schema','task_id','problem','source_path','source_sha256','test_path',
                'test_sha256','files','test_case_hints','inventory_status','requires','origin'}
BASE_FIELDS = ('tests','cases','failures','errors','skipped','failed_cases','error_cases')


def _draft(p, expected):
    p = path(p, private=True)
    _require(p.name == 'task-draft.json' and stat.S_ISREG(p.lstat().st_mode)
             and p.stat().st_size <= 1048576, 'published bounded draft required')
    _require(file_hash(p) == expected, 'draft snapshot drift')
    d = read_json(p)
    _require(isinstance(d,dict) and set(d)==DRAFT_FIELDS
             and d['schema']=='pi-task-package-draft-v1'
             and d['inventory_status']=='static_unverified' and d['requires']==REQUIRES,
             'unverified package draft required')
    _require(isinstance(d['task_id'],str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',d['task_id'])
             and isinstance(d['problem'],str) and d['problem'].strip()
             and len(d['problem'])<=2000, 'bounded task observations required')
    _require(all(isinstance(d[k],str) and re.fullmatch('[a-f0-9]{64}',d[k])
                 for k in ('source_sha256','test_sha256')), 'frozen draft identities required')
    origin = d['origin']
    _require(isinstance(origin,dict) and set(origin)=={'request_path','request_sha256','source_path','test_path'}
             and all(isinstance(v,str) and v for v in origin.values()), 'draft origin required')
    source, gold = path(d['source_path']), path(d['test_path'],private=True)
    _regular(gold)
    _require(source == p.parent/'source' and gold == p.parent/'test.py'
             and source.is_dir() and {x.name for x in source.iterdir()}=={'src'}
             and (source/'src').is_dir(), 'staged source and gold layout required')
    from .plans import _path
    files=d['files']
    _require(isinstance(files,list) and 0<len(files)<=8
             and all(_path(f) and f.startswith('src/') for f in files)
             and len(files)==len(set(files)) and all((source/f).is_file() for f in files),
             'declared existing staged files required')
    _require(_case_hints(gold.read_bytes())==d['test_case_hints'], 'static hint drift')
    _require(all(re.fullmatch(r'fixed_development_tests\.[A-Za-z0-9_.]{1,180}',v)
                 for v in d['test_case_hints']), 'fixed checker case bounds required')
    return d


def _stable_inputs(request, request_sha, c, d):
    _stable(request,request_sha,d)
    dp=path(c['draft_path'],private=True)
    _require(stat.S_ISREG(dp.lstat().st_mode) and dp.stat().st_size<=1048576
             and file_hash(dp)==c['draft_sha256'], 'draft snapshot drift')


def _prepare(request_path):
    request=path(request_path,private=True);_regular(request)
    sha=file_hash(request);c=read_json(request)
    _require(file_hash(request)==sha,'request drift')
    _require(isinstance(c,dict) and set(c)==FIELDS
             and c['schema']=='pi-package-baseline-request-v1', 'unsupported baseline request')
    _require(all(isinstance(c[k],str) for k in FIELDS-{'deadline_seconds'}), 'text baseline fields required')
    _require(re.fullmatch('[a-z0-9][a-z0-9-]{0,79}',c['baseline_id'])
             and re.fullmatch('[a-f0-9]{64}',c['draft_sha256'])
             and type(c['deadline_seconds']) is int and 1<=c['deadline_seconds']<=300,
             'bounded fresh baseline identity required')
    docker=path(c['docker'])
    _require(docker.is_file() and os.access(docker,os.X_OK), 'local Docker executable required')
    ProbeHost(docker=docker,endpoint=c['endpoint'],daemon_id=c['daemon_id'],
              image_id=c['checker_image_id'],operation_id=str(uuid.uuid4()))
    try:
        socket_path=Path(urlsplit(c['endpoint']).path).resolve()
    except (OSError,RuntimeError) as error:
        raise ValueError('resolvable local daemon endpoint required') from error
    d=_draft(c['draft_path'],c['draft_sha256'])
    root=path(c['root'])
    _require(not root.exists() and root.parent.is_dir()
             and stat.S_IMODE(root.parent.stat().st_mode)==0o700,'new private baseline root required')
    for value in (request,Path(c['draft_path']),Path(d['source_path']),Path(d['test_path']),docker,socket_path):
        _require(root!=value and root not in value.parents and value not in root.parents,
                 'baseline output and inputs overlap')
    _stable_inputs(request,sha,c,d)
    return request,sha,c,d


def check(request_path):
    _,_,c,d=_prepare(request_path)
    return dict(ready=True,mode='read-only-baseline',baseline_id=c['baseline_id'],
                test_case_hint_count=len(d['test_case_hints']))


def execute(request_path, *, cancel=None):
    cancel=Event() if cancel is None else cancel
    _require(not cancel.is_set(),'baseline cancelled')
    request,sha,c,d=_prepare(request_path)
    _require(not cancel.is_set(),'baseline cancelled')
    root=Path(c['root']);root.mkdir(mode=0o700)
    def write(name,value):
        atomic_write(root/name,json.dumps(value,sort_keys=True,indent=2).encode()+b'\n')
    limits=Limits(1,1,c['deadline_seconds'],cancel)
    owners=OwnedHosts(cancel,write);timer=Timer(c['deadline_seconds'],cancel.set)
    report=None;failure=None;cleanup_failure=None;cleanup=[];catalog=[];catalog_rejection=None
    timer.start()
    try:
        checker={k:c[k] for k in ('docker','endpoint','daemon_id','checker_image_id')}
        checker.update(test_path=d['test_path'],test_sha256=d['test_sha256'],test_cases=d['test_case_hints'])
        report=_fixed_check(checker,Path(d['source_path']),root/'check',limits,write,owners)
        validate_report({k:report[k] for k in REPORT_FIELDS},report['attach_returncode'],d['test_case_hints'])
        limits.alive()
    except BaseException as error:
        failure=type(error).__name__
    finally:
        try:cleanup=owners.finish()
        except BaseException as error:cleanup_failure=type(error).__name__
        timer.cancel()
    if not failure and not cleanup_failure:
        try:
            limits.alive()
            _stable_inputs(request,sha,c,d)
            _require(tree_hash(root/'check/src')==tree_hash(Path(d['source_path'])/'src')
                     and file_hash(root/'check/test.py')==d['test_sha256'], 'actual checker copy drift')
            limits.alive()
        except BaseException as error:
            failure=type(error).__name__
    verified=bool(report and not failure and not cleanup_failure and not owners.failed
                  and not cancel.is_set() and time.monotonic()<limits.deadline and cleanup
                  and all(row.get('removed') is True and type(row.get('exit_code')) is int
                          and row['exit_code']==report['attach_returncode'] for row in cleanup)
                  and any(row.get('container_id')==report['container_id'] for row in cleanup)
                  and report['tests']==len(d['test_case_hints']) and report['cases']==d['test_case_hints']
                  and report['errors']==report['skipped']==0 and not report['load_error'])
    if verified and report['failures']>0:
        baseline={k:report[k] for k in BASE_FIELDS}
        task=dict(task_id=d['task_id'],problem=d['problem'],source_sha256=d['source_sha256'],
                  test_sha256=d['test_sha256'],files=d['files'],test_cases=d['test_case_hints'],
                  baseline=baseline,evidence_sha256=digest(baseline))
        try:
            catalog=_catalog([task])
        except ValueError as error:
            # Valid check evidence can still exceed the selector's bounded catalog.
            # Preserve it without widening the limit or claiming eligibility.
            catalog_rejection=str(error)
    outcome=dict(schema='pi-package-baseline-outcome-v1',verified=verified,
        baseline_id=c['baseline_id'],request_sha256=sha,draft_sha256=c['draft_sha256'],
        source_sha256=d['source_sha256'],test_sha256=d['test_sha256'],
        check_passed=bool(report and report['passed']),eligible_for_selection=bool(catalog),
        catalog=catalog,catalog_rejection=catalog_rejection,checker_report=report,cleanup=cleanup,failure_class=failure,
        cleanup_failure_class=cleanup_failure,requires=['fresh_run_identity','independent_reviews','current_runtime'])
    retained=_publish_new(root/'outcome.json',json.dumps(outcome,sort_keys=True,indent=2).encode()+b'\n')
    return dict(verified=verified,eligible_for_selection=bool(catalog),mode='isolated-baseline-only',
                result_path=str(root/'outcome.json'),staging_retained=retained,catalog_rejection=catalog_rejection)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    try:result=(execute if args.execute else check)(args.request)
    except (OSError,ValueError,TypeError) as error:
        print(json.dumps(dict(ready=False,error_class=type(error).__name__)));return 1
    print(json.dumps(result))
    return 0 if result.get('ready') or result.get('verified') else 1


if __name__=='__main__':raise SystemExit(main())
