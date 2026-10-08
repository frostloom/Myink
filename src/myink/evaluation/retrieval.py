"""Retrieval metrics use fixture labels, never model confidence or vector rank."""
from myink.context_budget import estimate_tokens
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RetrievalEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1)
    chapter: int = Field(ge=1)
    summary: str = Field(min_length=1)


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$')
    group_id: str
    split: str
    canonical: str = Field(min_length=1)
    aliases: list[str]
    participants: list[str]
    query: str = Field(min_length=1)
    events: list[RetrievalEvent]
    required: list[str]
    label: str

    @model_validator(mode='after')
    def validate_required(self):
        ids = {event.id for event in self.events}
        if len(ids) != len(self.events) or len(set(self.required)) != len(self.required):
            raise ValueError('duplicate event or required id')
        valid = {event.id for event in self.events if event.chapter < 30}
        if not set(self.required) <= valid:
            raise ValueError('required history must exist before chapter 30')
        return self


def retrieval_metrics(required_ids, returned_events, *, chapter_seq, project_id):
    required = set(required_ids)
    unique = {str(row['event_id']): row for row in returned_events}
    valid = {key for key, row in unique.items()
             if row['chapter'] < chapter_seq and str(row['project_id']) == str(project_id)}
    hits = required & valid
    return {
        'required': len(required), 'hit': len(hits), 'returned_unique': len(unique),
        'recall_at_k': len(hits) / len(required) if required else None,
        'irrelevant_ratio': (len(unique) - len(hits)) / len(unique) if unique else None,
        'future_leaks': sum(row['chapter'] >= chapter_seq for row in unique.values()),
        'tenant_leaks': sum(str(row['project_id']) != str(project_id) for row in unique.values()),
        'tokens_est': estimate_tokens(list(unique.values())),
        'missing_ids': sorted(required - hits),
    }
