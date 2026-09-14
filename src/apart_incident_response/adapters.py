"""Controller-owned model transport; no agent tools or general network capability."""
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .task_updates import update_schema


class OllamaAdapter:
    source = 'local_model'

    def __init__(self, model='gemma2:2b', endpoint=None, logprobs=False):
        self.model = model
        self.endpoint = (endpoint or os.environ.get('APART_OLLAMA_URL', 'http://127.0.0.1:11434')).rstrip('/')
        self.logprobs = bool(logprobs)
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.path not in ('', '/') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Model endpoint must be an HTTP(S) origin without credentials or query')
        self.source = 'local_model' if parsed.hostname in ('localhost', '127.0.0.1', '::1') else 'remote_model'

    def request(self, route, payload=None, timeout=180):
        headers = {'Content-Type': 'application/json'}
        token = os.environ.get('APART_MODEL_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(self.endpoint + route, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)

    def metadata(self):
        tags = self.request('/api/tags', timeout=4)
        match = next((m for m in tags.get('models', []) if m.get('name') == self.model or m.get('model') == self.model), None)
        if not match:
            raise ValueError(f'Model {self.model} is not installed at the configured endpoint')
        return {'adapter': 'ollama-chat-v1', 'model': self.model, 'digest': match.get('digest'), 'details': match.get('details'),
                'runtime': self.request('/api/version', timeout=4), 'transport': self.source}

    def generate(self, messages, seed, max_output_tokens, choices):
        return self.generate_bounded(messages, seed, max_output_tokens, choices, 180)

    def generate_bounded(self, messages, seed, max_output_tokens, choices, timeout_seconds):
        started = time.monotonic()
        schema = update_schema(json.loads(messages[-1]['content']), choices)
        payload = {'model': self.model, 'messages': messages, 'format': schema, 'stream': False,
                    'options': {'temperature': 0.6, 'seed': seed, 'num_predict': max_output_tokens, 'num_ctx': 8192}, 'keep_alive': '10m'}
        if self.logprobs:
            payload.update(logprobs=True, top_logprobs=5)
        try:
            result = self.request('/api/chat', payload, timeout=timeout_seconds)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError('provider transport timeout') from exc
            raise
        logprobs_available = self.logprobs
        entries = result.get('logprobs')
        if self.logprobs and not entries:
            logprobs_available = False
        compact = [{'token': e.get('token'), 'logprob': e.get('logprob'),
                    'top': [{'token': t.get('token'), 'logprob': t.get('logprob')} for t in (e.get('top_logprobs') or [])]}
                   for e in entries] if entries else None
        return {'raw_response': result.get('message', {}).get('content', ''), 'model': result.get('model', self.model),
                'input_tokens': result.get('prompt_eval_count'), 'output_tokens': result.get('eval_count'),
                'latency_ms': round((time.monotonic()-started)*1000), 'done_reason': result.get('done_reason'),
                'provider_duration_ns': result.get('total_duration'), 'logprobs': compact,
                'logprobs_available': logprobs_available}


class FixtureAdapter:
    """Transparent deterministic plumbing fixture, never labeled LLM evidence."""
    source = 'fixture'
    model = 'deterministic-fixture-v1'

    def metadata(self):
        return {'adapter': self.model, 'model': self.model, 'transport': 'fixture'}

    def generate(self, messages, seed, max_output_tokens, choices):
        context = json.loads(messages[-1]['content'])
        answer = list(choices)[seed % len(choices)]
        update = {'response_text': f'Synthetic plumbing fixture: candidate {answer}. This is not a model generation.', 'answer_class': answer}
        contract = context.get('update_contract')
        if contract in ('key-insights-v1', 'locked-database-v1', 'collaboration-v1'):
            update['key_insights'] = []
        if contract == 'collaboration-v1':
            import re
            facts = ' '.join(context['private_evidence'])+' '+json.dumps(context['permitted_history'])
            role = context['agent_role']
            if 'healthy' in choices:
                one = re.search(r'sensor_one=([01])',facts)
                two = re.search(r'sensor_two=([01])',facts)
                answer = ('healthy','pump','valve','controller')[int(one[1])*2+int(two[1])] if one and two else list(choices)[seed%4]
            else:
                answer = 'blue' if 'blue' in choices else 'routing'
            update.update(answer_class=answer, evidence_ids=context['allowed_evidence_ids'],
                referenced_message_ids=context['visible_message_ids'],
                message_type='counterexample' if role=='critic' else 'proposal',
                rejected_option=('amber' if 'amber' in choices else 'logging') if role=='critic' else '',
                request_peer_context=True,
                response_text='Synthetic fixture. '+ ' '.join(context['private_evidence']))
        if contract == 'locked-database-v1':
            key = ''
            if context['agent_role'] == 'feedback_only':
                excerpt = context['private_evidence'][0].split(': ', 1)[1]
                key = json.loads(excerpt)['unlock_key']
                update.update(answer_class='feedback_only', candidate_key='', key_insights=[f'Synthetic unlock_key: {key}'],
                              response_text=f'Synthetic plumbing fixture feedback: unlock_key={key}. Not a model generation.')
            else:
                import re
                peer_text = json.dumps([e for e in context['permitted_history'] if e['agent'] == 'A'])
                match = re.search(r'TEST_ONLY_E1_[a-f0-9]{24}', peer_text)
                key = match.group() if match else ''
                update.update(answer_class='unlocked' if key else 'locked', candidate_key=key)
        raw = json.dumps(update)
        return {'raw_response': raw, 'model': self.model, 'input_tokens': None, 'output_tokens': None,
                'latency_ms': 0, 'done_reason': 'fixture', 'provider_duration_ns': 0}
