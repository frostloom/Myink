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
    /opt/myink-pi-venv/bin/python - "$base/lab-env.json" <<'PY'
import json,sys,subprocess
from ops.pi.resources import sample_resources,verify_limits
r=json.load(open(sys.argv[1]))
for group in ('agent','heavy'):
    proof=sample_resources(group)
    if not verify_limits(proof,group): raise SystemExit('kernel proof missing')
    r[group+'_proof']=proof
r['kernel_proof']=r['heavy_proof']
for name in r['test_containers']+[r['sandbox'],r['gateway']]:
    info=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
    if info['Config']['Labels'].get('myink.pi.lab')!=r['lab_uuid'] or not info['State']['Running']:
        raise SystemExit('owned running resource proof missing')
subprocess.run(['iptables','-C','INPUT','-i','pi-lab-agent','-j','DROP'],check=True)
subprocess.run(['iptables','-C','DOCKER-USER','-i','pi-lab-agent','-j','MYINKPI_B7'],check=True)
net=json.loads(subprocess.check_output(['docker','network','inspect',r['project']+'-agent']))[0]
if not net['Internal'] or net['EnableIPv6']: raise SystemExit('private network mismatch')
info=json.loads(subprocess.check_output(['docker','inspect',r['sandbox']]))[0]
if info['Config']['User']!='65534:65534' or not info['HostConfig']['ReadonlyRootfs'] or info['HostConfig']['CapDrop']!=['ALL']:
    raise SystemExit('sandbox privilege mismatch')
if any(m['Source'] not in ['/opt/myink-pi-lab/candidates/'+r['lab_uuid'],'/opt/myink-pi-lab/policy'] or m['RW'] for m in info['Mounts']):
    raise SystemExit('candidate mount mismatch')
print(json.dumps(r))
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
names=r['test_containers']+[r['sandbox'],r['gateway'],r['project']+'-denied']
networks=[r['project']+'-agent',r['project']+'-fixtures']
volumes=[r['project']+'-'+k+'-data' for k in ('pg','redis','rabbit')]
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
    iptables -F MYINKPI_B7
    iptables -X MYINKPI_B7
    exit 0
fi
if [[ $mode == prepare-probes ]]; then
    if ! systemctl is-active --quiet myinkpi-guest-host-probe; then
        systemctl reset-failed myinkpi-guest-host-probe 2>/dev/null || true
        systemd-run --quiet --unit=myinkpi-guest-host-probe --slice=myinkpi-infra.slice -p RuntimeMaxSec=180 \
          /opt/myink-pi-venv/bin/python "$base/gateway/server.py" 8080
    fi
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
    echo 1 > /sys/fs/cgroup/myinkpi.slice/myinkpi-heavy.slice/cgroup.kill
    /opt/myink-pi-venv/bin/python - <<'PY'
import pathlib,time,json
root=pathlib.Path('/sys/fs/cgroup/myinkpi.slice/myinkpi-heavy.slice')
for _ in range(30):
    pids=[p for f in root.rglob('cgroup.procs') for p in f.read_text().split()]
    if not pids: break
    time.sleep(.1)
if pids: raise SystemExit('heavy group not empty')
print(json.dumps({'heavy_empty':True,'cgroup_events':(root/'cgroup.events').read_text().strip()}))
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
      test/provenance) targets=(tests/test_run_provenance.py tests/test_admin_observability.py tests/test_run_ownership.py) ;;
      data-read/b7) targets=(ops/pi/tests/integration/test_db_reader_lab.py) ;;
      *) exit 64 ;;
    esac
    . "$base/test.env"
    opts=(--pi-lab)
    [[ $selection != provenance ]] || opts=()
    python_args=(-m pytest "${targets[@]}" -q "${opts[@]}" -m "not pi_live")
    [[ $selection != bootstrap ]] || python_args=(-m myink.cli init --seed)
    [[ $selection != watchdog ]] || python_args=(-c "import time;time.sleep(60)")
    [[ -z $(systemctl list-units 'myinkpi-test-*' --state=running --no-legend --no-pager) ]] || exit 73
    unit="myinkpi-test-$operation"
    export PYTHONPATH="$base/trusted-source/src:$base/trusted-source"
    /opt/myink-pi-venv/bin/python - "$unit" <<'PY'
from pathlib import Path
import sys,json
base=Path('/opt/myink-pi-lab')
r=json.loads((base/'lab-env.json').read_text())
(base/'current-operation.json').write_text(json.dumps({'unit':sys.argv[1],'lab_uuid':r['lab_uuid'],'group':'heavy','operation_id':sys.argv[1].removeprefix('myinkpi-test-')}))
PY
    watcher="myinkpi-watch-${unit#myinkpi-test-}"
    systemd-run --quiet --unit="$watcher" --slice=myinkpi-infra.slice -p RuntimeMaxSec="$((timeout+15))" \
      --working-directory="$base/trusted-source" \
      /usr/bin/env PYTHONPATH="$PYTHONPATH" PYTHONPYCACHEPREFIX="$PYTHONPYCACHEPREFIX" \
      /opt/myink-pi-venv/bin/python -m ops.pi.resources watch-guest "$unit" "$timeout"
    # Stop only this watcher before releasing mutex, preventing a stale watcher from killing the next run.
    trap 'systemctl stop "$watcher" >/dev/null 2>&1 || true' EXIT
    # Bound the test controller and every descendant; fixture Docker scopes have explicit same parent.
    set +e
    systemd-run --quiet --wait --pipe --collect --unit="$unit" \
      --slice=myinkpi-heavy.slice -p RuntimeMaxSec="$timeout" -p OOMScoreAdjust=-900 \
      --working-directory="$base/trusted-source" \
      /usr/bin/env -i PATH=/opt/myink-pi-venv/bin:/usr/bin:/bin HOME=/opt/myink-pi-cache \
      TMPDIR=/opt/myink-pi-cache PYTHONPYCACHEPREFIX=/opt/myink-pi-cache/pycache \
      PYTHONPATH="$base/trusted-source/src:$base/trusted-source" \
      DATABASE_URL="$DATABASE_URL" ADMIN_DATABASE_URL="$ADMIN_DATABASE_URL" REDIS_URL="$REDIS_URL" \
      AMQP_URL="$AMQP_URL" QUEUE_PREFIX="$QUEUE_PREFIX" JWT_SECRET="$JWT_SECRET" EMBED_ENABLED=0 \
      PI_LAB_ENV="$base/lab-env.json" \
      /opt/myink-pi-venv/bin/python "${python_args[@]}"
    result=$?
    set -e
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
chmod 600 "$base/lab-env.json"
cp "$base/lab-env.json" /mnt/e/tools/myink-pi/state/lab-env.json
iptables-save > "$evidence/firewall.txt"
docker inspect "$project-agent" "$project-pg" "$project-redis" "$project-rabbit" > "$evidence/containers.json"
