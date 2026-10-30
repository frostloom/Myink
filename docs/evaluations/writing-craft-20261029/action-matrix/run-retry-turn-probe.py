import base64,subprocess
from pathlib import Path
root=Path('/home/ubuntu/myink');p=root/'evaluations/writing-craft-20261029'
payload=base64.b64encode((p/'retry-turn-probe.json').read_bytes()).decode()
args=['sudo','-n','docker','compose','-f',str(root/'docker-compose.yml'),'-f',str(p/'compose-proof.json'),'run','--rm','--no-deps','-T','--entrypoint','python','-v',str(p/'action_matrix.py')+':/eval/action_matrix.py:ro','-e','RETRY_TURN_PROBE='+payload,'myink-worker','-']
with (p/'retry-turn-probe.jsonl').open('w') as f:r=subprocess.run(args,cwd=root,input=(p/'retry-turn-probe.py').read_bytes(),stdout=f)
raise SystemExit(r.returncode)
