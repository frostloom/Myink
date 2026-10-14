"""Host-prepared phase prompts; text guidance never grants machine capability."""
from copy import deepcopy
from pathlib import Path
from .tools import PHASE_TOOLS, canonical
from .writing_analysis import build_writing_prompt


def build_phase_prompt(phase, evidence, limits):
    if (phase not in PHASE_TOOLS or not isinstance(evidence,dict) or not isinstance(limits,dict)
            or set(limits) != {'max_attempts','budget_microyuan','deadline'}
            or (limits['max_attempts'] is not None and
                (type(limits['max_attempts']) is not int or not 1 <= limits['max_attempts'] <= 100))
            or type(limits['budget_microyuan']) is not int or not 1 <= limits['budget_microyuan'] <= 20000000
            or not isinstance(limits['deadline'],str) or not limits['deadline'].strip()):
        raise ValueError('fixed phase and controller limits required')
    data = dict(evidence=deepcopy(evidence),limits=deepcopy(limits),
                permissions={'tools':list(PHASE_TOOLS[phase]),'new_features_require_owner':True})
    instructions = ''
    if phase == 'analysis':
        writing_prompt=build_writing_prompt(evidence['view'],evidence['report'])
        import json
        writing_instructions, writing_data = writing_prompt.split('\nDATA\n', 1)
        instructions = writing_instructions.replace('Bodies in DATA', 'Bodies in CONTROLLED_DATA.writing')
        data['writing']=json.loads(writing_data)
        data['writing']['permissions']=deepcopy(data['permissions'])
        data['evidence']={}
    root=Path(__file__).parent
    template=root/'prompts'/('analyze.md' if phase=='analysis' else phase+'.md')
    skill=root/'skills/myink-iteration/SKILL.md'
    prompt=template.read_text(encoding='utf-8')+'\n'+skill.read_text(encoding='utf-8')+'\n'+instructions+'\nCONTROLLED_DATA\n'+canonical(data)
    if len(prompt.encode())>60000:raise ValueError('finite controller prompt required')
    return prompt
