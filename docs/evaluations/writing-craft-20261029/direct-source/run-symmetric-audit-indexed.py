import base64,subprocess
from pathlib import Path
root=Path('/home/ubuntu/myink');p=root/'evaluations/writing-craft-20261029'
payload=base64.b64encode((p/'symmetric-audit-indexed-input.json').read_bytes()).decode()
args=['sudo','-n','docker','compose','-f',str(root/'docker-compose.yml'),'-f',str(p/'compose-proof.json'),'run','--rm','--no-deps','-T','--entrypoint','python','-e','SYMMETRIC_INDEXED_AUDIT='+payload,'myink-worker','-']
with (p/'symmetric-audit-indexed.jsonl').open('w') as f:r=subprocess.run(args,cwd=root,input=(p/'symmetric-audit-indexed.py').read_bytes(),stdout=f)
raise SystemExit(r.returncode)
