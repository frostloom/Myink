"""Actual HTTP security/resource/attachment checks on the dedicated full-chain stack."""
import base64,json,os
from pathlib import Path
import httpx,pyotp
BASE='http://127.0.0.1:28110/api/v1'
p=Path('/tmp/myink-vue-chain-metadata-0025.json');m=json.loads(p.read_text());tokens=m['tokens'];checks=[]
c=httpx.Client(timeout=30,trust_env=False)
def call(method,path,data=None,role='user',status=200):
    r=c.request(method,BASE+path,json=data,headers={'Authorization':'Bearer '+tokens[role]})
    assert r.status_code==status,(method,path,r.status_code,r.text[:300]);return r.json()
def ok(name):checks.append(name);print(name,flush=True)
# Admin MFA is enrolled with actual encryption/storage, then challenge is verified.
enroll=call('POST','/auth/mfa/enroll',{'password':m['password']},role='admin');secret=enroll['secret'];m['admin']['mfaSecret']=secret;p.write_text(json.dumps(m,ensure_ascii=False))
call('POST','/auth/mfa/confirm',{'code':pyotp.TOTP(secret).now()},role='admin');call('GET','/auth/session',role='admin',status=401);ok('actual_mfa_confirmation_revokes_prior_session')
r=c.post(BASE+'/auth/token',json={'username':m['admin']['username'],'password':m['password']});assert r.status_code==200;challenge=r.json();assert challenge['mfa_required'] and 'token' not in challenge
r=c.post(BASE+'/auth/mfa/verify',json={'mfa_token':challenge['mfa_token'],'code':'000000'});assert r.status_code==401,(r.status_code,r.text[:200])
r=c.post(BASE+'/auth/mfa/verify',json={'mfa_token':challenge['mfa_token'],'code':pyotp.TOTP(secret).now()});assert r.status_code==200;tokens['admin']=r.json()['token'];ok('actual_mfa_challenge_wrong_code_and_valid_totp')
assert call('GET','/admin/overview',role='admin')['user_count']>=3;call('GET','/admin/overview',role='user',status=403);ok('actual_admin_report_role_and_nonadmin_denial')
invite=call('POST','/admin/invitations',{'label':'Vue chain admin invite','max_redemptions':1},role='admin',status=201)
call('POST',f'/admin/invitations/{invite["id"]}/revoke',role='admin');ok('actual_admin_invitation_create_revoke')
config=call('GET','/admin/configuration',role='admin');assert config['model_connections'][0]['model']=='fixture-local';assert not any('api_key_encrypted' in x or 'api_key' in x for x in config['model_connections']);ok('actual_admin_model_configuration_masks_credentials')
# Resource snapshots pin published revisions and stale mutations fail with 409.
resource=call('POST','/admin/writing-resources',{'name':'全链平台文风','kind':'style','source':'isolated HTTP fixture','body':{'profile':{'pov':'第三人称'}}},role='admin')
published=call('POST',f'/admin/writing-resources/{resource["id"]}/publish',{'expected_generation':resource['generation'],'note':'test-v1'},role='admin')
pid=m['longProjectId'];snapshot=call('GET',f'/projects/{pid}/writing-resources')
selection={'expected_revision':snapshot['revision'],'selections':[{'origin':'platform','resource_id':resource['id']}]}
saved=call('PUT',f'/projects/{pid}/writing-resources',selection);call('PUT',f'/projects/{pid}/writing-resources',selection,status=409);ok('actual_resource_selection_revision_conflict')
updated=call('PUT',f'/admin/writing-resources/{resource["id"]}',{'expected_generation':published['generation'],'name':'全链平台文风','source':'isolated HTTP fixture','body':{'profile':{'pov':'第三人称限知'}}},role='admin')
latest=call('POST',f'/admin/writing-resources/{resource["id"]}/publish',{'expected_generation':updated['generation'],'note':'test-v2'},role='admin')
updates=call('GET',f'/projects/{pid}/writing-resources/updates');target=next(i for i in updates['items'] if i['resource_id']==resource['id']);adopt={'expected_revision':saved['revision'],'updates':[{'resource_id':resource['id'],'target_generation':target['target_generation']}]}
adopted=call('POST',f'/projects/{pid}/writing-resources/adopt',adopt);assert adopted['selections'][0]['body']['profile']['pov']=='第三人称限知';call('POST',f'/projects/{pid}/writing-resources/adopt',adopt,status=409);ok('actual_resource_publish_adopt_and_stale_conflict')
# Byte-level attachment ownership through actual multipart and FileResponse.
image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1cAAAAASUVORK5CYII=')
r=c.post(BASE+'/feedback',headers={'Authorization':'Bearer '+tokens['user']},data={'description':'全链附件真实验证','category':'bug','page_url':'/projects/'+pid},files={'files':('evidence.png',image,'image/png')});assert r.status_code==200,(r.status_code,r.text);feedback=r.json();fid=feedback['id'];m['feedbackId']=fid
for role,status in [('user',200),('admin',200),('other',404)]:
    r=c.get(BASE+f'/feedback/{fid}/attachments/0',headers={'Authorization':'Bearer '+tokens[role]});assert r.status_code==status
    if status==200:assert r.content==image and r.headers['content-type'].startswith('image/png')
ok('actual_feedback_multipart_bytes_owner_admin_foreign_boundary')
resolved=call('PATCH',f'/admin/feedback/{fid}',{'status':'resolved'},role='admin');assert resolved['status']=='resolved';ok('actual_admin_feedback_resolution')
# Real password change invalidates the other account's old session.
call('POST','/auth/password',{'current_password':m['password'],'new_password':m['password']+'New'},role='other');call('GET','/auth/session',role='other',status=401);ok('actual_password_mutation_revokes_old_token')
m['tokens']=tokens;p.write_text(json.dumps(m,ensure_ascii=False));Path('/tmp/myink-vue-chain-security-receipt-0025.json').write_text(json.dumps({'checks':checks,'count':len(checks)},indent=2));print(json.dumps({'passed':len(checks)}))
