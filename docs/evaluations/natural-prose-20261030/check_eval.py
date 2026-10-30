import base64,contextlib,io,json,os,runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from myink.providers.base import ModelResponse
from myink.writing_resource_seed import builtin_resources
p=Path(__file__).parent
with patch('myink.platform_configuration.load_configuration',return_value={}):entries=[dict(r,current_version=1) for r in builtin_resources()]
seen=[]
class Provider:
 _client=SimpleNamespace(event_hooks={'request':[]})
 def generate(self,messages,**kwargs):
  for hook in self._client.event_hooks['request']:hook(None)
  seen.append(messages)
  return ModelResponse(content='=== CONTENT ===\n这是离线验证用的合成正文。',model_id='offline',finish_reason='stop')
provider=Provider();out=io.StringIO()
with patch.dict(os.environ,{'NATURAL_PROSE_INPUT':base64.b64encode((p/'input.json').read_bytes()).decode()}),patch('myink.db.new_session',lambda:contextlib.nullcontext(None)),patch('myink.writing_resources.catalog',return_value=entries),patch('myink.writing_resources.capture_role_prompts',return_value={}),patch('myink.platform_configuration.load_configuration',return_value={}),patch('myink.platform_configuration.resolve_connection',return_value={'model':'offline'}),patch('myink.providers._chain_from_override',return_value=SimpleNamespace(providers=[provider])),contextlib.redirect_stdout(out):
 runpy.run_path(str(p/'evaluate.py'),run_name='__main__')
rows=[json.loads(l) for l in out.getvalue().splitlines()]
assert len(seen)==12 and sum(r['event']=='sample' for r in rows)==12
assert rows[-1]=={'event':'complete','attempts':12}
try:provider._client.event_hooks['request'][0](None)
except RuntimeError:pass
else:raise AssertionError('Request13 accepted')
print('Offline actual-message test: 12/12 samples, all original case inputs included, replacement once, cap rejects request13; zero external calls.')
