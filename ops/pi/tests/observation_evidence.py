"""Reproduce four real checker branches from explicitly synthetic observations.

No credentials or provider calls. All observations/rules are host fixtures.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
from ops.pi.development_inputs import file_hash,path,tree_hash,read_json
from ops.pi.development_launcher import require
from ops.pi.observations import freeze
from ops.pi.proposals import execute


def run(output,environment):
    root=path(output);require(not root.exists() and root.parent.is_dir() and stat.S_IMODE(root.parent.stat().st_mode)==0o700,'new private output required')
    os.umask(0o077);root.mkdir(mode=0o700)
    def write(p,v):
        p.write_text(v if isinstance(v,str) else json.dumps(v,indent=2));p.chmod(0o600);return p
    fixtures=Path(__file__).parent/'fixtures/manager_benchmarks';sources=[];rules=[]
    for name in ('nfc','casefold','green','error'):
        b=root/name;b.mkdir(mode=0o700);source=b/'input';(source/'src').mkdir(parents=True)
        fixture=fixtures/('casefold' if name=='casefold' else 'nfc')
        text=(fixture/'managed_names.py').read_text()
        if name=='green':text="import unicodedata\ndef normalize_name(value):\n    return unicodedata.normalize('NFC',value.strip())\n"
        if name=='error':text="def normalize_name(value):\n    raise RuntimeError('synthetic checker error branch')\n"
        write(source/'src/managed_names.py',text);gold=write(b/'gold.py',(fixture/'fixed.py').read_text())
        recipe=write(b/'package.json',dict(schema='pi-task-package-v1',task_id='observation-'+name,problem='Synthetic observed '+name+' branch; fixed Unicode input/output checks. No product adoption.',source_path=str(source),source_sha256=tree_hash(source),test_path=str(gold),test_sha256=file_hash(gold),files=['src/managed_names.py'],root=str(b/'package')))
        extra='<testcase classname="Case" name="good"/><testcase classname="Case" name="skip"><skipped/></testcase><testcase classname="Case" name="unmapped"><failure/></testcase>' if name=='nfc' else ''
        xml=write(b/'seed.xml','<testsuite><testcase classname="Case" name="bad"><failure message="synthetic seed only"/></testcase>'+extra+'</testsuite>')
        sources.append(dict(source_id=name,kind='junit',path=str(xml),sha256=file_hash(xml),source_sha256=tree_hash(source)))
        rule=dict(rule_id=name,source_id=name,observation_id='Case::bad',package_request_path=str(recipe),package_request_sha256=file_hash(recipe),priority=4,trigger=dict(kind='failure'));rules.append(rule)
        if name=='nfc':
            rules.extend([dict(rule,rule_id='duplicate',priority=8),dict(rule,rule_id='healthy',observation_id='Case::good'),dict(rule,rule_id='skipped',observation_id='Case::skip')])
            metric=write(b/'metrics.json',dict(evidence_domain='synthetic',availability='unknown',confounders=[],measurements=dict(error_rate=dict(value=None,availability='unknown',samples=0,direction='lower'),latency=dict(value=None,availability='unknown',samples=0,direction='lower'))))
            sources.append(dict(source_id='metrics',kind='metrics',path=str(metric),sha256=file_hash(metric),source_sha256=tree_hash(source)))
            rules.append(dict(rule,rule_id='unknown-metric',source_id='metrics',observation_id='metric:error_rate',trigger=dict(kind='metric_threshold',operator='gt',threshold=2,minimum_samples=5)))
    intake=write(root/'intake.json',dict(schema='pi-observation-intake-v1',batch_id='synthetic-observations',sources=sources,root=str(root/'observations')))
    observations=freeze(intake)
    request=write(root/'proposal-request.json',dict(schema='pi-proposal-batch-v1',batch_id='synthetic-proposals',observation_path=observations['report_path'],observation_sha256=observations['report_sha256'],rules=rules,root=str(root/'proposals'),baseline_environment=environment,max_baselines=4,deadline_seconds=600))
    result=execute(request);r=read_json(result['report_path'])
    return dict(evidence_domain='synthetic',checker_execution='ACTUAL',provider_calls=0,observations=observations,proposals=result,states={p['task_id']:p['state'] for p in r['proposals']})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    for key in ('docker','endpoint','daemon-id','checker-image-id'):p.add_argument('--'+key,required=True)
    a=p.parse_args();env=dict(docker=a.docker,endpoint=a.endpoint,daemon_id=a.daemon_id,checker_image_id=a.checker_image_id,deadline_seconds=90)
    print(json.dumps(run(a.output,env),sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
