import base64,subprocess
from pathlib import Path
root=Path('/home/ubuntu/myink');p=root/'evaluations/writing-craft-20261029'
payload=base64.b64encode((p/'inventory-channel-input.json').read_bytes()).decode()
args=['sudo','-n','docker','compose','-f',str(root/'docker-compose.yml'),'-f',str(p/'compose-proof.json'),'run','--rm','--no-deps','-T','--entrypoint','python','-e','INVENTORY_PROBE='+payload,'myink-worker','-']
with (p/'inventory-channel-probe.jsonl').open('w') as f:r=subprocess.run(args,cwd=root,input=(p/'inventory-channel-probe.py').read_bytes(),stdout=f)
raise SystemExit(r.returncode)
