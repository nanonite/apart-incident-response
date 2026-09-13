"""Artifact-only analysis. No runtime imports or LLM calls."""
import math
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
        key = (p['task_id'], p.get('difficulty'), p['condition_id'], p['step'], p['agent_id'], p.get('source', 'imported'), p.get('model', 'unknown'), p.get('agent_config_version', 'unknown'))
        groups[key].append(e)
    rows = []
    for key, samples in sorted(groups.items()):
        task, difficulty, condition, step, agent, source, model, config = key
        classified = [e for e in samples if e['payload'].get('answer_class') is not None]
        counts = Counter(e['payload']['answer_class'] for e in classified)
        n = len(classified)
        score_samples = [evaluation[e['event_id']]['score'] for e in samples if e['event_id'] in evaluation]
        rows.append(dict(task_id=task, difficulty=difficulty, condition_id=condition, step=step, agent_id=agent, source=source, model=model,
            config_version=config, metric='answer_class_entropy_proxy', metric_version='frequency-bits-v1', unit='bits',
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
