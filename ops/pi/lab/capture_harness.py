"""SANDBOX ONLY. Candidate interpreter emits untrusted data, never pass authority.

Fixed host invocation: python -I -B capture_harness.py SOURCE REQUEST_JSON.
Root must provide the independently accepted UID65533 resource/mount envelope.
Do not run this interpreter as root or import it into the trusted oracle process.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys


def main():
    if not hasattr(os,'geteuid') or os.geteuid()!=65533 or len(sys.argv)!=3:
        raise SystemExit('fixed checker UID and two host-created paths required')
    source, request_path=map(Path,sys.argv[1:])
    if not source.is_absolute() or not request_path.is_absolute() or source.is_symlink() or request_path.is_symlink():
        raise SystemExit('fixed absolute regular inputs required')
    if source.stat().st_size>65536 or request_path.stat().st_size>4*1024**2:
        raise SystemExit('input cap exceeded')
    request=json.loads(request_path.read_bytes())
    if set(request)!={'cases'} or not isinstance(request['cases'],list) or not 1<=len(request['cases'])<=64:
        raise SystemExit('fixed bounded case request required')
    spec=importlib.util.spec_from_file_location('capture_candidate',source)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    rows=[]
    for case in request['cases']:
        if set(case)-{'id','method','input','max_bytes','special'} or case['method'] not in ('capture','capture_detail'):
            raise SystemExit('invalid fixed case')
        value=copy.deepcopy(case['input'])
        if case.get('special')=='cycle': value['self']=value
        elif case.get('special')=='unknown': value=object()
        result=(module.capture_detail(value) if case['method']=='capture_detail' else
                module.capture(value,max_bytes=case['max_bytes']))
        after=case['input'] if case.get('special') else value
        rows.append(dict(id=case['id'],result=result,input_after=after))
    raw=json.dumps({'rows':rows},ensure_ascii=True,allow_nan=False).encode('ascii')
    if len(raw)>4*1024**2: raise SystemExit('output cap exceeded')
    sys.stdout.buffer.write(raw)


if __name__=='__main__': main()
