"""A restored API uses private effective settings and a real main process."""
from copy import deepcopy
import importlib.util
import pytest
from ops.pi.audit import digest
from test_product_runtime_snapshot import sample
from test_product_activation import activation_inputs,bootstrap_case,context


def api():
    assert importlib.util.find_spec('ops.pi.product_restored_api'),'missing restored main API process'
    from ops.pi import product_restored_api
    return product_restored_api


def inputs(data):
    from ops.pi.product_runtime_snapshot import capture,authentication
    plan,c,ctx,n,v,rows=sample(data)
    snapshot=capture(plan,c,ctx,'PRE',rows,n,[v])
    auth=authentication(snapshot,digest(plan),'PRE','pi_restore_'+'a'*32,'target_only_password_1234567890123456')
    return plan,snapshot,auth


def test_restored_api_retains_settings_with_only_fixed_isolation_overrides(activation_inputs):
    plan,snapshot,auth=inputs(activation_inputs)
    row=next(v for v in snapshot['containers'] if v['service']=='api')
    row['config']['Env']+=['JWT_SECRET=synthetic-at-least-thirty-two-byte-secret','APP_ENV=prod','CONTEXT_BUDGET=12345','PLATFORM_MODEL_API_KEY=private-provider','LANGFUSE_SECRET_KEY=private-telemetry']
    result=api().api_environment(snapshot,auth)
    assert result['DATABASE_URL']==auth['app_url'] and result['ADMIN_DATABASE_URL']==auth['report_url']
    assert result['APP_ENV']=='prod' and result['CONTEXT_BUDGET']=='12345'
    assert result['MODEL_CREDENTIAL_KEY']=='synthetic-private-value'
    assert result['API_HOST']=='127.0.0.1' and result['API_PORT']=='8100'
    assert result['FEEDBACK_DIR']=='/data/feedback' and result['PGOPTIONS']=='-c default_transaction_read_only=on -c statement_timeout=10000'
    assert result['REDIS_URL']=='redis://:synthetic@127.0.0.1:6379/0'
    assert result['AMQP_URL']=='amqp://myink:synthetic@127.0.0.1:5672/'
    assert 'PLATFORM_MODEL_API_KEY' not in result and 'LANGFUSE_SECRET_KEY' not in result
    assert auth['admin_url'] not in result.values()


@pytest.mark.parametrize('fault',['database','report','command','root','interpreter','external-redis','external-amqp','redis-query','amqp-query','missing-api'])
def test_restored_main_api_rejects_unbounded_runtime(activation_inputs,fault):
    _,snapshot,auth=inputs(activation_inputs);row=next(v for v in snapshot['containers'] if v['service']=='api')
    if fault=='database':auth['app_url']='postgresql+psycopg://myink_app:synthetic@external.invalid/myink'
    elif fault=='report':auth['report_url']=auth['admin_url']
    elif fault=='command':row['config']['Cmd']=['sh','-c','arbitrary']
    elif fault=='root':row['config']['User']='0'
    elif fault=='interpreter':row['config']['Env'].append('PYTHONPATH=/unapproved')
    elif fault=='missing-api':snapshot['containers'].remove(row)
    else:
        key='REDIS_URL' if 'redis' in fault else 'AMQP_URL'
        value=('redis://:synthetic@external.invalid/0' if fault=='external-redis' else 'amqp://myink:synthetic@external.invalid/' if fault=='external-amqp' else 'redis://:synthetic@myink-redis/0?bad=1' if fault=='redis-query' else 'amqp://myink:synthetic@myink-rabbitmq/?bad=1')
        row['config']['Env']=[entry for entry in row['config']['Env'] if not entry.startswith(key+'=')]+[key+'='+value]
    with pytest.raises(ValueError):api().api_environment(snapshot,auth)
