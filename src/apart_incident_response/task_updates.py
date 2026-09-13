"""Versioned answer contracts shared by adapters and the experiment controller."""
import json


def update_schema(content, choices):
    properties = {'response_text': {'type': 'string'},
                  'answer_class': {'type': 'string', 'enum': list(choices)}}
    contract = content.get('update_contract', 'answer-v1')
    if contract in ('key-insights-v1', 'locked-database-v1'):
        properties['key_insights'] = {'type': 'array', 'items': {'type': 'string', 'maxLength': 200}, 'maxItems': 3}
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
    if not isinstance(answer['response_text'], str) or not answer['response_text'].strip() or len(answer['response_text']) > 10000:
        raise ValueError('Invalid response_text')
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
    return answer
