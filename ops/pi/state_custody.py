"""Trusted-host single-owner budget custody; never transports state or credentials."""
import hashlib
import json
import platform
import re
import subprocess
from pathlib import Path

from .ledger import Ledger, LedgerBlocked, _json


class CustodyDenied(ValueError):
    """Custody cannot safely authorize this host/path or transition."""


_KIND='state-custody'
_FIELDS={'schema_version','phase','transfer_id','source','destination',
         'authorization_reference','parent_sha256','input_snapshot_sha256','operations_sha256'}
_HEX=re.compile(r'[0-9a-f]{64}')


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _hex(value):
    return isinstance(value,str) and _HEX.fullmatch(value) is not None


def _native_identity(system,raw):
    if not isinstance(raw,str):raise CustodyDenied('custody native host identity unavailable')
    if system=='Linux':
        identity=raw.strip()
        if not re.fullmatch(r'[0-9a-f]{32}',identity) or identity=='0'*32:
            raise CustodyDenied('custody native host identity unavailable')
    elif system=='Darwin':
        matches=re.findall(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]{36})"',raw)
        if len(matches)!=1 or not re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}',matches[0]):
            raise CustodyDenied('custody native host identity unavailable')
        identity=matches[0].lower()
        if identity=='00000000-0000-0000-0000-000000000000':
            raise CustodyDenied('custody native host identity unavailable')
    else:
        raise CustodyDenied('custody unsupported native host')
    return hashlib.sha256(('myink-pi-custody-v1\0'+system+'\0'+identity).encode()).hexdigest()


def native_host_sha256():
    system=platform.system()
    try:
        if system=='Linux':raw=Path('/etc/machine-id').read_text(encoding='ascii')
        elif system=='Darwin':
            raw=subprocess.check_output(['/usr/sbin/ioreg','-rd1','-c','IOPlatformExpertDevice'],text=True,timeout=3)
        else:raise CustodyDenied('custody unsupported native host')
    except (OSError,UnicodeError,subprocess.SubprocessError):
        raise CustodyDenied('custody native host identity unavailable') from None
    return _native_identity(system,raw)


def _binding(value):
    if (not isinstance(value,dict) or set(value)!={'host_sha256','ledger_path'}
            or not _hex(value['host_sha256']) or not isinstance(value['ledger_path'],str)):
        raise CustodyDenied('custody invalid owner binding')
    path=value['ledger_path']
    if (not path or '\0' in path or not Path(path).is_absolute()
            or str(Path(path))!=path or '..' in Path(path).parts):
        raise CustodyDenied('custody canonical absolute ledger path required')
    return dict(value)


def current_binding(path):
    return _binding(dict(host_sha256=native_host_sha256(),ledger_path=str(Path(path).resolve(strict=True))))


def _operations_sha256(connection):
    return _hash([dict(row) for row in connection.execute('SELECT * FROM operations ORDER BY operation_id')])


def _snapshot(connection):
    return _hash(dict(operations_sha256=_operations_sha256(connection),
                      events_sha256=_hash([dict(row) for row in connection.execute('SELECT * FROM events ORDER BY id')])))


def _decode_custody(raw):
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise CustodyDenied('custody duplicate historical field')
            value[key]=item
        return value
    def constant(value):raise CustodyDenied('custody nonfinite historical value')
    try:
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
        if not isinstance(value,dict):raise CustodyDenied('custody invalid historical object')
        _json(value)
        return value
    except (ValueError,TypeError,RecursionError):
        raise CustodyDenied('custody invalid historical JSON') from None


def _reference(value):
    if not isinstance(value,str) or not value.strip() or len(value)>256:
        raise CustodyDenied('custody explicit operator authorization reference required')
    return value


def _transfer(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',value):
        raise CustodyDenied('custody invalid transfer identity')
    return value


def _chain(connection):
    previous=None;seen=set();prefix=[]
    for row in connection.execute('SELECT * FROM events ORDER BY id'):
        if not row['kind'].lower().startswith(_KIND):
            prefix.append(dict(row));continue
        if row['kind']!=_KIND:
            raise CustodyDenied('custody unknown event kind')
        value=_decode_custody(row['payload'])
        if (set(value)!=_FIELDS or type(value['schema_version']) is not int or value['schema_version']!=1
                or value['phase'] not in ('frozen','active') or not _hex(value['input_snapshot_sha256'])
                or not _hex(value['operations_sha256'])):
            raise CustodyDenied('custody invalid event schema')
        _transfer(value['transfer_id']);_reference(value['authorization_reference'])
        _binding(value['source']);_binding(value['destination'])
        if value['source']==value['destination'] or value['parent_sha256']!=(None if previous is None else _hash(previous)):
            raise CustodyDenied('custody invalid event chain')
        expected=_hash(dict(operations_sha256=value['operations_sha256'],events_sha256=_hash(prefix)))
        if value['input_snapshot_sha256']!=expected:
            raise CustodyDenied('custody historical input snapshot mismatch')
        if value['phase']=='frozen':
            if (value['transfer_id'] in seen or (previous is not None
                    and (previous['phase']!='active' or value['source']!=previous['destination']))):
                raise CustodyDenied('custody invalid freeze chain')
            seen.add(value['transfer_id'])
        elif (previous is None or previous['phase']!='frozen'
                or any(value[key]!=previous[key] for key in ('transfer_id','source','destination','operations_sha256'))):
            raise CustodyDenied('custody activation requires frozen transfer snapshot')
        previous=value;prefix.append(dict(row))
    return previous,seen


def _status(connection):
    latest,_=_chain(connection)
    return dict(phase='legacy' if latest is None else latest['phase'],
                transfer_id=None if latest is None else latest['transfer_id'],
                owner=latest['destination'] if latest is not None and latest['phase']=='active' else None,
                destination=None if latest is None else latest['destination'],
                snapshot_sha256=_snapshot(connection))


def status(ledger):
    with ledger.transaction() as connection:
        return dict(_status(connection),current_binding=current_binding(ledger.path))


def guard(connection,path):
    latest,_=_chain(connection)
    if latest is None:return
    if latest['phase']!='active':raise CustodyDenied('custody frozen: model reservation denied')
    if current_binding(path)!=latest['destination']:
        raise CustodyDenied('custody active owner host/path mismatch')


def freeze(ledger,*,transfer_id,destination,authorization_reference):
    transfer_id=_transfer(transfer_id);destination=_binding(destination)
    authorization_reference=_reference(authorization_reference)
    with ledger.transaction() as connection:
        latest,seen=_chain(connection);source=current_binding(ledger.path)
        if latest is not None:guard(connection,ledger.path)
        if transfer_id in seen or destination==source:
            raise CustodyDenied('custody repeated transfer or unchanged destination')
        if connection.execute("SELECT 1 FROM operations WHERE kind='model-attempt' AND status='pending' LIMIT 1").fetchone():
            raise CustodyDenied('custody pending model permit requires settlement')
        value=dict(schema_version=1,phase='frozen',transfer_id=transfer_id,source=source,destination=destination,
                   authorization_reference=authorization_reference,parent_sha256=None if latest is None else _hash(latest),
                   input_snapshot_sha256=_snapshot(connection),operations_sha256=_operations_sha256(connection))
        connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',(_KIND,_json(value)))
        return _status(connection)


def activate(ledger,*,transfer_id,snapshot_sha256,authorization_reference):
    transfer_id=_transfer(transfer_id);authorization_reference=_reference(authorization_reference)
    if not _hex(snapshot_sha256):raise CustodyDenied('custody invalid snapshot digest')
    with ledger.transaction() as connection:
        latest,_=_chain(connection)
        if latest is None or latest['phase']!='frozen' or latest['transfer_id']!=transfer_id:
            raise CustodyDenied('custody activation requires matching frozen transfer')
        if current_binding(ledger.path)!=latest['destination']:
            raise CustodyDenied('custody activation destination mismatch')
        if _operations_sha256(connection)!=latest['operations_sha256']:
            raise CustodyDenied('custody frozen operations snapshot changed')
        if _snapshot(connection)!=snapshot_sha256:
            raise CustodyDenied('custody frozen snapshot changed')
        value=dict(latest,phase='active',authorization_reference=authorization_reference,
                   parent_sha256=_hash(latest),input_snapshot_sha256=snapshot_sha256)
        connection.execute('INSERT INTO events(kind,payload,schema_version) VALUES (?,?,1)',(_KIND,_json(value)))
        return _status(connection)


def main(argv=None):
    import argparse
    import json
    import sys
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger',type=Path,required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('status')
    freezing=commands.add_parser('freeze')
    freezing.add_argument('--transfer-id',required=True)
    freezing.add_argument('--destination',required=True,help='JSON host_sha256 and canonical ledger_path')
    freezing.add_argument('--authorization-reference',required=True)
    activating=commands.add_parser('activate')
    activating.add_argument('--transfer-id',required=True)
    activating.add_argument('--snapshot-sha256',required=True)
    activating.add_argument('--authorization-reference',required=True)
    args=parser.parse_args(argv)
    try:
        ledger=Ledger(args.ledger,existing=True)
        if args.command=='status':result=status(ledger)
        elif args.command=='freeze':
            def pairs(items):
                result={}
                for key,value in items:
                    if key in result:raise CustodyDenied('custody duplicate destination field')
                    result[key]=value
                return result
            destination=json.loads(args.destination,object_pairs_hook=pairs)
            result=freeze(ledger,transfer_id=args.transfer_id,destination=destination,authorization_reference=args.authorization_reference)
        else:
            result=activate(ledger,transfer_id=args.transfer_id,snapshot_sha256=args.snapshot_sha256,authorization_reference=args.authorization_reference)
    except (CustodyDenied,LedgerBlocked,OSError,ValueError):
        print('custody operation refused; state was not authorized',file=sys.stderr)
        return 1
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
