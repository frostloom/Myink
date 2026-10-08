"""Versioned fixed-text cases and source/group validation."""
from __future__ import annotations

import json
import ast
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class EvaluationConfig(StrictModel):
    model: Literal['deepseek-v4-flash','deepseek-v4-pro']
    temperature: float = Field(ge=0,le=2,strict=True,allow_inf_nan=False)
    max_tokens: int = Field(ge=1,le=8192,strict=True)
    max_calls: int = Field(ge=1,strict=True)
    max_cost_yuan: float = Field(gt=0,strict=True,allow_inf_nan=False)
    deadline_seconds: float = Field(gt=0,strict=True,allow_inf_nan=False)


class Source(StrictModel):
    path: str
    case_name: str
    adapted_from: list[str] = Field(default_factory=list)


class Input(StrictModel):
    chapter_seq: int = Field(ge=1)
    context: dict
    plan: dict
    draft: str = Field(min_length=1)


class EvidenceSource(StrictModel):
    chapter: int = Field(ge=1)
    pointer: str


class Issue(StrictModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    allowed_conflict_types: list[str] = Field(min_length=1)
    allowed_severities: list[Literal['critical','major','minor','hint']] = Field(min_length=1)
    evidence_sources: list[EvidenceSource] = Field(min_length=1)


class Expected(StrictModel):
    allowed_verdicts: list[Literal['pass','rewrite','replan']] = Field(min_length=1)
    required_issues: list[Issue]
    forbidden_issues: list[str]


class Label(StrictModel):
    status: Literal['proposed','reviewed','disputed']
    review_note: str
    reviewer: str | None = None


def pointer(value: dict, path: str):
    if not path.startswith('/'):
        raise ValueError('evidence pointer must start with /')
    for raw in path[1:].split('/'):
        part = raw.replace('~1','/').replace('~0','~')
        value = value[int(part)] if isinstance(value,list) else value[part]
    return value


class Case(StrictModel):
    schema_version: Literal[1]
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9_.-]*$')
    group_id: str = Field(min_length=1)
    split: Literal['development','holdout']
    mode: Literal['audit']
    category: str
    polarity: Literal['positive','negative']
    source: Source
    input: Input
    expected: Expected
    label: Label

    @model_validator(mode='after')
    def consistent(self):
        issues=self.expected.required_issues
        if (self.polarity=='positive') != bool(issues):
            raise ValueError('positive cases need issues; negative cases must have none')
        if self.polarity=='negative' and not self.expected.forbidden_issues:
            raise ValueError('negative cases need an explicit forbidden issue')
        if len({i.id for i in issues}) != len(issues):
            raise ValueError('duplicate issue id')
        if self.label.status=='reviewed' and not self.label.reviewer:
            raise ValueError('reviewed label needs reviewer')
        for issue in issues:
            for source in issue.evidence_sources:
                try:
                    text=pointer(self.model_dump(),source.pointer)
                except (KeyError,IndexError,ValueError,TypeError) as exc:
                    raise ValueError('invalid evidence pointer') from exc
                if not isinstance(text,str) or not text.strip():
                    raise ValueError('evidence source must be nonempty text')
                if source.pointer=='/input/draft' or source.pointer.startswith('/input/plan/'):
                    chapter=self.input.chapter_seq
                elif source.pointer.startswith('/input/context/'):
                    value=self.model_dump();chapter=None
                    for part in source.pointer[1:].split('/'):
                        if isinstance(value,dict) and 'chapter' in value:chapter=value['chapter']
                        decoded=part.replace('~1','/').replace('~0','~')
                        value=value[int(decoded)] if isinstance(value,list) else value[decoded]
                else:raise ValueError('evidence pointer must refer to input text')
                if type(chapter) is not int or chapter!=source.chapter:
                    raise ValueError('evidence source chapter does not match input')
        return self


def load_cases(directory: Path, repo_root: Path) -> list[Case]:
    cases=[];ids=set();groups={}
    for file in sorted(directory.rglob('*.json')):
        case=Case.model_validate_json(file.read_text(encoding='utf-8'))
        if case.id in ids:
            raise ValueError(f'duplicate case id: {case.id}')
        ids.add(case.id)
        if case.group_id in groups and groups[case.group_id]!=case.split:
            raise ValueError(f'group split leak: {case.group_id}')
        groups[case.group_id]=case.split
        root=repo_root.resolve();source=(root/case.source.path).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError(f'invalid source path: {case.source.path}')
        if source.suffix=='.py':
            tree=ast.parse(source.read_text(encoding='utf-8'))
            if not any(isinstance(n,ast.Constant) and n.value==case.source.case_name for n in ast.walk(tree)):
                raise ValueError(f'source case not found: {case.source.case_name}')
        cases.append(case)
    if not cases:
        raise ValueError('no cases found')
    return cases


def json_text(value) -> str:
    return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n'


def validate_catalog(repo_root:Path) -> int:
    data=json.loads((repo_root/'evals/catalog.json').read_text(encoding='utf-8'))
    if data.get('schema_version')!=1:raise ValueError('unsupported catalog schema')
    expected={f'conflict-samples:{int(n):02d}' for n in re.findall(r'^### 样例 (\d+) ·',
        (repo_root/'spec/conflict-samples.md').read_text(encoding='utf-8'),re.M)}
    entries=data['cases'];ids=[c['id'] for c in entries]
    if len(set(ids))!=len(ids) or set(ids)!=expected:raise ValueError('catalog ids do not match specification')
    root=repo_root.resolve()
    for entry in entries:
        file=(root/entry['test']['path']).resolve()
        if not file.is_relative_to(root) or not file.is_file():raise ValueError('invalid catalog test path')
        functions={n.name:n for n in ast.parse(file.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)}
        if entry['test']['function'] not in functions:raise ValueError('catalog test function missing')
        if entry['polarity'] not in ('positive','negative') or entry['coverage'] not in ('implemented','gap','not_applicable'):
            raise ValueError('invalid catalog labels')
    return len(entries)
