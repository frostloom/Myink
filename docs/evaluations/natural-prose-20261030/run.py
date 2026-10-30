import base64,json,subprocess
from pathlib import Path
root=Path('/home/ubuntu/myink');p=root/'evaluations/natural-prose-20261030'
payload=base64.b64encode((p/'input.json').read_bytes()).decode()
args=['sudo','-n','docker','compose','-f',str(root/'docker-compose.yml'),'-f',str(p/'compose.json'),'run','--rm','--no-deps','-T','--entrypoint','python','-e','NATURAL_PROSE_INPUT='+payload,'myink-worker','-']
with (p/'results.jsonl').open('x') as output:r=subprocess.run(args,cwd=root,input=(p/'evaluate.py').read_bytes(),stdout=output)
print(json.dumps({'exit':r.returncode}),flush=True)
raise SystemExit(r.returncode)
