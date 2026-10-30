import base64,json,subprocess
from pathlib import Path
root=Path('/home/ubuntu/myink');p=root/'evaluations/writing-craft-20261029'
for sample in json.loads((p/'suite-focused.json').read_text()):
 payload=base64.b64encode(json.dumps(sample,ensure_ascii=False).encode()).decode()
 args=['sudo','-n','docker','compose','-f',str(root/'docker-compose.yml'),'-f',str(p/'compose-proof.json'),'run','--rm','--no-deps','-T','--entrypoint','python','-e','PROOF_PIPELINE='+payload,'myink-worker','/eval/pipeline.py']
 with (p/('proof-suite-v3-'+sample['id']+'.jsonl')).open('w') as f:
  result=subprocess.run(args,cwd=root,stdout=f)
 print(json.dumps({'id':sample['id'],'exit':result.returncode}),flush=True)
