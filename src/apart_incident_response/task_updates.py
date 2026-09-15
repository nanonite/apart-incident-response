"""Versioned answer contracts shared by adapters and the experiment controller."""
import json


def update_schema(content, choices):
    properties = {'response_text': {'type': 'string'},
                  'answer_class': {'type': 'string', 'enum': list(choices)}}
    contract = content.get('update_contract', 'answer-v1')
    if contract in ('key-insights-v1', 'locked-database-v1', 'collaboration-v1', 'creative-collab-v1'):
        properties['key_insights'] = {'type': 'array', 'items': {'type': 'string', 'maxLength': 200}, 'maxItems': 3}
    if contract in ('collaboration-v1', 'creative-collab-v1'):
        role = content['agent_role']
        message_types = ['counterexample' if role=='critic' else 'proposal']
        if contract == 'creative-collab-v1':
            message_types = ['draft' if role in ('opening_poet','historical_drafter') else 'revision']
        properties.update(
            evidence_ids={'type':'array','items':{'type':'string','enum':content['allowed_evidence_ids']}, 'maxItems':8},
            referenced_message_ids={'type':'array','items':{'type':'string'}, 'maxItems':16},
            message_type={'type':'string','enum':message_types},
            rejected_option={'type':'string','enum':list(choices) if role=='critic' else ['']},
            request_peer_context={'type':'boolean'})
    if contract == 'locked-database-v1':
        properties['candidate_key'] = {'type': 'string', 'maxLength': 96}
        if content.get('agent_role') == 'feedback_only':
            properties['candidate_key']['enum'] = ['']
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def parse_update(raw, content, choices):
    answer = json.loads(raw)
    schema = update_schema(content, choices)
    if not isinstance(answer, dict) or set(answer) != set(schema['properties']):
        raise ValueError('Output fields must match ' + content.get('update_contract', 'answer-v1'))
    max_chars = 50000 if content.get('update_contract') == 'creative-collab-v1' else 10000
    if not isinstance(answer['response_text'], str) or not answer['response_text'].strip() or len(answer['response_text']) > max_chars:
        raise ValueError('Invalid response_text')
    if content.get('update_contract') == 'creative-collab-v1' and len(answer['response_text'].split()) > int(content.get('max_words', 5000)):
        raise ValueError('Creative response exceeds max_words')
    if not isinstance(answer['answer_class'], str) or answer['answer_class'] not in choices:
        raise ValueError('Unknown or role-forbidden answer_class')
    if 'key_insights' in answer:
        insights = answer['key_insights']
        if not isinstance(insights, list) or len(insights) > 3 or any(not isinstance(s, str) or not s.strip() or len(s) > 200 for s in insights):
            raise ValueError('key_insights must contain at most three short, nonempty strings')
    if 'candidate_key' in answer:
        if not isinstance(answer['candidate_key'], str) or len(answer['candidate_key']) > 96:
            raise ValueError('Invalid candidate_key')
        if content.get('agent_role') == 'feedback_only' and answer['candidate_key']:
            raise ValueError('Agent A may share feedback but cannot submit a goal candidate')
    if content.get('update_contract') in ('collaboration-v1', 'creative-collab-v1'):
        if type(answer['request_peer_context']) is not bool:
            raise ValueError('request_peer_context must be boolean')
        for field, allowed, limit in [('evidence_ids',content['allowed_evidence_ids'],8),
                                      ('referenced_message_ids',content['visible_message_ids'],16)]:
            items = answer[field]
            if not isinstance(items,list) or len(items)>limit or any(not isinstance(x,str) or x not in allowed for x in items) or len(items)!=len(set(items)):
                raise ValueError('Invalid or invisible '+field)
        if not answer['evidence_ids']:
            raise ValueError('At least one supplied evidence ID must be cited')
        if content.get('update_contract') == 'creative-collab-v1':
            expected = 'draft' if content['agent_role'] in ('opening_poet','historical_drafter') else 'revision'
        else:
            expected = 'counterexample' if content['agent_role']=='critic' else 'proposal'
        if answer['message_type'] != expected:
            raise ValueError('Role-forbidden message_type')
        rejected = answer['rejected_option']
        if content['update_contract'] == 'creative-collab-v1':
            if rejected != '':
                raise ValueError('Creative tasks do not use rejected_option')
        elif content['agent_role']=='critic':
            if not isinstance(rejected,str) or rejected not in choices or rejected==answer['answer_class']:
                raise ValueError('Critic must reject a different candidate')
        elif rejected != '':
            raise ValueError('Only critics may submit rejected_option')
    return answer
