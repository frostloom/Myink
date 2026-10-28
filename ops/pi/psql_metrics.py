"""Fixed host SELECT transport. Models cannot supply config, SQL or CLI actions."""
from datetime import datetime
import math
from pathlib import Path
import re
import subprocess
from .audit import hash_value,require,strict_json
from .metrics_query import validate_metric_request
from .metrics_sql import ROLE,metadata_probe_sql

CONFIG=set('docker endpoint daemon_id container_id image_id database database_user view_sha256'.split())
FLAGS=set('superuser create_db create_role replication bypass_rls inherit login raw_privileges'.split())
TASK_FIELDS=set('id status task_type batch_task_id chapter_seq created_at updated_at'.split())
RUN_FIELDS=set('id task_id node model_id input_tokens output_tokens cost_est duration_ms created_at observation_collision provenance measurement'.split())
ENV={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','DOCKER_CONFIG':'/nonexistent'}


class PsqlMetricsReader:
    def __init__(self,config,run=None):
        require(isinstance(config,dict) and set(config)==CONFIG,'fixed metadata source config required')
        require(isinstance(config['docker'],str) and Path(config['docker']).is_absolute() and '..' not in Path(config['docker']).parts)
        require(isinstance(config['endpoint'],str) and re.fullmatch(r'unix:///[^\s?,#\x00]+',config['endpoint']))
        require(isinstance(config['daemon_id'],str) and re.fullmatch('[A-Za-z0-9:_-]{1,128}',config['daemon_id']))
        require(hash_value(config['container_id']) and isinstance(config['image_id'],str) and re.fullmatch('sha256:[0-9a-f]{64}',config['image_id']) and hash_value(config['view_sha256']))
        require(all(isinstance(config[k],str) and re.fullmatch('[a-z_][a-z0-9_]{0,62}',config[k]) for k in ('database','database_user')))
        if run is None:require(Path(config['docker']).is_file(),'existing Docker client required')
        self.config=dict(config);self.run=run or subprocess.run

    def _call(self,*args,input=None):
        command=[self.config['docker'],'--host',self.config['endpoint'],*args]
        try:result=self.run(command,input=input,capture_output=True,timeout=10,env=dict(ENV),shell=False)
        except (OSError,subprocess.TimeoutExpired) as error:raise ValueError('metadata transport unavailable') from error
        require(type(result.returncode) is int and result.returncode==0 and isinstance(result.stdout,bytes) and isinstance(result.stderr,bytes),'metadata transport failed')
        require(len(result.stdout)+len(result.stderr)<=4194304,'metadata output exceeds byte bound')
        return result.stdout

    def _parameters(self,request):
        validate_metric_request(request)
        require(set(request)=={'source','sql','params','read_only','timeout_ms'},'strict metric query envelope required')
        params=request['params'];threads=set(re.findall(r':(thread_\d+)',request['sql']))
        require(isinstance(params,dict) and set(params)=={'start','end','limit','offset'}|threads,'unexpected metric parameters')
        for key in ('start','end'):
            value=params[key];require(isinstance(value,datetime) and value.tzinfo is not None and value.utcoffset() is not None,'aware metric window required')
        require(params['start']<params['end'])
        require(type(params['limit']) is int and 1<=params['limit']<=500 and type(params['offset']) is int and 0<=params['offset']<=500,'bounded metric page required')
        require(all(isinstance(params[k],str) and 0<len(params[k])<=256 and '\0' not in params[k] for k in threads),'bounded task identifiers required')
        return params

    def __call__(self,request):
        params=self._parameters(request);c=self.config
        require(self._call('info','--format','{{.ID}}').decode().strip()==c['daemon_id'],'metadata daemon changed')
        template='{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}}}'
        source=strict_json(self._call('inspect','--format',template,c['container_id']))
        require(source==dict(id=c['container_id'],image=c['image_id'],running=True),'metadata container changed')
        def placeholder(match):
            key=match.group(1)
            return ":'"+key+"'"+('::integer' if key in ('limit','offset') else '::timestamptz' if key in ('start','end') else '')
        sql=re.sub(r':([a-z_][a-z_0-9]*)',placeholder,request['sql'])
        query=f"BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSET LOCAL ROLE {ROLE};\nSET LOCAL search_path=pi_metrics,pg_catalog;\nSET LOCAL statement_timeout={request['timeout_ms']};\nSET LOCAL work_mem='8MB';\n{metadata_probe_sql()}\nSELECT coalesce(json_agg(row_to_json(q)),'[]'::json) FROM ({sql}) q;\nROLLBACK;\n"
        args=['exec','-i',c['container_id'],'env','-i','PATH=/usr/local/bin:/usr/bin:/bin','psql','-X','--no-psqlrc','-A','-t','-q','-h','/var/run/postgresql','-U',c['database_user'],'-d',c['database'],'--set=ON_ERROR_STOP=1']
        for key,value in sorted(params.items()):args.extend(('-v',key+'='+(value.isoformat() if isinstance(value,datetime) else str(value))))
        lines=[line for line in self._call(*args,input=query.encode()).splitlines() if line.strip()]
        require(len(lines)==2,'missing or ambiguous metric result')
        meta,rows=map(strict_json,lines)
        expected=FLAGS|{'role','readonly','memberships','view_count','view_sha256'}
        require(isinstance(meta,dict) and set(meta)==expected and all(meta[k] is False for k in FLAGS)
            and meta['role']==ROLE and meta['readonly']=='on' and type(meta['memberships']) is int and meta['memberships']==0
            and type(meta['view_count']) is int and meta['view_count']==2 and meta['view_sha256']==c['view_sha256'],'unsafe or changed metric source role/view')
        require(isinstance(rows,list) and len(rows)<=params['limit'],'metric result exceeds page bound')
        expected=TASK_FIELDS if request['source']=='tasks' else RUN_FIELDS
        for row in rows:
            require(isinstance(row,dict) and set(row)==expected,'unexpected metric row projection')
            for key in ('created_at','updated_at'):
                if key not in row or row[key] is None:continue
                require(isinstance(row[key],str),'invalid metric timestamp')
                try:value=datetime.fromisoformat(row[key])
                except ValueError:raise ValueError('invalid metric timestamp') from None
                require(value.tzinfo is not None and value.utcoffset() is not None,'aware source time required');row[key]=value
            for key in ('input_tokens','output_tokens','duration_ms','chapter_seq'):
                if key in row:require(row[key] is None or type(row[key]) is int and row[key]>=0,'invalid metric count')
            if 'cost_est' in row:require(row['cost_est'] is None or type(row['cost_est']) in (int,float) and math.isfinite(row['cost_est']) and row['cost_est']>=0,'invalid source cost')
        return rows
