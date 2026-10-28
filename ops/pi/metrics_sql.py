"""Host-owned PostgreSQL16 metadata view/role contract. No product-row writes."""
ROLE='myink_pi_metrics'


def _scalar(group,key,kind='string',maximum=128):
    value=f"p.{group}->'{key}'"
    return f"CASE WHEN jsonb_typeof({value})='{kind}' AND octet_length(({value})::text)<={maximum} THEN {value} ELSE NULL END"


def _images():
    value="p.run_provenance->'image_ids'"
    return f"""CASE WHEN jsonb_typeof({value})='object' AND octet_length(({value})::text)<=2048
    THEN CASE WHEN (SELECT count(*) FROM jsonb_each_text({value}))<=8 AND NOT EXISTS
    (SELECT 1 FROM jsonb_each_text({value}) AS e WHERE e.key !~ '^[A-Za-z0-9_.-]{{1,80}}$' OR e.value !~ '^sha256:[0-9a-f]{{64}}$')
    THEN {value} ELSE NULL END ELSE NULL END"""


def metadata_probe_sql():
    # Fingerprint includes actual canonical definitions and security options.
    views="""SELECT c.oid,c.relname,c.reloptions FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='pi_metrics' AND c.relname IN ('tasks','agent_runs') AND c.relkind='v'
        AND pg_get_userbyid(c.relowner)=session_user"""
    return f"""SET LOCAL search_path=pi_metrics,pg_catalog;
SELECT json_build_object('role',current_user,'superuser',r.rolsuper,'create_db',r.rolcreatedb,
    'create_role',r.rolcreaterole,'replication',r.rolreplication,'bypass_rls',r.rolbypassrls,'inherit',r.rolinherit,'login',r.rolcanlogin,
    'readonly',current_setting('transaction_read_only'),'memberships',(SELECT count(*) FROM pg_auth_members WHERE member=r.oid),
    'raw_privileges',EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
    AND c.relkind IN ('r','v','p','m') AND has_table_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))
    OR EXISTS(SELECT 1 FROM information_schema.role_table_grants WHERE grantee=current_user AND table_schema NOT IN ('pg_catalog','information_schema')
    AND NOT (table_schema='pi_metrics' AND table_name IN ('tasks','agent_runs') AND privilege_type='SELECT')),
    'view_count',(SELECT count(*) FROM ({views}) v),
    'view_sha256',(SELECT encode(sha256(convert_to(string_agg(v.relname||E'\\n'||pg_get_viewdef(v.oid,true)||E'\\n'||coalesce(array_to_string(v.reloptions,','),'')||E'\\n'||(SELECT string_agg(a.attname||':'||format_type(a.atttypid,a.atttypmod),',' ORDER BY a.attnum) FROM pg_attribute a WHERE a.attrelid=v.oid AND a.attnum>0 AND NOT a.attisdropped),E'\\n' ORDER BY v.relname),'UTF8')),'hex') FROM ({views}) v))
    FROM pg_roles r WHERE r.rolname=current_user;"""


def metadata_bootstrap_sql():
    provenance=[]
    for key in ('deployment_id','owner','schema_id','config_id','prompt_id','rubric_id','data_id','commit_sha'):
        provenance.extend((repr(key),_scalar('run_provenance',key)))
    generation="p.run_provenance->'generation'"
    provenance.extend(("'generation'",f"CASE WHEN jsonb_typeof({generation})='number' AND ({generation})::text ~ '^[1-9][0-9]{{0,9}}$' THEN {generation} ELSE NULL END","'image_ids'",_images()))
    measurement=[]
    for key,kind,size in (('kind','string',32),('zero_cost','boolean',5),('cost','boolean',5),('latency','boolean',5),('quality_score','number',32),('quality_rubric_id','string',128),('pricing_id','string',128)):
        measurement.extend((repr(key),_scalar('measurement',key,kind,size)))
    return f"""BEGIN;
CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
CREATE SCHEMA pi_metrics;
REVOKE ALL ON SCHEMA pi_metrics FROM PUBLIC;
CREATE VIEW pi_metrics.tasks WITH (security_barrier=true) AS SELECT id,
CASE WHEN octet_length(status)<=128 THEN status ELSE NULL END AS status,
CASE WHEN octet_length(task_type)<=128 THEN task_type ELSE NULL END AS task_type,
batch_task_id,chapter_seq,created_at,updated_at FROM public.tasks;
CREATE VIEW pi_metrics.agent_runs WITH (security_barrier=true) AS SELECT a.id,
CASE WHEN octet_length(a.task_id)<=256 THEN a.task_id ELSE NULL END AS task_id,
CASE WHEN octet_length(a.node)<=128 THEN a.node ELSE NULL END AS node,
CASE WHEN octet_length(a.model_id)<=128 THEN a.model_id ELSE NULL END AS model_id,
a.input_tokens,a.output_tokens,a.cost_est,a.duration_ms,a.created_at,
json_build_object('run_provenance',json_build_object({','.join(provenance)}),
'measurement',json_build_object({','.join(measurement)}),
'observation_collision',CASE WHEN jsonb_typeof(p.observation_collision)='boolean' THEN p.observation_collision ELSE NULL END) AS detail
FROM public.agent_runs a LEFT JOIN LATERAL jsonb_to_record(CASE WHEN jsonb_typeof(a.detail::jsonb)='object' THEN a.detail::jsonb ELSE '{{}}'::jsonb END)
AS p(run_provenance jsonb,measurement jsonb,observation_collision jsonb) ON true;
GRANT USAGE ON SCHEMA pi_metrics TO {ROLE};
GRANT SELECT ON pi_metrics.tasks, pi_metrics.agent_runs TO {ROLE};
ALTER ROLE {ROLE} SET default_transaction_read_only=on;
ALTER ROLE {ROLE} SET statement_timeout='5s';
ALTER ROLE {ROLE} SET search_path=pi_metrics,pg_catalog;
SET LOCAL ROLE {ROLE};
{metadata_probe_sql()}
COMMIT;
"""
