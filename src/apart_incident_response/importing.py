"""Validated canonical JSONL ingress; imported provenance is never treated as verified."""
import json
import uuid

REQUIRED = {'run_id', 'task_id', 'condition_id', 'step', 'agent_id', 'response_text'}
OPTIONAL = {'answer_class', 'model', 'prompt_version', 'agent_config_version', 'visible_event_ids', 'visible_message_ids',
            'messages', 'communication_available', 'token_counts', 'latency_ms', 'timestamp', 'difficulty', 'minute',
            'submitted', 'termination_state', 'upload_within_deadline'}


def validate_records(text):
    records, seen = [], set()
    if not isinstance(text, str) or len(text.encode()) > 10_000_000:
        raise ValueError('Import must be JSONL text under 10 MB')
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Line {line_no}: invalid JSON') from exc
        if not isinstance(r, dict) or not REQUIRED <= set(r):
            raise ValueError(f'Line {line_no}: required fields are {sorted(REQUIRED)}')
        if set(r) - REQUIRED - OPTIONAL:
            raise ValueError(f'Line {line_no}: unsupported fields {sorted(set(r)-REQUIRED-OPTIONAL)}; map these explicitly')
        if r['condition_id'] not in ('C0', 'C1', 'C2') or r['agent_id'] not in ('A', 'B'):
            raise ValueError(f'Line {line_no}: use C0/C1/C2 and agent A/B')
        if type(r['step']) is not int or not 0 <= r['step'] <= 1000:
            raise ValueError(f'Line {line_no}: invalid step')
        if 'difficulty' in r and (type(r['difficulty']) is not int or not 1 <= r['difficulty'] <= 5):
            raise ValueError(f'Line {line_no}: difficulty must be an integer from 1 to 5')
        for name in ('run_id', 'task_id', 'response_text'):
            if not isinstance(r[name], str) or not r[name].strip() or len(r[name]) > 10000:
                raise ValueError(f'Line {line_no}: invalid {name}')
        key = (r['run_id'], r['step'], r['agent_id'])
        if key in seen:
            raise ValueError(f'Line {line_no}: duplicate run/step/agent')
        seen.add(key)
        if 'answer_class' in r and (not isinstance(r['answer_class'], str) or len(r['answer_class']) > 200):
            raise ValueError(f'Line {line_no}: invalid answer_class')
        for name in ('model', 'prompt_version', 'agent_config_version'):
            if name in r and (not isinstance(r[name], str) or len(r[name]) > 200):
                raise ValueError(f'Line {line_no}: invalid {name}')
        for name in ('visible_event_ids', 'visible_message_ids'):
            if name in r and (not isinstance(r[name], list) or any(not isinstance(v, str) for v in r[name])):
                raise ValueError(f'Line {line_no}: {name} must be a list of IDs')
        if 'communication_available' in r and type(r['communication_available']) is not bool:
            raise ValueError(f'Line {line_no}: invalid communication_available')
        if 'messages' in r:
            if not isinstance(r['messages'], list) or any(not isinstance(m, dict) or set(m) != {'role', 'content'} or m['role'] not in ('system','user','assistant','tool') or not isinstance(m['content'], str) for m in r['messages']):
                raise ValueError(f'Line {line_no}: messages require role/content')
        records.append(r)
    if not records or len(records) > 2000:
        raise ValueError('Import 1–2000 records')
    run_defs = {}
    for r in records:
        definition = (r['task_id'], r['condition_id'])
        if r['run_id'] in run_defs and run_defs[r['run_id']] != definition:
            raise ValueError('One source run cannot change task or condition')
        run_defs[r['run_id']] = definition
    return records


def import_jsonl(store, text):
    records = validate_records(text)  # Validate the entire upload before appending anything.
    batch = 'import-' + uuid.uuid4().hex[:12]
    store.append(batch, 'batch_started', {'source':'imported', 'config': {'protocol_id': 'external-unverified',
        'task_ids': sorted({r['task_id'] for r in records}), 'conditions': sorted({r['condition_id'] for r in records}),
        'steps': max(r['step'] for r in records)+1, 'repeats': None, 'expected_updates':len(records), 'model':'external'},
        'provenance': {'verification':'user-supplied; visibility and model execution not independently verified'}})
    runs = {}
    for r in sorted(records, key=lambda r: (r['run_id'], r['step'], r['agent_id'])):
        if r['run_id'] not in runs:
            runs[r['run_id']] = batch + '-' + uuid.uuid4().hex[:12]
            store.append(batch, 'run_started', {'task_id':r['task_id'], 'condition_id':r['condition_id'], 'repeat':len(runs)-1,
                'source':'imported', 'source_run_id':r['run_id'], 'provenance_status':'unverified'}, runs[r['run_id']])
        run = runs[r['run_id']]
        obs = None
        if 'messages' in r:
            obs = store.append(batch, 'agent_observation', {'agent_id':r['agent_id'], 'step':r['step'], 'messages':r['messages'],
                'visible_event_ids':r.get('visible_event_ids', []), 'visible_message_ids':r.get('visible_message_ids', []),
                'provenance_status':'imported_unverified'}, run)
        payload = {k:v for k,v in r.items() if k != 'messages'}
        payload.update(source_run_id=r['run_id'], run_id=run, experiment_id=batch, source='imported',
            observation_id=obs['event_id'] if obs else None, context_status='supplied_unverified' if obs else 'not_supplied',
            model=r.get('model','unknown'), agent_config_version=r.get('agent_config_version','unknown'),
            visible_event_ids=r.get('visible_event_ids',[]), visible_message_ids=r.get('visible_message_ids',[]),
            communication_available=r.get('communication_available'), termination_state='imported_update', tool_calls=[])
        store.append(batch, 'task_update', payload, run)
    for run in runs.values():
        store.append(batch, 'run_finished', {'status':'imported'}, run)
    store.append(batch, 'batch_finished', {'status':'imported', 'record_count':len(records)})
    return batch
