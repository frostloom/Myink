"""Isolated standard-library launcher; imports Pi code only after source verification."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path,PurePosixPath
import re
import stat
import sys


def require(value):
    if not value:raise ValueError('observer runtime integrity check failed')


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def strict(raw):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result);result[key]=value
        return result
    def invalid(_):raise ValueError('invalid runtime number')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def verify_release(root,expected,*,expected_owner=0):
    root=Path(root);require(root.is_absolute() and root.resolve()==root and root.is_dir())
    require(isinstance(expected,str) and re.fullmatch('[0-9a-f]{64}',expected))
    total=0;actual=set()
    for path in [root,*root.rglob('*')]:
        info=path.lstat()
        require(path.resolve()==path and info.st_uid==expected_owner and not stat.S_IMODE(info.st_mode)&0o022)
        require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
        if stat.S_ISREG(info.st_mode):
            require(info.st_nlink==1 and info.st_size<=4194304)
            actual.add(path.relative_to(root).as_posix());total+=info.st_size
        require(len(actual)<=5001 and total<=67108864)
    manifest=strict((root/'manifest.json').read_bytes())
    require(isinstance(manifest,dict) and set(manifest)=={'schema','files','code_sha256','git_commit'} and manifest['schema']=='pi-observer-runtime-v1')
    require(isinstance(manifest['git_commit'],str) and re.fullmatch('[0-9a-f]{40}',manifest['git_commit']))
    files=manifest['files'];require(isinstance(files,dict) and 0<len(files)<=5000 and actual==set(files)|{'manifest.json'})
    require(manifest['code_sha256']==expected and sha256(encoded(files)).hexdigest()==expected)
    for relative,value in files.items():
        require(isinstance(relative,str) and PurePosixPath(relative).as_posix()==relative and not PurePosixPath(relative).is_absolute() and '..' not in PurePosixPath(relative).parts)
        require(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value))
        require(sha256((root/relative).read_bytes()).hexdigest()==value)
    return root/'code'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--config-sha256',required=True)
    parser.add_argument('--component',choices=('observer','followup'),default='observer')
    args=parser.parse_args()
    try:
        root=Path(__file__).resolve().parent
        code=verify_release(root,os.environ.get('PI_OBSERVER_RUNTIME_SHA256'))
        sys.path.insert(0,str(code));sys.dont_write_bytecode=True
        if args.component=='followup':
            from ops.pi.followup import run_due
            result=run_due(args.config,args.config_sha256)
        else:
            from ops.pi.live_observer import observe
            result=observe(Path(args.config),expected_config_sha256=args.config_sha256)
    except Exception as error:
        print(json.dumps(dict(status='blocked',failure_class=type(error).__name__,automatic_execution=False)));return 1
    print(json.dumps(result));return 1 if result['status'] in ('blocked','uncertain','failed') else 0


if __name__=='__main__':raise SystemExit(main())
