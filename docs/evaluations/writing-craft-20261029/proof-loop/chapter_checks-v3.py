"""Source-linked chapter promises and literal evidence, without a combined LLM pass.

These checks validate provenance and completeness, not the truth of arbitrary
natural language. Semantic observations still require calibration and rechecks.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class SourceLink(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    event_index: int = Field(strict=True, ge=0)
    quote: str = Field(min_length=1, max_length=4000)


class Claim(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    subject: str = Field(min_length=1, max_length=100)
    subject_kind: Literal['person', 'object']
    action: str = Field(min_length=1, max_length=900)
    temporal_scope: Literal['occurrence', 'end_state']
    expected: Literal['present', 'absent']
    links: tuple[SourceLink, ...] = Field(min_length=1, max_length=32)

    @property
    def predicate(self) -> str:
        return self.subject + self.action

    @property
    def key(self) -> str:
        data = json.dumps(self.model_dump(), ensure_ascii=False, sort_keys=True)
        return 'chapter-check:' + sha256(data.encode()).hexdigest()[:20]


class Observation(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    observation: Literal['observed', 'not_observed', 'uncertain']
    quotes: tuple[str, ...] = Field(default=(), max_length=4)
    reason: str = Field(min_length=1, max_length=1200)
    scope: Literal['local', 'structural', 'unknown'] = 'unknown'


def parse_contract(data: dict, events: list[str], *, participants: list[str] | None = None,
                   max_claims: int = 12) -> list[Claim]:
    """Parse a source-linked contract, without certifying semantic equivalence.

    Complete character coverage only proves that source text was referenced;
    one unsupported predicate can still cite an entire compound sentence.
    Callers must not use this return value as a semantic approval gate.
    This experimental module is not enabled in the writing runtime.
    """
    if not events or any(not isinstance(event, str) or not event.strip() for event in events):
        raise ValueError('章节预期事件不能为空')
    if not isinstance(data, dict) or set(data) != {'atoms'} or not isinstance(data['atoms'], list):
        raise ValueError('校对约定必须包含 atoms 列表')
    if not data['atoms'] or len(data['atoms']) > max_claims * 4:
        raise ValueError('校对条目为空或超出上限')
    coverage = [set() for _ in events]
    merged: dict[tuple[str, str, str, str], Claim] = {}
    for raw in data['atoms']:
        claim = Claim.model_validate(raw)
        if claim.subject != claim.subject.strip() or claim.action != claim.action.strip():
            raise ValueError('校对主体和动作不能带首尾空白')
        if claim.subject_kind == 'person' and claim.subject not in (participants or []):
            raise ValueError('校对人物必须是名单中的单个人物')
        predicate = claim.predicate.strip()
        if not predicate:
            raise ValueError('校对命题不能为空')
        for link in claim.links:
            if link.event_index >= len(events) or not link.quote.strip():
                raise ValueError('校对来源索引或引文无效')
            event = events[link.event_index]
            start = event.find(link.quote)
            if start < 0:
                raise ValueError('校对来源引文必须逐字来自对应事件')
            coverage[link.event_index].update(range(start, start + len(link.quote)))
        identity = (claim.subject_kind, claim.subject, claim.action, claim.temporal_scope)
        previous = merged.get(identity)
        if previous and previous.expected != claim.expected:
            raise ValueError('相同校对命题的正反期望冲突')
        links = {(link.event_index, link.quote) for link in (*previous.links, *claim.links)} if previous else {
            (link.event_index, link.quote) for link in claim.links}
        merged[identity] = Claim(subject=claim.subject, subject_kind=claim.subject_kind,
            action=claim.action, temporal_scope=claim.temporal_scope, expected=claim.expected,
            links=tuple(SourceLink(event_index=index, quote=quote) for index, quote in sorted(links)))
    if len(merged) > max_claims:
        raise ValueError(f'校对条目超出上限 {max_claims}，不能截断后放行')
    for index, event in enumerate(events):
        missing = ''.join(char for position, char in enumerate(event)
                          if not char.isspace() and char not in '，。；、' and position not in coverage[index]
                          and not (char == '且' and position - 1 in coverage[index]
                                   and position + 1 in coverage[index]))
        if missing:
            raise ValueError(f'事件 {index} 存在未覆盖内容：{missing[:400]}')
    return list(merged.values())


def parse_observation(data: dict, draft: str) -> Observation:
    result = Observation.model_validate(data)
    if result.observation == 'observed' and not result.quotes:
        raise ValueError('肯定观察必须有正文引文')
    if any(not quote.strip() or len(quote) > 2000 or quote not in draft for quote in result.quotes):
        raise ValueError('正文引文必须是原稿中的逐字连续片段')
    return result


@dataclass(frozen=True)
class Assessment:
    failed: tuple[Claim, ...]
    uncertain: tuple[Claim, ...]

    @property
    def passed(self) -> bool:
        return not self.failed and not self.uncertain

    @property
    def needs_review(self) -> bool:
        return bool(self.uncertain)


def assess_observations(claims: list[Claim], observations: Mapping[str, Observation]) -> Assessment:
    keys = {claim.key for claim in claims}
    if not claims or set(observations) != keys:
        raise ValueError('校对结果未完整覆盖全部命题，或包含未知条目')
    failed, uncertain = [], []
    for claim in claims:
        result = observations[claim.key]
        if result.observation == 'uncertain':
            uncertain.append(claim)
        elif result.observation != ('observed' if claim.expected == 'present' else 'not_observed'):
            failed.append(claim)
    return Assessment(tuple(failed), tuple(uncertain))


class ObservationRow(Observation):
    index: int = Field(strict=True, ge=0)


def parse_observations(data: dict, claims: list[Claim], draft: str) -> dict[str, Observation]:
    if not isinstance(data, dict) or set(data) != {'checks'} or not isinstance(data['checks'], list):
        raise ValueError('校对结果必须包含 checks 列表')
    rows = [ObservationRow.model_validate(raw) for raw in data['checks']]
    if not claims or len(rows) != len(claims) or {row.index for row in rows} != set(range(len(claims))):
        raise ValueError('校对结果必须逐项完整覆盖，不可缺漏、重复或添加未知条目')
    return {claims[row.index].key: parse_observation(row.model_dump(exclude={'index'}), draft)
            for row in rows}


class ConsistencyIssue(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    before_quote: str = Field(min_length=1, max_length=2000)
    after_quote: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=1200)
    scope: Literal['local', 'structural', 'unknown']


class IssueGroup(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    issue_found: StrictBool
    issues: tuple[ConsistencyIssue, ...] = Field(max_length=2)

    @model_validator(mode='after')
    def consistent_flag(self):
        if self.issue_found != bool(self.issues):
            raise ValueError('矛盾标记必须与证据条目一致')
        return self


class ConsistencyReport(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    opening: IssueGroup
    internal: IssueGroup


def parse_consistency(data: dict, draft: str, opening_sources: list[str], *,
                      opening_chars: int = 350) -> ConsistencyReport:
    result = ConsistencyReport.model_validate(data)
    for category in ('opening', 'internal'):
        for issue in getattr(result, category).issues:
            sources = opening_sources if category == 'opening' else [draft]
            target = draft[:opening_chars] if category == 'opening' else draft
            if (not issue.before_quote.strip() or not issue.after_quote.strip()
                    or not any(issue.before_quote in source for source in sources)
                    or issue.after_quote not in target):
                raise ValueError('矛盾证据必须逐字来自对应来源与正文范围')
    return result


class FidelityRow(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    event_index: int = Field(strict=True, ge=0)
    status: Literal['faithful', 'unfaithful', 'uncertain']
    source_quotes: tuple[str, ...] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=1, max_length=1200)


class FidelityReport(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    checks: tuple[FidelityRow, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(row.status == 'faithful' for row in self.checks)


def parse_fidelity(data: dict, events: list[str]) -> FidelityReport:
    """Validate a separate model's source review; not a formal semantic proof."""
    result = FidelityReport.model_validate(data)
    if (not events or len(result.checks) != len(events)
            or {row.event_index for row in result.checks} != set(range(len(events)))):
        raise ValueError('语义核对必须逐项覆盖所有来源，不可缺漏或重复')
    for row in result.checks:
        if any(not quote.strip() or quote not in events[row.event_index] for quote in row.source_quotes):
            raise ValueError('语义核对引文必须逐字来自对应事件')
    return result


def draft_segments(draft: str) -> list[str]:
    """Stable within one draft; every segment is an unchanged contiguous span."""
    return [paragraph[start:start + 1000]
            for part in draft.split('\n\n') if (paragraph := part.strip())
            for start in range(0, len(paragraph), 1000)]


class IndexedObservation(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    index: int = Field(strict=True, ge=0)
    observation: Literal['observed', 'not_observed', 'uncertain']
    evidence_ids: tuple[int, ...] = Field(max_length=4)
    reason: str = Field(min_length=1, max_length=1200)
    scope: Literal['local', 'structural', 'unknown']


def parse_indexed_observations(data: dict, claims: list[Claim], draft: str) -> dict[str, Observation]:
    if not isinstance(data, dict) or set(data) != {'checks'} or not isinstance(data['checks'], list):
        raise ValueError('校对结果必须包含 checks 列表')
    segments = draft_segments(draft)
    rows = []
    for raw in data['checks']:
        # bool/float are not valid segment IDs even though Python equates them to ints.
        if any(type(index) is not int for index in raw.get('evidence_ids', [])):
            raise ValueError('正文证据编号必须为整数')
        row = IndexedObservation.model_validate(raw)
        if any(not 0 <= index < len(segments) for index in row.evidence_ids):
            raise ValueError('正文证据编号超出范围')
        rows.append({**row.model_dump(exclude={'evidence_ids'}),
                     'quotes': [segments[index] for index in row.evidence_ids]})
    return parse_observations({'checks': rows}, claims, draft)
