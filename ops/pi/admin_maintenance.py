"""Short publication fence over the existing PostgreSQL maintenance row.

No new task/fee manager, retries or automatic reopening after an unknown result.
"""
from datetime import timedelta
from .audit import encoded, require, strict_json, utc
from .nightly_deployment import _run
from .product_commands import _write

FIELDS=set('id epoch deployment_id generation owner image_ids deadline admission_closed consumer_blocked'.split())
IDENTITY=('deployment_id','generation','owner','image_ids')


def literal(value):return "'"+str(value).replace("'","''")+"'"


class Maintenance:
    def __init__(self, commands):
        self.commands=commands
        ids=_run(commands,['ps','-q','--no-trunc','--filter','label=com.docker.compose.project=myink','--filter','label=com.docker.compose.service=myink-pg']).decode().split()
        require(len(ids)==1,'original PG maintenance source required');self.container=ids[0]

    def query(self, sql):
        body='BEGIN;SET LOCAL lock_timeout=3000;SET LOCAL statement_timeout=5000;'+sql+';COMMIT;'
        return strict_json(_run(self.commands,['exec',self.container,'psql','-X','-q','-A','-t','-w','-U','myink','-d','myink','-v','ON_ERROR_STOP=1','-c',body],timeout=15))

    def read(self):
        row=self.query('SELECT row_to_json(m) FROM public.maintenance_control m WHERE id=1')
        require(isinstance(row,dict) and set(row)==FIELDS and type(row['id']) is int and row['id']==1 and type(row['generation']) is int and row['generation']>=0 and type(row['admission_closed']) is bool and type(row['consumer_blocked']) is bool,'complete original maintenance row required')
        return row

    def opened(self, identity):
        row=self.read();require(all(row[k]==identity[k] for k in IDENTITY) and not row['admission_closed'] and not row['consumer_blocked'],'original open deployment owner required');return row

    def quiet(self):
        row=self.query("SELECT json_build_object('active_tasks',(SELECT count(*) FROM public.tasks WHERE status IN ('queued','running')),'executions',(SELECT count(*) FROM public.maintenance_executions WHERE owner_token IS NOT NULL OR json_array_length(active_nodes)>0),'pending_admissions',(SELECT count(*) FROM public.admission_intents WHERE gate_state IN ('pending','unknown') OR publication_state IN ('pending','unknown')),'pending_handoffs',(SELECT count(*) FROM public.queue_handoffs WHERE state IN ('pending','unknown'))) ")
        require(isinstance(row,dict) and set(row)=={'active_tasks','executions','pending_admissions','pending_handoffs'} and all(type(v) is int and v==0 for v in row.values()),'business execution or publication remains in flight')

    def change(self, before, after):
        # Full-row CAS shares the same row lock as business admission/claims.
        desired=literal(encoded(after).decode());expected=literal(encoded(before).decode())
        columns=['epoch','deployment_id','generation','owner','image_ids','deadline','admission_closed','consumer_blocked']
        casts={'generation':'bigint','image_ids':'json','deadline':'timestamptz','admission_closed':'boolean','consumer_blocked':'boolean'}
        updates=[key+'=(d.value->>'+literal(key)+')::'+casts[key] if key in casts and key!='image_ids' else key+'=(d.value->'+literal(key)+')::json' if key=='image_ids' else key+'=d.value->>'+literal(key) for key in columns]
        result=self.query('WITH desired AS (SELECT '+desired+'::jsonb AS value) UPDATE public.maintenance_control m SET '+','.join(updates)+' FROM desired d WHERE m.id=1 AND to_jsonb(m)='+expected+'::jsonb RETURNING row_to_json(m)')
        require(result==after and self.read()==after,'maintenance owner transition unconfirmed')
        return after

    def close(self, before, cycle, now, root):
        require(self.read()==before,'maintenance owner changed before closure')
        self.quiet()
        deadline=utc(now)+timedelta(minutes=10)
        # PostgreSQL row_to_json trims fractional trailing zeroes. Keep the
        # intended value in that exact form so full-row confirmation is stable.
        fraction=f'.{deadline.microsecond:06d}'.rstrip('0') if deadline.microsecond else ''
        deadline=deadline.strftime('%Y-%m-%dT%H:%M:%S')+fraction+'+00:00'
        closed=dict(before,epoch='pi-console-'+cycle,deadline=deadline,admission_closed=True,consumer_blocked=True)
        _write(root/'maintenance-intent.json',dict(previous=before,closed=closed))
        self.change(before,closed);_write(root/'maintenance-closed.json',closed)
        # New snapshot after the committed closure sees admissions which held a
        # business FOR SHARE lock before the barrier acquired its exclusive lock.
        self.quiet();return closed

    def adopt(self, closed, identity, root):
        current=dict(closed,**{k:identity[k] for k in IDENTITY})
        self.change(closed,current);_write(root/'maintenance-candidate.json',current);return current

    def reopen(self, closed, root):
        current=dict(closed,deadline=None,admission_closed=False,consumer_blocked=False)
        self.change(closed,current);_write(root/'maintenance-open.json',current);return current
