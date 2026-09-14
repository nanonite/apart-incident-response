"""Local research control panel. Run with PYTHONPATH=src python -m apart_incident_response.panel."""
import argparse
import io
import json
import mimetypes
import os
import secrets
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .analysis import analyze, summarize, checkpoint_grid, intervention_changes
from .events import EventStore
from .experiment import BatchRunner, validate_config
from .importing import import_jsonl
from .tasks import public_tasks
from .diagnostics import calibration_summary, team_metrics

ROOT = Path(__file__).resolve().parents[2]
PANEL_API_VERSION = 'response-panel-v7'


def live_activity(events, batch, runs):
    """Researcher projection of recorded activity; never supplied to agents."""
    finished = any(e['kind'] == 'batch_finished' for e in events)
    running = [r for r in runs if r['status'] == 'running']
    run = (running[-1] if running and not finished else runs[-1]) if runs else None
    scoped = [e for e in events if run and e['run_id'] == run['id']]
    by_id = {e['event_id']: e for e in scoped}
    evaluations = {e['payload']['update_id']: e['payload'] for e in scoped if e['kind'] == 'evaluator_result'}
    step = max((e['payload']['step'] for e in scoped if type(e['payload'].get('step')) is int), default=None)
    agents = {}
    visible_to = {}
    insights_by_source = {}
    terminal = finished or bool(run and run['status'] != 'running')
    for agent in ('A', 'B'):
        own = [e for e in scoped if e['payload'].get('agent_id') == agent]
        observations = [e for e in own if e['kind'] == 'agent_observation']
        observation = observations[-1] if observations else None
        for event_id in (observation or {}).get('payload', {}).get('visible_message_ids', []):
            visible_to.setdefault(event_id, []).append(agent)
        for insight in (observation or {}).get('payload', {}).get('shared_key_insights', []):
            key = (insight['source_event_id'], insight['text'])
            entry = insights_by_source.setdefault(key, dict(insight, visible_to=[]))
            entry['visible_to'].append(agent)
        transitions = [e for e in own if e['kind'] in ('agent_observation', 'generation_started', 'generation_result', 'generation_finished', 'task_update', 'minute_violation')]
        last = transitions[-1] if transitions else None
        state_name = 'waiting'
        if last:
            state_name = {'agent_observation': 'queued', 'generation_started': 'generating',
                          'generation_result': 'validating', 'generation_finished':'validating', 'minute_violation': 'stalled', 'task_update': 'submitted'}[last['kind']]
            if last['kind']=='generation_finished' and last['payload']['status']!='valid':
                state_name='stalled'
            if last['kind'] == 'task_update' and last['payload'].get('termination_state') == 'stalled_no_generation':
                state_name = 'stalled'
        if terminal and state_name not in ('submitted', 'stalled'):
            state_name = 'interrupted' if last else 'not_started'
        transcript = [dict(e['payload'], event_id=e['event_id'], timestamp=e['timestamp'],
                           evaluator=evaluations.get(e['event_id'])) for e in own if e['kind'] == 'task_update']
        agents[agent] = {'state': state_name, 'step': (last or {}).get('payload', {}).get('step'),
                         'request_deadline_seconds':next((e['payload'].get('request_deadline_seconds') for e in reversed(own) if e['kind']=='generation_started'),None),
                         'heartbeat_at':next((e['timestamp'] for e in reversed(own) if e['kind']=='worker_heartbeat'),None),
                         'provider_cancellation_status':next((e['payload'].get('provider_cancellation_status') for e in reversed(own) if e['kind']=='generation_finished'),None),
                         'last_event_id': last['event_id'] if last else None,
                         'state_since': last['timestamp'] if last else None,
                         'observation': observation['payload'] if observation else None,
                         'updates': transcript}
    # Only peer responses actually included in the latest observations belong here.
    # Private task bundles and researcher annotations are excluded.
    shared = [dict(event_id=e['event_id'], timestamp=e['timestamp'], agent_id=e['payload']['agent_id'],
                   step=e['payload']['step'], response_text=e['payload']['response_text'],
                   key_insights=e['payload'].get('key_insights', []), candidate_key=e['payload'].get('candidate_key'),
                   visible_to=visible_to[event_id])
              for event_id in visible_to for e in [by_id.get(event_id)] if e and e['kind'] == 'task_update']
    shared.sort(key=lambda e: (e['step'], e['agent_id']))
    query = urlencode({'batch': batch['id']}) if batch else ''
    return {'batch_status': batch['status'] if batch else 'idle', 'run': run, 'step': step,
            'batch_started_at':next((e['timestamp'] for e in events if e['kind']=='batch_started'),None),
            'batch_finished_at':next((e['timestamp'] for e in events if e['kind']=='batch_finished'),None),
            'run_started_at': next((e['timestamp'] for e in scoped if e['kind'] == 'run_started'), None),
            'run_finished_at': next((e['timestamp'] for e in scoped if e['kind'] == 'run_finished'),
                                    next((e['timestamp'] for e in events if e['kind'] == 'batch_finished'), None)),
            'last_event_at': next((e['timestamp'] for e in reversed(events)
                                  if e['kind'] != 'researcher_action'), None), 'agents': agents,
            'shared_history': shared, 'shared_key_insights': list(insights_by_source.values()),
            'feed': [dict(event_id=e['event_id'], timestamp=e['timestamp'], kind=e['kind'],
                          step=e['payload'].get('step'), agent_id=e['payload'].get('agent_id') or e['payload'].get('recipient'),
                          detail=e['payload'].get('message') or e['payload'].get('reason') or e['payload'].get('status'))
                     for e in events if (run and e['run_id'] == run['id']) or not e['run_id']][-40:],
            'exports': {'ready': finished, 'available': bool(batch), 'partial': not finished,
                        'bundle_url': '/api/export?' + query if batch else None,
                        'responses_url': '/api/responses?' + query if batch else None}}


def state(store, selected=None):
    all_events = store.read()
    batches = []
    for batch_id in dict.fromkeys(e['batch_id'] for e in all_events):
        events = [e for e in all_events if e['batch_id'] == batch_id]
        batch, _ = summarize(events)
        if batch:
            batches.append(batch)
    selected = selected or (batches[-1]['id'] if batches else None)
    events = [e for e in all_events if e['batch_id'] == selected]
    batch, runs = summarize(events)
    metrics = analyze(events)
    by_difficulty = {}
    for row in metrics:
        key = str(row.get('difficulty'))
        by_difficulty.setdefault(key, {'difficulty': row.get('difficulty'), 'rows': 0, 'scores': [], 'entropy_bits': []})
        by_difficulty[key]['rows'] += 1
        if row.get('score') is not None:
            by_difficulty[key]['scores'].append(row['score'])
        if row.get('entropy_bits') is not None:
            by_difficulty[key]['entropy_bits'].append(row['entropy_bits'])
    for item in by_difficulty.values():
        item['accuracy'] = sum(item['scores']) / len(item['scores']) if item['scores'] else None
        item['mean_entropy_bits'] = sum(item['entropy_bits']) / len(item['entropy_bits']) if item['entropy_bits'] else None
        del item['scores']; del item['entropy_bits']
    return {'schema_version':'1.1', 'mode':'live',
            'server': {'api_version': PANEL_API_VERSION, 'pid': os.getpid(), 'source_root': str(ROOT)},
            'tasks':public_tasks(), 'batches':list(reversed(batches)),
            'batch':batch, 'runs':runs, 'events':events, 'metrics':metrics,
            'calibration':calibration_summary(events), 'team_metrics':team_metrics(events),
            'difficulty_metrics': sorted(by_difficulty.values(), key=lambda x: (x['difficulty'] is None, x['difficulty'])),
            'audit':research_actions(all_events), 'live_activity': live_activity(events, batch, runs)}


def report_markdown(data):
    batch = data.get('batch') or {}
    export = data.get('export_metadata') or export_metadata(data)
    lines = [f"# Experiment report: {batch.get('id', 'unknown')}", '',
             f"Status: **{batch.get('status', 'unknown')}**", '',
             f"Export: **{export['kind']}** · captured {export['captured_at']}.", '',
             f"Source: **{batch.get('source', 'unknown')}** · {export['response_count']} recorded updates.", '',
             'Running-batch exports contain only events recorded at the stated cutoff; later responses are excluded.', '',
             'Fixture data is deterministic plumbing, not model evidence. Entropy below is an answer-class proxy, not semantic entropy.', '',
             '| Condition | Scored checkpoints | Mean task score |',
             '|---|---:|---:|']
    run_conditions = {r['id']: r['condition_id'] for r in data.get('runs', [])}
    condition_scores = {}
    for event in data.get('events', []):
        if event['kind'] == 'evaluator_result' and event['payload'].get('score') is not None:
            condition = run_conditions.get(event.get('run_id'), 'unknown')
            condition_scores.setdefault(condition, []).append(event['payload']['score'])
    for condition, scores in sorted(condition_scores.items()):
        lines.append(f"| {condition} | {len(scores)} | {sum(scores)/len(scores):.3f} |")
    lines += ['', 'Scores pool recorded, scored checkpoints; they are not per-run success rates. Feedback-only agents receive no goal score.', '',
             '| Difficulty | Rows | Accuracy | Mean answer-class entropy (bits) |',
             '|---:|---:|---:|---:|']
    for row in data.get('difficulty_metrics', []):
        acc = '' if row.get('accuracy') is None else f"{row['accuracy']:.3f}"
        ent = '' if row.get('mean_entropy_bits') is None else f"{row['mean_entropy_bits']:.3f}"
        lines.append(f"| {row.get('difficulty')} | {row.get('rows', 0)} | {acc} | {ent} |")
    warnings = [e for e in data.get('events', []) if e.get('kind') == 'minute_violation' or
                (e.get('kind') == 'task_update' and e.get('payload', {}).get('termination_state') == 'stalled_no_generation')]
    lines += ['', f"Warnings: **{len(warnings)}** minute violations or stalled submissions.",
              '', 'Metrics are derived from stored events and never fed back into a running agent.', '',
              '## Task and configuration', '',
              f"Model: `{batch.get('config', {}).get('model', 'unknown')}`. "
              f"Checkpoints: {batch.get('config', {}).get('steps', 'unknown')}. "
              f"Unlock step: {batch.get('config', {}).get('unlock_step', 'unknown')}."]
    tasks = {}
    for run in data.get('runs', []):
        task = run.get('task') or {}
        tasks.setdefault(run['task_id'], task)
    for task_id, task in tasks.items():
        lines += ['', f"### {task.get('title', task_id)}", '',
                  f"Difficulty: {task.get('difficulty', 'unknown')}/5. " + task.get('question', 'Task text was not supplied.')]
    lines += ['', '## Scheduled-unlock comparison', '']
    cfg = batch.get('config', {})
    if 'C2' not in cfg.get('conditions', []):
        lines.append('This batch has no C2 intervention; C0/C1 comparisons cannot estimate a within-run unlock change.')
    else:
        lines += ['Signed answer-class entropy proxies only; evolving histories are not fixed-context semantic samples.', '',
                  '| Task | Agent | Before step | After step | Delta bits | C0 delta bits |',
                  '|---|---|---:|---:|---:|---:|']
        for row in intervention_changes(data.get('metrics', []), cfg.get('unlock_step')):
            delta = 'null' if row['delta_bits'] is None else f"{row['delta_bits']:.3f}"
            control = 'null' if row['C0_delta_bits'] is None else f"{row['C0_delta_bits']:.3f}"
            lines.append(f"| {row['task_id']} | {row['agent_id']} | {row['before_step']} | {row['after_step']} | {delta} | {control} |")
    cutoff = export['event_log_cutoff']
    lines += ['', '## Audit and source data', '',
              f"Cutoff event: `{cutoff.get('event_id', 'none')}` · sequence {cutoff.get('seq', 'none')}.",
              '', 'Use events.jsonl for raw events, responses.jsonl for exact agent contexts and evaluator results, '
              'metrics.jsonl for source_event_ids, and manifest.json for configuration, source versions, and export metadata.',
              '', 'Incomplete/stalled submissions remain explicit. No causal influence or semantic entropy is claimed.']
    return '\n'.join(lines) + '\n'


def export_metadata(data):
    """Cutoff/provenance for a frozen researcher download, including partial batches."""
    batch = data.get('batch') or {}
    events = data.get('events', [])
    terminal = any(e['kind'] == 'batch_finished' for e in events)
    last = events[-1] if events else {}
    return {'kind': 'completed' if terminal else 'partial',
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'batch_status': batch.get('status', 'unknown'), 'source': batch.get('source', 'unknown'),
            'event_count': len(events), 'response_count': sum(e['kind'] == 'task_update' for e in events),
            'event_log_cutoff': {k: last[k] for k in ('event_id', 'seq', 'timestamp', 'hash') if k in last}}


def responses(events):
    observations = {e['event_id']:e['payload'] for e in events if e['kind'] == 'agent_observation'}
    evaluations = {e['payload']['update_id']:e['payload'] for e in events if e['kind'] == 'evaluator_result'}
    for e in events:
        if e['kind'] == 'task_update':
            yield dict(e['payload'], event_id=e['event_id'], timestamp=e['timestamp'],
                       observation=observations.get(e['payload'].get('observation_id')),
                       evaluator=evaluations.get(e['event_id']))


def research_actions(events):
    """Audit trail: what a researcher did in the panel, in event order."""
    return [dict(e['payload'], seq=e['seq'], event_id=e['event_id'], batch_id=e['batch_id'],
                 timestamp=e['timestamp']) for e in events if e['kind'] == 'researcher_action']


def audit_action(store, batch_id, action, **detail):
    return store.append(batch_id or 'research', 'researcher_action', dict(action=action, **detail))


def projection_step(events, step, agent_order=('A', 'B')):
    """Global vs per-agent visibility at a discrete 0-based step, from stored records only.

    The global pane includes private evidence and evaluator truth that no agent ever sees.
    Each agent pane contains exactly the events the agent could have received
    (stored ``visible_event_ids``) plus its own records for that step.
    """
    global_up = [e for e in events if e['payload'].get('step') is None or e['payload']['step'] <= step]
    agents, communication = {}, {}
    for agent in agent_order:
        obs = next((e for e in events if e['kind'] == 'agent_observation'
                    and e['payload'].get('agent_id') == agent and e['payload'].get('step') == step), None)
        visible = set((obs or {}).get('payload', {}).get('visible_event_ids') or [])
        for e in events:
            if e['kind'] == 'task_update' and e['payload'].get('agent_id') == agent and e['payload'].get('step') == step:
                visible |= set(e['payload'].get('visible_event_ids') or [])
        agents[agent] = {'visible_event_ids': sorted(visible),
                         'visible_events': [e for e in global_up if e['event_id'] in visible],
                         'observation': obs['payload'] if obs else None}
        communication[agent] = bool(obs['payload'].get('communication_available')) if obs else None
    return {'step': step, 'minute': step + 1, 'global': global_up, 'agents': agents,
            'communication_available': communication,
            'note': 'Global includes private evidence and evaluator truth that no agent sees.',
            'source': 'stored_visible_event_ids'}


def bundle(data):
    data = dict(data, export_metadata=export_metadata(data))
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        def jl(name, values):
            z.writestr(name, ''.join(json.dumps(v,ensure_ascii=False,allow_nan=False)+'\n' for v in values))
        jl('events.jsonl', data['events'])
        jl('responses.jsonl', responses(data['events']))
        jl('metrics.jsonl', data['metrics'])
        jl('checkpoint-grid.jsonl', checkpoint_grid(data['events']))
        jl('intervention-proxy.jsonl', intervention_changes(data['metrics'], (data.get('batch') or {}).get('config', {}).get('unlock_step')))
        jl('team-metrics.jsonl',team_metrics(data['events']))
        z.writestr('calibration.json',json.dumps(calibration_summary(data['events']),allow_nan=False,indent=2))
        z.writestr('report.md', report_markdown(data))
        z.writestr('manifest.json', json.dumps({k:v for k,v in data.items() if k not in ('events','metrics','session_key')},ensure_ascii=False,indent=2))
        z.writestr('README.md', '''# Research handoff

Events are the researcher-visible ground truth. Each response links to its exact supplied observation, evaluator and source events. See manifest.json for protocol, configuration, model provenance, task definitions and completion status.

Start with report.md for a human-readable summary. manifest.json export_metadata records whether this is a partial or completed export and the exact last included event. An active-run download never includes later events or changes the agents' inputs.

checkpoint-grid.jsonl is a derived planned task × condition × repeat × checkpoint × agent table. submission_status distinguishes missing, stalled, and valid records, including runs not started. Missing rows are researcher annotations, not fabricated agent outputs. Join generation_event_id to events.jsonl for raw model responses and any exposed token log-probabilities; join observation_id for the exact prompt. context_hash identifies identical supplied message contexts, not identical provider hidden state.

intervention-proxy.jsonl records signed C2 entropy contrasts immediately around unlock and the corresponding C0 change, where available. It preserves source IDs and null for insufficient samples. These are descriptive answer-class proxies, not semantic entropy, statistical evidence, or causal influence.

calibration.json reports attempts, valid-output rate, coverage, latency and limitations of the serial-duration estimate. team-metrics.jsonl separates task correctness, role participation, delivery byte costs and net utility. worker_heartbeat denotes controller waiting, not provider token generation. generation_finished terminates a controller attempt; unknown cancellation does not establish provider termination. Semantic analysis and paired replay run separately on completed exports through apart_incident_response.offline and apart_incident_response.semantic.

C0 is isolation; C1 shares previous-step responses; C2 unlocks earlier permitted responses at the configured step. Neither agent sees the other's current-step output. Private evidence and evaluator truth never enter shared history.

Sources: local_model/remote_model = actual inference; fixture = deterministic non-LLM plumbing data; imported = user-supplied, unverified provenance. Failed/incomplete records are not silently filled.

metrics.jsonl contains per-agent cross-run ANSWER-CLASS ENTROPY PROXIES in bits for the finite task options. It is NOT entailment-based semantic entropy and is not a causal metric. Fewer than two classified samples yields null, not zero. Repetitions and agents are not independent observations. Exact-option scores assess the selected option. Experiment 1 instead verifies B's proposed key by decrypting synthetic SQLite data; A's feedback receives no goal score. Neither evaluator grades explanation quality.

For semantic entropy, cluster response_text (or a versioned answer extraction) using an explicitly validated equivalence rule. Preserve source_event_ids and grouping scope. Different evolving histories are not identical fixed-checkpoint contexts. No analysis is fed back to the agents.

The university security task is synthetic static text. No real university website is accessed. The batch export's hash chain may start from an earlier event in another batch; verify against the full store for global continuity.
''')
    return output.getvalue()


class App:
    def __init__(self, store):
        self.store = store
        self.key = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.runner = None
        self.thread = None
        self.batch_id = None

    def snapshot(self, selected=None):
        data = state(self.store, selected)
        worker_alive = bool(self.thread and self.thread.is_alive())
        batch = data.get('batch') or {}
        owns_selected = worker_alive and batch.get('id') == self.batch_id
        terminal = any(e['kind'] == 'batch_finished' for e in data['events'])
        data['can_stop'] = worker_alive
        data['execution'] = {'state': 'terminal' if terminal else 'verified_worker' if owns_selected
                             else 'unverified' if batch else 'idle',
                             'worker_batch_id': self.batch_id if worker_alive else None,
                             'explanation': 'No batch_finished event. This server has no verified worker for this batch; '
                             'a CLI or another server may own it. Request age is not model compute time.'
                             if batch and not terminal and not owns_selected else None}
        data['execution']['worker'] = self.runner.owner if owns_selected and self.runner else None
        data['execution']['observed_at'] = datetime.now(timezone.utc).isoformat()
        return data

    def launch(self, config):
        validate_config(config)
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('A batch is already running')
            snapshot = state(self.store)
            if any(b['status'] == 'running' for b in snapshot['batches']):
                raise ValueError('A CLI or earlier batch is running; wait for its terminal event')
            self.runner = BatchRunner(self.store)
            self.batch_id = 'batch-' + uuid.uuid4().hex[:12]
            self.thread = threading.Thread(target=self.runner.run, args=(config, self.batch_id), daemon=True)
            self.thread.start()
            return self.batch_id


def serve(store, port):
    app = App(store)
    static = ROOT / 'dashboard' / 'dist'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if args and isinstance(args[0], str) and '/api/state' in args[0]:
                return
            super().log_message(fmt, *args)

        def reply(self, status, body, kind='application/json', filename=None):
            if kind == 'application/json':
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
            if filename:
                self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def trusted_host(self):
            return self.headers.get('Host') in (f'localhost:{port}', f'127.0.0.1:{port}')

        def do_GET(self):
            if not self.trusted_host():
                return self.reply(403, {'error':'Local host required'})
            parsed = urlparse(self.path)
            selected = parse_qs(parsed.query).get('batch', [None])[0]
            if parsed.path == '/api/state':
                data = app.snapshot(selected)
                data['session_key'] = app.key
                return self.reply(200, data)
            if parsed.path == '/api/projections':
                try:
                    step = int(parse_qs(parsed.query).get('step', [''])[0])
                except ValueError:
                    return self.reply(400, {'error': 'step (0-based) is required'})
                run_id = parse_qs(parsed.query).get('run', [None])[0]
                events = state(store, selected)['events']
                if run_id:
                    events = [e for e in events if e.get('run_id') == run_id or not e.get('run_id')]
                return self.reply(200, projection_step(events, step))
            if parsed.path == '/api/audit':
                return self.reply(200, research_actions(state(store, selected)['events']))
            if parsed.path == '/api/task-pool':
                return self.reply(200, {'mode': 'read_only', 'tasks': public_tasks(),
                                        'message': 'Task editing is intentionally disabled for controlled runs.'})
            if parsed.path == '/api/report':
                data = state(store, selected)
                if not data['batch']:
                    return self.reply(404, {'error': 'Batch not found'})
                audit_action(store, data['batch']['id'], 'report_generated')
                return self.reply(200, report_markdown(data).encode(), 'text/markdown', 'experiment-report.md')
            if parsed.path == '/api/export':
                data = state(store, selected)
                if not data['batch']:
                    return self.reply(404, {'error':'Batch not found'})
                audit_action(store, data['batch']['id'], 'export_bundle', batches=1)
                data = state(store, data['batch']['id'])
                return self.reply(200, bundle(data), 'application/zip','apart-research-bundle.zip')
            if parsed.path == '/api/responses':
                snapshot = state(store, selected)
                if not snapshot['batch']:
                    return self.reply(404, {'error':'Batch not found'})
                audit_action(store, snapshot['batch']['id'], 'export_responses', response_count=sum(e['kind']=='task_update' for e in snapshot['events']))
                data = ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in responses(snapshot['events'])).encode()
                return self.reply(200,data,'application/x-ndjson','responses.jsonl')
            path = (static / ('index.html' if parsed.path == '/' else parsed.path.lstrip('/'))).resolve()
            if static.resolve() not in path.parents or not path.is_file():
                return self.reply(404, {'error':'Not found'})
            return self.reply(200,path.read_bytes(),mimetypes.guess_type(str(path))[0] or 'application/octet-stream')

        def do_POST(self):
            origin = self.headers.get('Origin')
            if not self.trusted_host() or (origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')) or self.headers.get('X-Session-Key') != app.key:
                return self.reply(403, {'error':'Use this panel from its local origin'})
            try:
                length = int(self.headers.get('Content-Length',0))
                if not 0 < length <= 10_000_000:
                    raise ValueError('Payload must be between 1 byte and 10 MB')
                if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                    raise ValueError('Use application/json')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Request must be an object')
                if self.path == '/api/run':
                    batch_id = app.launch(body)
                    audit_action(store, batch_id, 'launch', conditions=body.get('conditions'),
                                 task_ids=body.get('task_ids'), adapter=body.get('adapter'),
                                 model=body.get('model'), steps=body.get('steps'),
                                 unlock_step=body.get('unlock_step'), repeats=body.get('repeats'),
                                 engagement_mode=body.get('engagement_mode'), study_id=body.get('study_id'))
                    return self.reply(202, {'batch_id': batch_id})
                if self.path == '/api/stop':
                    if not app.runner or not app.thread or not app.thread.is_alive():
                        raise ValueError('No panel-controlled batch is running')
                    app.runner.stop.set()
                    store.append(app.batch_id, 'stop_requested', {'policy':'stop before next request; retain in-flight result'})
                    audit_action(store, app.batch_id, 'stop_requested', policy='stop before next request')
                    return self.reply(200, {'status':'stopping_after_current_request'})
                if self.path == '/api/import':
                    batch_id = import_jsonl(store, body.get('jsonl'))
                    records = sum(1 for line in (body.get('jsonl') or '').splitlines() if line.strip())
                    audit_action(store, batch_id, 'import', records=records)
                    return self.reply(201, {'batch_id': batch_id})
                return self.reply(404, {'error':'Not found'})
            except (ValueError, TypeError) as exc:
                return self.reply(400, {'error':str(exc)})
            except Exception:
                return self.reply(500, {'error':'Server error; existing events remain preserved'})

    server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Observatory ready: http://127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if app.runner:
            app.runner.stop.set()
    finally:
        if app.runner and app.thread and app.thread.is_alive():
            app.runner.stop.set()
            # Allow the bounded current request to finish and append terminal events.
            app.thread.join()
        server.server_close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default='artifacts/observatory.sqlite')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--snapshot',help='Write a portable dashboard snapshot, without starting the server')
    p.add_argument('--batch')
    args=p.parse_args()
    store=EventStore(args.db)
    if args.snapshot:
        selected = args.batch
        audit_action(store, selected or 'snapshot', 'snapshot_written', path=args.snapshot)
        data=state(store,selected); data['mode']='snapshot'
        Path(args.snapshot).write_text(json.dumps(data,ensure_ascii=False,indent=2))
    else:
        serve(store,args.port)


if __name__ == '__main__':
    main()
