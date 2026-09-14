"""Artifact-only analysis. No runtime imports or LLM calls."""
import math
from .semantic import fingerprint
from collections import Counter, defaultdict


def entropy(probabilities):
    if not probabilities or any(not math.isfinite(p) or p < 0 for p in probabilities) or not math.isclose(sum(probabilities), 1.0, abs_tol=1e-9):
        raise ValueError('Entropy requires a normalized finite probability distribution')
    return -sum(p * math.log2(p) for p in probabilities if p)


def analyze(events):
    groups = defaultdict(list)
    evaluation = {e['payload']['update_id']: e['payload'] for e in events if e['kind'] == 'evaluator_result'}
    for e in events:
        if e['kind'] != 'task_update':
            continue
        p = e['payload']
        # Never combine model, task, fixture/import, config or agent-role strata.
        key = (p['task_id'], p.get('difficulty'), p['condition_id'], p['step'], p['agent_id'], p.get('source', 'imported'), p.get('model', 'unknown'), p.get('agent_config_version', 'unknown'),
               p.get('agent_role','solver'),p.get('protocol_id','unknown'),(p.get('model_metadata') or {}).get('digest','unknown'))
        groups[key].append(e)
    rows = []
    for key, samples in sorted(groups.items()):
        task, difficulty, condition, step, agent, source, model, config, role, protocol, model_digest = key
        classified = [e for e in samples if e['payload'].get('answer_class') is not None]
        counts = Counter(e['payload']['answer_class'] for e in classified)
        n = len(classified)
        score_samples = [evaluation[e['event_id']]['score'] for e in samples if e['event_id'] in evaluation
                         and evaluation[e['event_id']].get('score') is not None]
        rows.append(dict(task_id=task, difficulty=difficulty, condition_id=condition, step=step, agent_id=agent, source=source, model=model,
            config_version=config, agent_role=role, protocol_id=protocol, model_digest=model_digest,
            task_versions=sorted({e['payload'].get('task_version','legacy_unspecified') for e in samples}),
            goal_owner=samples[0]['payload'].get('goal_owner'),
            shared_context_mode=samples[0]['payload'].get('shared_context_mode', 'full_history'),
            metric='answer_class_entropy_proxy', metric_version='frequency-bits-v1', unit='bits',
            entropy_bits=entropy([v/n for v in counts.values()]) if n >= 2 else None,
            probabilities={k: v/n for k, v in sorted(counts.items())} if n else {}, counts=dict(counts),
            sample_count=n, unclassified_count=len(samples)-n, status='descriptive' if n >= 2 else 'insufficient_samples',
            score=sum(score_samples)/len(score_samples) if score_samples else None,
            score_sample_count=len(score_samples), source_event_ids=[e['event_id'] for e in samples],
            scope='cross_run_response_per_agent', semantic_entropy_status='not_computed'))
    return rows


def summarize(events):
    runs = {}
    batch = None
    for e in events:
        if e['kind'] == 'batch_started':
            batch = dict(e['payload'], id=e['batch_id'], timestamp=e['timestamp'], status='running')
        elif e['kind'] == 'batch_finished' and batch:
            batch.update(e['payload'])
        if e['kind'] == 'run_started':
            runs[e['run_id']] = dict(e['payload'], id=e['run_id'], status='running', updates=0, completed_steps=0)
        elif e['run_id'] in runs:
            run = runs[e['run_id']]
            if e['kind'] == 'task_update':
                run['updates'] += 1
            elif e['kind'] == 'checkpoint_committed':
                run['completed_steps'] += 1
            elif e['kind'] == 'run_finished':
                run.update(e['payload'])
    return batch, list(runs.values())


def checkpoint_grid(events):
    """Planned researcher rows, including missing cells; never fabricate agent events."""
    batch, runs = summarize(events)
    if not batch:
        return []
    cfg = batch.get('config', {})
    observations = {e['event_id']: e for e in events if e['kind'] == 'agent_observation'}
    evaluation = {e['payload']['update_id']: e for e in events if e['kind'] == 'evaluator_result'}
    by_cell = {}
    for e in events:
        if e['kind'] == 'task_update':
            by_cell.setdefault((e['run_id'], e['payload']['step'], e['payload']['agent_id']), []).append(e)
    run_by_scenario = {(r['task_id'], r['condition_id'], r.get('repeat', 0)): r for r in runs}
    rows = []
    for task in cfg.get('task_ids', []):
        for condition in cfg.get('conditions', []):
            for repeat in range(cfg.get('repeats', 1)):
                run = run_by_scenario.get((task, condition, repeat), {})
                unlock_events = [e for e in events if e['run_id'] == run.get('id') and e['kind'] == 'communication_unlocked']
                for step in range(cfg.get('steps', 0)):
                    for agent in ('A', 'B'):
                        cell = by_cell.get((run.get('id'), step, agent), [])
                        update = cell[-1] if cell else {}
                        p = update.get('payload', {})
                        obs = observations.get(p.get('observation_id'), {})
                        result = evaluation.get(update.get('event_id'), {})
                        context = obs.get('payload', {}).get('messages')
                        rows.append(dict(batch_id=batch['id'], run_id=run.get('id'), task_id=task,
                            task_version=run.get('task_version'), pair_id=run.get('pair_id'), seed=run.get('seed'),
                            difficulty=p.get('difficulty', run.get('task', {}).get('difficulty')),
                            condition_id=condition, repeat=repeat, step=step, checkpoint=step+1, agent_id=agent,
                            agent_role=p.get('agent_role', run.get('task', {}).get('agent_roles', {}).get(agent, 'solver')),
                            run_status=run.get('status', 'not_started'), batch_status=batch['status'],
                            submission_status='missing' if not cell else 'stalled' if p.get('termination_state') == 'stalled_no_generation' else 'valid',
                            duplicate_count=max(0, len(cell)-1), source_event_ids=[e['event_id'] for e in cell],
                            observation_id=obs.get('event_id'), evaluator_event_id=result.get('event_id'),
                            response_text=p.get('response_text'), answer_class=p.get('answer_class'),
                            candidate_key=p.get('candidate_key'), key_insights=p.get('key_insights'),
                            score=result.get('payload', {}).get('score'),
                            communication_available=p.get('communication_available'),
                            visible_message_ids=p.get('visible_message_ids', []),
                            planned_unlock_step=cfg.get('unlock_step') if condition == 'C2' else None,
                            unlock_event_ids=[e['event_id'] for e in unlock_events if e['payload'].get('step', 0) <= step],
                            phase=p.get('phase'), source=p.get('source', batch.get('source')), model=p.get('model', cfg.get('model')),
                            config_version=p.get('agent_config_version', batch.get('config_hash')),
                            prompt_version=p.get('prompt_version', cfg.get('prompt_version')),
                            context_hash=fingerprint(context) if context is not None else None,
                            generation_event_id=p.get('attempt_event_id'), logprobs_available=p.get('logprobs_available', False),
                            logprob_token_count=p.get('logprob_token_count', 0), timestamp=update.get('timestamp'),
                            latency_ms=p.get('latency_ms'), run_elapsed_seconds=p.get('run_elapsed_seconds'),
                            termination_state=p.get('termination_state'), done_reason=p.get('done_reason')))
    return rows


def intervention_changes(metrics, unlock_step):
    """Signed descriptive proxy contrasts, not causal or semantic estimates."""
    if type(unlock_step) is not int or unlock_step < 1:
        return []
    rows = []
    strata = ('task_id', 'difficulty', 'agent_id', 'source', 'model', 'config_version', 'agent_role', 'protocol_id', 'model_digest')
    indexed = {(tuple(m.get(k) for k in strata), m['condition_id'], m['step']): m for m in metrics}
    for (key, condition, step), after in indexed.items():
        if condition != 'C2' or step != unlock_step:
            continue
        before = indexed.get((key, 'C2', step-1), {})
        control_before = indexed.get((key, 'C0', step-1), {})
        control_after = indexed.get((key, 'C0', step), {})
        def difference(a, b):
            return a['entropy_bits']-b['entropy_bits'] if a.get('entropy_bits') is not None and b.get('entropy_bits') is not None else None
        delta = difference(after, before)
        control = difference(control_after, control_before)
        rows.append(dict(zip(strata, key), metric='answer_class_entropy_intervention_proxy', unit='bits',
            before_step=step-1, after_step=step, before_entropy_bits=before.get('entropy_bits'),
            after_entropy_bits=after.get('entropy_bits'), delta_bits=delta,
            C0_delta_bits=control, difference_in_deltas_bits=delta-control if delta is not None and control is not None else None,
            before_sample_count=before.get('sample_count', 0), after_sample_count=after.get('sample_count', 0),
            status='descriptive' if delta is not None else 'insufficient_samples',
            source_event_ids=list(dict.fromkeys(event_id for m in (before, after, control_before, control_after)
                                               for event_id in m.get('source_event_ids', []))),
            semantic_entropy_status='not_computed', causal_claim=False))
    return rows
