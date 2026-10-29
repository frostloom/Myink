"""Validated platform defaults and per-field account preference resolution."""
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from myink.config import settings
from myink.task_budget import TaskBudgetLimits, public_limits


class RankingsDefaults(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool = Field(default_factory=lambda: bool(settings.rankings_enabled))
    timeout: StrictInt = Field(default_factory=lambda: int(settings.rankings_timeout), ge=1, le=60)
    limit: StrictInt = Field(default_factory=lambda: int(settings.rankings_limit), ge=1, le=50)


class UserDefaults(BaseModel):
    model_config = ConfigDict(extra='forbid')
    thinking_enabled: StrictBool = False
    task_budget: TaskBudgetLimits = Field(default_factory=TaskBudgetLimits)
    rankings: RankingsDefaults = Field(default_factory=RankingsDefaults)


def merge_defaults(raw, base=None) -> dict:
    """Merge only provided leaves; never replace a partial nested preference."""
    merged = deepcopy(base) if base is not None else UserDefaults().model_dump(mode='json')
    for key, value in raw.items():
        if key in ('task_budget', 'rankings') and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return UserDefaults.model_validate(merged).model_dump(mode='json')


def platform_defaults(config=None) -> dict:
    if config is None:
        from myink.platform_configuration import load_configuration
        config = load_configuration()
    try:
        return merge_defaults(config.get('user_defaults', {}))
    except (ValueError, TypeError, AttributeError):
        from myink.platform_readiness import PlatformNotReady
        raise PlatformNotReady() from None


def effective_preferences(raw, config=None) -> dict:
    """Use field presence, including explicit false/zero, to resolve overrides."""
    defaults = platform_defaults(config)
    if 'thinking_enabled' in raw:
        defaults['thinking_enabled'] = bool(raw['thinking_enabled'])
    budget = raw.get('task_budget')
    if isinstance(budget, dict):
        defaults['task_budget'] = public_limits(TaskBudgetLimits.model_validate({**defaults['task_budget'], **budget}))
    rankings = raw.get('rankings')
    if isinstance(rankings, dict):
        if 'enabled' in rankings:
            defaults['rankings']['enabled'] = bool(rankings['enabled'])
        for key, maximum in (('timeout', 60), ('limit', 50)):
            value = rankings.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum:
                defaults['rankings'][key] = value
    return defaults


def overridden_fields(raw) -> list[str]:
    fields = ['thinking_enabled'] if 'thinking_enabled' in raw else []
    for group, keys in (('task_budget', TaskBudgetLimits.model_fields), ('rankings', RankingsDefaults.model_fields)):
        if isinstance(raw.get(group), dict):
            fields.extend(f'{group}.{key}' for key in keys if key in raw[group])
    return fields
