#!/bin/bash
set -euo pipefail
export DOCKER_HOST=unix:///var/run/docker.sock
export TMPDIR=/opt/myink-pi-cache PYTHONPYCACHEPREFIX=/opt/myink-pi-cache/pycache
[[ $(id -u) == 0 ]]
[[ $(docker info --format '{{.ID}}') == 364e8400-3844-47e2-b86d-8b626332f61c ]]
[[ $(docker info --format '{{.CgroupVersion}}/{{.CgroupDriver}}') == 2/systemd ]]
base=/opt/myink-pi-lab
mkdir -p "$base" /opt/myink-pi-cache
exec 9>"$base/heavy.lock"
mode=${1:-up}
if [[ $mode == preflight ]]; then
    cd "$base/trusted-source"
    export PYTHONPATH=$PWD/src:$PWD
    /opt/myink-pi-venv/bin/python - <<'PY'
import json
from ops.pi.lab.verify import verify_runtime
print(json.dumps(verify_runtime()))
PY
    exit 0
fi
if [[ $mode == cleanup ]]; then
    flock -n 9 || exit 73
    export PYTHONPATH="$base/trusted-source/src:$base/trusted-source"
    /opt/myink-pi-venv/bin/python - "${2:?}" <<'PY'
import json,sys,subprocess
from pathlib import Path
base=Path('/opt/myink-pi-lab'); r=json.loads((base/'lab-env.json').read_text())
if sys.argv[1]!=r['lab_uuid']: raise SystemExit('cleanup UUID mismatch')
names=r['test_containers']+r.get('maintenance_containers',[])+[r['sandbox'],r['gateway'],r['project']+'-denied']
networks=[r['project']+'-agent',r['project']+'-fixtures']+([r['project']+'-maintenance'] if r.get('maintenance_containers') else [])
volumes=[r['project']+'-'+k+'-data' for k in ('pg','redis','rabbit')]+[n+'-data' for n in r.get('maintenance_containers',[]) if not n.endswith('-entry')]
# Freeze and verify every object before the first effect; anonymous recovery volumes are retained.
for kind,objects in [('container',names),('network',networks),('volume',volumes)]:
 for name in objects:
  info=json.loads(subprocess.check_output(['docker',kind,'inspect',name]))[0]
  labels=info['Config']['Labels'] if kind=='container' else info['Labels']
  if labels.get('myink.pi.lab')!=r['lab_uuid']: raise SystemExit('foreign cleanup object')
intent={'lab_uuid':r['lab_uuid'],'containers':names,'networks':networks,'volumes':volumes}
Path(r['evidence_dir']+'/cleanup-intent.json').write_text(json.dumps(intent))
subprocess.run(['docker','rm','-f',*names],check=True)
subprocess.run(['docker','network','rm',*networks],check=True)
subprocess.run(['docker','volume','rm',*volumes],check=True)
Path(r['evidence_dir']+'/cleanup-receipt.json').write_text(json.dumps({'status':'done',**intent}))
PY
    iptables -D INPUT -i pi-lab-agent -j DROP
    iptables -D DOCKER-USER -i pi-lab-agent -j MYINKPI_B7
    iptables -D DOCKER-USER -i pi-lab-fixtures ! -o pi-lab-fixtures -j DROP
    iptables -C DOCKER-USER -i pi-lab-maint ! -o pi-lab-maint -j DROP 2>/dev/null && iptables -D DOCKER-USER -i pi-lab-maint ! -o pi-lab-maint -j DROP || true
    iptables -F MYINKPI_B7
    iptables -X MYINKPI_B7
    exit 0
fi
if [[ $mode == prepare-probes || $mode == stop-probes ]]; then
    operation=${2:?}; lab_uuid=${3:?}
    [[ $operation =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]
    [[ $(/opt/myink-pi-venv/bin/python -c 'import json;print(json.load(open("/opt/myink-pi-lab/lab-env.json"))["lab_uuid"])') == "$lab_uuid" ]]
    probe="myinkpi-host-probe-$operation"
    description="myinkpi:$lab_uuid:$operation"
    if [[ $mode == stop-probes ]]; then
        if systemctl is-active --quiet "$probe"; then
            [[ $(systemctl show "$probe" -p Description --value) == "$description" ]]
            [[ $(systemctl show "$probe" -p ControlGroup --value) == /myinkpi.slice/myinkpi-infra.slice/* ]]
            systemctl stop "$probe"
        fi
        exit 0
    fi
    systemd-run --quiet --unit="$probe" --description="$description" --slice=myinkpi-infra.slice -p RuntimeMaxSec=180 \
      /opt/myink-pi-venv/bin/python "$base/gateway/server.py" 8080
    /opt/myink-pi-venv/bin/python - <<'PY'
from pathlib import Path
import json,socket,subprocess,urllib.request
r=json.loads(Path('/mnt/e/tools/myink-pi/evidence/b7-host-server.json').read_text())
identity=json.loads(Path('/opt/myink-pi-lab/lab-env.json').read_text())
if r.get('owner')!='B7-controlled-probe' or r.get('lab_uuid')!=identity['lab_uuid']: raise SystemExit('host probe ownership mismatch')
gateway=json.loads(subprocess.check_output(['ip','-j','route','show','default']))[0]['gateway']
url='http://'+gateway+':'+str(r['port'])
status=urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=3).status
receipt={'trusted_windows_host_status':status,'url':url,'trusted_dns_resolved':bool(socket.getaddrinfo('example.com',80)),'lab_uuid':identity['lab_uuid']}
Path('/mnt/e/tools/myink-pi/evidence/b7-host-reachability.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
PY
    exit 0
fi
if [[ $mode == stop-heavy ]]; then
    exec 8>"$base/ownership.lock"
    flock -w 10 8 || exit 73
    export PYTHONPATH="$base/trusted-source/src:$base/trusted-source"
    /opt/myink-pi-venv/bin/python - "${2:?}" "${3:?}" <<'PY'
import json,sys
from ops.pi.lab.verify import cancel_owned
print(json.dumps(cancel_owned(sys.argv[1],sys.argv[2])))
PY
    exit 0
fi
if [[ $mode == maintenance-up ]]; then
    flock -n 9 || exit 73
    cd "$base/trusted-source"
    export PYTHONPATH=$PWD/src:$PWD
    /opt/myink-pi-venv/bin/python - <<'PY'
from pathlib import Path
import json,shutil,subprocess,time,hashlib
from datetime import datetime,timedelta,timezone
from email.utils import format_datetime
from ops.pi.lab.verify import verify_runtime,_docker,_configuration,freeze_runtime
base=Path('/opt/myink-pi-lab');r=verify_runtime();project=r['project'];lab=r['lab_uuid']
if r.get('maintenance_containers'):raise SystemExit('persistent maintenance infra already prepared; verify instead')
peak=2*1024**3;reserve=5*1024**3
assert all(shutil.disk_usage(path).free>=peak+reserve for path in ('/','/mnt/e'))
evidence=Path('/mnt/e/tools/myink-pi/evidence');before=json.loads((base/'runtime-manifest.json').read_text())
(evidence/'b8-runtime-before.json').write_text(json.dumps(before,indent=2))
images={kind:_docker('inspect',project+'-'+kind)[0]['Image'] for kind in ('pg','redis','rabbit')}
images['entry']=_docker('image','inspect','sha256:f2a1290d0463aad60660d4ec134943f183ee2a5f6c3eb7bf32dd984f2f020772')[0]['Id']
static=base/'maintenance';static.mkdir(exist_ok=False)
now=datetime.now(timezone(timedelta(hours=8)));reopen=now.replace(hour=6,minute=0,second=0,microsecond=0)
if reopen<=now:reopen+=timedelta(days=1)
snapshot={'reopen_at':reopen.isoformat(),'retry_after':format_datetime(reopen.astimezone(timezone.utc),usegmt=True),'sha256':{}}
for file in ('maintenance.Caddyfile','maintenance.html'):
 content=(base/'trusted-source/ops/pi/lab'/file).read_text().replace('{{REOPEN_HTTP}}',snapshot['retry_after']).replace('{{REOPEN_AT}}',snapshot['reopen_at']).replace('{{REOPEN_DATE}}',reopen.date().isoformat())
 (static/file).write_text(content);snapshot['sha256'][file]=hashlib.sha256(content.encode()).hexdigest()
r['maintenance_snapshot']=snapshot
network=project+'-maintenance'
def run(*args):return subprocess.check_output(['docker','--host','unix:///var/run/docker.sock',*args],text=True,timeout=60).strip()
run('network','create','--label','myink.pi.lab='+lab,'--opt','com.docker.network.bridge.name=pi-lab-maint',network)
subprocess.run(['/usr/sbin/iptables','-A','DOCKER-USER','-i','pi-lab-maint','!','-o','pi-lab-maint','-j','DROP'],check=True)
containers=[]
for kind,port,memory,cpu in [('pg',5432,'256m','0.3'),('redis',6379,'96m','0.15'),('rabbit',5672,'320m','0.4'),('entry',8080,'96m','0.1')]:
 name=project+'-maintenance-'+kind;containers.append(name)
 args=['run','-d','--name',name,'--label','myink.pi.lab='+lab,'--label','myink.pi.owner=maintenance-infra',
       '--cgroup-parent','myinkpi-infra.slice','--memory',memory,'--memory-swap',memory,'--cpus',cpu,
       '--pids-limit','128','--network',network,'-p','127.0.0.1::'+str(port)]
 if kind!='entry':
  volume=name+'-data';run('volume','create','--label','myink.pi.lab='+lab,'--label','myink.pi.owner=maintenance-infra',volume)
  destination={'pg':'/var/lib/postgresql/data','redis':'/data','rabbit':'/var/lib/rabbitmq'}[kind]
  args+=['--mount','type=volume,source='+volume+',target='+destination]
 if kind=='pg':args+=['-e','POSTGRES_PASSWORD=synthetic-lab-only','-e','POSTGRES_DB=myink','--shm-size','32m']
 if kind=='rabbit':args+=['--hostname',name,'-e','RABBITMQ_DEFAULT_USER=myink','-e','RABBITMQ_DEFAULT_PASS=synthetic-lab-only','-e','RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS=+S 2:2']
 if kind=='entry':
  args+=['--user','65534:65534','--read-only','--cap-drop','ALL','--cap-add','NET_BIND_SERVICE','--security-opt','no-new-privileges','--tmpfs','/tmp:size=8m','--tmpfs','/config:size=4m','--tmpfs','/data:size=4m',
         '-v',str(static)+':/maintenance:ro',images[kind],'caddy','run','--config','/maintenance/maintenance.Caddyfile','--adapter','caddyfile']
 else:args+=[images[kind]]
 run(*args)
 info=_docker('inspect',name)[0]
 assert info['Image']==images[kind] and info['HostConfig']['CgroupParent']=='myinkpi-infra.slice'
 assert info['Config']['Labels']['myink.pi.owner']=='maintenance-infra' and info['HostConfig']['Memory']>0
 assert info['HostConfig']['MemorySwap']==info['HostConfig']['Memory']
 assert '/myinkpi.slice/myinkpi-infra.slice/' in Path('/proc/'+str(info['State']['Pid'])+'/cgroup').read_text()
# Preserve every previously frozen configuration; only the four new owned infra entries differ.
for name,configuration in before['containers'].items():assert _configuration(_docker('inspect',name)[0])==configuration
r['maintenance_containers']=containers;r['maintenance_images']=images
(base/'lab-env.json').write_text(json.dumps(r,indent=2));(base/'lab-env.json').chmod(0o600)
freeze_runtime(r)
after=json.loads((base/'runtime-manifest.json').read_text())
assert {name:after['containers'][name] for name in before['containers']}==before['containers']
assert set(after['containers'])-set(before['containers'])==set(containers)
(evidence/'b8-runtime-after.json').write_text(json.dumps(after,indent=2))
(evidence/'b8-runtime-delta.json').write_text(json.dumps({'added':containers,'old_configuration_unchanged':True,'images':images,'planned_peak_bytes':peak,'reserve_bytes':reserve,'host_free_bytes':shutil.disk_usage('/mnt/e').free,'guest_free_bytes':shutil.disk_usage('/').free},indent=2))
shutil.copyfile(base/'lab-env.json',Path('/mnt/e/tools/myink-pi/state/lab-env.json'))
print(json.dumps(verify_runtime()))
PY
    exit 0
fi
if [[ $mode == execute ]]; then
    flock -n 9 || exit 73
    command_id=${2:?}; selection=${3:?}; timeout=${4:?}; operation=${5:?}
    [[ $operation =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]
    [[ $timeout =~ ^[0-9]+$ && $timeout -ge 1 && $timeout -le 2700 ]]
    case "$command_id/$selection" in
      test/bootstrap|probe/watchdog) targets=() ;;
      probe/b7|test/b7) targets=(ops/pi/tests/integration/test_isolation.py) ;;
      test/b8-red|test/b8-focused|test/b8-survival|test/b8-reconcile) targets=(tests/test_maintenance_admission.py tests/test_maintenance_worker_barrier.py) ;;
      test/b8-ci-collection|test/b8-guarded-collection) targets=(tests/test_maintenance_admission.py tests/test_maintenance_worker_barrier.py) ;;
      test/b8) targets=(tests/test_maintenance_admission.py tests/test_maintenance_worker_barrier.py tests/test_enqueue_gates.py tests/test_task_budget_routes.py tests/test_manual_plan.py) ;;
      test/b9-red|test/b9) targets=(tests/test_maintenance_pause.py tests/test_maintenance_compatibility.py tests/test_task_budget_recovery.py tests/test_short_runner.py tests/test_worker.py tests/test_manual_plan.py) ;;
      test/b9-pause|test/b9-wait|test/b9-identity) targets=(tests/test_maintenance_pause.py) ;;
      test/b9-compatibility) targets=(tests/test_maintenance_compatibility.py) ;;
      test/b9-recovery) targets=(tests/test_task_budget_recovery.py) ;;
      test/b9-short) targets=(tests/test_short_runner.py) ;;
      test/b9-worker) targets=(tests/test_worker.py) ;;
      test/b9-plan) targets=(tests/test_manual_plan.py) ;;
      test/provenance) targets=(tests/test_run_provenance.py tests/test_admin_observability.py tests/test_run_ownership.py) ;;
      data-read/b7) targets=(ops/pi/tests/integration/test_db_reader_lab.py) ;;
      *) exit 64 ;;
    esac
    . "$base/test.env"
    opts=(--pi-lab)
    [[ $selection != provenance && $selection != b8 && $selection != b8-red && $selection != b8-focused && $selection != b8-survival && $selection != b8-reconcile && $selection != b8-ci-collection && $selection != b8-guarded-collection ]] || opts=()
    [[ $selection != b9* ]] || opts=()
    python_args=(-m pytest "${targets[@]}" -q "${opts[@]}" -m "not pi_live" --tb=short)
    [[ $selection != b9-identity ]] || python_args+=(-k "actual_control_drift or candidate_blocker or private_execution_roles")
    [[ $selection != b9-wait ]] || python_args+=(-k "wait_race or actual_plan_interrupt")
    [[ $selection != b9-red ]] || python_args=(-m pytest tests/test_maintenance_pause.py tests/test_maintenance_compatibility.py -q -m "not pi_live" --tb=short)
    [[ $selection != b8-red ]] || python_args+=(-k "generate_and_resume_denied or no_quota_charge or db_unavailable_fails_closed or worker_restart_does_not_consume")
    [[ $selection != b8-survival ]] || python_args+=(-k "maintenance_page_survives_candidate_failure")
    [[ $selection != b8-reconcile ]] || python_args+=(-k "uncertain_receipt")
    [[ $selection != b8-ci-collection ]] || python_args=(-c "import pytest; result=pytest.main(['tests/test_maintenance_admission.py','tests/test_maintenance_worker_barrier.py','--collect-only','-q','-m','not pi_lab and not pi_live']); raise SystemExit(0 if result == 5 else 1)")
    [[ $selection != b8-guarded-collection ]] || python_args=(-m pytest "${targets[@]}" --collect-only -q -m "not pi_live")
    [[ $selection != bootstrap ]] || python_args=(-m myink.cli init --seed)
    [[ $selection != watchdog ]] || python_args=(-c "import time;time.sleep(60)")
    [[ -z $(systemctl list-units 'myinkpi-test-*' --state=running --no-legend --no-pager) ]] || exit 73
    unit="myinkpi-test-$operation"
    export PYTHONPATH="$base/trusted-source/src:$base/trusted-source"
    exec 8>"$base/ownership.lock"
    flock -w 10 8 || exit 73
    /opt/myink-pi-venv/bin/python - "$unit" <<'PY'
from pathlib import Path
import sys,json
base=Path('/opt/myink-pi-lab')
r=json.loads((base/'lab-env.json').read_text())
from ops.pi.lab.verify import _write_owner
_write_owner({'unit':sys.argv[1],'lab_uuid':r['lab_uuid'],'group':'heavy','operation_id':sys.argv[1].removeprefix('myinkpi-test-'),'status':'active'})
PY
    watcher="myinkpi-watch-${unit#myinkpi-test-}"
    systemd-run --quiet --unit="$watcher" --slice=myinkpi-infra.slice -p RuntimeMaxSec="$((timeout+15))" \
      --working-directory="$base/trusted-source" \
      /usr/bin/env PYTHONPATH="$PYTHONPATH" PYTHONPYCACHEPREFIX="$PYTHONPYCACHEPREFIX" \
      /opt/myink-pi-venv/bin/python -m ops.pi.resources watch-guest "$unit" "$timeout"
    # Stop only this watcher before releasing mutex, preventing a stale watcher from killing the next run.
    finish_operation() {
        systemctl stop "$watcher" >/dev/null 2>&1 || true
        flock -w 10 8 || return 1
        /opt/myink-pi-venv/bin/python - "$operation" <<'PY'
from pathlib import Path
import sys,json
p=Path('/opt/myink-pi-lab/current-operation.json');r=json.loads(p.read_text())
if r['operation_id']==sys.argv[1] and r['status']=='active':
    from ops.pi.lab.verify import _write_owner
    r['status']='completed';_write_owner(r)
PY
        flock -u 8
    }
    trap finish_operation EXIT
    # Bound the test controller and every descendant; fixture Docker scopes have explicit same parent.
    systemd-run --quiet --wait --pipe --collect --unit="$unit" \
      --slice=myinkpi-heavy.slice -p RuntimeMaxSec="$timeout" -p OOMScoreAdjust=-900 \
      --working-directory="$base/trusted-source" \
      /usr/bin/env -i PATH=/opt/myink-pi-venv/bin:/usr/bin:/bin HOME=/opt/myink-pi-cache \
      TMPDIR=/opt/myink-pi-cache PYTHONPYCACHEPREFIX=/opt/myink-pi-cache/pycache \
      PYTHONPATH="$base/trusted-source/src:$base/trusted-source" \
      DATABASE_URL="$DATABASE_URL" ADMIN_DATABASE_URL="$ADMIN_DATABASE_URL" REDIS_URL="$REDIS_URL" \
      AMQP_URL="$AMQP_URL" QUEUE_PREFIX="$QUEUE_PREFIX" JWT_SECRET="$JWT_SECRET" EMBED_ENABLED=0 \
      PI_LAB_ENV="$base/lab-env.json" \
      /opt/myink-pi-venv/bin/python "${python_args[@]}" &
    runner=$!
    # Cancellation and a later start share this lock: publish/start is one guarded transition.
    for i in $(seq 1 50); do
        systemctl is-active --quiet "$unit" && break
        kill -0 "$runner" 2>/dev/null || break
        sleep .1
    done
    flock -u 8
    if wait "$runner"; then result=0; else result=$?; fi
    for i in $(seq 1 30); do systemctl is-active --quiet "$watcher" || break; sleep .1; done
    systemctl stop "$watcher" >/dev/null 2>&1 || true
    exit "$result"
fi
[[ $mode == up ]]
flock -n 9 || exit 73
[[ ! -f $base/lab-env.json ]] || { echo 'existing lab must be reconciled, not overwritten' >&2; exit 73; }
[[ -f $base/trusted-source/ops/pi/executor.py ]]
bash "$base/trusted-source/ops/pi/lab/cgroup-setup.sh"
uuid=$(cat /proc/sys/kernel/random/uuid)
project=myinkpi-${uuid:0:8}
evidence=/mnt/e/tools/myink-pi/evidence/b7-$uuid
mkdir -p "$evidence" "$base/gateway" "$base/policy" "$base/candidates"
trap 'code=$?; if [[ $code != 0 ]]; then printf "{\"status\":\"failed\",\"exit_code\":%s}\n" "$code" > "$evidence/provision-failure.json"; fi' EXIT
python_image=$(docker image inspect docker.m.daocloud.io/library/python:3.12-slim --format '{{.Id}}')
pg_image=$(docker image inspect docker.m.daocloud.io/pgvector/pgvector:pg16 --format '{{.Id}}')
redis_image=$(docker image inspect docker.m.daocloud.io/library/redis:7-alpine --format '{{.Id}}')
rabbit_image=$(docker image inspect docker.m.daocloud.io/library/rabbitmq:3.13-management --format '{{.Id}}')
# Only this bridge is subject to private distro firewall rules; no global Windows policy.
network=$project-agent
fixtures=$project-fixtures
[[ -z $(docker network ls --filter name='^myinkpi-' -q) ]]
docker network create --internal --subnet 172.29.220.0/24 --opt com.docker.network.bridge.name=pi-lab-agent --label "myink.pi.lab=$uuid" "$network"
docker network create --opt com.docker.network.bridge.name=pi-lab-fixtures --label "myink.pi.lab=$uuid" "$fixtures"
iptables -I DOCKER-USER 1 -i pi-lab-fixtures ! -o pi-lab-fixtures -j DROP
iptables -N MYINKPI_B7
iptables -I INPUT 1 -i pi-lab-agent -j DROP
iptables -I DOCKER-USER 1 -i pi-lab-agent -j MYINKPI_B7
iptables -A MYINKPI_B7 -s 172.29.220.10 -d 172.29.220.2 -p tcp --dport 8765 -j RETURN
iptables -A MYINKPI_B7 -s 172.29.220.10 -j DROP
iptables -A MYINKPI_B7 -j RETURN
# Network IPv6 is disabled; kernel IPv6 paths in candidate disabled explicitly.
cat > "$base/gateway/server.py" <<'PY'
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.server.server_port == 8080:
            code=200
        else:
            code=200 if self.path == '/mock' and self.headers.get('Authorization') == 'Bearer synthetic-b7-token' and self.headers.get('X-Pi-Scope') == 'b7-local' else 403
        self.send_response(code); self.end_headers(); self.wfile.write(b'{"mock":true}')
import sys
ThreadingHTTPServer(('0.0.0.0',int(sys.argv[1])),Handler).serve_forever()
PY
cat > "$base/policy/probe.py" <<'PY'
import json,os,pathlib,subprocess,urllib.request,urllib.error
urls=['http://172.29.220.20:8080','http://172.29.220.1:8080','http://169.254.169.254:80',
      'http://1.1.1.1:80','http://192.0.2.1:80','http://172.29.220.1:2375']
def request(url,token=None):
    try:
        req=urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'X-Pi-Scope':'b7-local'} if token else {})
        return urllib.request.urlopen(req,timeout=1).status
    except urllib.error.HTTPError as error: return error.code
    except (OSError,urllib.error.URLError): return None
r={'authenticated_mock':request('http://172.29.220.2:8765/mock','synthetic-b7-token'),
   'wrong_token':request('http://172.29.220.2:8765/mock','wrong'),
   'denied_urls':sum(request(url) is None for url in urls), 'nonroot':os.getuid()!=0,
   'no_caps':'CapEff:\t0000000000000000' in pathlib.Path('/proc/self/status').read_text()}
child=subprocess.run(['python','-c',"import urllib.request;urllib.request.urlopen('http://172.29.220.20:8080',timeout=1)"],capture_output=True)
r['nested_python_denied']=child.returncode!=0 and b'Timed out' in child.stderr or child.returncode!=0 and b'timed out' in child.stderr
curl=subprocess.run(['curl','--noproxy','*','--max-time','2','--fail','http://172.29.220.20:8080'],capture_output=True)
r['nested_curl_denied']=curl.returncode==28
import socket
try: socket.getaddrinfo('example.com',80); r['external_dns_denied']=False
except OSError: r['external_dns_denied']=True
checks=[('/mnt/e/tools/myink-pi/state/credentials/platform-model.json','r'),('/root/.ssh/id_rsa','r'),
        ('/primary/.env','r'),('/var/run/docker.sock','r'),('/source/.git/config','r'),
        ('/policy/probe.py','w'),('/source/.env','r'),('/mnt/e/github椤圭洰/Myink/.env','r'),('/mnt/c/Users/14341/.ssh/id_rsa','r')]
n=0
for path,mode in checks:
    try:
        with open(path,mode): pass
    except OSError: n+=1
r['file_denials']=n
print(json.dumps(r))
PY
# Curated curl runtime is prepared by trusted package install, never by candidate.
[[ -f $base/curl-image-id ]] || { echo 'trusted curl image preparation missing' >&2; exit 78; }
sandbox_image=$(cat "$base/curl-image-id")
/opt/myink-pi-venv/bin/python - "$base/trusted-source" "$base/candidates/$uuid" <<'PY'
import sys
from ops.pi.executor import stage_source
print(stage_source(sys.argv[1],sys.argv[2]))
PY
candidate=$base/candidates/$uuid
common=(--label "myink.pi.lab=$uuid" --cap-drop ALL --security-opt no-new-privileges --pids-limit 256)
docker run -d --name "$project-gateway" "${common[@]}" --user 65534:65534 --read-only \
 --cgroup-parent myinkpi-infra.slice --network "$network" --ip 172.29.220.2 \
 -v "$base/gateway:/gateway:ro" "$python_image" python /gateway/server.py 8765
docker run -d --name "$project-denied" "${common[@]}" --user 65534:65534 --read-only \
 --cgroup-parent myinkpi-infra.slice --network "$network" --ip 172.29.220.20 \
 -v "$base/gateway:/gateway:ro" "$python_image" python /gateway/server.py 8080
docker run -d --name "$project-agent" "${common[@]}" --user 65534:65534 --read-only \
 --cgroup-parent myinkpi-agent.slice --memory 384m --memory-swap 384m --cpus .5 \
 --network "$network" --ip 172.29.220.10 --dns 127.0.0.1 --dns-option timeout:1 --dns-option attempts:1 --sysctl net.ipv6.conf.all.disable_ipv6=1 \
 --tmpfs /tmp:rw,noexec,nosuid,size=32m --tmpfs /cache:rw,noexec,nosuid,size=32m \
 -v "$candidate:/source:ro" -v "$base/policy:/policy:ro" "$sandbox_image" python -c 'import time;time.sleep(86400)'
# Ephemeral test service fixtures ALL share the heavy parent with pytest runner.
for kind in pg redis rabbit; do
    docker volume inspect "$project-$kind-data" >/dev/null 2>&1 && exit 73
    docker volume create --label "myink.pi.lab=$uuid" "$project-$kind-data"
done
docker run -d --name "$project-pg" --label "myink.pi.lab=$uuid" --cgroup-parent myinkpi-heavy.slice \
 --mount "type=volume,source=$project-pg-data,target=/var/lib/postgresql/data" --network "$fixtures" -p 127.0.0.1::5432 -e POSTGRES_PASSWORD=synthetic-lab-only -e POSTGRES_DB=myink "$pg_image"
docker run -d --name "$project-redis" --label "myink.pi.lab=$uuid" --cgroup-parent myinkpi-heavy.slice \
 --mount "type=volume,source=$project-redis-data,target=/data" --network "$fixtures" -p 127.0.0.1::6379 "$redis_image"
docker run -d --name "$project-rabbit" --label "myink.pi.lab=$uuid" --cgroup-parent myinkpi-heavy.slice \
 --mount "type=volume,source=$project-rabbit-data,target=/var/lib/rabbitmq" --hostname "$project-rabbit" --network "$fixtures" -p 127.0.0.1::5672 -e RABBITMQ_DEFAULT_USER=myink -e RABBITMQ_DEFAULT_PASS=synthetic-lab-only "$rabbit_image"
for i in $(seq 1 60); do docker exec "$project-pg" pg_isready -U postgres >/dev/null && break; sleep 1; done
pgport=$(docker port "$project-pg" 5432 | awk -F: '{print $NF}')
redisport=$(docker port "$project-redis" 6379 | awk -F: '{print $NF}')
rabbitport=$(docker port "$project-rabbit" 5672 | awk -F: '{print $NF}')
cat > "$base/test.env" <<EOF
export DATABASE_URL='postgresql+psycopg://postgres:synthetic-lab-only@127.0.0.1:$pgport/myink'
export ADMIN_DATABASE_URL='postgresql+psycopg://postgres:synthetic-lab-only@127.0.0.1:$pgport/myink'
export REDIS_URL='redis://127.0.0.1:$redisport/0'
export AMQP_URL='amqp://myink:synthetic-lab-only@127.0.0.1:$rabbitport/'
export QUEUE_PREFIX='-pi-$uuid-'
export JWT_SECRET='synthetic-b7-jwt-secret-at-least-32-bytes'
export EMBED_ENABLED=0
EOF
chmod 600 "$base/test.env"
docker exec "$project-pg" psql -U postgres -d myink -v ON_ERROR_STOP=1 -c "CREATE ROLE myink LOGIN PASSWORD 'synthetic-lab-only'; GRANT ALL ON SCHEMA public TO myink; CREATE EXTENSION IF NOT EXISTS vector;"
export PYTHONPATH="$base/trusted-source/src:$base/trusted-source"
. "$base/test.env"
/opt/myink-pi-venv/bin/python - "$base/lab-env.json" "$uuid" "$project" "$evidence" "$python_image" <<'PY'
import json,sys
from ops.pi.resources import sample_resources
path,uuid,project,evidence,image=sys.argv[1:]
r=dict(schema_version=1,status='done',lab_uuid=uuid,project=project,daemon_id='364e8400-3844-47e2-b86d-8b626332f61c',distribution='MyinkPiLab',
       sandbox=project+'-agent',gateway=project+'-gateway',test_containers=[project+'-'+k for k in ('pg','redis','rabbit')],
       evidence_dir=evidence,python_image=image,kernel_proof=sample_resources('heavy'))
open(path,'w').write(json.dumps(r,indent=2))
open(evidence+'/identity.json','w').write(json.dumps(r,indent=2))
PY
/opt/myink-pi-venv/bin/python - <<'PY'
import json
from pathlib import Path
from ops.pi.lab.verify import freeze_runtime
freeze_runtime(json.loads(Path('/opt/myink-pi-lab/lab-env.json').read_text()))
PY
chmod 600 "$base/lab-env.json"
cp "$base/lab-env.json" /mnt/e/tools/myink-pi/state/lab-env.json
iptables-save > "$evidence/firewall.txt"
docker inspect "$project-agent" "$project-pg" "$project-redis" "$project-rabbit" > "$evidence/containers.json"
