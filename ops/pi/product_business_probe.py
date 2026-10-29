"""Root-approved authenticated GET checks. No mutation/model/HTTP entry point."""
from pathlib import Path
from copy import deepcopy
from hashlib import sha256
import uuid
from .audit import digest,encoded,hash_value,require,utc,strict_json
from .product_runtime import _pinned

FIELDS={'schema','mode','plan_sha256','context_sha256','expires_at','cases'}
CASE_FIELDS={'user_id','auth_version','foreign_user_id','foreign_auth_version','project_id','chapter_id','expected_sha256'}


def validate(value,plan,context_pin):
    require(isinstance(value,dict) and set(value)==FIELDS and value['schema']=='pi-business-read-probe-v1' and value['mode']==plan['mode'] and value['plan_sha256']==digest(plan) and value['context_sha256']==context_pin,'exact business read source required')
    require(utc(value['expires_at'])<=utc(plan['expires_at']) and isinstance(value['cases'],list) and 0<len(value['cases'])<=16 and len(encoded(value))<=32768,'bounded finite business reads required');seen=set()
    for case in value['cases']:
        require(isinstance(case,dict) and set(case)==CASE_FIELDS,'fixed read cases only')
        for key in ('user_id','foreign_user_id','project_id','chapter_id'):require(isinstance(case[key],str) and str(uuid.UUID(case[key]))==case[key],'canonical business object required')
        require(case['user_id']!=case['foreign_user_id'] and all(type(case[k]) is int and case[k]>0 for k in ('auth_version','foreign_auth_version')) and hash_value(case['expected_sha256']),'independent identities and response digest required')
        key=(case['user_id'],case['foreign_user_id'],case['project_id'],case['chapter_id']);require(key not in seen,'duplicate business sample');seen.add(key)
    return deepcopy(value)


PROGRAM=r"""
import sys,json,hashlib,uuid,urllib.request,urllib.error
from datetime import datetime,timezone,timedelta
import jwt
from myink.config import settings
from myink.api.auth import require_auth_configuration
packet=json.loads(sys.stdin.buffer.read(32769));cases=packet['cases'];require_auth_configuration()
checks=[]
def token(user,version):
 now=datetime.now(timezone.utc)
 return jwt.encode(dict(sub=user,iss='myink',tier='normal',ver=version,iat=now,exp=now+timedelta(seconds=60)),settings.jwt_secret,algorithm='HS256')
def get(path,bearer):
 headers={'Authorization':'Bearer '+bearer} if bearer else {}
 request=urllib.request.Request('http://127.0.0.1:8100'+path,headers=headers,method='GET')
 try:
  with urllib.request.urlopen(request,timeout=3) as reply:
   body=reply.read(4194305)
   if len(body)>4194304:raise RuntimeError('business response bound')
   return reply.status,json.loads(body)
 except urllib.error.HTTPError as error:return error.code,None
for case in cases:
 for key in ('user_id','foreign_user_id','project_id','chapter_id'):
  if str(uuid.UUID(case[key]))!=case[key]:raise RuntimeError('object identity differs')
 path='/api/v1/projects/'+case['project_id']+'/chapters/'+case['chapter_id']
 status,body=get(path,token(case['user_id'],case['auth_version']))
 if status!=200 or not isinstance(body,dict):raise RuntimeError('owner business read failed')
 value={k:body[k] for k in ('id','chapter_seq','title','status','content','version','summary')}
 pin=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
 if pin!=case['expected_sha256']:raise RuntimeError('business content differs')
 for bearer in (token(case['foreign_user_id'],case['foreign_auth_version']),None):
  if get(path,bearer)[0]!=403:raise RuntimeError('tenant or anonymous boundary failed')
 checks.append(pin)
print(json.dumps(dict(verified=True,cases=len(cases),http_reads=len(cases)*3,tenant_rejections=len(cases)*2,response_sha256=hashlib.sha256(json.dumps(checks,separators=(',',':')).encode()).hexdigest(),model_requests=0)))
"""


class BusinessReadProbe:
    def __init__(self,host,actor,path,pin):
        self.host=host;self.actor=actor;self.path=Path(path);self.pin=pin
        self.packet=validate(_pinned(path,pin,host.config['mode']=='ACTUAL'),host.plan,actor.context_pin)

    def check(self,backend):
        h=self.host;h.authorize(h.plan)
        require(validate(_pinned(self.path,self.pin,h.config['mode']=='ACTUAL'),h.plan,self.actor.context_pin)==self.packet and utc(h.clock())<utc(self.packet['expires_at']),'business read approval changed or expired')
        self.actor._control('candidate');rows=self.actor._scope();cohort=self.actor._cohort('candidate')
        require(all(rows[v['id']]['State']['Running'] for v in cohort),'validated candidate no longer running')
        api=next(v['id'] for v in cohort if v['service']=='api');before=backend._metadata()
        payload=h.root/'business-read-input.json'
        from .backup import durable_file
        durable_file(payload,encoded(self.packet))
        result=h._run(['exec','-i',api,'python','-B','-c',PROGRAM],stdin_path=payload,seconds=120)
        observed=strict_json(h._bytes(result));count=len(self.packet['cases'])
        require(isinstance(observed,dict) and set(observed)=={'verified','cases','http_reads','tenant_rejections','response_sha256','model_requests'} and observed['verified'] is True and type(observed['cases']) is int and observed['cases']==count and observed['http_reads']==3*count and observed['tenant_rejections']==2*count and observed['model_requests']==0 and hash_value(observed['response_sha256']),'authenticated business reads unconfirmed')
        after=backend._metadata()
        from .product_restore import _assert_read_only
        _assert_read_only(before,after);self.actor._scope();self.actor._control('candidate')
        return dict(observed,scope='authenticated_business_reads_only',identity=self.actor.identity('candidate'),probe_sha256=self.pin,database_content_sha256=digest(after['content']))
