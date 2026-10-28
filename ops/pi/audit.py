"""Append-only audit data. This store cannot authorize tools, fees or releases."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path,PurePosixPath
import re
import sqlite3
import stat

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
_COLUMNS=['sequence','record_key','input_sha256','event_sha256','previous_sha256','payload']
_DDL=[
    'CREATE TABLE pi_audit_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,record_key TEXT NOT NULL UNIQUE,input_sha256 TEXT NOT NULL,event_sha256 TEXT NOT NULL UNIQUE,previous_sha256 TEXT,payload TEXT NOT NULL)',
    "CREATE TRIGGER pi_audit_no_update BEFORE UPDATE ON pi_audit_events BEGIN SELECT RAISE(ABORT,'append only audit'); END",
    "CREATE TRIGGER pi_audit_no_delete BEFORE DELETE ON pi_audit_events BEGIN SELECT RAISE(ABORT,'append only audit'); END",
    "CREATE TRIGGER pi_audit_order AFTER INSERT ON pi_audit_events WHEN NEW.sequence != COALESCE((SELECT max(sequence) FROM pi_audit_events WHERE sequence != NEW.sequence),0)+1 OR NEW.previous_sha256 IS NOT (SELECT event_sha256 FROM pi_audit_events WHERE sequence < NEW.sequence ORDER BY sequence DESC LIMIT 1) BEGIN SELECT RAISE(ABORT,'audit sequence conflict'); END",
]


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


def _path(value):
    p=Path(value)
    require(p.is_absolute() and p.resolve()==p,'canonical non-link audit path required')
    return p


def _plain(p):
    s=p.lstat()
    require(stat.S_ISREG(s.st_mode) and s.st_nlink==1,'regular single-link audit file required')


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


def _schema(c):
    require(c.execute('PRAGMA user_version').fetchone()[0]==DB_VERSION,'unsupported audit database')
    require([x[1] for x in c.execute('PRAGMA table_info(pi_audit_events)')]==_COLUMNS,'unsupported audit schema')
    expected={sql.split()[2].split('(',1)[0]:sql for sql in _DDL}
    actual={row[0]:row[1] for row in c.execute("SELECT name,sql FROM sqlite_master WHERE name LIKE 'pi_audit_%'")}
    require(actual==expected,'audit schema or immutable guards changed')


def _decode(row):
    require(isinstance(row['payload'],str) and len(row['payload'].encode())<=MAX_EVENT_BYTES,'audit event exceeds byte bound')
    event=strict_json(row['payload'])
    metadata={'schema_version','authority','record_key','sequence','previous_sha256','recorded_at','day','time_basis','event_sha256','redacted','truncated'}
    require(isinstance(event,dict) and set(event)==FIELDS|metadata,'unsupported audit envelope')
    require(type(event['schema_version'])is int and event['schema_version']==SCHEMA_VERSION and event['authority']=='audit_only')
    require(type(event['sequence'])is int and event['sequence']>0 and name(event['record_key']))
    require(type(event['redacted'])is bool and type(event['truncated'])is bool)
    normalized=validate_record({key:event[key] for key in FIELDS})
    require(all(event[key]==normalized[key] for key in FIELDS),'invalid stored audit projection')
    recorded=utc(event['recorded_at']);require(recorded.isoformat()==event['recorded_at'])
    at=recorded if event['occurred_at'] is None else utc(event['occurred_at'])
    require(event['day']==at.astimezone(SHANGHAI).date().isoformat()
            and event['time_basis']==('recorded_at' if event['occurred_at'] is None else 'occurred_at'),'audit time provenance mismatch')
    for key in ('sequence','record_key','event_sha256','previous_sha256'):require(event[key]==row[key],'audit envelope mismatch')
    require(hash_value(row['input_sha256']) and digest({k:v for k,v in event.items() if k!='event_sha256'})==event['event_sha256'],'audit content hash mismatch')
    return event


def _iter(c):
    previous=None;sequence=0
    for row in c.execute('SELECT * FROM pi_audit_events ORDER BY sequence'):
        event=_decode(row);sequence+=1
        require(event['sequence']==sequence and event['previous_sha256']==previous,'audit chain mismatch')
        previous=event['event_sha256'];yield event


class AuditStore:
    def __init__(self,path,clock=None):
        self.path=_path(path);self.clock=clock or (lambda:datetime.now(timezone.utc))
        require(self.path.parent.is_dir() and stat.S_IMODE(self.path.parent.stat().st_mode)==0o700,'private audit parent required')
        if not self.path.exists():
            with self.path.open('xb'):pass
            self.path.chmod(0o600)
        _plain(self.path)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5)) as c:
            version=c.execute('PRAGMA user_version').fetchone()[0]
            if version==0 and not c.execute('SELECT 1 FROM sqlite_master').fetchone():
                with c:
                    for sql in _DDL:c.execute(sql)
                    c.execute('PRAGMA user_version='+str(DB_VERSION))
            _schema(c)
        require(stat.S_IMODE(self.path.stat().st_mode)==0o600,'private audit database required')

    def append(self,record_key,record):
        require(name(record_key),'invalid audit record key')
        normalized=validate_record(record)
        try:input_sha=digest(record)
        except (ValueError,TypeError,RecursionError):raise ValueError('invalid audit input') from None
        _plain(self.path)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5)) as c:
            c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE')
            try:
                _schema(c)
                old=c.execute('SELECT * FROM pi_audit_events WHERE record_key=?',(record_key,)).fetchone()
                if old:
                    require(old['input_sha256']==input_sha,'audit record key conflict')
                    event=_decode(old);c.commit();return event
                tail=c.execute('SELECT * FROM pi_audit_events ORDER BY sequence DESC LIMIT 1').fetchone()
                prior=None if tail is None else _decode(tail)
                now=utc(self.clock());at=now if normalized['occurred_at'] is None else utc(normalized['occurred_at'])
                event=dict(normalized,schema_version=SCHEMA_VERSION,authority='audit_only',record_key=record_key,
                    sequence=1 if prior is None else prior['sequence']+1,
                    previous_sha256=None if prior is None else prior['event_sha256'],
                    recorded_at=now.isoformat(),day=at.astimezone(SHANGHAI).date().isoformat(),
                    time_basis='recorded_at' if normalized['occurred_at'] is None else 'occurred_at')
                event['event_sha256']=digest(event)
                require(len(encoded(event))<=MAX_EVENT_BYTES,'audit event exceeds byte bound')
                c.execute('INSERT INTO pi_audit_events(sequence,record_key,input_sha256,event_sha256,previous_sha256,payload) VALUES (?,?,?,?,?,?)',
                    (event['sequence'],record_key,input_sha,event['event_sha256'],event['previous_sha256'],encoded(event).decode()))
                c.commit();return event
            except BaseException:c.rollback();raise

    def events(self,run_id=None,day=None):
        require(run_id is None or name(run_id))
        if day is not None:
            from datetime import date
            require(isinstance(day,str) and date.fromisoformat(day).isoformat()==day)
        _plain(self.path)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=5)) as c:
            c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN');_schema(c)
            return [event for event in _iter(c) if (run_id is None or event['run_id']==run_id) and (day is None or event['day']==day)]
