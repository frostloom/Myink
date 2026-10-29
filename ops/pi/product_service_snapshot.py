"""Private fixed infrastructure material and an atomic Redis data census."""
from copy import deepcopy
from urllib.parse import urlsplit,unquote
from .audit import digest,encoded,require,hash_value
from .product_activation import environment
from .product_runtime_snapshot import connection_settings

REDIS_LUA=r"""
local function hex(s) return (s:gsub('.',function(c) return string.format('%02x',string.byte(c)) end)) end
local cursor='0';local rows={};local seen={};local bytes=0;local scans=0
repeat
 local page=redis.call('SCAN',cursor,'COUNT',100);cursor=page[1];scans=scans+1
 if scans>1000 then return redis.error_reply('bounded_redis_census') end
 for _,key in ipairs(page[2]) do
  if not seen[key] and string.sub(key,1,16)~='queue:heartbeat:' then
   seen[key]=true;local value=redis.call('DUMP',key)
   if value then
    bytes=bytes+#key+#value;if #rows>=10000 or bytes>8388608 then return redis.error_reply('bounded_redis_material') end
    local expires=redis.call('PEXPIRETIME',key)
    table.insert(rows,{key_hex=hex(key),dump_hex=hex(value),expires_at_ms=expires<0 and cjson.null or expires})
   end
  end
 end
until cursor=='0'
local now=redis.call('TIME');local encoded={}
for _,row in ipairs(rows) do table.insert(encoded,cjson.encode(row)) end
return '{"observed_at_ms":'..string.format('%.0f',tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000))..',"keys":['..table.concat(encoded,',')..']}'
"""


def _redis(value):
    require(isinstance(value,dict) and set(value)=={'observed_at_ms','keys'} and type(value['observed_at_ms']) is int and value['observed_at_ms']>0 and isinstance(value['keys'],list) and len(value['keys'])<=10000,'bounded timed Redis snapshot required');rows={}
    for v in value['keys']:
        require(isinstance(v,dict) and set(v)=={'key_hex','dump_hex','expires_at_ms'},'closed Redis row required')
        for key in ('key_hex','dump_hex'):
            s=v[key];require(isinstance(s,str) and len(s)%2==0 and s and all(c in '0123456789abcdef' for c in s),'Redis binary hex required')
        require(v['key_hex'] not in rows and (v['expires_at_ms'] is None or type(v['expires_at_ms']) is int and v['expires_at_ms']>0),'unique Redis expiry required');rows[v['key_hex']]=v
    require(sum(len(v['key_hex'])+len(v['dump_hex']) for v in rows.values())<=16777216,'bounded Redis contents required');return rows


def same_redis(before,after):
    first=_redis(before);last=_redis(after);require(after['observed_at_ms']>=before['observed_at_ms'],'Redis observation clock reversed')
    expected={k:v for k,v in first.items() if v['expires_at_ms'] is None or v['expires_at_ms']>after['observed_at_ms']}
    actual={k:v for k,v in last.items() if v['expires_at_ms'] is None or v['expires_at_ms']>after['observed_at_ms']}
    require(actual==expected,'Redis protected state changed beyond natural expiry')


def unpublished(ports):
    return isinstance(ports,dict) and all(value is None or value==[] for value in ports.values())


def capture(plan,runtime,rows,ingress):
    connection_settings(runtime);require(runtime['plan_sha256']==digest(plan),'service/runtime plan differs')
    expected={v['id']:v for v in plan['legacy']['containers'] if v['service'] in ('redis','rabbitmq','frontend')}
    require(isinstance(rows,list) and len(rows)==3 and {v['Id'] for v in rows}==set(expected),'complete original infrastructure required');services={}
    for row in rows:
        source=expected[row['Id']];require(row['Image']==source['image_id'],'original service image differs')
        environment(row['Config']['Env']);services[source['service']]=deepcopy(dict(id=row['Id'],image_id=row['Image'],config=row['Config'],host_config=row['HostConfig'],mounts=row['Mounts']))
    redis=environment(services['redis']['config']['Env']);rabbit=environment(services['rabbitmq']['config']['Env'])
    for row in runtime['containers']:
        values=environment(row['config']['Env']);ru=urlsplit(values.get('REDIS_URL',''));au=urlsplit(values.get('AMQP_URL',''))
        require(ru.scheme=='redis' and ru.hostname in ('myink-redis','localhost','127.0.0.1') and unquote(ru.password or '')==redis.get('REDIS_PASSWORD') and redis.get('REDIS_PASSWORD'),'effective Redis credentials disagree')
        require(au.scheme=='amqp' and au.hostname in ('myink-rabbitmq','localhost','127.0.0.1') and au.username==rabbit.get('RABBITMQ_DEFAULT_USER')=='myink' and unquote(au.password or '')==rabbit.get('RABBITMQ_DEFAULT_PASS') and rabbit.get('RABBITMQ_DEFAULT_PASS'),'effective Rabbit credentials disagree')
    require(isinstance(ingress,dict) and len(encoded(ingress))<=1048576,'bounded original ingress required')
    result=dict(schema='pi-effective-services-v1',plan_sha256=digest(plan),runtime_sha256=digest(runtime),phase=runtime['phase'],services=services,ingress=deepcopy(ingress))
    require(len(encoded(result))<=2097152,'bounded private infrastructure required');return result


def isolated_ingress(original,certificates):
    require(isinstance(original,dict) and isinstance(certificates,list),'fixed isolated ingress input required');v=deepcopy(original)
    require(set(v.get('apps',{}))<= {'http','tls'} and isinstance(v.get('apps',{}).get('http',{}).get('servers'),dict),'known HTTP/TLS configuration required')
    servers=v['apps']['http']['servers'];require(0<len(servers)<=4,'bounded ingress servers required');ports=set();tls=False
    for server in servers.values():
        require(isinstance(server,dict) and isinstance(server.get('listen'),list) and server['listen'],'fixed ingress listeners required');mapped=[]
        for listen in server['listen']:
            require(listen in (':80',':443','0.0.0.0:80','0.0.0.0:443'),'unreviewed ingress bind')
            port=8443 if listen.endswith(':443') else 8080;require(port not in ports,'isolated listener collision');ports.add(port);mapped.append('127.0.0.1:'+str(port));tls|=port==8443
        server['listen']=mapped;server['automatic_https']={'disable':True}
        if '127.0.0.1:8443' in mapped:server.setdefault('tls_connection_policies',[{}])
    if tls:
        require(certificates,'restored HTTPS certificates required')
        v['apps']['tls']={'certificates':{'load_files':certificates}}
    else:v['apps'].pop('tls',None)
    v['admin']={'listen':'127.0.0.1:2019'}
    def walk(value):
        if isinstance(value,dict):
            if 'dial' in value:
                require(value['dial']=='myink-api:8100','unreviewed ingress upstream');value['dial']='127.0.0.1:8100'
            if 'writer' in value:require(isinstance(value['writer'],dict) and value['writer'].get('output') in ('stdout','stderr','discard'),'external log writer rejected')
            for item in value.values():walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    walk(v);return v
