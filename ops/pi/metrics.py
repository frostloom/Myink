"""Bounded read-only snapshots. Reader must enforce SELECT role and query timeout.

The callback receives a parameterized query request and returns mapping rows.
Only approved JSON leaves are projected; body sampling is a separate permission.
Missing historical observations are never backfilled from the collector identity.
"""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
import json
import math
import re
from time import monotonic
from typing import Callable

from .contracts import Identity, Record

_VERSION_FIELDS = ('deployment_id', 'generation', 'owner', 'schema_id', 'config_id',
                   'prompt_id', 'rubric_id', 'data_id', 'image_ids', 'commit_sha')


def _json_projection(field, keys):
    leaves = ', '.join(f"'{key}', detail->'{field}'->'{key}'" for key in keys)
    return f'json_build_object({leaves}) AS ' + ('provenance' if field == 'run_provenance' else field)


_PROJECTIONS = {
    'tasks': 'id, status, task_type, batch_task_id, chapter_seq, created_at, updated_at',
    'agent_runs': "id, task_id, node, model_id, input_tokens, output_tokens, cost_est, duration_ms, created_at, "
                  "detail->'observation_collision' AS observation_collision, "
                  + _json_projection('run_provenance', _VERSION_FIELDS) + ', '
                  + _json_projection('measurement', ('kind', 'zero_cost', 'cost', 'latency', 'quality_score',
                                                     'quality_rubric_id', 'pricing_id')),
}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _measurement(values, expected, direction='lower'):
    known = expected > 0 and len(values) == expected
    return dict(value=sum(values) / expected if known else None,
                availability='measured' if known else 'unknown', samples=len(values), direction=direction)


def collect_snapshot(reader: Callable, window: Record, identity: Identity) -> Record:
    start, end = window.get('start'), window.get('end')
    page_size = window.get('page_size', 500)
    timeout = window.get('query_timeout_ms', 5000)
    pages = window.get('max_pages', 20)
    domain = window.get('evidence_domain', 'online')
    if (not isinstance(start, datetime) or not isinstance(end, datetime)
            or start.tzinfo is None or end.tzinfo is None or start >= end
            or type(page_size) is not int or not 1 <= page_size <= 1000
            or type(timeout) is not int or not 1 <= timeout <= 5000
            or type(pages) is not int or not 1 <= pages <= 100
            or domain not in ('synthetic', 'online')):
        raise ValueError('invalid snapshot window or query bounds')
    truncated = False
    deadline = monotonic() + 120

    def read(source, where, parameters):
        nonlocal truncated
        result = []
        for page in range(pages):
            if monotonic() >= deadline:
                raise TimeoutError('snapshot deadline exceeded')
            request = dict(source=source, sql=f'SELECT {_PROJECTIONS[source]} FROM {source} '
                           f'WHERE {where} '
                           'ORDER BY created_at, id LIMIT :limit OFFSET :offset',
                           params=dict(start=start, end=end, **parameters, limit=page_size, offset=page * page_size),
                           read_only=True, timeout_ms=timeout)
            batch = list(reader(request))
            if len(batch) > page_size or any(not isinstance(r, dict) for r in batch):
                raise ValueError('reader exceeded page contract')
            result.extend(batch)
            if len(batch) < page_size:
                break
        else:
            truncated = True
        return result

    cohort = ('SELECT COALESCE(batch_task_id, id) FROM tasks '
              'WHERE created_at >= :start AND created_at < :end')
    task_rows = read('tasks', f'id IN ({cohort}) OR batch_task_id IN ({cohort})', {})
    groups, aliases = defaultdict(list), {}
    for task in task_rows:
        tid = str(task['id'])
        parent = str(task.get('batch_task_id') or tid)
        groups[parent].append(task)
        aliases[tid] = parent
        if task.get('batch_task_id') and task.get('chapter_seq') is not None:
            aliases[f"{parent}:ch{task['chapter_seq']}"] = parent
    counts = dict(planned=len(groups), completed=0, failed=0, paused=0, queued=0, human_waiting=0, status_unknown=0)
    confounders, unknown = [], False
    completed = set()
    for group, tasks in groups.items():
        root = next((t for t in tasks if str(t['id']) == group and not t.get('batch_task_id')), None)
        timestamps = [t.get(key) for t in tasks for key in ('created_at', 'updated_at')]
        bounded = (root is not None and all(isinstance(v, datetime) and v.tzinfo is not None for v in timestamps)
                   and all(start <= t['created_at'] <= t['updated_at'] < end for t in tasks))
        if not bounded:
            counts['status_unknown'] += 1
            unknown = True
            confounders.append('incomplete_or_cross_boundary_cohort')
            continue
        states = {t.get('status') for t in tasks}
        if states <= {'done'}:
            counts['completed'] += 1
            completed.add(group)
        elif states & {'failed', 'cancelled'}:
            counts['failed'] += 1
        elif 'paused' in states:
            counts['paused'] += 1
        elif states & {'awaiting_plan', 'awaiting_review'}:
            counts['human_waiting'] += 1
        elif 'queued' in states:
            counts['queued'] += 1
    thread_params = {f'thread_{i}': name for i, name in enumerate(sorted(aliases))}
    placeholders = ', '.join(':' + key for key in thread_params)
    run_rows = read('agent_runs', f'created_at < :end AND task_id IN ({placeholders})' if placeholders else 'FALSE', thread_params)
    runs = defaultdict(list)
    versions = {key: set() for key in _VERSION_FIELDS}
    models = set()
    pricing, pricing_unknown = set(), False
    for row in run_rows:
        if row.get('observation_collision') is True:
            confounders.append('observation_collision')
        task = str(row.get('task_id'))
        group = aliases.get(task)
        if group is None:
            confounders.append('orphan_or_cross_window_run')
            continue
        observed_at = row.get('created_at')
        if (not isinstance(observed_at, datetime) or observed_at.tzinfo is None
                or not start <= observed_at < end
                or (group in completed and observed_at > max(t['updated_at'] for t in groups[group]))):
            confounders.append('out_of_bounds_run')
            unknown = True
            completed.discard(group)
            continue
        runs[group].append(row)
        measurement = row.get('measurement')
        kind = measurement.get('kind') if isinstance(measurement, dict) else None
        price = measurement.get('pricing_id') if isinstance(measurement, dict) else None
        if kind == 'model':
            if (isinstance(price, str) and re.fullmatch(r'[0-9a-f]{64}', price)
                    and measurement.get('cost') is True):
                pricing.add(price)
            else:
                pricing_unknown = True
            if row.get('model_id'):
                models.add(row['model_id'])
            else:
                unknown = True
        elif (kind != 'deterministic' or row.get('model_id') is not None
              or row.get('cost_est') != 0 or row.get('input_tokens') != 0 or row.get('output_tokens') != 0
              or measurement.get('zero_cost') is not True):
            unknown = True
            pricing_unknown = True
        provenance = row.get('provenance') or {}
        if not isinstance(provenance, dict):
            provenance = {}
        for key in _VERSION_FIELDS:
            value = provenance.get(key)
            if key == 'commit_sha' and value is None and identity.commit_sha is None:
                continue
            if key == 'image_ids' and isinstance(value, dict) and value:
                value = json.dumps(value, sort_keys=True, separators=(',', ':'))
            if value is None or value == '' or type(value) not in (str, int):
                unknown = True
            else:
                versions[key].add(value)
        expected = dict(deployment_id=identity.deployment_id, generation=identity.generation,
                        owner=identity.owner, image_ids=identity.image_ids,
                        commit_sha=identity.commit_sha, schema_id=identity.schema_id, config_id=identity.config_hash)
        if any(provenance.get(key) is not None and value is not None and provenance[key] != value
               for key, value in expected.items()):
            confounders.append('identity_mismatch')
    if len(completed) != counts['completed']:
        counts['status_unknown'] += counts['completed'] - len(completed)
        counts['completed'] = len(completed)
    if any(not runs[group] for group in completed):
        unknown = True
    if any(len(values) > 1 for values in versions.values()) or len(models) > 1:
        confounders.append('mixed_versions')
    if truncated:
        confounders.append('query_truncated')
    if len(pricing) > 1:
        confounders.append('mixed_pricing')
    values = dict(cost=[], latency=[], node_time=[], quality=[])
    for group in completed:
        group_runs = runs[group]
        for name, column, marker in (('cost', 'cost_est', 'cost'),
                                     ('node_time', 'duration_ms', 'latency')):
            if group_runs and all(isinstance(r.get('measurement'), dict)
                                  and r['measurement'].get(marker) is True and _number(r.get(column)) for r in group_runs):
                if name != 'cost' or (not pricing_unknown and len(pricing) <= 1):
                    values[name].append(sum(r[column] for r in group_runs))
        starts = [t.get('created_at') for t in groups[group]]
        ends = [t.get('updated_at') for t in groups[group]]
        if (all(isinstance(v, datetime) and v.tzinfo is not None for v in starts + ends)
                and max(ends) >= min(starts)):
            values['latency'].append((max(ends) - min(starts)).total_seconds() * 1000)
        scored = [r for r in group_runs if isinstance(r.get('measurement'), dict)
                  and (r['measurement'].get('quality_score') is not None
                       or r['measurement'].get('quality_rubric_id') is not None)]
        quality = [r['measurement'].get('quality_score') for r in scored]
        rubric = next(iter(versions['rubric_id'])) if len(versions['rubric_id']) == 1 else None
        if (quality and all(_number(v) for v in quality) and rubric is not None
                and all(r['measurement'].get('quality_rubric_id') == rubric for r in scored)):
            values['quality'].append(sum(quality) / len(quality))
    measurements = {key: _measurement(v, counts['completed'], 'higher' if key == 'quality' else 'lower')
                    for key, v in values.items()}
    for key in ('queue_time', 'human_wait'):
        measurements[key] = _measurement([], counts['planned'])
    measurements['errors'] = dict(value=counts['failed'] / counts['planned'] if counts['planned'] else None,
                                  availability='measured' if counts['planned'] and not counts['status_unknown'] else 'unknown',
                                  samples=counts['planned'], direction='lower')
    tail = len(values['latency'])
    measurements['latency_p95'] = dict(value=sorted(values['latency'])[math.ceil(tail * .95) - 1] if tail >= 100 else None,
                                      availability='measured' if tail >= 100 else 'unknown', samples=tail, direction='lower')
    version_range = {key: sorted(v, key=str) for key, v in versions.items()}
    single = lambda key: next(iter(versions[key])) if len(versions[key]) == 1 else None
    # Dataset pairing is trusted fixture metadata, never inferred from run counts.
    pairs = window.get('paired_group_ids', []) if domain == 'synthetic' else []
    if not isinstance(pairs, list) or not all(isinstance(p, str) and p for p in pairs):
        raise ValueError('invalid pair identifiers')
    return dict(id=window['id'], metric=window.get('metric'), evidence_domain=domain,
                identity=asdict(identity), window=dict(start=start.isoformat(), end=end.isoformat()),
                **counts, complete_tasks=counts['completed'], measurements=measurements,
                tail_samples=tail, paired_group_ids=pairs, paired_groups=len(set(pairs)),
                config_hash=single('config_id'), prompt_hash=single('prompt_id'), rubric_hash=single('rubric_id'),
                data_hash=single('data_id'), schema_id=single('schema_id'), model_ids=sorted(models),
                version_range=version_range, confounders=sorted(set(confounders)),
                pricing_id=next(iter(pricing)) if len(pricing) == 1 and not pricing_unknown else None,
                pricing_range=sorted(pricing), pricing_availability='measured' if len(pricing) == 1 and not pricing_unknown else 'unknown',
                availability='unknown' if unknown or not run_rows else 'measured')
