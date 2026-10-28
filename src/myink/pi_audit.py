"""Read-only audit snapshot contract, independent of the Pi execution stack.

Hashes detect corruption, not a hostile trusted producer. Mount the published
snapshot read-only for the authenticated administrator API; it grants no actions.
"""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path,PurePosixPath
import re
import stat


def _require(value,message='invalid audit snapshot'):
    if not value:raise ValueError(message)


def _encoded(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _digest(value):return sha256(_encoded(value)).hexdigest()


def _hash(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None


def _name(value):return isinstance(value,str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}',value) is not None


def _json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            _require(key not in result,'duplicate audit JSON key');result[key]=value
        return result
    def invalid(_):raise ValueError('invalid audit JSON number')
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
    except (RecursionError,UnicodeError) as error:raise ValueError('invalid audit JSON') from error


def _read(path,bound):
    info=path.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=bound,'invalid audit file')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        opened=os.fstat(fd)
        _require((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino) and opened.st_nlink==1,'audit file changed')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(bound+1)
        _require(len(raw)<=bound,'audit file exceeds bound');return raw
    finally:os.close(fd)


SCHEMA_VERSION=1
DB_VERSION=1001
MAX_EVENT_BYTES=32768
KINDS=frozenset('observation analysis plan review tool development test deployment rollback followup version enhancement memory'.split())
STATUSES=frozenset('planned running passed failed blocked uncertain skipped no_change insufficient_evidence candidate_ready no_release rolled_back'.split())
DOMAINS=frozenset('online_business real_provider_fixed_input offline synthetic unknown'.split())
FIELDS=frozenset('kind status run_id occurred_at summary details version changes evidence followups mode evidence_domain'.split())
VERSION_FIELDS=frozenset('source_commit base_commit candidate_sha256 controller_sha256 policy_sha256 sdk_version model_id deployment_id generation owner image_ids'.split())
COUNT_FIELDS=frozenset('model_requests tool_calls input_tokens output_tokens known_cost_microyuan reserved_microyuan test_total test_failures test_errors test_skipped baseline_failures minimum_samples observed_samples'.split())
TEXT_FIELDS=frozenset('decision next_action reason hypothesis tool_name operation_id request_summary result_summary availability test_id reference change_summary'.split())
SHANGHAI=timezone(timedelta(hours=8),'Asia/Shanghai')
_NAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}')
_HEX=re.compile(r'[0-9a-f]{64}')
_SECRET=re.compile(r"""(?ix)(\b[\w-]*(?:api[_-]?key|token|secret|password|passwd|密码|密钥|口令)[\w-]*["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)""")
_BEARER=re.compile(r'(?i)\bBearer\s+[^\s,;]+')
_KEY=re.compile(r'\bsk[-_][A-Za-z0-9_-]{8,}\b')
_URL=re.compile(r'(?i)((?:https?|postgres(?:ql)?(?:\+psycopg)?)://)[^/\s@]+:[^/\s@]+@')

def require(value,reason='invalid audit record'):
    if not value:raise ValueError(reason)


def encoded(value):
    return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(value):return sha256(encoded(value)).hexdigest()


def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'duplicate audit JSON key');result[key]=value
        return result
    def invalid(_):raise ValueError('invalid audit JSON number')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def name(value):return isinstance(value,str) and _NAME.fullmatch(value) is not None


def hash_value(value,length=64):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{'+str(length)+'}',value) is not None


def utc(value):
    try:parsed=value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
    except (ValueError,TypeError,AttributeError):raise ValueError('aware audit time required') from None
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None,'aware audit time required')
    return parsed.astimezone(timezone.utc)



def _version(value):
    require(isinstance(value,dict) and set(value)<=VERSION_FIELDS)
    result={key:None for key in VERSION_FIELDS};result['image_ids']={}
    for key,item in value.items():
        if key=='image_ids':
            require(isinstance(item,dict) and len(item)<=8 and all(isinstance(k,str) and re.fullmatch('[A-Za-z0-9_.-]{1,80}',k) and isinstance(v,str) and re.fullmatch('sha256:[0-9a-f]{64}',v) for k,v in item.items()))
        elif item is None:pass
        elif key in ('source_commit','base_commit'):require(hash_value(item,40))
        elif key.endswith('_sha256'):require(hash_value(item))
        elif key=='generation':require(type(item)is int and item>=0)
        else:
            require(name(item))
            require(_KEY.search(item) is None,'sensitive audit identity refused')
        result[key]=item
    return result


def validate_record(record):
    require(isinstance(record,dict) and set(record)==FIELDS)
    require(isinstance(record['kind'],str) and record['kind'] in KINDS and isinstance(record['status'],str) and record['status'] in STATUSES and name(record['run_id']))
    require(record['mode'] in ('ACTUAL','SIMULATED','UNKNOWN') and isinstance(record['evidence_domain'],str) and record['evidence_domain'] in DOMAINS)
    require(record['evidence_domain']!='online_business' or record['mode']=='ACTUAL','online audit requires actual evidence')
    flags=dict(redacted=False,truncated=False)
    def text(value,maximum):
        require(isinstance(value,str) and len(value)<=65536)
        clean=''.join(c if ord(c)>=32 or c in '\n\t' else '\ufffd' for c in value)
        clean=_URL.sub(r'\1[REDACTED]@',clean)
        clean=_BEARER.sub('Bearer [REDACTED]',clean)
        clean=_SECRET.sub(r'\1[REDACTED]',clean)
        clean=_KEY.sub('[REDACTED]',clean)
        flags['redacted']|=clean!=value
        flags['truncated']|=len(clean)>maximum
        return clean[:maximum]
    details=record['details'];require(isinstance(details,dict) and len(details)<=32)
    projected={}
    for key,value in details.items():
        if key in COUNT_FIELDS:require(value is None or type(value)is int and value>=0)
        elif key=='duration_ms':require(value is None or type(value) in (int,float) and math.isfinite(value) and value>=0)
        elif key=='range_complete':require(type(value)is bool)
        elif key in TEXT_FIELDS:
            if value is not None:value=text(value,1000)
        else:raise ValueError('unsupported audit detail field')
        projected[key]=value
    changes=record['changes'];require(isinstance(changes,list) and len(changes)<=128)
    paths=set()
    for item in changes:
        require(isinstance(item,dict) and set(item)=={'path','category','added','deleted'})
        p=item['path'];require(isinstance(p,str) and 0<len(p)<=4096 and '\\' not in p and '\0' not in p)
        lexical=PurePosixPath(p)
        require(not lexical.is_absolute() and str(lexical)==p and '..' not in lexical.parts and p not in paths)
        require(item['category'] in ('production','test','docs','config') and all(item[k] is None or type(item[k])is int and item[k]>=0 for k in ('added','deleted')))
        paths.add(p)
    evidence=record['evidence'];require(isinstance(evidence,list) and len(evidence)<=32)
    for item in evidence:
        require(isinstance(item,dict) and set(item)=={'kind','sha256','verified','evidence_domain'})
        require(name(item['kind']) and hash_value(item['sha256']) and type(item['verified'])is bool and item['evidence_domain'] in DOMAINS)
    followups=record['followups'];require(isinstance(followups,list) and len(followups)<=32)
    planned=[];ids=set()
    for item in followups:
        require(isinstance(item,dict) and set(item)=={'test_id','scheduled_for','target_run_id','target_version_sha256','criterion','kind','status'})
        require(name(item['test_id']) and item['test_id'] not in ids and name(item['target_run_id']))
        require(item['target_version_sha256'] is None or hash_value(item['target_version_sha256']))
        require(item['kind'] in ('regression','metrics','quality','restore') and item['status'] in ('planned','blocked','insufficient_evidence'),'followup plan cannot certify execution')
        ids.add(item['test_id'])
        planned.append(dict(item,scheduled_for=utc(item['scheduled_for']).isoformat(),criterion=text(item['criterion'],2000)))
    result=dict(record,summary=text(record['summary'],2000),details=projected,version=_version(record['version']),
                occurred_at=None if record['occurred_at'] is None else utc(record['occurred_at']).isoformat(),
                changes=[dict(x) for x in changes],evidence=[dict(x) for x in evidence],followups=planned)
    result.update(flags)
    require(len(encoded(result))<=MAX_EVENT_BYTES,'audit event exceeds byte bound')
    return result




_FIELDS=set('kind status run_id occurred_at summary details version changes evidence followups mode evidence_domain schema_version authority record_key sequence previous_sha256 recorded_at day time_basis event_sha256 redacted truncated'.split())
_KINDS=set('observation analysis plan review tool development test deployment rollback followup version enhancement memory'.split())
_STATUSES=set('planned running passed failed blocked uncertain skipped no_change insufficient_evidence candidate_ready no_release rolled_back'.split())
_DOMAINS=set('online_business real_provider_fixed_input offline synthetic unknown'.split())


def _event(event):
    _require(isinstance(event,dict) and set(event)==_FIELDS)
    _require(type(event['schema_version']) is int and event['schema_version']==1 and event['authority']=='audit_only')
    _require(_name(event['record_key']) and _name(event['run_id']) and type(event['sequence']) is int and event['sequence']>0)
    _require(isinstance(event['kind'],str) and event['kind'] in _KINDS and isinstance(event['status'],str) and event['status'] in _STATUSES)
    _require(event['mode'] in ('ACTUAL','SIMULATED','UNKNOWN') and isinstance(event['evidence_domain'],str) and event['evidence_domain'] in _DOMAINS)
    _require(event['evidence_domain']!='online_business' or event['mode']=='ACTUAL')
    _require(type(event['redacted']) is bool and type(event['truncated']) is bool)
    normalized=validate_record({key:event[key] for key in FIELDS})
    _require(all(event[key]==normalized[key] for key in FIELDS),'invalid stored audit projection')
    _require(isinstance(event['summary'],str) and len(event['summary'])<=2000 and isinstance(event['details'],dict) and len(event['details'])<=32)
    _require(isinstance(event['version'],dict) and isinstance(event['changes'],list) and isinstance(event['evidence'],list) and isinstance(event['followups'],list))
    _require(len(event['changes'])<=128 and len(event['evidence'])<=32 and len(event['followups'])<=32 and len(_encoded(event))<=32768)
    try:
        recorded=datetime.fromisoformat(event['recorded_at']);at=recorded if event['occurred_at'] is None else datetime.fromisoformat(event['occurred_at'])
        _require(recorded.utcoffset()==timedelta(0) and at.utcoffset()==timedelta(0))
        _require(event['day']==at.astimezone(timezone(timedelta(hours=8))).date().isoformat())
        _require(event['time_basis']==('recorded_at' if event['occurred_at'] is None else 'occurred_at'))
    except (TypeError,AttributeError,ValueError):raise ValueError('invalid audit time provenance') from None
    _require(_hash(event['event_sha256']) and _digest({k:v for k,v in event.items() if k!='event_sha256'})==event['event_sha256'],'audit content hash mismatch')


def _indexes(pages,groups):
    runs={};days={}
    for page,items in zip(pages,groups):
        for event in items:
            run=runs.setdefault(event['run_id'],dict(run_id=event['run_id'],event_count=0,days=set(),pages=[]))
            day=days.setdefault(event['day'],dict(day=event['day'],event_count=0,runs=set(),pages=[]))
            run['event_count']+=1;run['days'].add(event['day']);day['event_count']+=1;day['runs'].add(event['run_id'])
            for index in (run,day):
                if page['sha256'] not in index['pages']:index['pages'].append(page['sha256'])
    return ([dict(v,days=sorted(v['days'])) for _,v in sorted(runs.items())],[dict(v,runs=sorted(v['runs'])) for _,v in sorted(days.items())])


class AuditReader:
    def __init__(self,root):
        self.root=Path(root)
        _require(self.root.is_absolute() and self.root.resolve()==self.root and (self.root/'pages').resolve()==self.root/'pages','non-link snapshot root required')
        manifest=_json(_read(self.root/'manifest.json',8388608))
        _require(isinstance(manifest,dict) and set(manifest)==set('schema_version authority generated_at watermark pages runs days snapshot_sha256'.split()))
        _require(type(manifest['schema_version']) is int and manifest['schema_version']==1 and manifest['authority']=='audit_only','unsupported audit schema')
        _require(_hash(manifest['snapshot_sha256']) and _digest({k:v for k,v in manifest.items() if k!='snapshot_sha256'})==manifest['snapshot_sha256'],'audit manifest hash mismatch')
        _require(isinstance(manifest['pages'],list) and len(manifest['pages'])<=10000)
        self.manifest=manifest;sequence=0;previous=None
        def groups():
            nonlocal sequence,previous
            for page in manifest['pages']:
                _require(isinstance(page,dict) and set(page)==set('sha256 event_count first_sequence last_sequence previous_sha256 last_sha256'.split()) and _hash(page['sha256']))
                items=self._page(page['sha256'])
                _require(type(page['event_count']) is int and 0<page['event_count']<=100 and len(items)==page['event_count'])
                for event in items:
                    _event(event);sequence+=1
                    _require(event['sequence']==sequence and event['previous_sha256']==previous,'audit chain mismatch');previous=event['event_sha256']
                _require(page==dict(sha256=page['sha256'],event_count=len(items),first_sequence=items[0]['sequence'],last_sequence=sequence,previous_sha256=items[0]['previous_sha256'],last_sha256=previous))
                yield items
        runs,days=_indexes(manifest['pages'],groups())
        _require(manifest['runs']==runs and manifest['days']==days,'audit index mismatch')
        _require(manifest['watermark']==dict(sequence=sequence,event_sha256=previous),'audit watermark mismatch')

    def _page(self,key):
        _require(_hash(key))
        raw=_read(self.root/'pages'/(key+'.json'),1048576)
        _require(sha256(raw).hexdigest()==key,'audit page hash mismatch')
        page=_json(raw)
        _require(isinstance(page,dict) and set(page)=={'schema_version','authority','events'} and type(page['schema_version']) is int and page['schema_version']==1 and page['authority']=='audit_only' and isinstance(page['events'],list))
        return page['events']

    @staticmethod
    def _slice(items,limit,offset):
        _require(type(limit) is int and 1<=limit<=100 and type(offset) is int and offset>=0,'invalid audit pagination')
        return dict(items=items[offset:offset+limit],total=len(items),limit=limit,offset=offset)

    def runs(self,limit=25,offset=0,day=None):
        return self._slice([dict(x) for x in self.manifest['runs'] if day is None or day in x['days']],limit,offset)

    def events(self,run_id,limit=25,offset=0,kind=None):
        _require(_name(run_id) and (kind is None or isinstance(kind,str) and kind in _KINDS))
        run=next((x for x in self.manifest['runs'] if x['run_id']==run_id),None)
        if run is None:raise LookupError('unknown audit run')
        items=[e for key in run['pages'] for e in self._page(key) if e['run_id']==run_id and (kind is None or e['kind']==kind)]
        return self._slice(items,limit,offset)

    def _events(self,keys=None):
        for page in self.manifest['pages']:
            if keys is None or page['sha256'] in keys:
                yield from self._page(page['sha256'])

    def enhancements(self,limit=25,offset=0):
        latest={}
        for event in self._events():
            if event['kind']=='enhancement':
                reference=event['details'].get('reference')
                if reference is not None:latest[reference]=event
        return self._slice([latest[key] for key in sorted(latest)],limit,offset)

    def daily(self,day):
        from datetime import date
        _require(isinstance(day,str) and date.fromisoformat(day).isoformat()==day,'invalid audit day')
        index=next((x for x in self.manifest['days'] if x['day']==day),None)
        events=[] if index is None else [e for e in self._events(set(index['pages'])) if e['day']==day]
        versions={};changes={};counters={};plans={};release='unknown'
        for event in events:
            version=event['version'];versions[_digest(version)]=version
            candidate=version['candidate_sha256']
            for change in event['changes']:
                # Each change is a cumulative diff against the frozen base.
                key=(candidate or event['event_sha256'],change['path'])
                changes[key]=dict(change,candidate_sha256=candidate,source_commit=version['source_commit'])
            for key in ('known_cost_microyuan','observed_samples'):
                if key in event['details']:counters[(event['run_id'],key)]=event['details'][key]
            if event['kind'] in ('deployment','rollback') and event['mode']=='ACTUAL':
                if event['status']=='no_release':release='no_release'
                elif event['evidence_domain']=='online_business':
                    if event['kind']=='deployment' and event['status']=='passed':release='deployed'
                    elif event['kind']=='rollback' and event['status']=='rolled_back':release='rolled_back'
                    elif event['status'] in ('uncertain','blocked','failed'):release='unknown'
            for plan in event['followups']:
                key=(plan['target_run_id'],plan['test_id'],plan['target_version_sha256'])
                plans[key]=dict(plan,plan_event_sha256=event['event_sha256'],result=None)
        if plans:
            for event in self._events():
                if event['kind']!='test' or event['mode']!='ACTUAL' or event['occurred_at'] is None:continue
                key=(event['run_id'],event['details'].get('test_id'),event['version']['candidate_sha256'])
                plan=plans.get(key)
                if plan is not None and plan['target_version_sha256'] is not None and event['sequence']>next(e['sequence'] for e in events if e['event_sha256']==plan['plan_event_sha256']) and datetime.fromisoformat(event['occurred_at'])>=datetime.fromisoformat(plan['scheduled_for']):
                    plan['result']=dict(status=event['status'],event_sha256=event['event_sha256'],occurred_at=event['occurred_at'],evidence_domain=event['evidence_domain'])
        result=dict(schema_version=1,authority='audit_only',day=day,timezone='Asia/Shanghai',event_count=len(events),
            unknown_occurrence_count=sum(e['occurred_at'] is None for e in events),release_state=release,
            runs=[] if index is None else index['runs'],versions=list(versions.values()),change_scope=list(changes.values()),next_tests=list(plans.values()))
        for key in ('known_cost_microyuan','observed_samples'):
            values=[v for (_,field),v in counters.items() if field==key]
            result[key]=sum(values) if values and all(v is not None for v in values) else None
        return result
