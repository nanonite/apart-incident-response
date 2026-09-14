"""Whole-message projections. No observer annotations enter agent contexts."""
import json


def record(event):
    p = event['payload']
    result = {'agent':p['agent_id'], 'step':p['step'], 'response_text':p['response_text'], 'answer_class':p['answer_class']}
    for field in ('key_insights','candidate_key','evidence_ids','rejected_option','message_type','referenced_message_ids','request_peer_context'):
        if field in p:
            result[field] = p[field]
    return result


def project(history, agent, step, condition, cfg):
    available = condition=='C1' or condition=='C2' and step>=cfg['unlock_step']
    own = [e for e in history if e['payload']['agent_id']==agent and e['payload']['step']<step]
    eligible = [e for e in history if e['payload']['agent_id']!=agent and
                e['payload']['step'] < step-cfg.get('communication_delay_steps',0)] if available else []
    requested = bool(own and own[-1]['payload'].get('request_peer_context'))
    pool = eligible if not cfg.get('communication_request_required') or requested else []
    budget = cfg.get('communication_budget_bytes')
    delivered, used = [], 0
    # Prefer recent whole messages; never expose a partial synthetic key or JSON object.
    for e in reversed(pool):
        size = len(json.dumps(record(e), ensure_ascii=False, sort_keys=True).encode())
        if budget is None or used+size <= budget:
            delivered.append(e)
            used += size
    ids = {e['event_id'] for e in own+delivered}
    visible = [e for e in history if e['event_id'] in ids]
    return visible, {'communication_available':available, 'requested':requested,
        'eligible_message_ids':[e['event_id'] for e in eligible],
        'delivered_message_ids':[e['event_id'] for e in reversed(delivered)],
        'omitted_message_ids':[e['event_id'] for e in eligible if e not in delivered],
        'delivered_bytes':used, 'cost':used/1024*cfg.get('communication_cost_per_kib',0),
        'cost_unit':'configured_utility_units', 'byte_scope':'serialized_peer_records_utf8',
        'policy_version':'whole-message-v1', 'selection_order':'newest_first_whole_records'}
