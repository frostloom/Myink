"""Readonly research context and untrusted test proposal; no execution authority.

The caller authenticates observation receipts and root source policy before using
this compiler. A reference Git snapshot never proves deployed product identity.
"""
import ast,re
from pathlib import Path
from hashlib import sha256
from .audit import _plain,digest,encoded,hash_value,require,strict_json
from .development_inputs import path,tree_hash,file_hash
from .plans import _path
from .task_package import _case_hints

MAX_CONTEXT=24000
PROPOSAL=set('schema input_sha256 decision problem files test_source summary'.split())
PENDING=set('path file_sha256 symbol symbol_sha256 candidate_sha256'.split())


def symbol_hash(text,symbol):
    require(isinstance(symbol,str) and re.fullmatch('[A-Za-z_][A-Za-z0-9_.]{0,160}',symbol),'static pending symbol required')
    node=ast.parse(text)
    for name in symbol.split('.'):
        matches=[n for n in getattr(node,'body',[]) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==name]
        require(len(matches)==1,'pending symbol missing or ambiguous');node=matches[0]
    return digest(ast.dump(node,include_attributes=False))


def _secrets(text,credential_literal):
    if credential_literal is not None:require(isinstance(credential_literal,str) and len(credential_literal)>0 and credential_literal not in text,'credential literal in investigation material')
    key=r'\b[A-Za-z0-9_]*(?:api[_-]?key|access[_-]?token|password|secret)[A-Za-z0-9_]*'
    literal=r'''(?:["']?\s*:\s*["'][^"']+["']|(?:\s*:\s*[^=\n]{0,120})?\s*=\s*["'][^"']+["'])'''
    require(not re.search(key+literal,text,re.IGNORECASE) and not re.search(r'''[a-z][a-z0-9+.-]*://[^\s/'"<>]+:[^\s/'"<>]+@''',text,re.IGNORECASE),'credential-shaped investigation material')


def compile_context(source_path,source_sha256,files,evidence,*,reference_commit=None,pending=None,credential_literal=None):
    source=path(source_path);require(source.is_dir() and {p.name for p in source.iterdir()}=={'src'} and hash_value(source_sha256) and tree_hash(source)==source_sha256,'closed reference source identity required')
    require(isinstance(files,list) and 0<len(files)<=3 and len(files)==len(set(files)) and all(_path(f) and f.startswith('src/') and f.endswith('.py') for f in files),'bounded existing research files required')
    require(reference_commit is None or hash_value(reference_commit,40),'reference Git identity required')
    require(isinstance(evidence,dict) and evidence.get('mode') in ('ACTUAL','SIMULATED') and hash_value(evidence.get('evidence_fingerprint')) and hash_value(evidence.get('cohort_sha256')),'host observation identity required')
    require(type(evidence.get('observed_samples')) is int and evidence['observed_samples']>=0,'host observation count required')
    observed_commit=evidence.get('source_commit');require(observed_commit is None or hash_value(observed_commit,40),'observed source identity invalid')
    gaps=evidence.get('gaps');require(isinstance(gaps,list) and len(gaps)<=32 and all(isinstance(x,str) and re.fullmatch('[a-z_]{1,80}',x) for x in gaps),'host observation gaps required')
    pending=[] if pending is None else pending;require(isinstance(pending,list) and len(pending)<=32,'bounded known pending findings required')
    for item in pending:
        require(isinstance(item,dict) and set(item)==PENDING and _path(item['path']) and item['path'].startswith('src/') and hash_value(item['file_sha256']) and hash_value(item['candidate_sha256']),'source-bound pending candidate required')
        require(item['symbol'] is None and item['symbol_sha256'] is None or isinstance(item['symbol'],str) and hash_value(item['symbol_sha256']),'pending symbol binding invalid')
    facts=evidence.get('facts')
    if facts is not None:
        from .live_diagnosis import COUNTS
        fields=set('counts measurements version_range availability confounders task_types model_ids pricing_id pricing_range pricing_availability cohort_sha256 minimum_samples'.split())
        require(isinstance(facts,dict) and set(facts)==fields and len(encoded(facts))<=8192,'bounded host metric facts required')
        counts=facts['counts'];require(isinstance(counts,dict) and set(counts)==COUNTS and all(type(v) is int and 0<=v<=1000 for v in counts.values()) and counts['complete_tasks']==counts['completed']==evidence['observed_samples'] and counts['completed']<=counts['planned'],'host metric counts drift')
        require(facts['cohort_sha256']==evidence['cohort_sha256'] and type(facts['minimum_samples']) is int and 1<=facts['minimum_samples']<=1000 and facts['availability'] in ('measured','unknown') and facts['pricing_availability'] in ('measured','unknown'),'host metric provenance drift')
        require(isinstance(facts['measurements'],dict) and isinstance(facts['version_range'],dict) and all(isinstance(facts[k],list) and all(isinstance(x,str) and len(x)<=256 for x in facts[k]) for k in ('confounders','task_types','model_ids','pricing_range')),'host metric metadata required')
        facts=strict_json(encoded(facts))
    require(evidence['mode']!='ACTUAL' or facts is not None,'ACTUAL research requires authenticated metric facts')
    materials=[]
    for relative in sorted(files):
        p=path(source/relative);_plain(p);require(p.stat().st_size<=MAX_CONTEXT,'complete source context exceeds bound');raw=p.read_bytes();require(len(raw)<=MAX_CONTEXT)
        text=raw.decode('utf-8');pin=sha256(raw).hexdigest();_secrets(text,credential_literal)
        for item in pending:
            if item['path']!=relative:continue
            require(item['file_sha256']!=pin,'known pending source candidate; no paid rediscovery')
            if item['symbol'] is not None:
                try:same=symbol_hash(text,item['symbol'])==item['symbol_sha256']
                except ValueError:same=False
                require(not same,'known pending symbol candidate; no paid rediscovery')
        materials.append(dict(path=relative,sha256=pin,text=text))
    fingerprint=digest(dict(evidence_fingerprint=evidence['evidence_fingerprint'],cohort_sha256=evidence['cohort_sha256'],files={m['path']:m['sha256'] for m in materials}))
    result=dict(schema='pi-investigation-input-v1',authority='proposal_only',source_kind='reference_snapshot',untrusted_material=True,online_improvement_proven=False,mode=evidence['mode'],source_sha256=source_sha256,reference_commit=reference_commit,observed_source_commit=observed_commit,evidence_fingerprint=evidence['evidence_fingerprint'],research_fingerprint=fingerprint,cohort_sha256=evidence['cohort_sha256'],observed_samples=evidence['observed_samples'],observation_facts=facts,gaps=list(gaps),files=materials)
    require(len(encoded(result))<=MAX_CONTEXT,'complete investigation context exceeds wire bound')
    require(tree_hash(source)==source_sha256 and all(file_hash(source/m['path'])==m['sha256'] for m in materials),'investigation source changed while reading')
    return result


def validate_proposal(value,context):
    require(isinstance(value,dict) and set(value)==PROPOSAL and value['schema']=='pi-test-proposal-v1','strict untrusted test proposal required')
    require(value['input_sha256']==digest(context) and value['decision'] in ('task','no_task'),'proposal input or decision drift')
    require(isinstance(value['summary'],str) and 0<len(value['summary'])<=1000,'bounded untrusted proposal summary required')
    if value['decision']=='no_task':
        require(value['problem'] is None and value['files']==[] and value['test_source'] is None,'no-task proposal must have no executable payload');return dict(value)
    require(isinstance(value['problem'],str) and bool(value['problem'].strip()) and len(value['problem'])<=1000,'bounded existing-behavior problem required')
    files=value['files'];allowed={f['path'] for f in context['files']}
    require(isinstance(files,list) and 0<len(files)<=3 and len(set(files))==len(files) and all(isinstance(f,str) and f in allowed for f in files),'proposal outside frozen research scope')
    text=value['test_source'];require(isinstance(text,str) and 0<len(text.encode())<=12000,'bounded test source required');_secrets(text,None)
    cases=_case_hints(text.encode());require(len(cases)<=200,'bounded fixed test inventory required')
    return dict(value)
