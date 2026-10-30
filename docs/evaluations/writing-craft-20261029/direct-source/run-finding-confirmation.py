import base64,subprocess
from pathlib import Path
root=Path('/home/ubuntu/myink');p=root/'evaluations/writing-craft-20261029'
payload=base64.b64encode((p/'finding-confirmation-input.json').read_bytes()).decode()
args=['sudo','-n','docker','compose','-f',str(root/'docker-compose.yml'),'-f',str(p/'compose-proof.json'),'run','--rm','--no-deps','-T','--entrypoint','python','-e','FINDING_CONFIRMATION_CALIBRATION='+payload,'myink-worker','-']
with (p/'finding-confirmation-calibration.jsonl').open('w') as f:r=subprocess.run(args,cwd=root,input=(p/'finding-confirmation-calibration.py').read_bytes(),stdout=f)
raise SystemExit(r.returncode)
