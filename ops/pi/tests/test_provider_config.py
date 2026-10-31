"""Synthetic provider settings only. Never read developer CC-Switch/keys."""
from dataclasses import asdict, replace
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3

import pytest

from ops.pi.tests.test_budget import ledger, policy
from ops.pi.tests.test_fee_only_budget import fee_policy, seeded, upgrade
from ops.pi.ledger import _json


def api():
    return importlib.import_module('ops.pi.provider_config')


def config():
    return dict(name='DeepSeek', baseUrl='https://api.deepseek.com/v1', api='openai-completions',
                apiKey='sk-synthetic-only-never-real', models=[dict(id='deepseek-flash')])


def database(tmp_path, settings=None, count=1):
    path = tmp_path / 'cc-switch.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE providers(id TEXT,app_type TEXT,name TEXT,settings_config TEXT)')
        for index in range(count):
            db.execute('INSERT INTO providers VALUES (?,?,?,?)',
                (str(index), 'pi', 'DeepSeek', json.dumps(config() if settings is None else settings)))
        db.execute('INSERT INTO providers VALUES (?,?,?,?)',
            ('unrelated', 'claude', 'Other', json.dumps(dict(apiKey='PRIVATE-OTHER'))))
    return path


def creds():
    return dict(PLATFORM_MODEL_API_KEY='sk-synthetic-only-never-real',
                PLATFORM_MODEL_BASE_URL='https://api.deepseek.com/anthropic',
                PLATFORM_MODEL_NAME='deepseek-flash', PLATFORM_MODEL_PROTOCOL='anthropic')


def test_readonly_unique_pi_deepseek_maps_key_without_touching_switch(tmp_path, monkeypatch):
    path = database(tmp_path);before = path.read_bytes()
    original = sqlite3.connect
    def connect(*args, **kwargs):
        assert args[0].endswith('?mode=ro') and kwargs['uri']
        db = original(*args, **kwargs)
        db.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action in
                          (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE)
                          else sqlite3.SQLITE_OK)
        return db
    monkeypatch.setattr(sqlite3, 'connect', connect)
    assert api().cc_switch_deepseek_credentials(path) == creds()
    assert path.read_bytes() == before


@pytest.mark.parametrize('count', [0,2])
def test_missing_or_ambiguous_provider_refused(tmp_path, count):
    with pytest.raises(ValueError, match='trusted provider configuration invalid'):
        api().cc_switch_deepseek_credentials(database(tmp_path, count=count))


@pytest.mark.parametrize('changes', [dict(baseUrl='https://evil.example'),
    dict(baseUrl='https://api.deepseek.com@evil.example/v1'),dict(api='custom'),
    dict(apiKey='$DEEPSEEK_KEY'),dict(apiKey='$(echo PRIVATE)'),dict(apiKey='!command'),
    dict(apiKey='env:DEEPSEEK_KEY'),dict(apiKey='sk-x\r\nX-Extra: bad'),
    dict(models=[dict(id='deepseek-v4-pro')]),dict(apiKey='')])
def test_untrusted_cc_config_never_executes_or_leaks(tmp_path, changes):
    with pytest.raises(ValueError, match='^trusted provider configuration invalid$') as exc:
        api().cc_switch_deepseek_credentials(database(tmp_path, config() | changes))
    assert 'PRIVATE' not in str(exc.value)


def test_missing_database_not_created(tmp_path):
    path = tmp_path / 'missing.db'
    with pytest.raises(ValueError): api().cc_switch_deepseek_credentials(path)
    assert not path.exists()


@pytest.mark.parametrize('changes', [dict(PLATFORM_MODEL_NAME='other'),
    dict(PLATFORM_MODEL_BASE_URL='https://evil.example'),dict(PLATFORM_MODEL_PROTOCOL='openai'),
    dict(PLATFORM_MODEL_API_KEY='bad\nPRIVATE'),dict(PLATFORM_MODEL_API_KEY='$TOKEN'),
    dict(extra='PRIVATE')])
def test_credentials_bind_policy_before_network(tmp_path, policy, changes):
    p = replace(policy, model='deepseek-flash', base_url='https://api.deepseek.com/anthropic')
    path = tmp_path/'credential.json';path.write_text(json.dumps(creds() | changes))
    with pytest.raises(ValueError, match='^trusted provider configuration invalid$'):
        api().load_credentials(path,p)


def test_credential_duplicate_keys_refused(tmp_path, policy):
    path=tmp_path/'bad.json';path.write_text('{"PLATFORM_MODEL_API_KEY":"a","PLATFORM_MODEL_API_KEY":"PRIVATE"}')
    with pytest.raises(ValueError): api().load_credentials(path,policy)


def test_preflight_binds_credentials_without_echoing_key(tmp_path, ledger, policy):
    from ops.pi.analysis_budget import _scope_identity
    from ops.pi.analysis_preflight import audit
    seeded(ledger);upgrade(ledger)
    p=replace(fee_policy(policy),model='deepseek-flash',base_url='https://api.deepseek.com/anthropic')
    path=tmp_path/'policy-current.json';path.write_text(json.dumps(asdict(p)))
    secret=tmp_path/'credential.json';secret.write_text(json.dumps(creds()))
    with ledger.transaction() as db:scope=_scope_identity(db)
    args=dict(expected_scope_sha256=scope,expected_policy_sha256=hashlib.sha256(_json(asdict(p)).encode()).hexdigest())
    result=audit(ledger.path,path,credential_path=secret,**args)
    assert result['credentials_checked'] is True and result['paid_admission'] is False
    assert 'sk-synthetic' not in json.dumps(result)
    secret.write_text(json.dumps(creds() | dict(PLATFORM_MODEL_NAME='other')))
    from ops.pi.ledger import LedgerBlocked
    with pytest.raises(LedgerBlocked): audit(ledger.path,path,credential_path=secret,**args)


def test_new_model_default_and_historical_freeze_are_explicit(tmp_path):
    from ops.pi.analysis_trial import GROUPS, freeze_contract_trial
    from ops.pi.analysis_execution import prepare_contract_slots
    from ops.pi.tests.test_writing_analysis import fixture
    view,report=fixture()
    assert api().DEFAULT_MODEL=='deepseek-flash'
    fresh=freeze_contract_trial(view,report)
    assert fresh['model']=='deepseek-flash'
    old=freeze_contract_trial(view,report,model='deepseek-v4.1-flash')
    assert old['model']=='deepseek-v4.1-flash' and old['freeze_sha256']!=fresh['freeze_sha256']
    slots=prepare_contract_slots({g:view for g in GROUPS},report,model='deepseek-flash',cwd=tmp_path)
    assert len(slots)==30 and all(s['request']['model']=='deepseek-flash' for s in slots)
    from ops.pi.analysis_execution import verify_contract_request
    with pytest.raises(ValueError):
        verify_contract_request(slots[0]['request'] | dict(model='deepseek-v4.1-flash'),slots[0])
