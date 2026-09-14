"""Artifact-only reliability, cost, and team outcome projections."""
from collections import Counter, defaultdict
import math


def calibration_summary(events):
    started=[e for e in events if e['kind']=='generation_started']
    updates=[e for e in events if e['kind']=='task_update']
    valid=[e for e in updates if e['payload'].get('termination_state')!='stalled_no_generation']
    latencies=sorted(e['payload']['latency_ms']/1000 for e in updates if isinstance(e['payload'].get('latency_ms'),(int,float)))
    cfg=next((e['payload'].get('config',{}) for e in events if e['kind']=='batch_started'),{})
    p95=latencies[max(0,math.ceil(len(latencies)*.95)-1)] if latencies else None
    expected=cfg.get('expected_updates',0)
    return {'attempted_requests':len(started),'planned_updates':expected,'valid_updates':len(valid),
        'stalled_updates':len(updates)-len(valid),'missing_updates':max(0,expected-len(updates)),
        'valid_output_rate':len(valid)/len(started) if started else None,
        'submission_coverage':len(updates)/expected if expected else None,
        'latency_p95_seconds':p95,'latency_mean_seconds':sum(latencies)/len(latencies) if latencies else None,
        'estimated_serial_run_seconds':p95*cfg.get('steps',5)*2 if p95 is not None else None,
        'estimate_scope':'p95 observed controller waits times requests; excludes setup/IO, censored failures may bias estimate',
        'failure_counts':dict(Counter(e['payload'].get('failure_kind','legacy_unspecified') for e in updates if e not in valid)),
        'source_event_ids':[e['event_id'] for e in started+updates],
        'source':next((e['payload'].get('source') for e in events if e['kind']=='batch_started'),None)}


def team_metrics(events):
    scored=defaultdict(list); delivered=defaultdict(list)
    for e in events:
        if e['kind']=='evaluator_result' and e['payload'].get('score') is not None:
            scored[(e['run_id'],e['payload']['step'])].append(e)
        elif e['kind']=='communication_delivery':
            delivered[(e['run_id'],e['payload']['step'])].append(e)
    rows=[]
    for key in sorted(scored.keys() | delivered.keys()):
        result=scored[key]; messages=delivered[key]
        score=sum(e['payload']['score'] for e in result)/len(result) if result else None
        cost=sum(e['payload'].get('cost',0) for e in messages)
        actors=sorted({e['payload']['agent_id'] for e in result})
        rows.append({'run_id':key[0],'step':key[1],'metric_version':'team-mean-minus-delivery-cost-v1',
            'mean_scored_answer':score,'scored_agents':actors,'complete_two_agent_score':actors==['A','B'],
            'delivered_bytes':sum(e['payload'].get('delivered_bytes',0) for e in messages),
            'communication_cost':cost,'net_utility':score-cost if score is not None and actors==['A','B'] else None,
            'source_event_ids':[e['event_id'] for e in result+messages],
            'scope':'checkpoint_descriptive; team net utility only when both agents are scored'})
    return rows
