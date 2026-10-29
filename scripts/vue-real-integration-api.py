"""Real isolated HTTP contracts; requires the dedicated test stack and one test invitation.

Never runs against the normal application ports. No LLM/provider calls are made.
Run with MYINK_REAL_METADATA and MYINK_REAL_INVITATION; see real-integration-report.md.
"""
import json, uuid, os, time
from pathlib import Path
import httpx
from myink.db import tenant_session
from myink.models import Project, Chapter
from myink.config import settings
from sqlalchemy.engine import make_url
assert settings.app_env == 'test'
database = make_url(settings.database_url)
assert database.host == '127.0.0.1' and database.port == 25432, 'Requires the dedicated isolated database port 25432'
assert os.environ.get('MYINK_REAL_METADATA') and os.environ.get('MYINK_REAL_INVITATION')
base='http://127.0.0.1:28100/api/v1'
run=str(int(time.time()))
name_a='vue_a_'+run
name_b='vue_b_'+run
invitation=os.environ['MYINK_REAL_INVITATION']
checks=[]
def call(method,path,body=None,token=None,status=200):
    r=httpx.request(method,base+path,json=body,headers={'Authorization':f'Bearer {token}'} if token else {},timeout=20)
    assert r.status_code==status,(method,path,r.status_code,r.text[:300])
    return r.json()
def passed(name): checks.append(name)
users=[]
for name in [name_a,name_b]:
    out=call('POST','/auth/register',{'username':name,'password':'VueRealPass2305','invitation_code':invitation},status=201)
    users.append(out)
passed('real_invitation_registration_two_accounts')
a,b=users
login=call('POST','/auth/token',{'username':name_a,'password':'VueRealPass2305'})
assert login['user_id']==a['user_id'];passed('real_password_login')
session=call('GET','/auth/session',token=a['token']);assert session['role']=='user';passed('real_session_verification')
call('GET','/environment',status=403);passed('anonymous_environment_denied')
payload={'request_id':str(uuid.uuid4()),'title':'Vue真实隔离作品','genre':'现实','chapter_count':50,'target_words':1000,'form':'long'}
project=call('POST','/projects',payload,a['token']);pid=project['id']
assert call('POST','/projects',payload,a['token'])['id']==pid;passed('real_project_create_idempotency')
assert pid in [p['id'] for p in call('GET','/projects',token=a['token'])]
assert pid not in [p['id'] for p in call('GET','/projects',token=b['token'])];passed('real_project_account_list_isolation')
call('GET',f'/projects/{pid}/chapters',token=b['token'],status=403);passed('real_foreign_project_owner_denied')
env=call('GET','/environment',token=a['token'])
changed=call('PUT','/environment',{'thinking_enabled':not env['thinking_enabled']},a['token'])
assert changed['thinking_enabled']!=env['thinking_enabled'];passed('real_environment_leaf_update')
assert call('GET','/environment',token=b['token'])['overridden_fields']==[];passed('real_environment_account_isolation')
call('PUT','/environment',{'reset_preferences':['thinking_enabled']},a['token']);passed('real_environment_reset')
resource=call('POST','/my-writing-resources',{'name':'隔离文风','kind':'style','source':'Vue验证','body':{'profile':{'pov':'第三人称'}}},a['token'])
rid=resource['id']
assert rid not in [r['id'] for r in call('GET','/my-writing-resources',token=b['token'])['items']];passed('real_personal_resource_account_isolation')
snapshot=call('GET',f'/projects/{pid}/writing-resources',token=a['token'])
selection={'expected_revision':snapshot['revision'],'selections':[{'origin':'personal','resource_id':rid}]}
selected=call('PUT',f'/projects/{pid}/writing-resources',selection,a['token'])
assert selected['configured'] and selected['selections'][0]['resource_id']==rid;passed('real_resource_snapshot_selection')
call('PUT',f'/projects/{pid}/writing-resources',selection,a['token'],status=409);passed('real_resource_revision_conflict')
assert call('GET',f'/projects/{pid}/writing-resources/updates',token=a['token'])['items']==[];passed('real_resource_update_endpoint')
with tenant_session(pid) as db:
    p=db.get(Project,uuid.UUID(pid));p.creation_status='ready';p.current_chapter=1
    chapter=Chapter(project_id=uuid.UUID(pid),chapter_seq=1,title='隔离雨夜',content='真实数据库中的原始正文。',summary='Vue浏览器隔离读写',status='confirmed',version=1)
    db.add(chapter);db.flush();cid=str(chapter.id)
passed('isolated_database_chapter_fixture_seeded_without_model')
assert call('GET',f'/projects/{pid}/chapters/{cid}',token=a['token'])['version']==1;passed('real_chapter_detail_read')
call('PUT',f'/projects/{pid}/chapters/{cid}/content',{'content':'真实接口第一次写入。','expected_version':1},a['token'])
call('PUT',f'/projects/{pid}/chapters/{cid}/content',{'content':'不应覆盖','expected_version':1},a['token'],status=409);passed('real_chapter_optimistic_conflict')
assert len(call('GET',f'/projects/{pid}/chapters/{cid}/versions',token=a['token'])['versions'])==1;passed('real_chapter_history_snapshot')
call('POST','/auth/logout',token=b['token']);call('GET','/auth/session',token=b['token'],status=401);passed('real_logout_revokes_token')
Path(os.environ['MYINK_REAL_METADATA']).write_text(json.dumps({'projectId':pid,'chapterId':cid,'username':name_a,'password':'VueRealPass2305','registerUsername':'vue_c_','invitation':invitation,'apiChecks':checks},ensure_ascii=False))
Path(os.environ.get('MYINK_REAL_API_RECEIPT', '/tmp/myink-vue-real-api-receipt.json')).write_text(json.dumps({'kind':'real_isolated_http_postgres_redis','checks':checks,'count':len(checks),'model_calls':0},ensure_ascii=False,indent=2))
print(json.dumps({'api_checks_passed':len(checks)},ensure_ascii=False))
